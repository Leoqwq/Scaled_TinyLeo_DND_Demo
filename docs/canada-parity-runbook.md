# Canada parity-scale emulation runbook

This runbook is the reproducible acceptance procedure for one Google Cloud
`n2-standard-8` VM (8 vCPU, 32 GiB RAM). The finite 12-epoch profile preserves
TinyLEO's real orbital positions, MPC topology generation, Linux namespace
nodes, ISL/GSL link model, SRv6 agents, measurements, and deterministic failure
path. Only concurrent satellite count and total run duration are reduced.

No n2 measurements are checked into this repository. Every result table below
is deliberately marked `PENDING` until the commands are run on the target VM.

## 1. VM and environment capture

Use Ubuntu 22.04 or later, a clean checkout of the commit under test, and a
dedicated VM. Run all commands from one shell so the exported paths remain in
scope. Offline synthesis and topology validation do not require root; only the
namespace/SRv6 emulation command does.

```bash
export REPO="$PWD"
test -z "$(git status --porcelain)" || {
  echo "Refusing to run from a dirty worktree" >&2
  exit 1
}
export RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export RUN_ROOT="${TINYLEO_RUN_ROOT:-/tmp/tinyleo-canada-parity-$RUN_ID}"
case "$RUN_ROOT" in
  "$REPO"|"$REPO"/*)
    echo "RUN_ROOT must be outside the repository: $RUN_ROOT" >&2
    exit 1
    ;;
esac
export VENV="/tmp/tinyleo-venv-$RUN_ID"
export KEY_FILE="/tmp/tinyleo-n2-key-$RUN_ID"
mkdir -p "$RUN_ROOT"

sudo apt-get update
sudo apt-get install -y \
  build-essential curl iperf3 iproute2 iptables iputils-ping \
  libnetfilter-queue-dev libnfnetlink-dev openssh-server \
  python3-dev python3-venv traceroute util-linux
python3 -m venv --copies "$VENV"
export PYTHON_BIN="$VENV/bin/python"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install \
  haversine grpcio grpcio-tools NetfilterQueue networkx numpy pandas \
  paramiko psutil pyroute2 python-iptables requests scapy scipy tqdm watchdog

{
  date -u --iso-8601=seconds
  git rev-parse HEAD
  git status --short
  uname -a
  cat /etc/os-release
  lscpu
  free -h
  swapon --show
  "$PYTHON_BIN" --version
  "$PYTHON_BIN" -m pip freeze
  curl -fsS -H 'Metadata-Flavor: Google' \
    http://metadata.google.internal/computeMetadata/v1/instance/machine-type
  printf '\n'
} | tee "$RUN_ROOT/environment.txt"
```

The clean-worktree check runs before any result directory is created. The last
metadata line must end in `machineTypes/n2-standard-8`; stop if it differs.
Configure passwordless localhost SSH for the disposable VM because the existing
multi-machine path is retained:

```bash
ssh-keygen -q -t ed25519 -N '' -f "$KEY_FILE"
sudo install -d -m 0700 /root/.ssh
sudo sh -c "cat '$KEY_FILE.pub' >> /root/.ssh/authorized_keys"
sudo chmod 0600 /root/.ssh/authorized_keys
sudo systemctl enable --now ssh
ssh -o StrictHostKeyChecking=accept-new \
  -i "$KEY_FILE" root@127.0.0.1 true
```

Record the disposable key's path in generated run configurations only. Never
commit the key.

## 2. Offline synthesis and artifact generation

Run each requested scale independently. The scale is both the MP cap and the
required actual selected count. If MP reaches the coverage target before that
count, the command marks that scale unavailable; do not pad the constellation
with hand-picked satellites.

