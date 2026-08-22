"""Quick check: C2 density and empty transit after capacity fix."""
import importlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.chdir(Path(__file__).resolve().parent)

import northbound as nb

nb = importlib.reload(nb)
base = json.loads(Path("config/mpc_config.json").read_text(encoding="utf-8"))
GRID = "data/topo_data/grid_satellites_map_for_backbone.npy"


def run(pol: str):
    cfg = deepcopy(base)
    for d in cfg["traffic_demands"]:
        d["routing_policy"] = pol
        if pol == "shortest_path":
            d.pop("avoid_cells", None)
    out = Path("result/cap_fix") / pol
    out.mkdir(parents=True, exist_ok=True)
    p = out / "mpc.json"
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    api = nb.TinyLEONorthboundAPI(str(p))
    tm, isl = api.generate_and_save_traffic_matrices(
        grid_satellites_file=GRID, output_dir=str(out)
    )
    dens = []
    empty_paths = 0
    for d in cfg["traffic_demands"]:
        if d.get("service_class") != "C2" and int(d.get("priority", 3)) < 5:
            continue
        path = api.paths.get((d["source"], d["destination"]), [])
        if len(path) < 2:
            continue
        mean_s = sum(api._cell_satellite_count(c) for c in path) / len(path)
        dens.append(mean_s)
        empty = [c for c in path[1:-1] if api._cell_satellite_count(c) <= 0]
        if empty:
            empty_paths += 1
        print(
            pol,
            f"{d['source']}-{d['destination']}",
            "hops",
            len(path) - 1,
            "mean_sats",
            round(mean_s, 1),
            "empty",
            empty,
            "path",
            path,
        )
    # all-path empty transit count
    all_empty = 0
    for path in api.paths.values():
        if any(api._cell_satellite_count(c) <= 0 for c in path[1:-1]):
            all_empty += 1
    return float(isl.sum() / 2), dens, all_empty


sp_isl, sp_d, sp_empty = run("shortest_path")
print("---")
qos_isl, qos_d, qos_empty = run("qos_priority")
print(
    "ISL SP",
    sp_isl,
    "QoS",
    qos_isl,
    "delta_pct",
    round(100 * (qos_isl - sp_isl) / sp_isl, 2),
)
print(
    "C2 mean density SP",
    round(sum(sp_d) / len(sp_d), 1) if sp_d else None,
    "QoS",
    round(sum(qos_d) / len(qos_d), 1) if qos_d else None,
)
print("paths with empty transit: SP", sp_empty, "QoS", qos_empty)
