# One-second Canada emulation

## Verified run: 2026-09-05

On the existing n2-standard-8 VM, shortest routing completed 301 states (t=0..300)
with zero one-second deadline misses. Last state completion: 300.634 seconds.
Update p50: 0.630 s; p95 (nearest-rank sample): 0.691 s; maximum: 0.762 s.
Maximum start lateness: 1.98 ms. Sampled peak host memory: 9.07 GiB; swap: zero.
Continuous one-second ping: 304 sent, 289 received (4.93% loss), including the
brief measurement-drain period after the last update. This is timing feasibility
and observed connectivity, not a claim of lossless forwarding or QoS acceptance.
No synthetic failure was injected in this full timing run.

Offline validation checked all 301 states: zero errors, 32 topology changes,
36 inter-cell gateway changes and 93.0% of frames passing the two-edge-disjoint
path requirement. It uses the existing grid-based GSL selection policy, whose
elevation cutoff is not enforced in the inherited code; this run does not certify
all aspects of radio visibility. It validates the new physical time axis and
actual per-second link updates under that inherited policy.

Evidence on the VM:
`/home/leo/tinyleo-runs/seconds-20260905/live-shortest-1788654765058048796/checked-summary.json`.
The dedicated source checkout is `/home/leo/tinyleo-seconds-work-20260905`.

This workflow supersedes the old 12-snapshot profile for temporal-resolution
testing. It uses 301 physical states at t=0..300 seconds. Startup and the
15-second SRv6 warmup occur before the timed run. No animation interpolation
or time acceleration is used in these inputs.

## Generate and validate offline

```sh
python tools/prepare_second_run.py /path/to/archived/scale-96 /path/to/new-run --duration 300
```

The exporter retains the archived 96 satellites and anchors them at archived
epoch 5 by default. It advances circular orbits using Kepler angular speed and
subtracts Earth's rotation (86400 seconds). This corrects the backbone texture
generator's use of orbital angular speed for Earth rotation. It does not use
SGP4 or add perturbations. The anchor is a synthetic configuration, not a TLE
timestamp. The exporter checks that the orbital phase reproduces anchor latitude.

The new directory contains `time-axis.json`, `artifacts/`, and `topology/`.
Run `network_orchestrator/test/validate_topology_artifacts.py` with these inputs
and `--expected-epochs 301` before deploying. Topology quality can change with
window duration or anchor; do not reuse a validation report from another run.

## Run on the existing Linux VM

```sh
sudo /home/leo/tinyleo-venv/bin/python tools/run_second_emulation.py \
  /path/to/new-run /path/to/existing/local-vm/config.json --limit 20
```

Remove `--limit 20` for the full run. Use `--mode geographic` for the geographic
policy. The template provides the existing loopback SSH key, remote Python,
link bandwidth/loss, and failure-service settings. This runner requires the
existing single-VM Linux namespace deployment; do not run two instances together.

MPC artifacts are computed before the timed run and replayed through the actual
TinyLEO southbound/kernel path every second. A deadline is measured from an
absolute monotonic origin; slow updates are reported, never hidden by moving
the next deadline. Link-delay commands now include decreases and changes at
the existing 0.01-ms output precision, instead of only increases above 1 ms.

`live-<mode>-<timestamp>/telemetry.jsonl` flushes one JSON record per applied
state. It records simulation time, elapsed wall time, update duration, deadline
misses and memory. `ping-continuous.txt` records one ping per second independently.
Additional ping/iperf/traceroute batches run on one separate worker and can span
multiple topology epochs; filenames identify their start epoch, not a static
measurement window. The runtime directory contains the original node snapshots,
ISL/GSL commands and packet outputs. `summary.json` checks timing completion;
it is not a substitute for packet-delivery or topology-quality validation.

This runner starts the configured failure service but does not automatically
inject the legacy epoch-6 failure. Use `--failure-second 150` to request an
explicit mid-run ISL failure. The failure operation counts against that second's
deadline and can produce a reported miss; do not interpret it as subsecond
data-plane recovery without packet evidence. The current HTML embeds the recorded
301-state run and also includes a Live tab. The new Live runner has separate
integration/timing acceptance requirements; see tools/replay/LIVE.md.
