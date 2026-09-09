# Live QoS Competition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Work inline; do not delegate without user approval.

**Goal:** Produce matched real multi-flow emulation archives and an offline-first Summary + synchronized single-map Compare mode.

**Architecture:** A validated scenario and physical-capacity adapter feed existing northbound policies. A run-owned traffic collector records receiver measurements independently of the topology clock; versioned archives feed pure comparison functions and the existing HTML. Offline feasibility gates deployment, and VM acceptance gates performance claims.

**Tech Stack:** Python 3.10-compatible standard library, existing numpy/networkx northbound, Linux namespaces/SRv6/netem, iperf3 UDP/ping, standalone HTML/JS/canvas, unittest and Node/Playwright.

**Spec:** `docs/superpowers/specs/2026-09-08-live-qos-competition-design.md`

## Global Constraints

- Preserve 96 satellites, six GS nodes, the validated 301-state time axis, one-second topology updates.
- Runtime algorithms remain `shortest_path` and `qos_priority`.
- No preferential DSCP/priority queue for QoS.
- Do not sum every physically present link unless forwarding can distribute traffic over those links.
- Missing measurements remain unknown, with coverage visible.
- Do not build a dual-map layout or a single/dual-map switch in the first version.
- Never interrupt a user-started run; current deployed service remains unchanged during local development.
- Preserve existing dirty files and historical archives; stage only task-owned changes after reviewing the diff.

## File boundaries and execution checkpoints

Progress/evidence: `2026-09-08-live-qos-progress.md` in this directory. Tasks
1–3 implemented and locally verified; Tasks 4–8 pending. Work continues in
the current directory at the user's request after responsibility-based baseline
commits. No worktree or subagent is needed.

1. `scenario.py`, `competition-routing.json`: validated demands, phases and shaping.
2. `competition.py`: physical graph, capacity injection, multi-policy conversion; does not launch processes.
3. `check_competition.py`: read ZIP snapshots, run existing algorithms, report feasibility and hashes.
4. `traffic.py`: process ownership, iperf/ping parsing, timestamped measurements.
5. `competition_archive.py`: versioned records, provenance and summary inputs.
6. `compare.js`: pure comparison/summary functions, embedded at build time for offline HTML.
7. `seconds.html`: Compare controls, map overlays and plots; existing single Replay remains supported.

All new modules live under `tools/replay/`. Tests use `test_competition.py`,
`test_traffic.py`, `test_competition_archive.py`, `test_compare.cjs` and
`test_compare_browser.cjs` in the same directory.

### Task 1: Validated multi-demand scenario

**Files:** Create `tools/replay/scenario.py`, `tools/replay/competition-routing.json`, `tools/replay/test_competition.py`.
**Interfaces:** `validate_scenario(config: dict) -> dict`; `active_demands(config: dict, second: float) -> list[dict]`; `phase_at(second: float) -> str`. Input demands retain northbound source/destination/demand_gbps/priority; add id, source_gs, destination_gs, start_s, end_s, port. Shaping uses `isl_gbps`, `gsl_gbps`, packet size and queue limit.

- [x] Write real validation tests. Literal boundary expectations:
  ```python
  self.assertEqual([d['id'] for d in active_demands(config, 19)], [])
  self.assertEqual([d['id'] for d in active_demands(config, 20)], ['c2-north', 'telemetry-east'])
  self.assertEqual(len(active_demands(config, 80)), 3)
  self.assertEqual(len(active_demands(config, 240)), 2)
  self.assertEqual(active_demands(config, 290), [])
  ```
  Reject reverse duplicate cell pairs, duplicate IDs/ports, wrong GS mappings,
  nonfinite/nonpositive rates, unknown keys affecting unsupported route weights,
  and invalid phase bounds. Work from deep copies; input must not mutate.
- [x] Run `python -m unittest discover -s tools/replay -p test_competition.py -v`; observe missing feature failure.
- [x] Implement pure validation and phase scheduling. Initial rates and endpoints are those in the spec. Canonical JSON must omit algorithm when hashing shared inputs.
- [x] Rerun tests. Commit only these new files after reviewing changes.

### Task 2: Actual-capacity multi-flow routing

**Files:** Create `tools/replay/competition.py`; extend `test_competition.py`. Preserve old `live.py:RoutingAdapter` until the new runtime is ready.
**Interfaces:** `PhysicalGraph(states: dict, capacity_gbps: float)` exposes adjacency, density and `capacity(a,b)`; `CompetitionRouter(config: dict, algorithm: str).choose(states: dict, second: float) -> dict` returns phase, flows, policy, edge_capacity_gbps and directed_load_gbps.

