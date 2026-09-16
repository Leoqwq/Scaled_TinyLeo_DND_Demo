# QoS implementation checkpoint — 2026-09-08

> Historical paths and frontend filenames below describe the original delivery.
> The published frontend is now root [replay.html](../../../replay.html);
> recordings are under [data/](../../../data/README.md). Live is currently unavailable.

## Completed: first implementation batch

The user requested pre-existing changes be committed by responsibility and
development continue in the current directory. Baseline commits:

- `3fa5ba1`: ignore local Python caches/environments.
- `681fa43`: apply second-resolution link delay changes.
- `a712975`: second-resolution orbit/clock and run tools.
- `32f35c9`: historical standalone replay.
- `cebd276`: browser Live and second-resolution replay.
- `1166c67`: approved design and implementation plan.

Baseline verification: six existing Live unit tests and two orbit/clock tests
passed. The full Linux-dependent Canada integration suite was not run on the
Mac; these baseline commits preserve prior work, not a new full VM certification.

Tasks 1–3 now have a local implementation:

- `tools/replay/scenario.py`: strict scenario/GS mapping validation, unique
  unordered cell pairs and ports, finite rates, half-open phase scheduling.
- `tools/replay/competition.py`: multi-demand adaptation using the existing
  northbound algorithms; actual single-gateway capacities, physical adjacency,
  explicit failure on parallel unverified gateways or reverse-direction
  reservation conflicts; no modification to the old Live controller.
- `tools/replay/check_competition.py`: read-only full 301-epoch ZIP checker,
  complete decisions, reservations, bottleneck evidence, hashes and gate report.

The implementation supplies actual edge capacities locally; it does not
modify `network_orchestrator/northbound.py` or its offline default behavior.

## Real-snapshot feasibility results

Source: `TinyLeo_CA/outputs/53464db9114943deb01df8c22d7ebb4b.zip`.
Both candidates retain the spec's original rates; no calibration was needed.

| Result | C2 + bulk | C2 + telemetry + bulk |
|---|---:|---:|
| Evaluated physical epochs | 301 | 301 |
| Competition epochs | 160 | 160 |
| Alternate corridor available | 160 | 160 |
| Lower-priority routing differs | 139 | 139 |
| Shared overload reduced in model | 139 | 139 |
| Error epochs | 0 | 0 |
| Offline feasibility gate | PASS | PASS |
| Real performance validated | NO | NO |

The observed difference fraction is 86.875%. This is a route/capacity-model
result on real recorded topology, **not measured throughput, latency or loss**.
The full reports are retained locally (ignored by Git):

- `tools/replay/results/20260908-two-flow-feasibility-v2.json`
- `tools/replay/results/20260908-three-flow-feasibility-v2.json`

Initial reports without `-v2` are retained for audit. They failed because the
new adapter initially rejected `sat_cell: []`, the actual representation of
out-of-region satellites. A regression test and compatible input handling
corrected that parser issue; those reports were not failed traffic candidates.

Source inspection also corrected the design's baseline description:
`shortest_path` uses density-weighted edge costs, not pure hop count. On the
six-cell test fixture it chooses bulk 12→13→24→25, while QoS chooses
12→23→24→25. C2 remains 12→13→14. Existing weights and tie-breaking are unchanged.

## Verification commands

An isolated Python environment exists at `/tmp/tinyleo-qos-venv`; it is temporary.
Dependencies for this batch are numpy and networkx. Do not use the system Python
without checking them. Reproduction:

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/tinyleo-qos-venv/bin/python -m unittest discover -s tools/replay -p test_competition.py -v
PYTHONDONTWRITEBYTECODE=1 /tmp/tinyleo-qos-venv/bin/python -m unittest discover -s tools/replay -p test_live.py -v
```

The existing Live HTTP test needs permission to bind a random loopback port.
The checker accepts `--two-flow` and writes output exclusively: use a fresh
output filename on each run so old evidence is not overwritten.

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/tinyleo-qos-venv/bin/python tools/replay/check_competition.py \
  /Users/leo/Desktop/Obsidian/Satellite/TinyLeo/TinyLeo_CA/outputs/53464db9114943deb01df8c22d7ebb4b.zip \
  --output /tmp/tinyleo-three-flow-new-report.json
```

## Next batch: real traffic and Compare data

VM read-only inspection found iperf3 3.9 with `--forceflush` and `--timestamps`,
but no documented JSON streaming mode. A separate 2-second, 1 Mbit/s host
loopback format probe on port 61983 succeeded; it did not use emulation nodes
or modify the prepared controller. Its processes exited afterward.

The receiver's text output has one-second packet/loss/jitter intervals but
rounded transfer sizes and interval boundaries. The client final JSON contains
sender intervals and embedded receiver text; do NOT label sender intervals as
receiver throughput. Task 4 must handle this precision limitation explicitly,
using the recorded payload size/packet evidence and clear precision/provenance,
or a validated exact receiver collection method before final metric acceptance.
Do not assume `-J` alone streams real-time receiver JSON on this version.

## Second implementation batch: local implementation, VM acceptance pending

Tasks 4–7 now have local implementations:

