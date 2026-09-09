"""Versioned, provenance-bearing real-flow archives, compatible with Replay."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from scenario import PHASES, validate_scenario


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def physical_digest(frames):
    rows = []
    for frame in frames:
        links = [dict(link, a=min(link['a'], link['b']), b=max(link['a'], link['b']))
                 for link in frame['links']]
        links.sort(key=lambda link: (link['a'], link['b'], link['kind']))
        rows.append({'time': frame['telemetry']['simulation_time_s'],
                     'nodes': frame['nodes'], 'links': links})
    return digest(rows)


def runtime_digest(root):
    root = Path(root)
    files = [root / 'network_orchestrator/northbound.py', root / 'network_orchestrator/second_clock.py']
    for folder in ('tools/replay', 'network_orchestrator/southbound', 'network_orchestrator/geographic_srv6_anycast'):
        files += sorted((root / folder).glob('*.py'))
    return digest({str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in files if not path.name.startswith('test_')})


def build_competition_archive(run_dir, frames, config, measurements, provenance, *, algorithm, boundary, error=None):
    config = validate_scenario(config)
    if algorithm not in ('shortest_path', 'qos_priority'):
        raise ValueError('Invalid archive algorithm')
    times = [frame['telemetry']['simulation_time_s'] for frame in frames]
    complete = times == list(range(301)) and not error
    flows = measurements.get('flows', {})
    events = measurements.get('events', {})
    measurement_complete = not measurements.get('errors') and all(
        flows.get(d['id'], {}).get('complete') is True
        and bool(flows[d['id']].get('intervals'))
        and flows[d['id']].get('final') is not None
        and 'started_s' in events.get(d['id'], {})
        and 'receiver_end_s' in events.get(d['id'], {})
        for d in config['traffic_demands'])
    provenance = dict(provenance, scenario_sha256=digest(config),
                      physical_sha256=physical_digest(frames), time_axis_sha256=digest(times),
                      shaping_sha256=digest(config['shaping']),
                      measurement_version=measurements.get('iperf_version', 'unknown'))
    known_runtime = len(provenance.get('runtime_sha256', '')) == 64
    summary = {'algorithm': algorithm, 'expected_epochs': 301, 'completed_epochs': len(frames),
               'deadline_misses': sum(bool(f['telemetry']['deadline_missed']) for f in frames),
               'error': error, 'measurement_complete': measurement_complete,
               'comparison_eligible': bool(complete and measurement_complete and known_runtime),
               'status': 'completed' if complete else 'failed'}
    return deepcopy({'schema_version': 2, 'map': boundary, 'modes': {algorithm: frames},
                     'summary': summary, 'scenario': config, 'provenance': provenance,
                     'flow_measurements': flows, 'traffic_events': events,
                     'measurement_errors': measurements.get('errors', []),
                     'phases': [{'name': name, 'start_s': a, 'end_s': b} for name, a, b in PHASES],
                     'batches': {}, 'continuous_ping': '', 'source': Path(run_dir).name,
                     'recording_note': 'Recorded emulation results; no inferred receiver measurements'})