```bash
for SCALE in 64 80 96; do
  SCALE_DIR="$RUN_ROOT/scale-$SCALE"
  mkdir -p "$SCALE_DIR/artifacts" "$SCALE_DIR/topology"
  PYTHONPATH="$REPO/network_synthesizer" \
    "$PYTHON_BIN" - "$SCALE" "$SCALE_DIR" <<'PY'
import json
import sys
from pathlib import Path

import numpy as np

from canada_parity_artifacts import save_canada_parity_artifacts
from window_config import WindowConfig
from windowed_synthesizer_mp import save_synthesis_result, synthesize_windowed
from windowed_texture import (
    build_windowed_texture,
    generate_candidate_states,
    save_windowed_artifacts,
)

scale = int(sys.argv[1])
root = Path(sys.argv[2])
config = WindowConfig.from_dict(
    {
        "start_epoch": 0,
        "num_epochs": 12,
        "region_grid_ids": [12, 13, 14, 23, 24, 25],
        "satellite_height_km": 573.0,
        "coverage_target": 0.95,
        "target_satellites": scale,
        "max_satellites": scale,
        "num_processes": 6,
        "memory_threshold_gb": 20.0,
        "random_seed": 20260821,
    }
)
demand = np.load(
    Path.cwd() / "network_synthesizer/test/data/canada_parity_backbone_demand.npy",
    allow_pickle=False,
)
candidates = generate_candidate_states(config)
coverage = build_windowed_texture(config, demand, candidates)
result = synthesize_windowed(demand, coverage, config)
save_synthesis_result(root / "synthesis_result.npy", result)
save_windowed_artifacts(
    root / "coverage_texture.npz",
    root / "candidate_states.npy",
    root / "candidate_positions.npy",
    coverage,
    candidates,
)
selected_count = len(result.selected_candidate_ids)
summary = {
    "requested_scale": scale,
    "selected_satellite_count": selected_count,
    "candidate_count": len(candidates),
    "coverage_ratio": result.coverage_ratio,
    "stop_reason": result.stop_reason,
    "window": [int(value) for value in config.epoch_indices],
}
(root / "synthesis_summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
if selected_count != scale:
    (root / "scale-status.txt").write_text("UNAVAILABLE\n", encoding="utf-8")
    print(
        f"scale {scale} unavailable: MP selected {selected_count}; do not pad",
        file=sys.stderr,
    )
else:
    save_canada_parity_artifacts(
        root / "artifacts", result.selected_candidate_ids, candidates, coverage
    )
    (root / "scale-status.txt").write_text("AVAILABLE\n", encoding="utf-8")
PY
done
```

Generate all 12 MPC topology epochs with the actual TinyLEO MPC function. Copy
the existing grid geometry, then validate every cross-file topology output
before any namespace is created:

```bash
for SCALE in 64 80 96; do
  SCALE_DIR="$RUN_ROOT/scale-$SCALE"
  test "$(cat "$SCALE_DIR/scale-status.txt")" = AVAILABLE || continue
  cp "$REPO/network_orchestrator/test/data/topo_data/block_positions.json" \
    "$SCALE_DIR/artifacts/block_positions.json"
  PYTHONPATH="$REPO/network_orchestrator" \
    "$PYTHON_BIN" - "$SCALE_DIR" <<'PY'
import sys
from pathlib import Path
from sn_orchestrator_mpc import (
    generate_topology_for_timestamp,
    predict_all_topologies,
)

root = Path(sys.argv[1])
artifacts = root / "artifacts"
predict_all_topologies(
    duration=12,
    satellite_file=artifacts / "canada_parity_satellite_data.npy",
    traffic_matrix_file=artifacts / "canada_parity_traffic_matrix.npy",
    grid_satellites_file=artifacts / "canada_parity_grid_satellites.npy",
    result_output_dir=root / "topology",
    num_processes=6,
    start_epoch=0,
)
for epoch in range(12):
    generate_topology_for_timestamp(
        timestamp=epoch,
        satellite_file=artifacts / "canada_parity_satellite_data.npy",
        block_positions_file=artifacts / "block_positions.json",
        traffic_matrix_file=artifacts / "canada_parity_traffic_matrix.npy",
        grid_satellites_file=artifacts / "canada_parity_grid_satellites.npy",
        output_dir=root / "topology",
        num_processes=6,
        start_epoch=0,
        num_epochs=12,
    )
PY

  (
    cd "$REPO/network_orchestrator"
    PYTHONPATH=. "$PYTHON_BIN" test/validate_topology_artifacts.py \
      --satellite-file "$SCALE_DIR/artifacts/canada_parity_satellite_data.npy" \
      --grid-satellites-file "$SCALE_DIR/artifacts/canada_parity_grid_satellites.npy" \
      --traffic-matrix-file "$SCALE_DIR/artifacts/canada_parity_traffic_matrix.npy" \
      --block-positions-file "$SCALE_DIR/artifacts/block_positions.json" \
      --topology-dir "$SCALE_DIR/topology" \
      --output-dir "$SCALE_DIR/validation-12" \
      --expected-epochs 12 --active-grids 12,13,14,23,24,25 \
      --min-satellites "$SCALE" --max-satellites "$SCALE" \
      --min-edge-disjoint-paths 2 --min-path-epoch-ratio 0.8 \
      --min-topology-changes 3 --min-gateway-handovers 2
  )
done
```

