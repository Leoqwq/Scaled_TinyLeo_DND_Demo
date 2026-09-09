# Real-flow QoS competition demo — design for review

Date: 2026-09-08. Status: design for user review; not implemented or VM-validated.

## Objective

Extend the existing Canada Live/Replay demonstration from one probe demand to
multiple real competing flows. Reproduce the teammate's mechanism: critical
traffic retains its useful corridor while lower-priority traffic can move to
another corridor. Demonstrate benefits with receiver measurements, not merely
different route drawings. Do not guarantee a positive result before testing.

Reference: `/Users/leo/Desktop/Obsidian/Satellite/TinyLeo/TinyLeo GUI Demo.md`.
Its 15-demand global-scale offline figures are context, not acceptance targets
or claims transferable to this 96-satellite, six-ground-station experiment.

## Evidence and existing constraints

- `tools/replay/live.py:RoutingAdapter` currently enforces exactly one demand,
  grid 23 to 25. This is a demo adapter restriction, not a TinyLEO restriction.
- Existing archived QoS run `53464db9114943deb01df8c22d7ebb4b` has priority 5
  and no fallback in all 301 epochs. Its paths match the shortest-path run.
- Each northbound generation clears reservations. The only demand sees zero
  previous reservations. Its priority cannot order competing business flows.
- Active GS cells are GS1=12, GS2=13, GS3=14, GS4=23, GS5=24, GS6=25.
- At sampled archived epochs 0, 150 and 300, each of the seven geographic
  adjacencies has one physical inter-cell ISL; each cell has 2–3 satellites.
  The density-minimum capacity estimate consequently overcounts these links.
  Full-epoch validation is required; these samples are not a full-run proof.
- Existing GS SRv6 policies are keyed by a cell pair and destination prefix,
  including a generated reverse policy. Distinct UDP ports alone cannot give
  two demands between the same cell pair different routes.
- Existing link shaping uses Linux netem with configurable rate, delay and
  loss. It does not need a new priority scheduler to test routing.

## Chosen approach and alternatives

Chosen: multiple unique cell-pair demands, real rate-controlled traffic,
existing SRv6 policies, and capacity-aware routing against actual active ISLs.
This preserves the original forwarding mechanism and limits the extension to
the adapter, scenario/measurement runner, and Live/Replay data presentation.

Rejected as insufficient: only add demands to offline northbound and draw
different paths. It cannot establish a real-emulation benefit.

Deferred: per-service policy routing for several classes between identical
endpoints. It needs packet classification and additional policy tables; not
necessary for the first competition demonstration.

## Preserved behavior and explicit experimental changes

Preserve 96 satellites, six GS nodes, the validated 301-state time axis,
one-second topology updates, positions, connectivity evolution, geographic
SRv6 forwarding, manual node preparation, browser-controlled run start, and
automatic archive/replay. Do not invent topology edges or change topology per
algorithm. Runtime algorithms remain `shortest_path` and `qos_priority`.

Explicit changes: multiple demands and probes; a documented, scaled link-rate
profile suitable for a single VM; live physical-capacity inputs instead of
planning capacity estimates; per-flow result data. This is a controlled
bandwidth-scaled experiment, not a claim to emulate production Starlink rates.

Use the same netem queue type, queue limits, delay, loss, rates, packet sizes,
and flow schedule in both arms. No preferential DSCP/priority queue for QoS.
Do not alter QoS weights or choose asymmetric inputs just to obtain a win.

## Initial candidate scenario

| ID | Class | Priority | Endpoints | Cell pair | Starting offered rate |
|---|---|---|---|---|---|
| c2-north | C2 | 5 | GS1 → GS3 | 12 → 14 | 4 Mbit/s |
| telemetry-east | telemetry | 3 | GS2 → GS6 | 13 → 25 | 2 Mbit/s |
| bulk-cross | bulk | 1 | GS1 → GS6 | 12 → 25 | 9 Mbit/s |

