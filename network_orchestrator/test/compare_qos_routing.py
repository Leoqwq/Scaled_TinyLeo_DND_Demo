"""
Compare default shortest_path vs centralized qos_priority routing (DND Part 2).
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np

TEST_DIR = Path(__file__).resolve().parent
ORCH_DIR = TEST_DIR.parent
sys.path.insert(0, str(ORCH_DIR))
os.chdir(TEST_DIR)

from northbound import TinyLEONorthboundAPI

CONFIG = TEST_DIR / "config" / "mpc_config.json"
GRID = TEST_DIR / "data" / "topo_data" / "grid_satellites_map_for_backbone.npy"
OUT = TEST_DIR / "result" / "qos_compare"
OUT.mkdir(parents=True, exist_ok=True)


def run_with_policy(policy: str) -> dict:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for d in cfg["traffic_demands"]:
        d["routing_policy"] = policy
    tmp = OUT / f"mpc_config_{policy}.json"
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    api = TinyLEONorthboundAPI(str(tmp))
    tm, isl = api.generate_and_save_traffic_matrices(
        grid_satellites_file=str(GRID),
        output_dir=str(OUT / policy),
    )
    paths = api.get_and_save_paths(output_dir=str(OUT / policy))
    return {
        "paths": {f"{a}-{b}": p for (a, b), p in api.paths.items()},
        "traffic_total": float(tm.sum() / 2),
        "isl_total": float(isl.sum() / 2),
        "mean_hops": float(np.mean([max(len(p) - 1, 0) for p in api.paths.values()])) if api.paths else 0.0,
    }


def main() -> None:
    print("=" * 72)
    print("DND Part 2: Replace default routing with QoS/priority controller")
    print("=" * 72)

    base_cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    priority_map = {
        f"{d['source']}-{d['destination']}": (
            d.get("priority", 3),
            d.get("service_class", "?"),
        )
        for d in base_cfg["traffic_demands"]
    }

    sp = run_with_policy("shortest_path")
    qos = run_with_policy("qos_priority")

    print("\n--- Aggregate ---")
    print(f"shortest_path: mean_hops={sp['mean_hops']:.2f}, traffic={sp['traffic_total']:.1f} Gbps, ISL_req={sp['isl_total']:.1f}")
    print(f"qos_priority:  mean_hops={qos['mean_hops']:.2f}, traffic={qos['traffic_total']:.1f} Gbps, ISL_req={qos['isl_total']:.1f}")

    print("\n--- Per-demand paths (priority | class | shortest vs qos) ---")
    keys = sorted(set(sp["paths"]) | set(qos["paths"]), key=lambda k: -priority_map.get(k, (0, ""))[0])
    changed = 0
    for k in keys:
        prio, cls = priority_map.get(k, (3, "?"))
        a = sp["paths"].get(k, [])
        b = qos["paths"].get(k, [])
        mark = "CHANGED" if a != b else "same"
        if a != b:
            changed += 1
        print(f"P{prio} {cls:12} {k:8} hops {max(len(a)-1,0)}->{max(len(b)-1,0)} [{mark}]")
        print(f"    SP : {' → '.join(map(str, a))}")
        print(f"    QoS: {' → '.join(map(str, b))}")

    summary = {
        "demands": len(keys),
        "paths_changed": changed,
        "shortest_mean_hops": sp["mean_hops"],
        "qos_mean_hops": qos["mean_hops"],
    }
    (OUT / "comparison_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{changed}/{len(keys)} paths differ under qos_priority.")
    print(f"Wrote artifacts under {OUT}")


if __name__ == "__main__":
    main()
