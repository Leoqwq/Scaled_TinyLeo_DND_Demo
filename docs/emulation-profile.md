# Scaled emulation profile

This is the consolidated configuration reference for the recorded Canada demo.
It describes recorded experiments, not a Live deployment guide. Live is currently
unavailable. Open root [replay.html](../replay.html) for offline review.

## Current 300-second multi-flow profile

| Parameter | Value | Evidence |
|---|---|---|
| Satellite nodes | 96 | Recorded time axis and 102-node snapshots |
| Ground stations | 6; total emulated nodes: 102 | Recorded GS1-GS6 positions |
| Satellite altitude | 573 km | Guarded input profile in `tools/prepare_second_run.py` |
| Active region | Grid IDs 12, 13, 14, 23, 24, 25 in an 11 x 11 geographic grid | Scenario and topology validation |
| Recorded time axis | t=0 through t=300 seconds, inclusive | `time-axis.json` |
| Duration / resolution | 300 seconds; 301 states; one state per second | `time-axis.json`, `run-config.json` |
| Startup | Manual node preparation and 15-second SRv6 warmup precede the timed run | `tools/replay/live.py` |
| Orbit model | Circular Kepler orbits, spherical Earth radius 6371 km, 86400-second Earth rotation | `network_synthesizer/second_orbits.py` |
| Orbit anchor | Epoch 5 of the archived 96-satellite profile | Recorded time axis |
| ISL shaping rate | 10 Mbit/s per directed interface | Recorded scenario: 0.01 Gbit/s |
| GSL shaping rate | 100 Mbit/s | Recorded scenario: 0.1 Gbit/s |
| Queue / UDP payload | 1000 packets / 1000 bytes | Recorded scenario |
| Configured random loss | ISL 0%, GSL 0% | Recorded run config; congestion can still cause measured loss |
| Antenna number setting | 1 | Recorded run config |
| Flow measurement | iperf3 3.20 receiver intervals and per-flow ping probes | Recorded provenance and measurement files |
| Routing arms | Upstream-derived `shortest_path` baseline and this fork's `qos_priority` extension | `northbound.py`, runtime adapters |

Rates are deliberately scaled for a single-VM experiment. They are not production
satellite capacities. The older generic config's 200/96 Gbit/s values do not
represent the recorded multi-flow competition profile.

The physical topology and time axis are shared across each paired run. Topology
artifacts are prepared in advance and applied through TinyLEO's actual southbound
and Linux/SRv6 path at one-second intervals. Browser playback speed does not change
the physical time axis. Startup, reporting, and archival make total wall time
longer than the 300-second measurement timeline. No automatic legacy epoch-6
failure injection is part of this multi-flow profile.

## Geographic scope and coverage

| Station | Reference location | Latitude | Longitude | Cell |
|---|---|---:|---:|---:|
| GS1 | Whitehorse | 60.7212 | -135.0568 | 12 |
| GS2 | Yellowknife | 62.4540 | -114.3718 | 13 |
| GS3 | Iqaluit | 63.7467 | -68.5170 | 14 |
| GS4 | Vancouver | 49.2827 | -123.1207 | 23 |
| GS5 | Calgary | 51.0447 | -114.0719 | 24 |
| GS6 | Toronto | 43.6532 | -79.3832 | 25 |

These points and six model cells define a Canada-focused test scenario. They do
not establish continuous coverage of Canada's land area, all Canadian users, or
global service. The inherited grid-based GSL selection does not enforce the
configured elevation cutoff; a 25-degree config field is not proof of radio
line-of-sight compliance. The orbit model is synthetic, not TLE/SGP4 propagation.

Three different measures must remain separate:

1. **Finite-window synthesis coverage:** satisfied modeled demand, calculated as
   `1 - sum(residual_demand) / sum(initial_demand)` over the original 12 epochs.
   Archived 64/80/96-satellite results are **70.00% / 83.75% / 93.75%**.
   All stopped at their satellite caps. The configured 95% target was therefore
   **not reached** by those runs. This is not land-area or radio coverage.
2. **One-second topology validation:** all 301 states pass the recorded validator,
   with 32 topology changes, 36 gateway handovers, and a two-edge-disjoint-path
   epoch ratio of **93.023%**. That ratio is not the synthesis coverage metric.
