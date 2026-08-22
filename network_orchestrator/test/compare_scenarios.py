"""
Multi-scenario comparison for TinyLEO northbound routing (DND Part 2).

Scenarios = named overlays on mpc_config.json (policy, priority shifts, avoid cells, etc.).
Outputs a side-by-side hop/path table and aggregate KPIs under result/scenario_compare/.

Important: hop counts often stay the same when *routes* change. Always check
paths_changed / path__* columns, not only mean_hops.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List

import numpy as np
import pandas as pd

TEST_DIR = Path(__file__).resolve().parent
ORCH_DIR = TEST_DIR.parent
sys.path.insert(0, str(ORCH_DIR))
os.chdir(TEST_DIR)


def _load_api():
    import importlib
    import northbound as nb

    nb = importlib.reload(nb)
    if not hasattr(nb.TinyLEONorthboundAPI, "find_qos_priority_path"):
        raise RuntimeError(
            f"Stale northbound at {nb.__file__} lacks find_qos_priority_path. Restart the process."
        )
    return nb.TinyLEONorthboundAPI


CONFIG = TEST_DIR / "config" / "mpc_config.json"
GRID = TEST_DIR / "data" / "topo_data" / "grid_satellites_map_for_backbone.npy"
OUT = TEST_DIR / "result" / "scenario_compare"


ScenarioFn = Callable[[dict], dict]


def base_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def with_uniform_policy(policy: str) -> ScenarioFn:
    def _fn(cfg: dict) -> dict:
        cfg = deepcopy(cfg)
        for d in cfg["traffic_demands"]:
            d["routing_policy"] = policy
            # Strip QoS-only knobs so SP / oceanic runs are clean baselines
            if policy == "shortest_path":
                d.pop("avoid_cells", None)
                d.pop("max_latency_ms", None)
        return cfg

    return _fn


def with_priority_boost(delta: int) -> ScenarioFn:
    """Shift all priorities by delta, clipped to [1,5]."""

    def _fn(cfg: dict) -> dict:
        cfg = deepcopy(cfg)
        for d in cfg["traffic_demands"]:
            d["routing_policy"] = "qos_priority"
            p = int(d.get("priority", 3)) + delta
            d["priority"] = max(1, min(5, p))
        return cfg

    return _fn


def with_equal_priority(priority: int = 3) -> ScenarioFn:
    """Remove mission differentiation — all flows same priority."""

    def _fn(cfg: dict) -> dict:
        cfg = deepcopy(cfg)
        for d in cfg["traffic_demands"]:
            d["routing_policy"] = "qos_priority"
            d["priority"] = priority
            d["service_class"] = "equal_priority"
            d.pop("max_latency_ms", None)
        return cfg

    return _fn


def with_global_avoid(cells: List[int]) -> ScenarioFn:
    def _fn(cfg: dict) -> dict:
        cfg = deepcopy(cfg)
        for d in cfg["traffic_demands"]:
            d["routing_policy"] = "qos_priority"
            avoid = set(d.get("avoid_cells", []) or [])
            avoid.update(cells)
            avoid.discard(int(d["source"]))
            avoid.discard(int(d["destination"]))
            d["avoid_cells"] = sorted(avoid)
        return cfg

    return _fn


def with_c2_only_latency(ms: float) -> ScenarioFn:
    def _fn(cfg: dict) -> dict:
        cfg = deepcopy(cfg)
        for d in cfg["traffic_demands"]:
            d["routing_policy"] = "qos_priority"
            if int(d.get("priority", 3)) >= 5 or d.get("service_class") == "C2":
                d["max_latency_ms"] = ms
                d["approx_hop_ms"] = 25.0
        return cfg

    return _fn


def with_inverted_priority() -> ScenarioFn:
    """Swap mission order (C2 becomes best-effort) — stress-test reservation."""

    def _fn(cfg: dict) -> dict:
        cfg = deepcopy(cfg)
        for d in cfg["traffic_demands"]:
            d["routing_policy"] = "qos_priority"
            p = int(d.get("priority", 3))
            d["priority"] = 6 - p  # 5↔1, 4↔2, 3↔3
        return cfg

    return _fn


BUILTIN_SCENARIOS: Dict[str, ScenarioFn] = {
    # Always-different pair (use these first)
    "A_shortest_path": with_uniform_policy("shortest_path"),
    "B_qos_priority": with_uniform_policy("qos_priority"),
    # Policy / geography / priority variants
    "C_oceanic_offload": with_uniform_policy("oceanic_offload"),
    "D_geo_avoid_mid": with_global_avoid([28, 29, 39, 50, 38, 49, 60]),
    "E_strict_C2_latency": with_c2_only_latency(75.0),  # max ~3 hops @ 25ms
    "F_equal_priority": with_equal_priority(3),
    "G_inverted_priority": with_inverted_priority(),
}

# Human-readable one-liners for the GUI
SCENARIO_HELP: Dict[str, str] = {
    "A_shortest_path": "Baseline: hop-minimizing Dijkstra (old TinyLEO default)",
    "B_qos_priority": "Part 2: QoS weights + priority-ordered load reservation",
    "C_oceanic_offload": "Prefer preferred_cells (oceanic offload)",
    "D_geo_avoid_mid": "QoS + hard-avoid mid-grid cells (28/29/38/39/49/50/60)",
    "E_strict_C2_latency": "QoS + C2 limited to ~3 hops (75 ms budget)",
    "F_equal_priority": "QoS but every demand priority=3 (no mission ordering)",
    "G_inverted_priority": "QoS with priorities flipped (C2 routed last)",
}


def run_scenario(name: str, cfg: dict) -> dict:
    out_dir = OUT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = out_dir / "mpc_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    TinyLEONorthboundAPI = _load_api()
    api = TinyLEONorthboundAPI(str(cfg_path))
    tm, isl = api.generate_and_save_traffic_matrices(
        grid_satellites_file=str(GRID),
        output_dir=str(out_dir),
    )
    api.get_and_save_paths(output_dir=str(out_dir))
    conn = api.analyze_and_save_connectivity(output_dir=str(out_dir))

    paths = {f"{a}-{b}": list(p) for (a, b), p in api.paths.items()}
    hops = {k: max(len(p) - 1, 0) for k, p in paths.items()}
    return {
        "name": name,
        "paths": paths,
        "hops": hops,
        "mean_hops": float(np.mean(list(hops.values()))) if hops else 0.0,
        "traffic_path_volume": float(tm.sum() / 2),
        "isl_total": float(isl.sum() / 2),
        "connected": bool(conn.get("is_connected", False)),
        "demands": deepcopy(cfg.get("traffic_demands", [])),
    }


def compare(scenario_names: List[str]):
    OUT.mkdir(parents=True, exist_ok=True)
    base = base_config()
    results = []
    for name in scenario_names:
        if name not in BUILTIN_SCENARIOS:
            raise KeyError(f"Unknown scenario {name}. Choose from {list(BUILTIN_SCENARIOS)}")
        cfg = BUILTIN_SCENARIOS[name](base)
        print(f"Running scenario {name} ...")
        results.append(run_scenario(name, cfg))

    # Aggregate KPI table
    agg_rows = []
    first = results[0]
    for r in results:
        path_delta = sum(
            1 for k in set(first["paths"]) | set(r["paths"]) if first["paths"].get(k) != r["paths"].get(k)
        )
        agg_rows.append(
            {
                "scenario": r["name"],
                "mean_hops": round(r["mean_hops"], 3),
                "mean_hops_delta_vs_first": round(r["mean_hops"] - first["mean_hops"], 3),
                "paths_changed_vs_first": path_delta if r is not first else 0,
                "path_volume_Gbps": round(r["traffic_path_volume"], 1),
                "isl_req_total": round(r["isl_total"], 1),
                "connected": r["connected"],
                "num_paths": len(r["paths"]),
            }
        )
    agg = pd.DataFrame(agg_rows)
    agg.to_csv(OUT / "aggregate_kpis.csv", index=False)
    (OUT / "aggregate_kpis.json").write_text(agg.to_json(orient="records", indent=2), encoding="utf-8")

    # Per-demand hop / path comparison
    all_keys = sorted(set().union(*[set(r["hops"]) for r in results]))
    pmap = {
        f"{d['source']}-{d['destination']}": (
            int(d.get("priority", 3)),
            d.get("service_class", ""),
        )
        for d in base.get("traffic_demands", [])
    }
    hop_rows = []
    for k in all_keys:
        row: Dict[str, Any] = {
            "demand": k,
            "priority": pmap.get(k, (None, None))[0],
            "service_class": pmap.get(k, (None, None))[1],
        }
        for r in results:
            row[f"hops__{r['name']}"] = r["hops"].get(k)
            row[f"path__{r['name']}"] = "→".join(map(str, r["paths"].get(k, [])))
        base_path = row.get(f"path__{results[0]['name']}")
        base_h = row.get(f"hops__{results[0]['name']}")
        row["path_changed_vs_first"] = any(
            row.get(f"path__{r['name']}") != base_path for r in results[1:]
        )
        row["hops_changed_vs_first"] = any(
            row.get(f"hops__{r['name']}") != base_h for r in results[1:]
        )
        hop_rows.append(row)
    hops_df = pd.DataFrame(hop_rows)
    hops_df.to_csv(OUT / "per_demand_hops.csv", index=False)

    if len(results) >= 2:
        summary = {"baseline": first["name"], "comparisons": []}
        for r in results[1:]:
            changed = sum(1 for k in all_keys if first["paths"].get(k) != r["paths"].get(k))
            hop_changed = sum(1 for k in all_keys if first["hops"].get(k) != r["hops"].get(k))
            summary["comparisons"].append(
                {
                    "scenario": r["name"],
                    "paths_changed": changed,
                    "hops_changed": hop_changed,
                    "paths_total": len(all_keys),
                    "mean_hops_delta": round(r["mean_hops"] - first["mean_hops"], 3),
                }
            )
        (OUT / "comparison_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )

    return agg, hops_df


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare TinyLEO northbound scenarios")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=["A_shortest_path", "B_qos_priority", "D_geo_avoid_mid", "F_equal_priority", "G_inverted_priority"],
        help=f"Subset of {list(BUILTIN_SCENARIOS)}",
    )
    args = parser.parse_args()
    print("Built-in scenarios:", ", ".join(BUILTIN_SCENARIOS))
    for name, help_txt in SCENARIO_HELP.items():
        print(f"  {name}: {help_txt}")
    agg, hops = compare(args.scenarios)
    print("\n=== Aggregate KPIs ===")
    print(agg.to_string(index=False))
    print(f"\nWrote {OUT / 'aggregate_kpis.csv'}")
    print(f"Wrote {OUT / 'per_demand_hops.csv'}")
    print(f"Wrote {OUT / 'comparison_summary.json'}")
    path_chg = int(hops["path_changed_vs_first"].sum()) if "path_changed_vs_first" in hops else 0
    hop_chg = int(hops["hops_changed_vs_first"].sum()) if "hops_changed_vs_first" in hops else 0
    print(f"Demands with PATH change vs first: {path_chg}/{len(hops)}")
    print(f"Demands with HOP  change vs first: {hop_chg}/{len(hops)}")
    print("(Hop counts can match even when the geographic route changes.)")


if __name__ == "__main__":
    main()