Do not continue with a scale unless `validation_summary.txt` says `PASS`, all
six grids are nonempty in all epochs, and the reported satellite count equals
the requested scale. `largest_component_ratio` is measured over satellites
participating in that epoch's MPC links; `constellation_largest_component_ratio`
separately reports the fraction of all fixed containers in the largest
component without treating intentionally idle satellites as a routing failure.

## 3. Three-epoch 64/80/96 resource preflight

Each preflight uses the same artifacts and complete node, link, MPC, SRv6, GSL,
ISL, QoS and failure-server code paths. The three-epoch resource preflight does
not reach the fixed epoch-6 failure injection; recovery is tested only in the
formal 12-epoch run.

Create a three-row demand, derive an exact three-epoch report from the already
passing 12-epoch validation report, and write an absolute-path configuration
for each scale. The derivation does not weaken topology validation: those three
epochs are a strict subset of the validated immutable artifacts.

```bash
for SCALE in 64 80 96; do
  SCALE_DIR="$RUN_ROOT/scale-$SCALE"
  test "$(cat "$SCALE_DIR/scale-status.txt")" = AVAILABLE || continue
  PREFLIGHT_DIR="$SCALE_DIR/preflight"
  mkdir -p "$PREFLIGHT_DIR"
  "$PYTHON_BIN" - "$REPO" "$SCALE_DIR" "$KEY_FILE" "$PYTHON_BIN" <<'PY'
import json
import sys
from pathlib import Path
import numpy as np

repo, root, key, remote_python = map(Path, sys.argv[1:])
base = json.loads(
    (repo / "network_orchestrator/test/config/tinyleo_canada_parity.json")
    .read_text(encoding="utf-8")
)
artifacts = root / "artifacts"
preflight = root / "preflight"
base.update(
    {
        "Name": f"tinyleo_canada_parity_preflight_{root.name}",
        "Duration (s)": 3,
        "start_epoch": 0,
        "num_epochs": 3,
        "satellite_file": str(artifacts / "canada_parity_satellite_data.npy"),
        "traffic_matrix_file": str(artifacts / "canada_parity_traffic_matrix.npy"),
        "grid_satellites_file": str(artifacts / "canada_parity_grid_satellites.npy"),
        "block_positions_file": str(artifacts / "block_positions.json"),
        "topo_dir": str(root / "topology"),
        "remote_python": str(remote_python),
        "failure_controller_endpoint": "127.0.0.1:50051",
        "Machines": [{
            "IP": "127.0.0.1", "port": 22, "username": "root",
            "key_filename": str(key),
        }],
    }
)
(preflight / "config.json").write_text(
    json.dumps(base, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
south_policy = (
    repo / "network_orchestrator/test/config/geographic_routing_policy_canada_south.json"
).read_text(encoding="utf-8")
(preflight / "geopraphic_routing_policy.json").write_text(
    south_policy, encoding="utf-8"
)
demand = np.load(
    repo / "network_synthesizer/test/data/canada_parity_backbone_demand.npy",
    allow_pickle=False,
)
np.save(preflight / "backbone_demand_3.npy", demand[:3])
report = json.loads(
    (root / "validation-12/validation_report.json").read_text(encoding="utf-8")
)
epochs = report["epochs"][:3]
if [metric["epoch"] for metric in epochs] != [0, 1, 2]:
    raise SystemExit("validated report does not start with exact epochs 0,1,2")
report.update(
    {
        "expected_epochs": 3,
        "epochs": epochs,
        "path_epoch_ratio": sum(
            metric["edge_disjoint_paths"] >= 2 for metric in epochs
        ) / 3,
        "topology_change_count": sum(
            bool(metric.get("added_links") or metric.get("removed_links"))
            for metric in epochs[1:]
        ),
        "gateway_handover_count": sum(
            metric.get("gateway_handovers", 0) for metric in epochs
        ),
    }
)
(preflight / "validation_report_3.json").write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

  (
    cd "$REPO/network_orchestrator"
    set -o pipefail
    if ! sudo -E env PYTHONPATH="$REPO/network_orchestrator" \
      "$PYTHON_BIN" test/example_canada_parity.py \
      --config "$PREFLIGHT_DIR/config.json" \
      --south-policy test/config/geographic_routing_policy_canada_south.json \
      --north-policy test/config/geographic_routing_policy_canada_north.json \
      --backbone-demand "$PREFLIGHT_DIR/backbone_demand_3.npy" \
      --validation-report "$PREFLIGHT_DIR/validation_report_3.json" \
      --result-dir "$PREFLIGHT_DIR/results" \
      --measurement-wait-s 15 \
      2>&1 | tee "$PREFLIGHT_DIR/emulation.log"; then
      printf 'FAIL\n' > "$PREFLIGHT_DIR/command-status.txt"
    else
      printf 'PASS\n' > "$PREFLIGHT_DIR/command-status.txt"
    fi
  )
  sudo chown -R "$(id -u):$(id -g)" "$PREFLIGHT_DIR"
  sudo ip netns list | tee "$PREFLIGHT_DIR/netns-after-cleanup.txt"
  free -b | tee "$PREFLIGHT_DIR/free-after-cleanup.txt"
  swapon --show --bytes | tee "$PREFLIGHT_DIR/swap-after-cleanup.txt"
  "$PYTHON_BIN" - "$SCALE_DIR" "$PREFLIGHT_DIR" <<'PY'
import csv
import json
import sys
from pathlib import Path

import numpy as np

scale_root, preflight = map(Path, sys.argv[1:])
resource_path = preflight / "results/resource-usage.csv"
update_path = preflight / "results/topology-update-times.csv"
with resource_path.open(newline="") as stream:
    resources = list(csv.DictReader(stream))
with update_path.open(newline="") as stream:
    updates = list(csv.DictReader(stream))
durations = np.asarray([float(row["duration_seconds"]) for row in updates])
used = np.asarray([float(row["system_memory_used_bytes"]) for row in resources])
swap = np.asarray([float(row["swap_used_bytes"]) for row in resources])
satellites = np.load(
    scale_root / "artifacts/canada_parity_satellite_data.npy", allow_pickle=True
)
summary = {
    "actual_nodes": len(satellites),
    "runtime_rows": len(resources),
    "peak_used_gib": float(used.max() / 1024**3) if len(used) else None,
    "peak_swap_gib": float(swap.max() / 1024**3) if len(swap) else None,
    "p50_update_s": (
        float(np.percentile(durations, 50, method="linear"))
        if len(durations) else None
    ),
    "p95_update_s": (
        float(np.percentile(durations, 95, method="linear"))
        if len(durations) else None
    ),
    "all_updates_returned": (
        len(updates) == 3 and all(row["status"] == "returned" for row in updates)
    ),
    "command_status": (preflight / "command-status.txt").read_text().strip(),
}
(preflight / "preflight_summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY
done
```

