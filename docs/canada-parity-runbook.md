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
export RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export RUN_ROOT="$REPO/run/canada-parity-$RUN_ID"
export VENV="/tmp/tinyleo-venv-$RUN_ID"
export KEY_FILE="/tmp/tinyleo-n2-key-$RUN_ID"
mkdir -p "$RUN_ROOT"

sudo apt-get update
sudo apt-get install -y \
  build-essential curl iperf3 iproute2 iptables iputils-ping \
  libnetfilter-queue-dev libnfnetlink-dev openssh-server \
  python3-dev python3-venv traceroute util-linux
python3 -m venv "$VENV"
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

The last metadata line must end in `machineTypes/n2-standard-8`. Stop if the
worktree is dirty or the machine type differs. Configure passwordless localhost
SSH for the disposable VM because the existing multi-machine path is retained:

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
    "window": list(config.epoch_indices),
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
the requested scale.

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
  "$PYTHON_BIN" - "$REPO" "$SCALE_DIR" "$KEY_FILE" <<'PY'
import json
import sys
from pathlib import Path
import numpy as np

repo, root, key = map(Path, sys.argv[1:])
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

## 4. Formal privileged 12-epoch run

Set the selected passing scale explicitly, generate an absolute-path 12-epoch
configuration, and run the fixed scenario. This is the only step that asserts
the full deterministic epoch-6 failure and epoch-7 recovery observation.

```bash
export SELECTED_SCALE=80  # replace only with the scale selected above
export SCALE_DIR="$RUN_ROOT/scale-$SELECTED_SCALE"
export FORMAL_DIR="$SCALE_DIR/formal"
mkdir -p "$FORMAL_DIR"

"$PYTHON_BIN" - "$REPO" "$SCALE_DIR" "$FORMAL_DIR" \
  "$KEY_FILE" <<'PY'
import json
import sys
from pathlib import Path

repo, root, formal, key = map(Path, sys.argv[1:])
base = json.loads(
    (repo / "network_orchestrator/test/config/tinyleo_canada_parity.json")
    .read_text(encoding="utf-8")
)
artifacts = root / "artifacts"
base.update(
    {
        "Name": f"tinyleo_canada_parity_formal_{root.name}",
        "Duration (s)": 12,
        "start_epoch": 0,
        "num_epochs": 12,
        "satellite_file": str(artifacts / "canada_parity_satellite_data.npy"),
        "traffic_matrix_file": str(artifacts / "canada_parity_traffic_matrix.npy"),
        "grid_satellites_file": str(artifacts / "canada_parity_grid_satellites.npy"),
        "block_positions_file": str(artifacts / "block_positions.json"),
        "topo_dir": str(root / "topology"),
        "Machines": [{
            "IP": "127.0.0.1", "port": 22, "username": "root",
            "key_filename": str(key),
        }],
    }
)
(formal / "config.json").write_text(
    json.dumps(base, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
south_policy = (
    repo / "network_orchestrator/test/config/geographic_routing_policy_canada_south.json"
).read_text(encoding="utf-8")
(formal / "geopraphic_routing_policy.json").write_text(
    south_policy, encoding="utf-8"
)
PY

(
  cd "$REPO/network_orchestrator"
  set -o pipefail
  if ! sudo -E env PYTHONPATH="$REPO/network_orchestrator" \
    "$PYTHON_BIN" test/example_canada_parity.py \
    --config "$FORMAL_DIR/config.json" \
    --south-policy test/config/geographic_routing_policy_canada_south.json \
    --north-policy test/config/geographic_routing_policy_canada_north.json \
    --backbone-demand "$REPO/network_synthesizer/test/data/canada_parity_backbone_demand.npy" \
    --validation-report "$SCALE_DIR/validation-12/validation_report.json" \
    --result-dir "$FORMAL_DIR/results" \
    --measurement-wait-s 15 \
    2>&1 | tee "$FORMAL_DIR/emulation.log"; then
    exit 1
  fi
)
sudo chown -R "$(id -u):$(id -g)" "$FORMAL_DIR"

sudo ip netns list | tee "$FORMAL_DIR/netns-after-cleanup.txt"
pgrep -af 'sn_remote.py|srv6_agent.py|iperf3' \
  | tee "$FORMAL_DIR/processes-after-cleanup.txt" || true
free -b | tee "$FORMAL_DIR/free-after-cleanup.txt"
swapon --show --bytes | tee "$FORMAL_DIR/swap-after-cleanup.txt"
```

