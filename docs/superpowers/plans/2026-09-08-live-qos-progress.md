# QoS implementation checkpoint — 2026-09-08

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

Tasks 4–8 remain unfinished: traffic lifecycle, v2 runtime/archive integration,
comparison math, single-map Compare UI, and VM A/B acceptance. No new prepared
session was created, no live emulation was started, and the user's current
HTML/VM service has not been replaced. The candidate is locked for the next
measurement trial only; its QoS performance advantage is not yet validated.