`remote_python` is the absolute venv interpreter used to launch every uploaded
`sn_remote.py` command and every namespace SRv6 agent. A nonzero SSH exit,
worker exception, missing failure acknowledgement, or agent that exits during
startup aborts the scenario; it is not converted into a successful event.

The runner writes three `resource-usage.csv` and
`topology-update-times.csv` rows per scale. Calculate p50/p95 with NumPy's
linear percentile and transcribe only measured values:

| Scale | Actual nodes | Peak used GiB | Peak swap GiB | p50 update s | p95 update s | startup/link errors | Result |
|---:|---:|---:|---:|---:|---:|---|---|
| 64 | PENDING — run on n2-standard-8 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| 80 | PENDING — run on n2-standard-8 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| 96 | PENDING — run on n2-standard-8 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

Pass requires actual node count equal to the row, peak host used memory below
24 GiB, zero swap, p95 below 15 seconds, no namespace/link/agent startup error,
and the 12-epoch offline quality report already passing.

Scale policy:

1. Prefer the largest passing scale.
2. If both 80 and 96 pass, keep 80 until a second complete 96-node preflight is
   stable; only then promote 96.
3. If 96 fails, use 80; if 80 fails, use 64.
4. If 64 fails topology quality, choose a richer continuous legacy window and
   regenerate. Never disable MPC, SRv6, the link model, failure recovery, or
   substitute a static topology.