- Owned receiver/sender/probe lifecycle with raw logs, exact receiver JSON
  intervals and millisecond wall-clock alignment. New competition mode requires
  iperf3 **3.20 or newer**; VM 3.9 is rejected before node preparation. Install
  a separate binary and pass `--iperf-binary`; do not replace the system binary.
- Explicit `--competition-scenario` opt-in; the original single-demand mode
  remains available. Version-2 archives include per-flow measurements, events,
  scenario, physical/time-axis/runtime hashes and completion eligibility.
- Asynchronous read-only kernel routes, qdiscs and interface counters at phase
  boundaries and policy changes. These captures are evidence for manual review,
  not automatic certification of kernel convergence.
- Offline comparison math: raw receiver packet-weighted loss, exact-byte
  throughput, successful-ping p95, coverage and boundary exclusions. Missing
  values stay unknown. Scenario/provenance mismatches reject comparison.
- English Compare mode: final summary, directed shared-map route overlay,
  per-flow selection, difference-only display, synchronized seek/playback,
  phase jumps and three measurement charts. Live polling/download continues
  while Compare is open. Live/Replay also display per-flow receiver samples.

Local verification: 41 Python tests passed. The pure JavaScript comparison
tests and Chrome suites for Compare, Live and historical 301-frame Replay
passed. Browser fixtures verify behavior only, not QoS performance.

Development build: `/tmp/tinyleo-compare-dev.html`. The user-facing HTML and
VM service have not been replaced. Read-only VM inspection still found the old
prepared `tinyleo-live-demo` service and iperf3 3.9; gcc and make are present.

Task 8 remains: safe VM handover, side-by-side iperf upgrade, namespace traffic
smoke test, kernel shaping/forwarding review, then matched real A/B recordings
and repeatability acceptance. No new multi-flow emulation has run on the VM.
The candidate's measured QoS advantage is **not yet validated**.

## VM handover and single-pair acceptance — 2026-09-08 (local time)

The statements above describe the earlier checkpoint. The user subsequently
authorized VM handover and reduced acceptance from three automatic pairs to
**one successful A/B pair**, leaving repetition to manual browser runs.

Deployment: `/home/leo/tinyleo-compare-20260909-v1`, preparation log
`prepare-v6.log`; independent iperf3 3.20 binary under
`/home/leo/tinyleo-tools/iperf-3.20`. Fresh protobuf modules were generated
according to the upstream deployment instructions. Old source and all run
files remain preserved. Only validated old namespace init PIDs were retired.

Integration discoveries and fixes:

- Real out-of-order UDP arrivals generate signed negative interval loss
  corrections. Preserve them; never clip them to zero.
- Retain physically valid routing during flow teardown, without continuing
  its bandwidth reservation or declaring it an active demand.
- The original 5-second report timeout was too short: in the successful
  shortest run, bulk returned its real final receiver report at t=246.116 s.
  Report exchange now has a bounded 30-second grace; missing reports or
  abnormal process exits remain failures. The 301-state topology clock and
  80–240 s comparison window are unchanged.

Three failed attempts (88, 245, 245 frames) are retained separately and are not
included in the accepted pair. Their run IDs are listed in the delivered report.

Accepted records:

| Algorithm | Run ID | Frames | Deadline misses | Maximum apply time |
|---|---|---:|---:|---:|
| shortest_path | 27241ed67b124bec98114f5acba5c3fc | 301 | 0 | 0.8173 s |
| qos_priority | dac7c802b96343fb992c4ade04924066 | 301 | 0 | 0.8077 s |

Both archives passed SHA-256 checks, normal sender/receiver end-event checks,
signed loss-total reconciliation, 301-frame physical-state equality, shared
scenario/runtime/time-axis provenance checks and kernel evidence command checks.
Receiver interval totals omit a few final tail bytes (up to 2000 bytes); those
bytes remain in raw final totals and are not assigned to a phase. Completed
interval coverage is approximately 159/160 seconds after boundary exclusions.

Competition-window C2: loss 46.239% → 6.331%, p95 ping RTT 2505 → 140 ms,
received throughput 2.116 → 3.747 Mbit/s. C2 routes are unchanged; bulk routes
differ in 139/160 competition states. Telemetry p95 worsened 1331 → 2113 ms,
and bulk p95 worsened 2653 → 2946 ms; the UI/report retain these tradeoffs.
This meets the visible-improvement magnitude for **this pair**, not the
superseded three-pair repeatability gate or a universal superiority claim.

Delivery directory:
`/Users/leo/Desktop/Obsidian/Satellite/TinyLeo/TinyLeo_CA/outputs/compare-20260909`.
Contains the bundled `tinyleo-compare.html`, both accepted replay JSON/ZIP/hash
sets, failed archives, `acceptance-runs.json`, `acceptance-report.md`, and
`Quickstart.md`. Browser URL remains `http://127.0.0.1:8765/`.

Actual browser verification: bundled Summary loads, bulk routes overlay on one
map, 10× playback advances real shared states, first-difference seek works,
and Live shows completed + Archive saved with Start enabled. The browser was
left paused in Compare. Automatic acceptance scripts exited; only the prepared
VM service, SSH tunnel and local relay remain for the user's manual runs.
Local regression: 46 Python tests and all three Chrome suites passed.
