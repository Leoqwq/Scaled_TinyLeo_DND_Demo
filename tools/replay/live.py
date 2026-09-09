"""Manual VM preparation and persistent, single-run-at-a-time TinyLEO session."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
GROUND = [(60.7212, -135.0568), (62.454, -114.3718), (63.7467, -68.517),
          (49.2827, -123.1207), (51.0447, -114.0719), (43.6532, -79.3832)]


def validate_algorithm(value):
    if value not in ('shortest_path', 'qos_priority'):
        raise ValueError('Choose shortest_path or qos_priority')
    return value


def policy_from_path(path):
    if not path or path[0] != 23 or path[-1] != 25:
        raise ValueError('No GS4 to GS6 route; refusing to reuse a stale policy')
    for a, b in zip(path, path[1:]):
        if abs(a // 11 - b // 11) + abs(a % 11 - b % 11) != 1:
            raise ValueError('Non-adjacent geographic path')
    return {'[3, 2]->[3, 4]': [[g // 11 + 1, g % 11 + 1] for g in path[1:-1]]}


def make_frame(states, telemetry, routing):
    nodes = {name: state['position']['lla'] for name, state in states.items() if 'position' in state}
    nodes.update({f'GS{i}': [lat, lon, 0] for i, (lat, lon) in enumerate(GROUND, 1)})
    links = {}
    for name, state in states.items():
        for kind in ('isls', 'gsls'):
            for other, props in state.get(kind, {}).items():
                if other in nodes:
                    links[tuple(sorted((name, other)))] = dict(a=name, b=other, kind=kind, delay=props[2])
    return dict(nodes=nodes, links=list(links.values()), telemetry=telemetry, routing=routing)


class RoutingAdapter:
    """Existing northbound algorithms; graph restricted to actual inter-cell ISLs."""
    def __init__(self, config, algorithm):
        from northbound import TinyLEONorthboundAPI
        self.api = TinyLEONorthboundAPI(str(config))
        self.algorithm = validate_algorithm(algorithm)
        demands = self.api.config.get('traffic_demands', [])
        if len(demands) != 1 or (demands[0]['source'], demands[0]['destination']) != (23, 25):
            raise ValueError('Live demo requires one explicit GS4→GS6 demand (23→25)')

    def choose(self, states):
        adjacency = {}
        density = {}
        def cell(state):
            value = state.get('sat_cell')
            return (value[0]-1)*11 + value[1]-1 if value else None
        for name, state in states.items():
            a = cell(state)
            if a is None:
                continue
            density[a] = density.get(a, 0) + 1
            for other in state.get('isls', {}):
                b = cell(states.get(other, {}))
                if b is not None and a != b:
                    adjacency.setdefault(a, set()).add(b)
        self.api.grid_density = density
        self.api.get_neighbors = lambda g: sorted(adjacency.get(g, ()))
        self.api.config['traffic_demands'][0]['routing_policy'] = self.algorithm
        self.api.generate_traffic_matrix()
        path = self.api.paths.get((23, 25), [])
        policy = policy_from_path(path)
        return policy, dict(algorithm=self.algorithm, path=path,
                            qos_status=self.api.path_status.get((23, 25), {}),
                            model_note='QoS costs and latency are model estimates, not measured RTT')


class Session:
    def __init__(self, root, template, routing_config, *, competition_scenario=None, iperf_binary='iperf3'):
        self.root, self.template, self.routing_config = root, template, routing_config
        self.lock = threading.Lock()
        self.state = dict(status='not_prepared', run_id=None, frames=0)
        self.frames = []
        self.controller = None
        self.out = None
        self.archive = None
        self.competition_config = None
        self.iperf_binary = str(iperf_binary)
        self.traffic = None
        if competition_scenario is not None:
            from scenario import validate_scenario
            self.competition_config = validate_scenario(json.loads(Path(competition_scenario).read_text()))

    def profile_config(self, config):
        config = dict(config)
        if self.competition_config is not None:
            shaping = self.competition_config['shaping']
            if shaping['queue_packets'] != 1000:
                raise ValueError('Current netem profile supports its existing 1000-packet limit only')
            config['satellite link bandwidth ("X" Gbps)'] = shaping['isl_gbps']
            config['sat-ground bandwidth ("X" Gbps)'] = shaping['gsl_gbps']
        return config

    def prepare(self):
        """Called only by the human-invoked VM command, never by an HTTP request."""
        import fcntl
        self.preparation_lock = os.open('/tmp/tinyleo-live-session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(self.preparation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sys.path[:0] = [str(ROOT / 'network_orchestrator'), str(ROOT / 'network_orchestrator/test')]
        from southbound.sn_controller import RemoteController
        from example_canada_parity import GS_LAT_LONG, GS_CELL
        existing = subprocess.check_output(['ip', 'netns', 'list'], text=True)
        if any(line.split()[0].startswith(('SH1SAT', 'GS')) for line in existing.splitlines() if line.split()):
            raise ValueError('Existing TinyLEO nodes found; manual cleanup is required before preparing a new session')
        axis = json.loads((self.root / 'time-axis.json').read_text())
        report = json.loads((self.root / 'validation/validation_report.json').read_text())
        if axis['num_epochs'] != 301 or axis['sample_interval_s'] != 1 or not report.get('valid') or report.get('errors') or report.get('expected_epochs') != 301:
            raise ValueError('Requires validated 301-state, one-second artifacts')
        config = self.profile_config(json.loads(self.template.read_text()))
        if self.competition_config is not None:
            from traffic import require_streaming
            version = subprocess.check_output([self.iperf_binary, '--version'], text=True, timeout=5)
            help_text = subprocess.check_output([self.iperf_binary, '--help'], text=True, timeout=5)
            require_streaming(version, help_text)
        if len(config['Machines']) != 1 or config['Machines'][0]['IP'] != '127.0.0.1':
            raise ValueError('Live preparation supports only the existing single-VM loopback deployment')
        name = 'live-session-' + uuid.uuid4().hex
        directory = self.root / name
        directory.mkdir()
        config.update(Name=name, start_epoch=0, num_epochs=301, topology_update_interval_s=1.)
        for key, filename in [('satellite_file','satellites.npy'), ('grid_satellites_file','grids.npy'),
                              ('traffic_matrix_file','traffic.npy'), ('block_positions_file','block_positions.json')]:
            config[key] = str(self.root / 'artifacts' / filename)
        path = directory / 'config.json'
        path.write_text(json.dumps(config, indent=2))
        (directory / 'geopraphic_routing_policy.json').write_text('{}')
        def predict(**kwargs):
            target = Path(kwargs['result_output_dir'])
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root / 'topology/predict_isl_position_all.json', target)
        def generate(**kwargs):
            for folder, suffix in [('all_isl_positions','json'), ('sat_cells','json'), ('inter_cell_isls','json'),
                                   ('inter_topology','npy'), ('intra_topology','npy')]:
                target = Path(kwargs['output_dir']) / folder
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.root / 'topology' / folder / f"{kwargs['timestamp']}.{suffix}", target)
        argv = sys.argv
        try:
            sys.argv = [argv[0]]
            controller = RemoteController(path, GS_LAT_LONG, GS_CELL, topology_predictor=predict, topology_generator=generate)
        finally:
            sys.argv = argv
        controller.init_remote_machine()
        controller.create_nodes()
        controller.create_links()
        # Agents start at 300 so the first live t=0 generates a distinct event.
        controller.update_tinyleo_topology(300)
        controller.deploy_tinyleo_srv6_agent()
        if controller.enable_failure_recovery:
            controller.start_link_faliure_server()
        time.sleep(15)
        self.controller = controller
        self.state['status'] = 'ready'

    def start(self, algorithm):
        validate_algorithm(algorithm)
        with self.lock:
            if self.state['status'] not in ('ready', 'completed'):
                raise ValueError('Session is not ready; failed sessions require manual preparation')
            expected = [f'SH1SAT{i}' for i in range(1,97)] + [f'GS{i}' for i in range(1,7)]
            if self.controller is None or any(not Path('/run/netns', name).exists() for name in expected):
                raise ValueError('Prepared nodes are no longer available; manual preparation required')
            run_id = uuid.uuid4().hex
            self.out = self.root / 'live-results' / run_id
            self.out.mkdir(parents=True)
            self.frames, self.archive = [], None
            self.traffic = None
            self.state = dict(status='running', run_id=run_id, algorithm=algorithm, frames=0)
            threading.Thread(target=self._run, args=(algorithm,), daemon=True).start()
            return dict(self.state)

    def snapshot(self, after=-1):
        with self.lock:
            value = dict(self.state)
            value['new_frames'] = self.frames[max(0, after+1):]
            out = self.out
        if out and (out / 'ping-continuous.txt').exists():
            value['ping'] = (out / 'ping-continuous.txt').read_text(errors='replace')[-16000:]
        if out and (out / 'run.log').exists():
            with (out / 'run.log').open('rb') as stream:
                stream.seek(max(0, (out / 'run.log').stat().st_size-12000))
                value['log'] = stream.read().decode(errors='replace')
        if self.traffic is not None:
            value['traffic'] = self.traffic.snapshot()
        return value

    def _run(self, algorithm):
        with (self.out / 'run.log').open('w', buffering=1) as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                self._execute(algorithm)

    def _execute(self, algorithm):
        from second_clock import run_seconds
        from example_canada_parity import _default_resource_sample
        controller, out = self.controller, self.out
        ping = None
        ping_file = None
        failure = None
        traffic = None
        evidence = None
        previous_policy = None
        previous_routing = None
        run_origin_unix = run_origin_mono = None
        try:
            if self.competition_config is None:
                adapter = RoutingAdapter(self.routing_config, algorithm)
            else:
                from competition import CompetitionRouter
                from traffic import TrafficSession
                adapter = CompetitionRouter(self.competition_config, algorithm)
                (out / 'scenario.json').write_text(json.dumps(self.competition_config, indent=2))
                traffic = TrafficSession(self.competition_config, out, self.iperf_binary)
                self.traffic = traffic
                traffic.start()
                from evidence import EvidenceCollector
                ground = sorted({d[k] for d in self.competition_config['traffic_demands']
                                 for k in ('source_gs', 'destination_gs')})
                evidence = EvidenceCollector(out, ground)
            if self.competition_config is None:
                shutil.copy2(self.routing_config, out / 'routing-config.json')
            else:
                (out / 'routing-config.json').write_text(json.dumps(self.competition_config, indent=2))
            (out / 'run-config.json').write_text(json.dumps({
                'algorithm': algorithm, 'frames':301, 'sample_interval_s':1,
                'sat_bandwidth_gbps':controller.sat_bandwidth,
                'gsl_bandwidth_gbps':controller.sat_ground_bandwidth,
                'sat_loss_percent':controller.sat_loss,
                'gsl_loss_percent':controller.sat_ground_loss,
                'antenna_number':controller.antenna_number,
                'nodes_created_by_live_start':False,
            }, indent=2))
            shutil.copy2(self.root / 'time-axis.json', out / 'time-axis.json')
            (out / 'snapshots').mkdir()
            # Preview uses the original link/state generator without kernel mutation.
            # The same state will then be generated and applied by RemoteController.
            from southbound.sn_utils import update_tinyleo_link
            from copy import deepcopy
            routing = {}
            if traffic is None:
                ping_file = (out / 'ping-continuous.txt').open('w')
                ping = subprocess.Popen(['ip','netns','exec','GS4','ping','-n','-6','-i','1','-D','-O',
                                         'ce:3:ce:4:6::6'], stdout=ping_file, stderr=subprocess.STDOUT,
                                        start_new_session=True)
            preview_dir = out / 'preview'
            for folder in ('shell0/isl', 'GS-6/gsl', 'all_node_states'):
                (preview_dir / folder).mkdir(parents=True)
            with (out / 'telemetry.jsonl').open('w') as log:
                def apply(epoch):
                    nonlocal routing, previous_policy, previous_routing
                    controller._generate_topology_for_timestamp(epoch)
                    runtime = Path(controller.local_dir)
                    shell = json.loads((runtime / 'all_isl_positions' / f'{epoch}.json').read_text())
                    shell['name'] = 'shell0'
                    cells = json.loads((runtime / 'sat_cells' / f'{epoch}.json').read_text())
                    gateways = json.loads((runtime / 'inter_cell_isls' / f'{epoch}.json').read_text())
                    states = {}
                    update_tinyleo_link(str(preview_dir), epoch, deepcopy(controller.all_link_states),
                                        [shell], controller.gs_lat_long, controller.antenna_number, cells,
                                        controller.GS_cell, controller.link_count, {}, gateways, states)
                    if traffic is None:
                        policy, routing = adapter.choose(states)
                    else:
                        routing = adapter.choose(states, epoch)
                        from competition import retain_draining_routes
                        completed = {key: flow['complete'] for key, flow in traffic.snapshot()['flows'].items()}
                        retain_draining_routes(routing, previous_routing, completed, epoch)
                        previous_routing = deepcopy(routing)
                        policy = routing['policy']
                    controller.geopraphic_routing_policy = policy
                    controller.update_tinyleo_topology(epoch)
                    if traffic is not None:
                        traffic.advance(epoch, run_origin_unix, run_origin_mono)
                        if epoch in (0, 20, 79, 80, 239, 240, 289, 290, 300) or policy != previous_policy:
                            evidence.submit(epoch, routing, 'phase' if epoch in (0,20,79,80,239,240,289,290,300) else 'route-change')
                        previous_policy = deepcopy(policy)
                def emit(row):
                    row.update(_default_resource_sample(row['epoch']))
                    row['recorded_unix_s'] = time.time()
                    row['routing'] = routing
                    log.write(json.dumps(row) + '\n')
                    log.flush()
                    states = deepcopy(controller.all_node_states)
                    (out / 'snapshots' / f"{row['epoch']}.json").write_text(json.dumps(states))
                    for folder in ('shell0/isl', 'GS-6/gsl'):
                        target = out / 'commands' / folder
                        target.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(Path(controller.local_dir) / folder / f"{row['epoch']}.txt", target)
                    print(f"STATE t={row['simulation_time_s']}s apply={row['apply_duration_s']:.3f}s algorithm={algorithm}", flush=True)
                    frame = make_frame(states, row, routing)
                    with self.lock:
                        self.frames.append(frame)
                        self.state['frames'] = len(self.frames)
                run_origin_unix, run_origin_mono = time.time(), time.monotonic()
                run_seconds(301, apply, emit)
                if traffic is not None:
                    traffic.finish()
        except Exception as error:
            failure = str(error)
        finally:
            if ping is not None:
                if ping.poll() is None:
                    os.killpg(ping.pid, signal.SIGINT)
                    try:
                        ping.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(ping.pid, signal.SIGKILL)
                        ping.wait()
            if ping_file:
                ping_file.close()
            if traffic is not None:
                traffic.close()
                measurements = traffic.snapshot()
                (out / 'flow-measurements.json').write_text(json.dumps(measurements, indent=2))
                if measurements['errors']:
                    failure = failure or '; '.join(measurements['errors'])
                if not all(f.get('complete') for f in measurements['flows'].values()):
                    failure = failure or 'Missing completed receiver measurements'
            if evidence is not None:
                evidence.close()
                (out / 'evidence-status.json').write_text(json.dumps({
                    'errors': evidence.errors, 'kernel_convergence_certified': False,
                    'note': 'Raw kernel policies and counters require VM acceptance review'}))
        with self.lock:
            self.state.update(status='archiving', error=failure)
        try:
            summary = dict(algorithm=algorithm, expected_epochs=301, completed_epochs=len(self.frames),
                           deadline_misses=sum(f['telemetry']['deadline_missed'] for f in self.frames), error=failure)
            boundary = json.loads(Path(__file__).with_name('canada.geo.json').read_text())
            if boundary['type'] == 'FeatureCollection':
                boundary = boundary['features'][0]
            data = dict(schema_version=1, map=boundary, modes={algorithm:self.frames}, summary=summary, batches={},
                        continuous_ping=(out / 'ping-continuous.txt').read_text() if ping_file else '',
                        source=out.name)
            if traffic is not None:
                from competition_archive import build_competition_archive, runtime_digest
                data = build_competition_archive(out, self.frames, self.competition_config,
                    traffic.snapshot(), {'runtime_sha256': runtime_digest(ROOT)},
                    algorithm=algorithm, boundary=boundary, error=failure)
                summary = data['summary']
            (out / 'replay.json').write_text(json.dumps(data))
            (out / 'summary.json').write_text(json.dumps(summary, indent=2))
            archive = out.with_suffix('.zip')
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                for path in out.rglob('*'):
                    if path.is_file() and 'preview' not in path.relative_to(out).parts:
                        z.write(path, str(path.relative_to(out)))
                for folder in ('artifacts', 'topology', 'validation'):
                    for path in (self.root / folder).rglob('*'):
                        if path.is_file():
                            z.write(path, 'inputs/' + str(path.relative_to(self.root)))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.lock:
                self.archive = archive
                self.state.update(status='failed' if failure else 'completed', sha256=digest,
                                  archive_bytes=archive.stat().st_size)
        except Exception as error:
            with self.lock:
                self.state.update(status='failed', error=f'Archive failed: {error}; files retained at {out}')