5. Shortening the run reduces duration, not peak concurrent-node memory, and is
   not a valid remedy for a failed scale gate.

## 4. Two full privileged fixed-artifact A/B runs

Set the selected passing scale explicitly. Both modes reuse the exact same
constellation, MPC topology files, validation report, demand, epoch schedule,
and deterministic failure schedule. Both runs create real namespaces and
links, deploy verified SRv6 agents, inject the epoch-6 physical ISL failure,
and collect packet-level evidence. An offline `find_path` call is not
acceptance evidence.

```bash
set -euo pipefail
export SELECTED_SCALE=80  # replace only with the scale selected above
export SCALE_DIR="$RUN_ROOT/scale-$SELECTED_SCALE"
export AB_ROOT="$SCALE_DIR/formal-ab"
mkdir -p "$AB_ROOT"

find "$SCALE_DIR/artifacts" "$SCALE_DIR/topology" \
  "$SCALE_DIR/validation-12" "$SCALE_DIR/synthesis_result.npy" \
  -type f -print0 | sort -z | xargs -0 sha256sum \
  > "$AB_ROOT/fixed-artifact-sha256.txt"

for ROUTING_MODE in shortest geographic; do
  MODE_DIR="$AB_ROOT/$ROUTING_MODE"
  mkdir -p "$MODE_DIR"
  "$PYTHON_BIN" - "$REPO" "$SCALE_DIR" "$MODE_DIR" \
    "$KEY_FILE" "$PYTHON_BIN" "$ROUTING_MODE" <<'PY'
import json
import sys
from pathlib import Path

repo, root, mode_dir, key, remote_python = map(Path, sys.argv[1:6])
routing_mode = sys.argv[6]
base = json.loads(
    (repo / "network_orchestrator/test/config/tinyleo_canada_parity.json")
    .read_text(encoding="utf-8")
)
artifacts = root / "artifacts"
base.update(
    {
        "Name": f"tinyleo_canada_parity_{routing_mode}_{root.name}",
        "Duration (s)": 12,
        "start_epoch": 0,
        "num_epochs": 12,
        "satellite_file": str(artifacts / "canada_parity_satellite_data.npy"),
        "traffic_matrix_file": str(artifacts / "canada_parity_traffic_matrix.npy"),
        "grid_satellites_file": str(artifacts / "canada_parity_grid_satellites.npy"),
        "block_positions_file": str(artifacts / "block_positions.json"),
        "topo_dir": str(root / "topology"),
        "remote_python": str(remote_python),
        "failure_controller_endpoint": "127.0.0.1:50051",
        "Machines": [{
            "IP": "127.0.0.1", "port": 22, "username": "root",
            "key_filename": str(key),
        }],
    }
)
(mode_dir / "config.json").write_text(
    json.dumps(base, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
policy_name = (
    "geographic_routing_policy_canada_south.json"
    if routing_mode == "shortest"
    else "geographic_routing_policy_canada_north.json"
)
policy = (
    repo / "network_orchestrator/test/config" / policy_name
).read_text(encoding="utf-8")
(mode_dir / "geopraphic_routing_policy.json").write_text(
    policy, encoding="utf-8"
)
PY

  (
    cd "$REPO/network_orchestrator"
    set -o pipefail
    if sudo -E env PYTHONPATH="$REPO/network_orchestrator" \
      "$PYTHON_BIN" test/example_canada_parity.py \
      --config "$MODE_DIR/config.json" \
      --south-policy test/config/geographic_routing_policy_canada_south.json \
      --north-policy test/config/geographic_routing_policy_canada_north.json \
      --routing-mode "$ROUTING_MODE" \
      --backbone-demand "$REPO/network_synthesizer/test/data/canada_parity_backbone_demand.npy" \
      --validation-report "$SCALE_DIR/validation-12/validation_report.json" \
      --result-dir "$MODE_DIR/results" \
      --measurement-wait-s 15 \
      2>&1 | tee "$MODE_DIR/emulation.log"; then
      printf 'PASS\n' > "$MODE_DIR/command-status.txt"
    else
      printf 'FAIL\n' > "$MODE_DIR/command-status.txt"
    fi
  )
  sudo chown -R "$(id -u):$(id -g)" "$MODE_DIR"

  sudo ip netns list | tee "$MODE_DIR/netns-after-cleanup.txt"
  pgrep -af '[s]n_remote.py|[s]rv6_agent.py|[i]perf3' \
    | tee "$MODE_DIR/processes-after-cleanup.txt" || true
  free -b | tee "$MODE_DIR/free-after-cleanup.txt"
  swapon --show --bytes | tee "$MODE_DIR/swap-after-cleanup.txt"
  test "$(cat "$MODE_DIR/command-status.txt")" = PASS
  test ! -s "$MODE_DIR/netns-after-cleanup.txt"
  test ! -s "$MODE_DIR/processes-after-cleanup.txt"

  "$PYTHON_BIN" \
    "$REPO/network_orchestrator/test/check_canada_parity_results.py" \
    "$MODE_DIR/results" \
    --validation-report "$SCALE_DIR/validation-12/validation_report.json" \
    --synthesis-result "$SCALE_DIR/synthesis_result.npy"
  test "$("$PYTHON_BIN" -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["valid"])' \
    "$MODE_DIR/results/acceptance_summary.json")" = True

  (
    cd /
    sha256sum -c "$AB_ROOT/fixed-artifact-sha256.txt"
  ) > "$MODE_DIR/fixed-artifact-verification.txt"
done
```