- [x] Add hand-checked six-cell ladder fixture with a single physical gateway on each boundary. Assert 2–3 satellites do not multiply a single gateway's capacity.
- [x] Add tests rejecting asymmetric links, parallel unverified gateways, missing routes, opposite-direction sharing, unknown algorithms and stale-path reuse. Assert aggregate policies contain every active demand and original input config is unchanged.
- [x] Assert C2 route `[12,13,14]` and equal-hop bulk alternatives are selected by actual imported `TinyLEONorthboundAPI`, not a mock solver. Mutations to priority ordering/reservations should fail this test.
- [x] Run tests red. Implement localized capacity/neighbor input injection, keeping the original northbound weight/risk/priority/fallback code. Validate every returned path against active physical adjacency and unique unordered GS pairs.
  ```python
  api.get_neighbors = lambda cell: sorted(graph.adjacency.get(cell, ()))
  api._edge_capacity_gbps = graph.capacity
  api.grid_density = graph.density
  api.generate_traffic_matrix()
  ```
  The actual implementation must preserve original input and serialize capacities with stable edge keys; no solver rewrite.
- [x] Rerun all competition tests and the six old Live contract tests. Record any baseline dependency failures separately from regressions.

### Task 3: Full-epoch feasibility report (gate)

**Files:** Create `tools/replay/check_competition.py`; extend `test_competition.py`. Output a new report under `tools/replay/results/`, never overwrite historical archives.
**Interfaces:** `check_archive(archive: Path, config: dict) -> dict`; CLI accepts archive, `--scenario`, `--output`.

- [x] Test ZIP fixtures for missing/duplicate epochs and invalid snapshots; verify no archive member extraction to disk. Test threshold calculations with literal counts (80/160 differs = 50%).
- [x] Run tests red; implement sequential reads of snapshots 0..300, both algorithms at each timestamp, complete path/fallback/edge-load evidence and shared input hashes.
- [x] Derive alternate-corridor availability by removing a contested directed boundary from the baseline route and checking connectivity; do not equate every path difference with a bottleneck improvement. Store both per-frame data and counts.
- [x] Run against `TinyLeo_CA/outputs/53464db9114943deb01df8c22d7ebb4b.zip` with the spec's two-flow C2/bulk case first, then all three flows. Store all tested candidates. Require spec thresholds before locking a preset.
- [x] If the candidate fails, explain the exact failing invariant and calibrate only within approved endpoint/rate scope. If changing forwarding/model semantics is necessary, stop and get design approval. No performance claim follows from this gate alone. Both original candidates passed after handling out-of-region empty cell lists; no rate calibration was needed.

### Task 4: Owned real-traffic measurement lifecycle

Local implementation and parser/process tests are committed in `e1dbfa3`.
The selected exact receiver format requires iperf3 >=3.20 with `--json-stream`;
the real fixture was captured on Mac loopback. VM 3.9 text is not used for
measurement arithmetic. Full Linux namespace scheduling acceptance is pending.

**Files:** Create `tools/replay/traffic.py`, `tools/replay/test_traffic.py`.
**Interfaces:** `parse_iperf_interval(line: str) -> dict | None`; `parse_ping(line: str) -> dict | None`; `TrafficSession(config, output).start()`, `.advance(second)`, `.snapshot()`, `.close()`.

- [ ] Inspect VM iperf version/help read-only before fixing parser format. Save representative receiver output as a test fixture, without fabricated measurements. Avoid undocumented version-specific streaming options.
- [ ] Test interval packet counts, bytes, duration, jitter, ping reply/timeouts, malformed/partial lines and missing records. Literal summary fixture: 1 loss/10 packets plus 9/90 = 10%, not a mean of unrelated interval denominators.
- [ ] Implement bounded server/client processes in the configured namespaces, distinct ports, rate/packet size from validated config, monotonic start timestamps, background readers and raw log retention. Match version-tested `iperf3 -s -1 -i 1 --forceflush` receiver output and UDP client options.
- [ ] Add real local subprocess lifecycle tests: early exit fails, late start is recorded, close stops only owned PIDs, repeated close is safe. Mock namespace launch only for local tests, not the parser/owner behavior.
- [ ] Test quiet/competition/recovery transitions using an injected clock; topology apply cannot block on traffic reads or shutdown. A failed receiver never produces zero-loss success.

### Task 5: Runtime integration and archive schema

Local implementation is committed in `12c8dcc`; HTTP/archive tests pass.
Kernel evidence is collected asynchronously but not yet certified on the VM.

**Files:** Modify `tools/replay/live.py`, `live_server.py`; create `competition_archive.py`, `test_competition_archive.py`; extend `test_live.py`.
**Interfaces:** `build_competition_archive(run_dir, frames, config, measurements, provenance) -> dict` returns schema_version=2 with legacy map/modes plus scenario, flow_measurements and comparison provenance.

