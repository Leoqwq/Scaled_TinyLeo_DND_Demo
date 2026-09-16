# Consolidated changes from upstream TinyLEO

This document summarizes the substantive changes present in this fork, including
the pre-existing work captured in the initial local checkpoint. The comparison
baseline is upstream commit **`bd5dc9711f1d509812db2cf6d3c8bc6de331d1bb`** (`update: artifacts`).
The reviewed fork baseline for this inventory is **`ddfda68`**. Later documentation
commits add this consolidated explanation. Git history remains the exact file-level record.

For experiment parameters, hardware, geographic scope, and coverage definitions,
see [Scaled emulation profile](emulation-profile.md). For offline use, open root
[replay.html](../replay.html). Live is currently unavailable.

## Attribution boundary

TinyLEO supplies the network synthesis approach, orbital MPC architecture,
southbound framework, and geographic SRv6 forwarding design. This fork adapts
and extends that implementation; it does not claim those foundations as new work.

In particular, **`qos_priority` is an addition in this fork**, not a stock upstream
routing mode. The earlier phrase “existing northbound algorithms” in development
notes refers to the algorithms already present in the local checkout at that
stage, including this extension. The Shortest Path baseline remains derived from
upstream's density-weighted routing, not a new satellite-level minimum-RTT solver.

## Changes by subsystem

| Area | Additions or changes | Main source / evidence |
|---|---|---|
| Priority-aware routing | Added `qos_priority`, priority-ordered demand processing, bandwidth reservations, delay/risk/utilization costs, empty-cell rejection, latency-budget/fallback status; default unspecified routing now selects QoS | [`northbound.py`](../network_orchestrator/northbound.py) |
| Routing analysis and GUI | Added interactive routing exploration, shortest/QoS comparisons, priority and avoidance variants, capacity checks, sample configs and saved results | [`test/`](../network_orchestrator/test/) including `routing_gui.py`, `compare_qos_routing.py`, `compare_scenarios.py` |
| Finite regional synthesis | Explicit 12-epoch windows, six-cell region, bounded 64/80/96-node candidate profiles, sparse window textures, capped matching pursuit, residual/coverage/stop-reason output | [`window_config.py`](../network_synthesizer/window_config.py), [`windowed_texture.py`](../network_synthesizer/windowed_texture.py), [`windowed_synthesizer_mp.py`](../network_synthesizer/windowed_synthesizer_mp.py) |
| Synthesis correctness and export | Linear phase-slot progression, retained position sequences, scalar coverage gain, selected-candidate exports with consistent satellite/grid/traffic inputs | [`orbital_texture_generator.py`](../network_synthesizer/orbital_texture_generator.py), [`synthesizer_mp.py`](../network_synthesizer/synthesizer_mp.py), [`canada_parity_artifacts.py`](../network_synthesizer/canada_parity_artifacts.py) |
| Topology validation | Schema and cross-file checks, finite positions and identities, physical matched connectivity, path diversity, topology churn and gateway handovers, explicit failed acceptance | [`topology_artifact_validator.py`](../network_orchestrator/topology_artifact_validator.py), [`validator CLI`](../network_orchestrator/test/validate_topology_artifacts.py) |
| MPC and time-window isolation | Configurable source start/count, consistent locally numbered snapshots, finite-horizon output, failure recovery using the configured topology | [`sn_orchestrator_mpc.py`](../network_orchestrator/sn_orchestrator_mpc.py), [`utility_functions.py`](../network_orchestrator/utility_functions.py), [`failure_recovery_mpc.py`](../network_orchestrator/failure_recovery_mpc.py) |
| Single-VM runtime reliability | Loopback deployment configuration, explicit Python/SSH paths, propagated worker and command failures, target-root SRv6 agent launch, startup acknowledgments, resource/timing evidence and controlled cleanup | [`southbound/`](../network_orchestrator/southbound/), [`geographic_srv6_anycast/`](../network_orchestrator/geographic_srv6_anycast/), [`Canada runner`](../network_orchestrator/test/example_canada_parity.py) |
| Runtime link/route updates | Wait for route readiness, retain physically valid gateways, deduplicate topology events, apply link-delay decreases and precision-level changes | Southbound controller/remote utilities and SRv6 helpers above |
| Physical one-second trajectory | Circular-orbit propagation with Earth rotation, synthetic anchor validation, 301 states, monotonic deadlines without hidden time shifts, independent probes and telemetry | [`second_orbits.py`](../network_synthesizer/second_orbits.py), [`second_clock.py`](../network_orchestrator/second_clock.py), [`tools/`](../tools/) |
| Prepared-session control and local relay | Explicit manual preparation, serialized runs, token-protected loopback APIs, SSH-tunnel relay, archive hash verification and retry, run folders by local recording time | [`live.py`](../tools/replay/live.py), [`live_server.py`](../tools/replay/live_server.py) |
| Multi-flow competition | Validated unique endpoint pairs and phases, actual active physical-gateway capacity, shared-topology feasibility checks, opt-in three-flow scenario | [`scenario.py`](../tools/replay/scenario.py), [`competition.py`](../tools/replay/competition.py), [`check_competition.py`](../tools/replay/check_competition.py) |
| Packet measurement and kernel evidence | Owned iperf/ping lifecycle, iperf3 3.20 receiver JSON, aligned timestamps, phase-boundary kernel counters/routes/queues, retained failure evidence | [`traffic.py`](../tools/replay/traffic.py), [`evidence.py`](../tools/replay/evidence.py) |
| Measurement correctness | Preserve signed late-packet loss corrections, retain forwarding while flows drain, allow bounded receiver-report grace, distinguish missing values and incomplete coverage | Traffic, competition, archive, and comparison modules |
| Versioned records and comparisons | Legacy replay support plus v2 scenario/runtime/physical/time-axis hashes, completion eligibility, receiver-based statistics and matched-pair validation | [`competition_archive.py`](../tools/replay/competition_archive.py), [`compare.js`](../tools/replay/compare.js) |
| Unified browser frontend | Offline Replay/Compare, one shared route map, flow/time/phase selection, synchronized playback, throughput/loss/RTT plots, final summaries and tradeoffs | [`replay.html`](../replay.html), [`seconds.html`](../tools/replay/seconds.html), [`compare_ui.js`](../tools/replay/compare_ui.js) |
| Team delivery | Original archives moved into root `data/`, run index and SHA-256 manifest, English guides, TinyLEO attribution, root frontend, repository-relative relay defaults | [`data/`](../data/README.md), [`README`](../README.md), relay and documentation |