`netns-after-cleanup.txt` and `processes-after-cleanup.txt` must be empty. Treat
residual namespaces or TinyLEO processes as a failed run; inspect them before
manual removal rather than hiding a cleanup defect.

Run the machine-readable checker with explicit inputs:

```bash
"$PYTHON_BIN" \
  "$REPO/network_orchestrator/test/check_canada_parity_results.py" \
  "$FORMAL_DIR/results" \
  --validation-report "$SCALE_DIR/validation-12/validation_report.json" \
  --synthesis-result "$SCALE_DIR/synthesis_result.npy"
test "$("$PYTHON_BIN" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["valid"])' \
  "$FORMAL_DIR/results/acceptance_summary.json")" = True
```

The checker exits zero only when all 12 epochs, memory/swap/update gates,
topology dynamics, path diversity, ping, and independently parsed recovery
evidence pass. `STATUS: ERROR`, `STATUS: MISSING`, attempted-only recovery,
malformed/duplicate evidence, and non-finite numbers fail closed.

| Formal metric | Observed |
|---|---|
| Selected satellites | PENDING — run on n2-standard-8 |
| Coverage ratio | PENDING — run on n2-standard-8 |
| Peak host used GiB / swap GiB | PENDING — run on n2-standard-8 |
| p50 / p95 topology update | PENDING — run on n2-standard-8 |
| Path-diverse epochs | PENDING — run on n2-standard-8 |
| Topology changes / gateway handovers | PENDING — run on n2-standard-8 |
| Vancouver→Toronto ping | PENDING — run on n2-standard-8 |
| Epoch-6 failure / epoch-7 changed recovery path | PENDING — run on n2-standard-8 |
| Overall acceptance | PENDING — run on n2-standard-8 |

## 5. Fixed-artifact routing A/B

Keep the selected constellation and epoch-0 grid mapping immutable. Compare
stock shortest path against a geographic policy that avoids southern cell 24,
which is intended to steer onto the available northern Canada corridor. Inspect
the recorded paths rather than assuming the steering succeeded. This is a control-plane A/B;
the formal packet-level run above remains the end-to-end evidence.

```bash
PYTHONPATH="$REPO/network_orchestrator" \
  "$PYTHON_BIN" - "$SCALE_DIR/artifacts/canada_parity_grid_satellites.npy" \
  "$FORMAL_DIR/routing-ab.json" <<'PY'
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from northbound import TinyLEONorthboundAPI

grid_path, output_path = map(Path, sys.argv[1:])
mapping = np.load(grid_path, allow_pickle=True).item()
base = {
    "grid_config": {"rows": 11, "cols": 11},
    "global_settings": {"isl_capacity_gbps": 200.0},
    "traffic_demands": [],
}
with tempfile.TemporaryDirectory() as tmp:
    config_path = Path(tmp) / "config.json"
    config_path.write_text(json.dumps(base), encoding="utf-8")
    api = TinyLEONorthboundAPI(str(config_path))
    rows = []
    for epoch in range(12):
        api.grid_density = {
            grid: len(mapping[epoch][grid]) for grid in range(121)
        }
        shortest = api.find_path(
            23, 25, {"routing_policy": "shortest_path"}
        )
        geographic = api.find_path(
            23, 25, {"routing_policy": "geo_avoid", "avoid_cells": [24]}
        )
        rows.append(
            {"epoch": epoch, "shortest_path": shortest,
             "geographic_avoid_24": geographic,
             "path_changed": shortest != geographic}
        )
output_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
PY
```

Report path sequences, changed-epoch count, reachability, ping/throughput (when
packet-level A/B is repeated), and never describe stock `multipath` as a
separate algorithm because it currently falls back to shortest path.

| Routing comparison | Geographic policy | Shortest path |
|---|---|---|
| Reachable epochs | PENDING — run on n2-standard-8 | PENDING — run on n2-standard-8 |
| Path sequences / changed epochs | PENDING — run on n2-standard-8 | PENDING — run on n2-standard-8 |
| Ping / throughput | PENDING — optional packet-level repeat | PENDING — optional packet-level repeat |

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