Initial satellite-link shaping: 10 Mbit/s per directed interface. GS links:
100 Mbit/s, subject to checking that uplinks do not become the bottleneck.
Rates are offered UDP payload rates; network overhead must be accounted for
when comparing to netem interface limits. These are a calibration candidate,
not a validated or promised production preset.

Expected mechanism to test: C2 takes 12–13–14. Bulk has equal-hop alternatives
12–13–14–25 and 12–23–24–25. QoS can react to reservations on the northern
corridor and use the southern corridor. Shortest-path tie-breaking is left
unchanged. Telemetry supplies another independently measurable flow, but
the two-flow C2/bulk case must work and be understood before enabling it.

Run schedule uses simulation time and a monotonic wall clock:

- t=0–19: topology/policy convergence and probes; no workload claims.
- t=20–79: C2 and telemetry only, establishing a quiet baseline.
- t=80–239: add bulk, creating a controlled competition interval.
- t=240–289: stop bulk and measure recovery.
- t=290–300: drain and final probes before archival.

Generate northbound reservations only for currently active traffic demands;
probes are recorded separately. Record scheduled and actual process start/
stop times, readiness, and receiver success. A future failed startup is not
allowed to masquerade as low loss or low offered load.

## Mandatory feasibility gate before locking the preset

Replay all 301 archived physical snapshots through the unchanged algorithms
with the candidate demands and real-capacity adapter. Report per-flow paths,
fallback, shared directed edges, estimated directional loads and connectivity.

The candidate must have an available alternate corridor during at least 80%
of the competition interval, a QoS/shortest decision difference on a lower-
priority flow during at least 50% of that interval, and a plausibly relieved
shared bottleneck. These are screening criteria, not measured QoS benefit.

If it fails, report the cause and perform a bounded, documented calibration
of offered rates and unique endpoint pairs on the SAME topology, never hidden
changes to the algorithm. Record all candidates. Lock scenario hashes before
the final A/B validation. If no useful candidate exists, report the limitation
instead of producing a scripted route comparison.

## Routing and capacity integration

1. Validate stable demand IDs, known GS-to-cell mappings, finite positive
   rates, priority range 1–5, and unique unordered cell pairs. Reject reversed
   duplicate pairs too: generated reverse SRv6 policy would conflict.
2. Derive active adjacency and density from actual per-epoch link state.
3. Provide effective capacity for the physical gateways that forwarding can
   actually use. Do not sum every physically present link unless forwarding
   can distribute traffic over those links. For this scenario, validate the
   single-active-gateway invariant at every used cell boundary.
4. Keep the teammate's cost weights, risk formula, priority ordering and
   fallback reporting. Supply actual edge capacity through a localized
   optional capacity provider; offline northbound defaults remain unchanged.
5. The current northbound reservations are undirected while netem links are
   full duplex. For this first demo, screen out paths that share an edge in
   opposite directions; fail preflight if this invariant is violated. Do not
   silently treat opposite-direction traffic as real congestion.
6. Convert every selected cell path to the original policy dictionary; apply
   the complete policy atomically at the controller-state level each epoch.
   Verify kernel convergence separately; a controller call alone is not proof.
7. A missing path is explicitly recorded. First version fails the run and
   retains partial evidence, rather than silently reusing a stale route.
8. Handle direct neighboring routes without intermediate segments correctly;
   test empty segment lists against existing agent behavior before allowing
   such demands in a deployed preset.

## Traffic and measurements

Use iperf3 UDP with receiver-side one-second interval reporting, distinct
ports and one server per flow, plus one-second IPv6 ping per pair. Confirm
the installed iperf3 supports a usable live interval output mode; preserve
raw text/JSON and test parsers against that exact version before deployment.
No unsupported streaming flag is assumed. Receiver reporting must be local
to the VM; do not rely on waiting for the final client report for Live metrics.

Keep workload generation bounded in rate and packet count. Use equal packet
sizes and traffic schedules in A/B; record bytes offered, bytes received,
UDP sequence loss/jitter and ping RTT. Missing intervals are unknown, not zero.
Do not call iperf jitter latency or ping RTT one-way application delay.