The table groups behavior changes rather than counting formatting-only edits as
new features. The initial checkpoint also includes saved offline outputs and
local-environment changes. Some inherited tracked cache files remain in history;
those are not scientific contributions or required demo inputs.

## Main design constraints retained

- Both routing arms reuse the same physical constellation and time axis.
- The original destination-based SRv6 mechanism cannot assign independent policies
  to multiple service classes with the same endpoint pair. The demo uses distinct pairs.
- Capacity is derived from usable active gateways, not all nominal parallel links.
  Unverified parallel/asymmetric capacity and reverse-direction reservation conflicts
  are rejected rather than silently counted as valid congestion experiments.
- QoS changes routing and reservation decisions; it does not add a preferential
  packet scheduler or DSCP class.
- Browser frames and model paths are not fabricated packet traces. Raw measurement
  outputs and failures remain available for inspection.
- The new orbit model is circular and synthetic. GSL visibility and coverage
  limitations are documented in the emulation profile.

## Development milestones

| Milestone | Representative commits |
|---|---|
| Initial local routing/GUI work checkpoint | `53d0e86` |
| Offline validator and bounded regional synthesis | `901f2c9`, `9e3dfcb`, `7e50028`, `29d23fb`, `56b73e5` |
| Finite-window runtime and acceptance hardening | `ff35232`, `b879a3b`, `c044ed5`, `8432a7a`, `bacb008`, `44d0697` |
| Gateway/event and one-second updates | `1e135b6`, `437b4b6`, `681fa43`, `a712975` |
| Historical replay and prepared Live interface | `32f35c9`, `cebd276` |
| Multi-flow feasibility, measurement, archives, and UI | `96971f9`, `e1dbfa3`, `12c8dcc`, `a8aedda` |
| Real-run loss/drain/report corrections | `04b68d3`, `b8b0ed1`, `729017e` |
| Single-pair evidence and delivery | `20dc22a`, `0effb31`, `5847e85` |
| Unified root frontend, defaults, and English docs | `ddfda68` |

To inspect the exact cumulative changes from the fixed upstream baseline:

```sh
git log --oneline bd5dc9711f1d509812db2cf6d3c8bc6de331d1bb..HEAD
git diff --name-status bd5dc9711f1d509812db2cf6d3c8bc6de331d1bb..HEAD
git diff -w bd5dc9711f1d509812db2cf6d3c8bc6de331d1bb..HEAD -- network_orchestrator network_synthesizer tools
```

## What the evidence establishes

The earlier single-flow timing run and one formally accepted multi-flow A/B pair
have separate dated evidence. The frontend embeds a later manual pair. Local
regression tests validate software contracts; they do not certify a newly deployed
VM. No current Live availability, universal QoS superiority, full-country radio
coverage, or completed formal multi-pair repeatability study is claimed.

Read the [profile](emulation-profile.md), [recording guide](../data/README.md), and
[dated progress record](superpowers/plans/2026-09-08-live-qos-progress.md) together.
