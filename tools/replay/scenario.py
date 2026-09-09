"""Validated inputs for the fixed, finite Canada competition experiment."""
from copy import deepcopy
import math
import re

GS_CELLS = {'GS1': 12, 'GS2': 13, 'GS3': 14, 'GS4': 23, 'GS5': 24, 'GS6': 25}
PHASES = (('warmup', 0, 20), ('baseline', 20, 80),
          ('competition', 80, 240), ('recovery', 240, 290), ('drain', 290, 301))


def _number(value, low, high, label, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high
            or (integer and not isinstance(value, int))):
        raise ValueError(f'{label} must be {"an integer" if integer else "finite"} in [{low}, {high}]')


def phase_at(second):
    _number(second, 0, 300, 'simulation time')
    return next(name for name, start, end in PHASES if start <= second < end)


def validate_scenario(config):
    """Fail closed on unsupported settings; return a detached, validated copy."""
    if not isinstance(config, dict):
        raise ValueError('Scenario must be an object')
    required = {'schema_version', 'name', 'grid_config', 'shaping', 'traffic_demands'}
    if set(config) != required or config['schema_version'] != 1:
        raise ValueError('Unsupported scenario fields or schema version')
    if not isinstance(config['name'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', config['name']):
        raise ValueError('Scenario name must be a portable identifier')
    if config['grid_config'] != {'rows': 11, 'cols': 11}:
        raise ValueError('Competition requires the validated 11 x 11 grid')
    shaping = config['shaping']
    if not isinstance(shaping, dict) or set(shaping) != {'isl_gbps', 'gsl_gbps', 'queue_packets', 'udp_payload_bytes'}:
        raise ValueError('Unsupported shaping fields')
    for key in ('isl_gbps', 'gsl_gbps'):
        _number(shaping[key], .000001, 1, key)
    _number(shaping['queue_packets'], 1, 10000, 'queue_packets', integer=True)
    _number(shaping['udp_payload_bytes'], 64, 1200, 'udp_payload_bytes', integer=True)
    demands = config['traffic_demands']
    if not isinstance(demands, list) or not 1 <= len(demands) <= 15:
        raise ValueError('Expected 1–15 unique cell-pair demands')
    fields = {'id', 'source', 'destination', 'source_gs', 'destination_gs',
              'priority', 'service_class', 'demand_gbps', 'start_s', 'end_s', 'port'}
    identifiers, ports, pairs = set(), set(), set()
    for d in demands:
        if not isinstance(d, dict) or set(d) != fields:
            raise ValueError('Unsupported demand fields; route weights are not scenario knobs')
        if not isinstance(d['id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', d['id']):
            raise ValueError('Invalid demand id')
        for side in ('source', 'destination'):
            if (not isinstance(d[side + '_gs'], str)
                    or d[side + '_gs'] not in GS_CELLS
                    or type(d[side]) is not int
                    or GS_CELLS[d[side + '_gs']] != d[side]):
                raise ValueError('Ground station and cell mapping disagree')
        pair = tuple(sorted((d['source'], d['destination'])))
        if pair[0] == pair[1] or pair in pairs:
            raise ValueError('Duplicate/reverse cell-pair policy or identical endpoints')
        _number(d['priority'], 1, 5, 'priority', integer=True)
        _number(d['demand_gbps'], .000001, 1, 'demand_gbps')
        _number(d['port'], 1024, 65535, 'port', integer=True)
        _number(d['start_s'], 20, 289, 'start_s', integer=True)
        _number(d['end_s'], d['start_s'] + 1, 290, 'end_s', integer=True)
        if d['service_class'] not in ('C2', 'ISR', 'telemetry', 'bulk', 'best_effort'):
            raise ValueError('Unknown service class')
        if d['id'] in identifiers or d['port'] in ports:
            raise ValueError('Duplicate demand id or port')
        identifiers.add(d['id'])
        ports.add(d['port'])
        pairs.add(pair)
    return deepcopy(config)


def active_demands(config, second):
    phase_at(second)
    return deepcopy([d for d in config['traffic_demands'] if d['start_s'] <= second < d['end_s']])