The absolute host venv interpreter recorded in each config launches remote
commands. During node creation, TinyLEO validates and bind-mounts that venv at
`/resources/venv` and the current experiment controller at
`/resources/controller` in every emulated root. The deploy helper validates
both host sources, then `nsenter` joins each target's mount, UTS, IPC, network,
and PID namespaces, adopts `/proc/PID/root`, and executes only
`/resources/venv/bin/python` plus the target-root controller agent. Thus
`/resources`, `/etc/hostname`, and `/etc/hosts` resolve inside the emulated
overlay root; no host path or legacy experiment path is used after entry.
`python3 -m venv --copies` makes the interpreter location explicit; a legacy
system-Python config is accepted only when its probe resolves an absolute
interpreter already present through the `lowerdir=/` root and agent liveness
validation succeeds.
Each deployment must acknowledge exactly the validated satellite count plus
the six ground-station agents, with unique remote and namespace identities.
Failure injection deterministically selects the lexicographically first
same-machine physical ISL; its acknowledgement is written only after remote
mutation and recovery complete, and names the failed link, removed satellite,
and replacement. A nonzero SSH exit, worker exception, missing acknowledgement,
or dead agent aborts the scenario.

The namespace and TinyLEO-process cleanup files must be empty after each mode.
Inspect residual state before manual removal; never hide a cleanup defect and
continue the comparison.

