# Live / Replay demo

## Status

Implemented locally; real VM integration and one-second deadline acceptance
are not yet verified for this new Live runner. Do not infer that the previous
301-frame timing result applies to this runner, which also computes routing.

The existing HTML has Replay and Live modes. Opening it as a file supports
offline replay/import only. Live requires the local relay and a manually
prepared VM session. All servers bind 127.0.0.1; no GCP firewall rule is needed.

## Manual preparation (VM)

Deploy the current repository source to the VM first. Keep the existing Python
environment and validated seconds-20260905 input directory. The command below
must be run manually in a persistent terminal (for example tmux). It creates
the nodes once, initializes links/agents, then waits for Live requests. It
refuses to overwrite existing TinyLEO namespaces. Stop other experiments and
perform their normal manual cleanup before preparing this session.

From the deployed repository, run as root, using the existing venv Python:

```sh
/home/leo/tinyleo-venv/bin/python tools/replay/live_server.py prepare-vm \
  --root /home/leo/tinyleo-runs/seconds-20260905 \
  --template /absolute/path/to/existing/loopback-vm-config.json \
  --routing-config tools/replay/live-routing.json \
  --token-file /tmp/tinyleo-live-session.token
```

`--template` is the previously verified single-VM configuration with loopback
root SSH, its key and Python path. It is not the repository's generic example.
Use a new token-file path for a new preparation. The token is mode 0600; copy
it securely to the Mac using SSH, without pasting it into HTML or committing it.
VM preparation is deliberately not exposed through the browser API. Start does
not recreate nodes; completed runs leave them available. Failed runs require
manual diagnosis/repreparation. Preparation currently owns the controller in
this persistent process; it cannot attach to nodes created by an unrelated run.

## SSH tunnel and local relay (Mac)

With the same existing SSH/GCP connection used to access the VM, forward local
port 8767 to VM loopback port 8766. For an existing SSH host alias:

```sh
ssh -N -L 127.0.0.1:8767:127.0.0.1:8766 YOUR_EXISTING_VM_SSH_ALIAS
```

For gcloud, append `-- -N -L 127.0.0.1:8767:127.0.0.1:8766` to the existing
`gcloud compute ssh` command for project `satellite-emulator`. Do not open the
VM API to the public internet. Keep the tunnel and relay running; closing only
the browser does not stop the run or the automatic download.

```sh
python3 tools/replay/live_server.py local \
  --token-file /absolute/path/to/copied/session.token \
  --output /Users/leo/Desktop/Obsidian/Satellite/TinyLeo/outputs \
  --html /Users/leo/Desktop/Obsidian/Satellite/TinyLeo/outputs/tinyleo-replay.html
```

Open http://127.0.0.1:8765 and choose Live. Wait for `ready`, choose Shortest
Path or QoS Priority, then Start emulation. Nodes are not started by this button.
Keep the local relay process running to finish automatic archival.

## Algorithm meaning and measurements

Both modes invoke the repository's northbound algorithm on the same physical
topology. Current ISLs restrict the geographic adjacency graph; generated paths
are converted into the original GS SRv6 segment-list policy before kernel
updates. Shortest Path is the existing `find_shortest_path` implementation,
not a newly introduced minimum-RTT satellite-level solver. QoS is the existing
`qos_priority`, including its recorded fallback/budget status.

`live-routing.json` configures one GS4→GS6 demand (grid 23→25), priority 5,
0.01 Gbps modeled demand. These are demo inputs, not measured traffic or a
multi-class QoS benchmark. Current live probes are continuous one-second ping;
no iperf throughput or traceroute measurement is fabricated. The inherited
destination-based SRv6 policy cannot distinguish multiple service classes
sharing the same source/destination. The adapter refuses an unreachable path
instead of silently reusing a stale policy.

Each frame records actual applied state and total update time (including routing
selection); a missed one-second deadline is reported, never hidden. Controller
completion does not independently certify that every agent has converged.
Live disconnection is not emulation completion. A failed run retains its partial
data and is archived when possible.

## Automatic files

The local relay saves `<run-id>.zip`, `<run-id>.sha256`, and
`<run-id>.replay.json` in the chosen outputs directory. ZIP includes frame
snapshots, actual link commands, telemetry, raw continuous ping, run log,
algorithm input/settings/decisions, summary, time axis and input topology and
validation artifacts. SSH credentials are not included. SHA-256 is checked
before the archive is marked saved; failed transfers retry while the relay runs.

After download, use Replay this run, or import the `.replay.json` later into
the same HTML offline. The embedded historical run keeps its historical preset
label; it is not relabeled as the newly integrated shortest-path algorithm.

## Validation

```sh
python -m unittest discover -s tools/replay -p test_live.py -v
node tools/replay/test_seconds.cjs /absolute/path/to/tinyleo-replay.html
node tools/replay/test_live.cjs /absolute/path/to/tinyleo-replay.html
```

Python tests need numpy/networkx; browser tests need Playwright and Chrome.
The browser Live test uses a controlled HTTP fixture, not the VM. Required VM
acceptance: manual prepare, 301-frame run for each mode, check actual GS policy
and packet forwarding, deadline telemetry, second run without node recreation,
browser reconnect, automatic downloaded archive and offline replay round trip.
