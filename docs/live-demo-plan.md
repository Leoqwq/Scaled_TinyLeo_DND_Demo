# Live / Replay implementation

> Historical single-demand implementation plan. For the later multi-flow scope
> and the accepted real A/B pair, see the final section of the
> [dated QoS progress record](superpowers/plans/2026-09-08-live-qos-progress.md).
> Pending items below describe this earlier checkpoint, not current overall status.

Approved scope: one English page, manual node preparation, remote experiment
start, shortest_path and qos_priority, second-resolution telemetry, automatic
local archival. Existing recorded experiments remain historical, not relabeled.

Architecture: manually prepared VM session owns the existing RemoteController.
A loopback HTTP API serializes experiments without recreating nodes. A local
loopback relay reaches it through an SSH tunnel and saves verified archives.
The existing map renderer consumes the same frame schema in both modes.

## Implementation and verification

Local implementation and tests are in place. VM deployment, manual preparation,
two real 301-frame runs and end-to-end SSH archival remain an explicit acceptance
gate; the previous historical experiment does not satisfy this new gate.

- [x] Routing adapter: invoke existing northbound algorithms on actual current
  inter-cell adjacency; convert paths to existing geographic SRv6 policies.
  Check invalid modes, cell coordinates, route continuity and QoS status.
- [x] Prepared runner: explicit manual preparation, no create/clean during Live;
  one run at a time; retain snapshots, policy decisions, telemetry and logs.
- [x] VM API: token protected, loopback only, bounded request size, whitelist
  operations; independent worker survives browser disconnection; immutable runs.
- [x] Local relay: fixed remote endpoint, token protected mutations, origin and
  host checks; archive download in background, SHA-256 verification, atomic
  finalization and retry on failure. No private keys in browser.
- [x] UI: shared map, Live/Replay switch, two algorithm options, status/errors,
  per-second state, saved replay import and archive status. Historical embedded
  replay remains correctly labeled.
- [ ] Tests: real algorithm adapter, HTTP access control and state transitions,
  archive integrity, browser replay and mocked-transport UI checks. A real VM
  run is a separate required integration gate after manual node preparation.

QoS uses the repository's existing model estimates; estimated load and latency
must not be labeled measured. Algorithm choice does not regenerate the physical
topology, so comparisons have the same network. Multiple classes sharing one
source/destination cannot be represented as separate policies by the existing
destination-based SRv6 agent; this demo uses one GS4→GS6 demand.
