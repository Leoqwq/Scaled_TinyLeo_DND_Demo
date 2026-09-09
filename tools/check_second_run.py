"""Summarize deadline and packet evidence from a completed one-second run."""
import argparse
import json
import re
from pathlib import Path


def check(run):
    rows = [json.loads(line) for line in (run / 'telemetry.jsonl').read_text().splitlines()]
    summary = json.loads((run / 'summary.json').read_text())
    ping = (run / 'ping-continuous.txt').read_text()
    match = re.search(r'(\d+) packets transmitted, (\d+) received,.*?([\d.]+)% packet loss', ping)
    exact_axis = [r['simulation_time_s'] for r in rows] == list(range(summary['expected_epochs']))
    durations = sorted(r['apply_duration_s'] for r in rows)
    result = dict(summary, exact_second_axis=exact_axis,
                  p50_apply_s=durations[len(durations)//2],
                  p95_apply_s=durations[min(len(durations)-1, int(len(durations)*.95))],
                  final_wall_elapsed_s=rows[-1]['wall_elapsed_s'],
                  max_start_lateness_s=max(r['start_lateness_s'] for r in rows),
                  peak_used_gib=max(r['system_memory_used_bytes'] for r in rows)/1024**3,
                  peak_swap_bytes=max(r['swap_used_bytes'] for r in rows),
                  continuous_ping={'transmitted': int(match[1]), 'received': int(match[2]),
                                   'loss_percent': float(match[3])} if match else None)
    result['timing_and_connectivity_pass'] = (exact_axis and summary['valid_realtime']
        and match is not None and int(match[2]) > 0)
    (run / 'checked-summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    args = p.parse_args()
    raise SystemExit(0 if check(args.run)['timing_and_connectivity_pass'] else 1)
