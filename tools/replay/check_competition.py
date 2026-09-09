"""Read-only offline feasibility gate; never produces measured QoS claims."""
import argparse
from collections import deque
import contextlib
import hashlib
import io
import json
from pathlib import Path
import zipfile

from competition import CompetitionRouter, PhysicalGraph
from scenario import phase_at, validate_scenario


def gate_result(total, alternate, different, relieved, errors):
    return {'passed': total == 160 and alternate >= .8 * total
            and different >= .5 * total and relieved > 0 and errors == 0,
            'alternate_fraction': alternate / total if total else None,
            'difference_fraction': different / total if total else None,
            'requirements': {'competition_epochs': 160, 'alternate_fraction': .8,
                             'difference_fraction': .5, 'at_least_one_relieved_epoch': True,
                             'error_epochs': 0}}


def _edges(path):
    return set(zip(path, path[1:]))


def _reachable(adjacency, start, end, blocked):
    queue, visited = deque([start]), {start}
    while queue:
        cell = queue.popleft()
        if cell == end:
            return True
        for other in adjacency.get(cell, ()):
            if (cell, other) not in blocked and other not in visited:
                visited.add(other)
                queue.append(other)
    return False


def _evidence(states, rate, decisions):
    shortest, qos = (decisions[a] for a in ('shortest_path', 'qos_priority'))
    qflows = {d['id']: d for d in qos['flows']}
    critical = [d for d in shortest['flows'] if d['service_class'] == 'C2']
    lower = [d for d in shortest['flows']
             if any(d['priority'] < high['priority'] for high in critical)]
    different = any(d['path'] != qflows[d['id']]['path'] for d in lower)
    graph = PhysicalGraph(states, rate)
    alternate, relieved = False, False
    contested = []
    for high in critical:
        for low in lower:
            shared = _edges(high['path']) & _edges(low['path'])
            for a, b in sorted(shared):
                edge = f'{a}->{b}'
                before = shortest['directed_load_gbps'][edge]
                after = qos['directed_load_gbps'].get(edge, 0.)
                capacity = graph.capacity(a, b)
                has_alternate = _reachable(graph.adjacency, low['source'], low['destination'], {(a, b)})
                improves = (before > capacity and after < before
                            and high['path'] == qflows[high['id']]['path']
                            and low['path'] != qflows[low['id']]['path'])
                alternate |= has_alternate
                relieved |= improves
                contested.append({'critical_id': high['id'], 'lower_id': low['id'],
                                  'edge': edge, 'capacity_gbps': capacity,
                                  'shortest_load_gbps': before, 'qos_load_gbps': after,
                                  'alternate_available': has_alternate,
                                  'model_overload_reduced': improves})
    return {'lower_priority_difference': different, 'alternate_corridor': alternate,
            'relieved_bottleneck': relieved, 'contested_edges': contested}


def check_archive(archive, config):
    config = validate_scenario(config)
    transcript = io.StringIO()
    with contextlib.redirect_stdout(transcript):
        routers = {name: CompetitionRouter(config, name) for name in ('shortest_path', 'qos_priority')}
    rows = []
    topology_hash = hashlib.sha256()
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive member names')
        expected = {f'snapshots/{epoch}.json' for epoch in range(301)}
        actual = {name for name in names if name.startswith('snapshots/') and name.endswith('.json')}
        if actual != expected:
            raise ValueError('Expected exactly 301 snapshots, epochs 0..300')
        for second in range(301):
            row = {'simulation_time_s': second, 'phase': phase_at(second)}
            try:
                states = json.loads(source.read(f'snapshots/{second}.json'))
                if not isinstance(states, dict):
                    raise ValueError('Snapshot must contain a node dictionary')
                # Hash full input state with unambiguous epoch separators.
                topology_hash.update(f'{second}\n'.encode())
                topology_hash.update(json.dumps(states, sort_keys=True, separators=(',', ':')).encode())
                topology_hash.update(b'\n')
                with contextlib.redirect_stdout(transcript):
                    row['decisions'] = {name: router.choose(states, second) for name, router in routers.items()}
                row.update(_evidence(states, config['shaping']['isl_gbps'], row['decisions']))
            except (ValueError, KeyError, TypeError) as error:
                row['error'] = str(error)
            rows.append(row)
    competition = [row for row in rows if row['phase'] == 'competition']
    alternate = sum(bool(row.get('alternate_corridor')) for row in competition)
    different = sum(bool(row.get('lower_priority_difference')) for row in competition)
    relieved = sum(bool(row.get('relieved_bottleneck')) for row in competition)
    errors = sum('error' in row for row in rows)
    return {'schema_version': 1, 'kind': 'offline-competition-feasibility',
            'real_performance_validated': False, 'input_archive': str(archive),
            'scenario': config,
            'scenario_sha256': hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'snapshot_sha256': topology_hash.hexdigest(),
            'evaluated_epochs': len(rows), 'competition_epochs': len(competition),
            'alternate_corridor_epochs': alternate, 'lower_priority_difference_epochs': different,
            'relieved_bottleneck_epochs': relieved, 'error_epochs': errors,
            'gate': gate_result(len(competition), alternate, different, relieved, errors),
            'frames': rows, 'northbound_log': transcript.getvalue()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--scenario', type=Path, default=Path(__file__).with_name('competition-routing.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--two-flow', action='store_true', help='Test C2 and bulk before enabling telemetry')
    args = parser.parse_args()
    config = json.loads(args.scenario.read_text())
    if args.two_flow:
        config['traffic_demands'] = [d for d in config['traffic_demands'] if d['service_class'] != 'telemetry']
    report = check_archive(args.archive, config)
    # Exclusive creation retains previous calibration evidence.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k not in ('frames', 'scenario', 'northbound_log')}, indent=2))
    return 0 if report['gate']['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
