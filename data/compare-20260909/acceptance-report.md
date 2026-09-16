# TinyLEO single-pair real A/B acceptance

This historical acceptance used one successful automated A/B pair; further
repeatability was left to manual experiments. The results are measured
emulation outcomes, not offline algorithm estimates.

- Shortest Path: `27241ed67b124bec98114f5acba5c3fc`
- QoS Priority: `dac7c802b96343fb992c4ade04924066`

The fixed measurement window is 80 <= t < 240 seconds. Both recordings contain
301 complete frames, with matching per-frame positions, links, scenario,
time axis, and recorded runtime-code hashes.

| Flow | Metric | Shortest Path | QoS Priority | QoS − Shortest |
|---|---|---:|---:|---:|
| c2-north | UDP loss (%) | 46.239 | 6.331 | -39.908 |
| c2-north | ping p95 RTT (ms) | 2505.000 | 140.000 | -2365.000 |
| c2-north | received throughput (Mbit/s) | 2.116 | 3.747 | 1.631 |
| telemetry-east | UDP loss (%) | 34.570 | 34.237 | -0.333 |
| telemetry-east | ping p95 RTT (ms) | 1331.000 | 2113.000 | 782.000 |
| telemetry-east | received throughput (Mbit/s) | 1.305 | 1.307 | 0.002 |
| bulk-cross | UDP loss (%) | 33.274 | 12.188 | -21.087 |
| bulk-cross | ping p95 RTT (ms) | 2653.000 | 2946.000 | 293.000 |
| bulk-cross | received throughput (Mbit/s) | 5.919 | 7.813 | 1.894 |

- c2-north: routes differ in 0/160 frames; receiver interval coverage is
  159.000/160.000 seconds and 159.000/160.000 seconds.
- telemetry-east: routes differ in 0/160 frames; coverage is
  159.000/160.000 seconds and 159.000/160.000 seconds.
- bulk-cross: routes differ in 139/160 frames; coverage is
  159.001/160.000 seconds and 159.001/160.000 seconds.

This pair met the predefined visible-improvement magnitude. It is neither
three-pair repeatability acceptance nor a universal superiority conclusion.

UDP loss aggregates signed receiver-counter deltas, retaining late-packet
corrections. RTT p95 uses raw successful ping samples. Intervals crossing a
phase boundary are not apportioned into that window; final-report tail bytes
that cannot be assigned precisely to an interval are not added to phase totals.

Map overlays show cell-level SRv6 routing intent, not packet-captured satellite
hop traces. Raw queue, route, interface-counter, and traffic logs remain in ZIP archives.

Failed attempts `0db3736821654266b2a1e94062699ca4`,
`d4dc989dec5543c999965d8851e7a021`, and `a213412edab84fd4a42126029bb693f6`
are retained and excluded from this summary.

To reproduce these figures, open [replay.html](../../replay.html) and import the
acceptance pair listed in the [data guide](../README.md). The frontend's default
embedded pair is a later manual run pair and has different measurements.
