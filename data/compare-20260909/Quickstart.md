# Recorded comparison quickstart and historical deployment notes

## Current offline entry point

Open **[replay.html](../../replay.html)** at the repository root. Use this same
page for Replay and Compare. Live is currently unavailable; no VM or Google
Cloud access is needed for recorded playback. The page embeds a later manual
A/B pair, while the report in this directory describes the earlier acceptance
pair. Exact recording paths are listed in the [data guide](../README.md).

## Present the recorded comparison

1. The default summary window is the competition phase, 80-240 seconds. Start
   with the map and playback controls, then inspect charts, Final summary, and
   Route statistics below.
2. Select `bulk-cross` in Flow and choose First route difference to explain
   rerouting. Then select C2 to examine whether its path stayed unchanged.
3. Blue solid lines indicate Shortest Path, orange dashed lines indicate QoS,
   and gray lines indicate shared segments.
4. Clear Only show differences to inspect complete paths; use 10x playback
   for synchronized review.
5. Use measured RTT, loss, and throughput with the summary to explain benefits
   and costs. Route differences alone do not establish a performance advantage.

The overlays are geographic cell-level routing policies, not packet-captured
satellite paths. Signed negative UDP loss corrections are retained in aggregation;
the charts do not display them as zero loss. Phase-boundary data is not silently
moved into the selected measurement window.

## Historical deployment context

The following describes the September 2026 experiment environment, not a
currently available service or instructions for team members to start Live.

At the original handoff, `http://127.0.0.1:8765/` served a local relay through
an SSH tunnel. The VM controller owned 96 satellites and six ground stations.
Browser Start selected one algorithm and reused manually prepared nodes; it
never recreated them. The operator ran Shortest Path and QoS sequentially,
waited for archival after each run, and imported the resulting JSON files.
Changing views or closing the browser did not stop the VM experiment.
Mac sleep, VM shutdown, or closing the tunnel/relay disconnected Live.
Disconnected or failed sessions required diagnosis rather than repeated Start clicks.

Each run saved ZIP, SHA-256, and replay JSON together under a timestamped
algorithm directory. The timestamp used the first frame's actual wall time in
the relay's local timezone; pre-frame failures used download receipt time.
Failed or incomplete records were retained but excluded from completed comparisons.
The original seven runs were reorganized before later manual recordings were added.
Only one A/B pair was automatically accepted; three-pair repeatability was not claimed.

Historical environment:

- VM: `tinyleo-canada-parity`; project: `satellite-emulator`;
  zone: `northamerica-northeast1-b`.
- VM source: `/home/leo/tinyleo-compare-20260909-v1`.
- Preparation log: `prepare-v6.log` in that source directory.
- Measurement binary: `/home/leo/tinyleo-tools/iperf-3.20/bin/iperf3`, installed
  alongside the original system binary.
- Local logs: `ssh-tunnel.log` and `relay.log` in this directory.
- Session credentials were kept outside recordings in `/Users/leo/.tinyleo-live/`.

The current source defaults future relay downloads to the repository's `data/`
and the browser frontend to root `replay.html`. An existing process retains its
explicit arguments; local compatibility links preserve the former paths on the
developer machine. Old single-flow instructions and historical HTML exports are
retained as references, not alternative team entry points.
