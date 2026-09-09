"""Local-VM, one-second TinyLEO runner with precomputed MPC and streamed evidence.

Startup/agent warmup precede t=0. Packet measurements run on a separate worker.
Each applied epoch is flushed to telemetry.jsonl, with no silent time dilation.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'network_orchestrator'), str(ROOT / 'network_orchestrator/test')]
from second_clock import run_seconds
from southbound.sn_controller import RemoteController
from example_canada_parity import GS_LAT_LONG, GS_CELL, _default_resource_sample


def run(root, template, mode, limit, failure_second=None):
    axis = json.loads((root / 'time-axis.json').read_text())
    count = axis['num_epochs'] if limit is None else min(limit, axis['num_epochs'])
    if axis['sample_interval_s'] != 1.0:
        raise ValueError('Expected one-second physical samples')
    if count < 1:
        raise ValueError('limit must be positive')
    report = json.loads((root / 'validation/validation_report.json').read_text())
    if not report.get('valid') or report.get('errors') or report.get('expected_epochs') != axis['num_epochs']:
        raise ValueError('A passing validation report for the complete input window is required')
    if failure_second is not None and not 0 < failure_second < count - 1:
        raise ValueError('failure-second must be inside the window, excluding endpoints')
    out = root / f'live-{mode}-{time.time_ns()}'
    out.mkdir()
    config = json.loads(template.read_text())
    for key, name in [('satellite_file','satellites.npy'), ('grid_satellites_file','grids.npy'),
                      ('traffic_matrix_file','traffic.npy'), ('block_positions_file','block_positions.json')]:
        config[key] = str((root / 'artifacts' / name).resolve())
    config.update(Name=out.name, start_epoch=0, num_epochs=count,
                  topology_update_interval_s=1.0, topo_dir=str(root / 'topology'))
    path = out / 'config.json'
    path.write_text(json.dumps(config, indent=2))
    def predict(**kwargs):
        dest = Path(kwargs['result_output_dir'])
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / 'topology/predict_isl_position_all.json', dest)
    def generate(**kwargs):
        epoch = kwargs['timestamp']
        for folder, suffix in [('all_isl_positions','json'), ('sat_cells','json'),
                               ('inter_cell_isls','json'), ('inter_topology','npy'), ('intra_topology','npy')]:
            dest = Path(kwargs['output_dir']) / folder
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / 'topology' / folder / f'{epoch}.{suffix}', dest)
    argv = sys.argv
    try:
        sys.argv = [argv[0]]  # Legacy config loader has its own CLI parser.
        controller = RemoteController(path, GS_LAT_LONG, GS_CELL, topology_predictor=predict, topology_generator=generate)
    finally:
        sys.argv = argv
    policy_name = 'south' if mode == 'shortest' else 'north'
    controller.geopraphic_routing_policy = json.loads((ROOT / f'network_orchestrator/test/config/geographic_routing_policy_canada_{policy_name}.json').read_text())
    (out / 'geopraphic_routing_policy.json').write_text(json.dumps(controller.geopraphic_routing_policy))
    rows = []
    measurements = []
    pool = ThreadPoolExecutor(max_workers=1)
    pending = None
    failures = []
    ping_process = None
    ping_log = None
    def measure(epoch):
        for kind in ('ping','iperf','traceroute'):
            getattr(controller, f'set_{kind}')('GS4','GS6',f'second-{epoch}').result()
        return epoch
    try:
        controller.init_remote_machine()
        controller.create_nodes()
        controller.create_links()
        controller.update_tinyleo_topology(0)
        if controller.enable_failure_recovery:
            controller.start_link_faliure_server()
        controller.deploy_tinyleo_srv6_agent()
        time.sleep(15)
        # A continuous one-packet-per-second data-plane probe is independent
        # of topology updates and of the slower iperf/traceroute worker.
        ping_log = (out / 'ping-continuous.txt').open('w', buffering=1)
        ping_process = subprocess.Popen(
            ['sudo', '-n', 'ip', 'netns', 'exec', 'GS4', 'ping', '-n', '-6',
             '-i', '1', '-D', '-O', 'ce:3:ce:4:6::6'],
            stdout=ping_log, stderr=subprocess.STDOUT, start_new_session=True)
        with (out / 'telemetry.jsonl').open('w', buffering=1) as log:
            def emit(row):
                nonlocal pending
                row.update(_default_resource_sample(row['epoch']))
                row['controller_snapshot'] = str(Path(controller.local_dir) / 'all_node_states' / f"{row['epoch']}.json")
                log.write(json.dumps(row) + '\n')
                rows.append(row)
                print(f"SECOND_STATE t={row['simulation_time_s']:.0f}s "
                      f"wall={row['wall_elapsed_s']:.3f}s "
                      f"apply={row['apply_duration_s']:.3f}s "
                      f"late={row['start_lateness_s']:.3f}s "
                      f"deadline={'MISS' if row['deadline_missed'] else 'OK'}", flush=True)
                if pending is None or pending.done():
                    if pending is not None:
                        measurements.append(pending.result())
                    pending = pool.submit(measure, row['epoch'])
            def apply(epoch):
                controller.update_tinyleo_topology(epoch)
                if epoch == failure_second:
                    if not controller.enable_failure_recovery:
                        raise ValueError('Failure service must be enabled for injection')
                    failures.append(controller.tinyleo_fault_test())
                    (out / 'failure-events.json').write_text(json.dumps(failures, indent=2))
            run_seconds(count, apply, emit)
        if pending:
            measurements.append(pending.result())
    finally:
        pool.shutdown(wait=True)
        if ping_process is not None:
            if ping_process.poll() is None:
                os.killpg(ping_process.pid, signal.SIGINT)
                try:
                    ping_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(ping_process.pid, signal.SIGKILL)
                    ping_process.wait()
        if ping_log is not None:
            ping_log.close()
        if hasattr(controller, 'remote_lst'):
            controller.clean()
        summary = {'expected_epochs': count, 'completed_epochs': len(rows),
                   'deadline_misses': sum(r['deadline_missed'] for r in rows),
                   'max_apply_s': max((r['apply_duration_s'] for r in rows), default=None),
                   'sample_interval_s': 1.0, 'measurement_start_epochs': measurements,
                   'valid_realtime': len(rows) == count and not any(r['deadline_missed'] for r in rows)}
        (out / 'summary.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
    return out


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('template', type=Path)
    p.add_argument('--mode', choices=['shortest','geographic'], default='shortest')
    p.add_argument('--limit', type=int)
    p.add_argument('--failure-second', type=int, help='Optional explicit ISL failure time; its cost counts against the deadline')
    a = p.parse_args()
    run(a.root.resolve(), a.template.resolve(), a.mode, a.limit, a.failure_second)
