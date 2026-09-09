"""Multi-flow routing on actual physical state; no emulation process control."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import tempfile

from scenario import active_demands, phase_at, validate_scenario


def _cell(state):
    value = state.get('sat_cell')
    if value is None or value == []:
        return None
    if (not isinstance(value, list) or len(value) != 2
            or any(type(v) is not int or not 1 <= v <= 11 for v in value)):
        raise ValueError('Invalid physical cell')
    return (value[0] - 1) * 11 + value[1] - 1


def _geographic(cell):
    return [cell // 11 + 1, cell % 11 + 1]


class PhysicalGraph:
    """Conservative capacity: exactly one verified physical ISL per boundary.

    Multiple gateways are rejected, not aggregated: the current data plane
    does not establish multipath load balancing. Density remains a risk input.
    """
    def __init__(self, states, capacity_gbps):
        if not math.isfinite(capacity_gbps) or capacity_gbps <= 0:
            raise ValueError('Invalid physical capacity')
        self.adjacency = defaultdict(set)
        self.density = Counter()
        self.gateways = {}
        self.rate = capacity_gbps
        cells = {name: _cell(state) for name, state in states.items()}
        self.density.update(c for c in cells.values() if c is not None)
        for name, state in states.items():
            a = cells[name]
            if a is None:
                continue
            for other in state.get('isls', {}):
                if other not in states or name not in states[other].get('isls', {}):
                    raise ValueError('Physical ISLs must be symmetric')
                b = cells[other]
                if b is None:
                    raise ValueError('ISL peer has no satellite cell')
                if a == b or name > other:
                    continue
                if abs(a // 11 - b // 11) + abs(a % 11 - b % 11) != 1:
                    raise ValueError('Non-adjacent geographic ISL')
                edge = tuple(sorted((a, b)))
                if edge in self.gateways:
                    raise ValueError(f'Unverified parallel gateways at {edge}')
                self.gateways[edge] = [name, other]
                self.adjacency[a].add(b)
                self.adjacency[b].add(a)

    def capacity(self, a, b):
        return self.rate if tuple(sorted((a, b))) in self.gateways else 0.0


def validate_directions(flows):
    directions = set()
    for flow in flows:
        for a, b in zip(flow['path'], flow['path'][1:]):
            if (b, a) in directions:
                raise ValueError('Undirected reservation model cannot represent opposite-direction sharing')
            directions.add((a, b))


class CompetitionRouter:
    def __init__(self, config, algorithm):
        if algorithm not in ('shortest_path', 'qos_priority'):
            raise ValueError('Unknown competition algorithm')
        self.config = validate_scenario(config)
        self.algorithm = algorithm
        northbound = str(Path(__file__).resolve().parents[2] / 'network_orchestrator')
        if northbound not in sys.path:
            sys.path.insert(0, northbound)
        from northbound import TinyLEONorthboundAPI
        api_config = {'grid_config': self.config['grid_config'],
                      'global_settings': {'isl_capacity_gbps': self.config['shaping']['isl_gbps']},
                      'traffic_demands': []}
        # Use the existing public loader without changing its offline contract.
        with tempfile.TemporaryDirectory(prefix='tinyleo-routing-') as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(api_config))
            self.api = TinyLEONorthboundAPI(str(path))

    def choose(self, states, second):
        graph = PhysicalGraph(states, self.config['shaping']['isl_gbps'])
        demands = active_demands(self.config, second)
        self.api.grid_density = graph.density
        self.api.get_neighbors = lambda cell: sorted(graph.adjacency.get(cell, ()))
        self.api._edge_capacity_gbps = graph.capacity
        self.api.config['traffic_demands'] = [dict(d, routing_policy=self.algorithm) for d in demands]
        self.api.generate_traffic_matrix()
        flows, policy = [], {}
        loads = defaultdict(float)
        for d in demands:
            path = self.api.paths.get((d['source'], d['destination']), [])
            if not path or path[0] != d['source'] or path[-1] != d['destination']:
                raise ValueError(f"No physical path for {d['id']} at {second}")
            if any(graph.capacity(a, b) <= 0 for a, b in zip(path, path[1:])):
                raise ValueError('Selected route leaves physical topology')
            key = f"{_geographic(path[0])}->{_geographic(path[-1])}"
            policy[key] = [_geographic(c) for c in path[1:-1]]
            for a, b in zip(path, path[1:]):
                loads[f'{a}->{b}'] += d['demand_gbps']
            flows.append(dict(d, path=list(path), qos_status=deepcopy(
                self.api.path_status.get((d['source'], d['destination']), {}))))
        validate_directions(flows)
        return {'algorithm': self.algorithm, 'phase': phase_at(second), 'flows': flows,
                'policy': policy, 'directed_load_gbps': dict(loads),
                'edge_capacity_gbps': {f'{a}->{b}': graph.capacity(a, b)
                                      for a in sorted(graph.adjacency)
                                      for b in sorted(graph.adjacency[a])},
                'gateways': {f'{a}<->{b}': names for (a, b), names in sorted(graph.gateways.items())},
                'density': dict(graph.density),
                'model_note': 'Reserved offered load and QoS costs are model estimates, not receiver measurements'}
