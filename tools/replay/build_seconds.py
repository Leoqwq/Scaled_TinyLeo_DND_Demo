"""Build the 301-frame offline replay directly from a one-second run archive."""
import argparse
import json
import tarfile
from pathlib import Path


def build(archive, output):
    with tarfile.open(archive) as tar:
        def read(name):
            stream = tar.extractfile(name)
            if stream is None:
                raise ValueError(f'Not a file: {name}')
            return stream.read().decode()

        candidates = []
        for name in tar.getnames():
            if '/live-shortest-' in name and name.endswith('/summary.json'):
                summary = json.loads(read(name))
                if summary.get('completed_epochs') == 301:
                    candidates.append((name.rsplit('/', 1)[0], summary))
        if len(candidates) != 1:
            raise ValueError('Expected exactly one completed 301-frame shortest run')
        run, summary = candidates[0]
        runtime = run + '-Arbitrary-LeastDelay'
        telemetry = [json.loads(line) for line in read(run + '/telemetry.jsonl').splitlines()]
        if [t['epoch'] for t in telemetry] != list(range(301)):
            raise ValueError('Missing or unordered telemetry frames')
        if [t['simulation_time_s'] for t in telemetry] != list(range(301)):
            raise ValueError('Expected consecutive one-second samples')
        ground = [(60.7212, -135.0568), (62.454, -114.3718),
                  (63.7467, -68.517), (49.2827, -123.1207),
                  (51.0447, -114.0719), (43.6532, -79.3832)]
        frames = []
        for epoch in range(301):
            states = json.loads(read(f'{runtime}/all_node_states/{epoch}.json'))
            nodes = {name: state['position']['lla'] for name, state in states.items()
                     if 'position' in state}
            nodes.update({f'GS{i}': [lat, lon, 0] for i, (lat, lon) in enumerate(ground, 1)})
            links = {}
            for name, state in states.items():
                for kind in ('isls', 'gsls'):
                    for other, props in state.get(kind, {}).items():
                        if other in nodes:
                            links[tuple(sorted((name, other)))] = dict(a=name, b=other, kind=kind, delay=props[2])
            frames.append(dict(nodes=nodes, links=list(links.values()), telemetry=telemetry[epoch]))
        batches = {str(epoch): {kind: read(f'{runtime}/result/{kind}-second-{epoch}.txt')
                               for kind in ('ping', 'traceroute', 'iperf')}
                   for epoch in summary['measurement_start_epochs']}
        boundary = json.loads(Path(__file__).with_name('canada.geo.json').read_text())
        if boundary['type'] == 'FeatureCollection':
            boundary = boundary['features'][0]
        data = dict(map=boundary, modes={'shortest': frames}, summary=summary,
                    batches=batches, continuous_ping=read(run + '/ping-continuous.txt'), source=run)
    output.write_text(render_html(data))
    print(f'Built {output}: {output.stat().st_size:,} bytes; 301 frames, 1 second/frame')


def render_html(data, comparison=None):
    template = Path(__file__).with_name('seconds.html').read_text()
    pair = json.dumps(comparison, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    template = template.replace('<script>__COMPARE_JS__',
        '<script id="comparisonData" type="application/json">' + pair + '</script><script>__COMPARE_JS__')
    # Embed code and data for file:// use; no external script or CDN requests.
    for marker, name in [('__COMPARE_JS__', 'compare.js'), ('__COMPARE_UI_JS__', 'compare_ui.js')]:
        template = template.replace(marker, Path(__file__).with_name(name).read_text())
    payload = json.dumps(data, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    return template.replace('__REPLAY_DATA__', payload)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.archive, args.output)