3. **Measured packet delivery:** receiver throughput/loss and ping samples depend
   on traffic and routing. Connectivity or a passed topology gate does not imply
   lossless delivery or a QoS advantage.

The one-second validation reports **12-14 participating satellites per state**
within the matched regional topology, although all 96 satellite nodes exist.
Its participating-component connectivity must not be described as all 96
satellites belonging to one connected component.

## Experiment host and software

The project records identify one Google Compute Engine **n2-standard-8** VM:
**8 vCPUs and 32 GiB RAM**, hosting the controller and emulated nodes. The deployment
notes identify zone `northamerica-northeast1-b` and VM `tinyleo-canada-parity`.
Nodes use Linux namespaces and emulated filesystem roots; they are not 102 cloud VMs.

The runbook specifies Ubuntu 22.04 or later, Linux networking tools, Python,
SRv6 support, and generated gRPC modules. The multi-flow archives record iperf3
**3.20 (cJSON 1.7.15)**. The exact deployed OS image, kernel, Python/package lock,
CPU model, and disk size/type are not established by the published v2 run metadata;
do not treat the runbook's requirements as a measured environment inventory.

For the pair embedded in the frontend:

| Recorded telemetry | Shortest Path | QoS Priority |
|---|---:|---:|
| Completed states | 301 | 301 |
| Deadline misses | 0 | 0 |
| Maximum topology apply time | 0.7874 s | 0.8294 s |
| Peak sampled host used memory | 9.169 GiB | 9.197 GiB |

Memory is sampled whole-host usage, not a minimum RAM requirement or per-process
memory figure. The earlier single-flow run's 9.07 GiB result belongs to a different
experiment and must not be substituted for this pair.

## Traffic and schedule

| Flow | Priority | Endpoints | Offered UDP rate | Active interval | Port |
|---|---:|---|---:|---|---:|
| c2-north | 5 | GS1 to GS3; cells 12 to 14 | 4 Mbit/s | 20 <= t < 290 s | 5201 |
| telemetry-east | 3 | GS2 to GS6; cells 13 to 25 | 2 Mbit/s | 20 <= t < 290 s | 5202 |
| bulk-cross | 1 | GS1 to GS6; cells 12 to 25 | 9 Mbit/s | 80 <= t < 240 s | 5203 |

- 0-20 s: convergence/probe warmup; no workload benefit claim.
- 20-80 s: C2 and telemetry baseline.
- 80-240 s: three-flow competition; the default summary window is 160 seconds.
- 240-290 s: bulk stops; recovery observation.
- 290-300 s: traffic drain and final observations, including the t=300 state.

Both arms use the same shaping, packet sizes, and schedules. QoS is a routing
policy comparison, not a preferential DSCP or priority-queue configuration.
Late receiver packets can reduce signed loss counters. Boundary-crossing intervals
and unassignable final tail bytes are excluded from phase summaries rather than
invented or redistributed.

## Evidence and historical profiles

The [data guide](../data/README.md) separates the embedded later manual pair from
the earlier formally accepted single pair. The latter's report does not describe
the embedded pair's measurements. More archived runs do not automatically establish
formal repeatability acceptance.

Primary evidence for this profile is inside the embedded pair's
[Shortest Path ZIP](../data/2026-09-08_20-28-45_shortest_path/336d637ad4df45aeb2bf4533187db122.zip)
and [QoS ZIP](../data/2026-09-08_20-34-51_qos_priority/3b0768e620924df4acb4437a5116e6d8.zip):
`time-axis.json`, `run-config.json`, `scenario.json`, `replay.json`, and
`inputs/validation/validation_report.json`.

Synthesis figures come from the archived
[64-node](../data/canada-parity-20260901T232741Z/scale-64/synthesis_summary.json),
[80-node](../data/canada-parity-20260901T232741Z/scale-80/synthesis_summary.json), and
[96-node](../data/canada-parity-20260901T232741Z/scale-96/synthesis_summary.json) summaries.
Host identity comes from the [one-second record](second-resolution-emulation.md),
[historical runbook](canada-parity-runbook.md), and
[deployment notes](../data/compare-20260909/Quickstart.md).

The older 12-epoch profile used legacy sampled positions and a separate failure/
recovery workflow. It is not a 12-second version of this physically propagated
300-second scenario. Legacy v1 single-demand archives also differ from v2 multi-flow
recordings. See [changes from upstream](upstream-changes.md) for implementation scope.