- [ ] Test schema v1 compatibility and v2 round-trip. Verify algorithm-independent hashes match across A/B and change for packet rate, topology, shaping or phase changes.
- [ ] Add explicit preparation profile selection; keep legacy default unchanged. Validate netem limits and float bandwidth handling before creating nodes. The new profile uses a new manual session/token.
- [ ] At each epoch apply full new routing policy; schedule active flows against the same clock. Capture kernel policy/counter evidence at phase boundaries and selected route changes asynchronously. Report convergence evidence separately from controller completion.
- [ ] Finalize receiver data, raw logs and failure evidence before checksum/archive. Keep failed partial runs importable but ineligible for comparison. Test local relay archiving while UI is in Compare.
- [ ] Preserve all current Live security, node ownership, polling and download tests. Do not enable VM profile until tests and feasibility gate pass.

### Task 6: Offline comparison math and contracts

Local implementation and passing Node contract tests are in `a8aedda`.

**Files:** Create `tools/replay/compare.js`, `test_compare.cjs`.
**Interfaces:** `validatePair(a,b)`, `summarize(run,phase)`, `frameAt(run,second)`, `routeSegments(a,b)`, `firstDifference(a,b,flow)` exported for Node and browser use.

- [ ] Write failing pure Node tests:
  ```js
  assert.deepEqual(routeSegments([12,13,14],[12,13,24,25]).shared, [[12,13]]);
  assert.equal(frameAt({frames:[{simulation_time_s:2}]}, 1), null);
  ```
  Test reversed edges are exclusive; missing routes are unavailable, not equal.
- [ ] Test packet-weighted loss, raw-sample nearest-rank p95, measured-duration throughput, half-open phase bounds, excluded partial intervals, missing coverage and zero-baseline N/A.
- [ ] Implement canonical pair checks from v2 provenance. Reject duplicate times, failed/incompatible runs and mismatched topology/settings. Do not infer v2 metrics from legacy archives.
- [ ] Run `node tools/replay/test_compare.cjs`; ensure no DOM/network dependency. Delta signs follow the spec. Record sample counts and denominator coverage with every metric.

### Task 7: Single-map Compare UI and offline packaging

Local implementation and passing Chrome contract tests are in `a8aedda`.
Fixture screenshots were inspected, including English file-picker controls.
Final visual inspection using matched real v2 recordings awaits Task 8.

**Files:** Modify `tools/replay/seconds.html`, `build_seconds.py`; create `test_compare_browser.cjs`; extend existing browser tests as needed.

- [ ] Write browser tests importing two explicit v2 fixtures. Summary must appear before playback, default to competition, show run IDs and `Recorded emulation results`.
- [ ] Build Compare controls using current typography/map conventions. Embed compare.js at HTML build time (no CDN/import request). Render safe text, never archive strings as HTML.
- [ ] Add one-map overlay, shared gray segments, blue solid/orange dashed exclusive segments, arrows/offset opposing directions, flow selector, complete route strings, difference-only mode and honest equal/missing-state labels.
- [ ] Add shared second cursor, 1×/5×/10×, exact steps, phase jumps and computed first-difference jump. Summaries change with phase selection, not with cursor motion.
- [ ] Add aligned C2 RTT/loss and bulk-throughput plots with gap handling, phase shading and cursor; no interpolated measurements. Draw physical topology once after per-frame matching.
- [ ] Test offline network-disabled import/replay, mismatch rejection, timestamp gaps, zero baselines, playback speed/seek, Live polling continuity, and old archive imports. Inspect a screenshot at laptop size with real validated data before delivery.

### Task 8: VM validation and presenter handoff

**Files:** New versioned VM deployment; local new results; update `tools/replay/LIVE.md` and the user's manual only after validated commands exist.

- [ ] Verify VM idle state and obtain a safe manual re-preparation window before retiring the old prepared session. Do not interrupt a user run or issue broad cleanup commands.
- [ ] Deploy versioned code, prepare new rate profile, copy fresh token and run bounded smoke tests. Verify kernel routes, active netem rates and actual receiver traffic.
- [ ] Run three locked-scenario A/B pairs in alternating order; archive every attempt. Require 301 frames/no missed deadlines and full data coverage before performance acceptance.
- [ ] Report the spec's C2 loss/RTT/throughput gate with bulk tradeoffs; do not replace failed results. If benefit is absent, diagnose and report rather than calling UI completion a successful QoS demo.
- [ ] Deliver standalone HTML and matched replay JSON files into a new clearly named output folder; verify checksums/import. Document 3–4 minute offline-first presentation and short Live capability demonstration.

## Review record

The plan deliberately gates traffic/UI integration on real-topology feasibility.
No claim of physical congestion relief is made from the offline report. Task 8
requires a safe VM handover and real measurements; Tasks 1–7 do not authorize
interrupting current services. Workspace preference is requested before source
changes because existing Live files are not yet committed.