Collect directed interface counters and netem statistics at phase boundaries
and around selected route changes, with scoped packet captures where needed
to verify the traversed corridor. Collect relevant GS kernel policies. The
display distinguishes intended geographic path, verified kernel policy, and
observed forwarding evidence; it never invents a complete satellite hop path.

Track CPU, memory, deadline misses, collector overhead and process failures.
Terminate only run-owned traffic processes on completion or failure. Do not
destroy manually prepared nodes as a side effect of browser Start.

## Live/Replay and archive contract

Version the replay schema while retaining the old single-flow import path.
Each new frame carries a flow list keyed by stable demand ID, algorithm,
active phase, paths and QoS feasibility, observed measurements with source
timestamps, and their known/unknown state. Preserve original physical map and
telemetry. Append measurements asynchronously so traffic collectors cannot
block the one-second topology loop.

English UI: demand table (class, priority, endpoints, offered rate), selected
flow path, per-flow throughput/loss/RTT, phase label and QoS fallback status.
Keep estimates visibly separate from measurements. Completed-run A/B view
requires matching input/topology/scenario hashes and shows tradeoffs for bulk
as well as C2 gains. Live still starts only one selected algorithm per run.

Archive includes scenario/config hashes, versions, per-epoch routing and
capacity evidence, snapshots, actual link commands, raw sender/receiver/probe
logs, per-flow interval data, phase timestamps, kernel/counter verification,
resource telemetry and computed summaries. ZIP checksum and automatic local
download remain required before the next run is permitted.

## Acceptance and claim boundaries

Technical acceptance:

- Both algorithms complete 301 states with no missed topology deadlines in
  acceptance runs; failures and partial archives remain visible.
- Same physical input hashes and shaping schedule in each matched A/B pair.
- Kernel policies and observed corridor evidence agree with generated routes.
- Every configured flow starts/stops and has receiver measurements; archive
  import reproduces its phase/path/measurement history.
- Old single-flow archives still replay; SSH token security and manual node
  lifecycle are preserved.

Demonstration acceptance after calibration: execute three matched A/B pairs,
alternating order, using the locked scenario. Analyze the full predeclared
competition interval, not a handpicked good frame. Report per-run C2 UDP loss,
received throughput, ping RTT p95, bulk results and topology/resource health.

A defensible visible benefit requires either a C2 loss reduction of at least
one percentage point or ping p95 reduction of at least 20% in at least two of
the three pairs, with no material C2 throughput regression (more than 5%) and
no increase in C2 loss greater than one percentage point. This is a practical
demo gate, not statistical proof or a universal algorithm superiority claim.
Publish actual values, including runs that do not improve. If it fails, do
not label the demo as demonstrating a measured QoS advantage.

Equal-priority offline ablation is a diagnostic only: changing priorities
changes both sorting and cost coefficients. Do not attribute that comparison
solely to scheduling order. No extra algorithm is added to the Live selector.

## Deployment and rollback

Implement and test locally first. Keep current deployed source and historical
outputs intact. Before VM changes, inspect current experiment status; never
interrupt a user-started run. A new shaping profile needs manual preparation
with a distinct configuration/session and fresh token; do not hot-patch the
existing controller or change its nodes in place during an experiment.

Deploy to a new versioned directory after local validation. Perform short
smoke checks, then full paired acceptance. Rollback uses the previous code,
profile and normal manual re-preparation, without deleting historic archives.

## Implementation boundaries

Expected areas: `tools/replay/live.py`, new focused scenario/traffic/capacity
modules beside it, `live_server.py`, `seconds.html`, archive builders and tests;
one optional northbound capacity-input extension if adapter injection alone
cannot express the physical capacity contract. No new routing policy, no
synthetic route playback presented as Live, no topology/synthesizer redesign,
no general multi-tenant traffic platform, and no same-cell-pair classifier in
this first version.

Next gate: user review of this design, then a concrete implementation plan.