## 5. Machine-readable A/B comparison

Build the comparison only after both complete acceptance summaries pass. This
script fails if the scenarios did not use the same failure schedule and link,
replacement, or if packet-level latency, loss, or hop evidence is unparseable.
Epoch 6 may have zero replies, 100% loss, and therefore no RTT summary; it may
likewise have no resolved traceroute hops, represented as JSON `null`.
Epoch 7 must have a positive reply count, parseable RTT, and resolved path.
Failure/recovery interruption comes only from the separately timed interval
surrounding remote injection, acknowledgement, and recovery—not from an
ordinary topology update.

```bash
PYTHONPATH="$REPO/network_orchestrator" \
  "$PYTHON_BIN" - "$AB_ROOT" <<'PY'
import json
import sys

from test.check_canada_parity_results import compare_routing_runs

comparison = compare_routing_runs(sys.argv[1])
print(json.dumps(comparison, indent=2, sort_keys=True))
PY
```

The checker summaries include independently validated peak TinyLEO process RSS
and ping-loss metrics, in addition to host-memory, swap, topology, SRv6, and
recovery gates. Transcribe only values produced above:

| Full 12-epoch metric | Geographic policy | Shortest path |
|---|---|---|
| Fixed artifact manifest | PENDING — run on n2-standard-8 | PENDING — run on n2-standard-8 |
| Mean traceroute hops | PENDING | PENDING |
| Mean ping latency / loss | PENDING | PENDING |
| Failure/recovery interruption | PENDING | PENDING |
| Peak process RSS / recovery ping loss | PENDING | PENDING |
| Epoch-6 acknowledged link / replacement | PENDING | PENDING |
| Overall acceptance | PENDING — run on n2-standard-8 | PENDING — run on n2-standard-8 |

Optionally run `TinyLEONorthboundAPI.find_path` against the immutable grid map
to explain a packet-level difference. Label it supplementary: it can never
substitute for either privileged run, acknowledgements, or this comparison.

## 6. Checksums and archival

Archive inputs, generated topology, validation reports, raw runtime evidence,
acceptance summary, environment capture, and A/B output together:

```bash
find "$RUN_ROOT" -type f \
  ! -name SHA256SUMS ! -name '*.tar.gz' ! -name '*.tar.gz.sha256' \
  -print0 | sort -z | xargs -0 sha256sum > "$RUN_ROOT/SHA256SUMS"
(
  cd "$(dirname "$RUN_ROOT")"
  tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 \
    --numeric-owner -czf "$(basename "$RUN_ROOT").tar.gz" \
    "$(basename "$RUN_ROOT")"
  sha256sum "$(basename "$RUN_ROOT").tar.gz" \
    > "$(basename "$RUN_ROOT").tar.gz.sha256"
)
```

Retain the archive, archive checksum, git commit, VM image/kernel, and the
unmodified `acceptance_summary.json`. A failed result is still evidence and
must not be deleted or edited before archival.

The private SSH key lives under `/tmp` and is excluded from the archive. After
the last run, destroy the disposable VM (which revokes its corresponding
`authorized_keys` entry) and remove the local temporary key and virtualenv:

```bash
shred -u "$KEY_FILE" "$KEY_FILE.pub"
rm -rf "$VENV"
```
