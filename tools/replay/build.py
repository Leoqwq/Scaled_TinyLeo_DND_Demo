"""Build a standalone, offline HTML replay from a Canada experiment archive."""
import argparse
import json
import ipaddress
import re
from pathlib import Path


def build(root, output):
    scale = root / 'scale-96'
    formal = scale / 'formal-ab'
    data = {'summary': json.loads((root / 'run-summary.json').read_text()),
            'comparison': json.loads((formal / 'ab-comparison.json').read_text()),
            'map': json.loads(Path(__file__).with_name('canada.geo.json').read_text()),
            'modes': {}}
    for mode in ('shortest', 'geographic'):
        runtime = formal / f'tinyleo_canada_parity_{mode}_scale-96-Arbitrary-LeastDelay'
        epochs = []
        for epoch in range(data['summary']['epochs']):
            states = json.loads((runtime / 'all_node_states' / f'{epoch}.json').read_text())
            nodes = {name: state['position']['lla'] for name, state in states.items()
                     if 'position' in state}
            # Ground-station coordinates are fixed in example_canada_parity.py.
            ground = [(60.7212, -135.0568), (62.4540, -114.3718),
                      (63.7467, -68.5170), (49.2827, -123.1207),
                      (51.0447, -114.0719), (43.6532, -79.3832)]
            nodes.update({f'GS{i}': [lat, lon, 0] for i, (lat, lon)
                          in enumerate(ground, 1)})
            links = {}
            for name, state in states.items():
                for kind in ('isls', 'gsls'):
                    for other, props in state.get(kind, {}).items():
                        if other in nodes:
                            key = tuple(sorted((name, other)))
                            links[key] = {'a': name, 'b': other, 'kind': kind, 'delay': props[2]}
            raw = {}
            for kind in ('ping', 'traceroute', 'iperf'):
                path = formal / mode / 'results' / f'{kind}-epoch-{epoch}.txt'
                raw[kind] = path.read_text() if path.exists() else None
            owners = {}
            for name, state in states.items():
                if state.get('gs_ip'):
                    owners[str(ipaddress.ip_address(state['gs_ip']))] = name
                for kind in ('isls', 'gsls'):
                    for other, props in state.get(kind, {}).items():
                        owners[str(ipaddress.ip_address(props[0]))] = other
            path = ['GS4']
            for line in (raw['traceroute'] or '').splitlines():
                match = re.match(r'\s*\d+\s+(\S+)', line)
                if match:
                    try:
                        path.append(owners.get(str(ipaddress.ip_address(match[1]))))
                    except ValueError:
                        path.append(None)
            epochs.append({'nodes': nodes, 'links': list(links.values()),
                           'path': path, 'raw': raw})
        data['modes'][mode] = epochs
    if data['map']['type'] == 'FeatureCollection':
        data['map'] = data['map']['features'][0]
    template = Path(__file__).with_name('template.html').read_text()
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    output.write_text(template.replace('__REPLAY_DATA__', payload))
    print(f'Built {output}: {output.stat().st_size:,} bytes; 2 modes × 12 epochs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.archive, args.output)
