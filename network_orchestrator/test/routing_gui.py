"""
TinyLEO Part 2 — Routing Configuration GUI

Edit northbound routing policies, save mpc_config.json, optionally edit
geographic segment policies, and re-run the northbound example to inspect paths.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import traceback
from copy import deepcopy
from pathlib import Path

import pandas as pd
import streamlit as st

TEST_DIR = Path(__file__).resolve().parent
ORCH_DIR = TEST_DIR.parent
CONFIG_PATH = TEST_DIR / "config" / "mpc_config.json"
GEO_POLICY_PATH = TEST_DIR / "config" / "geopraphic_routing_policy.json"
GRID_MAP = TEST_DIR / "data" / "topo_data" / "grid_satellites_map_for_backbone.npy"
OUTPUT_DIR = TEST_DIR / "result" / "gui_nbi"

# multipath kept for TinyLEO parity — upstream implements it as shortest_path
POLICIES = ["qos_priority", "shortest_path", "oceanic_offload", "geo_avoid", "multipath"]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def demands_to_df(demands: list) -> pd.DataFrame:
    rows = []
    for d in demands:
        rows.append(
            {
                "source": int(d.get("source", 0)),
                "destination": int(d.get("destination", 0)),
                "demand_gbps": float(d.get("demand_gbps", 0)),
                "routing_policy": d.get("routing_policy", "qos_priority"),
                "priority": int(d.get("priority", 3)),
                "service_class": d.get("service_class", ""),
                "max_latency_ms": float(d.get("max_latency_ms"))
                if d.get("max_latency_ms") is not None
                else None,
                "avoid_cells": ",".join(str(x) for x in d.get("avoid_cells", []) or []),
                "preferred_cells": ",".join(
                    str(x) for x in d.get("preferred_cells", []) or []
                ),
                "preference_weight": float(d.get("preference_weight", 0.5)),
            }
        )
    return pd.DataFrame(rows)


def df_to_demands(df: pd.DataFrame) -> list:
    demands = []
    for _, row in df.iterrows():
        policy = str(row["routing_policy"]).strip() or "qos_priority"
        if policy not in POLICIES:
            policy = "qos_priority"
        demand = {
            "source": int(row["source"]),
            "destination": int(row["destination"]),
            "demand_gbps": float(row["demand_gbps"]),
            "routing_policy": policy,
            "priority": int(row.get("priority", 3) or 3),
        }
        sc = str(row.get("service_class", "") or "").strip()
        if sc:
            demand["service_class"] = sc
        ml = row.get("max_latency_ms")
        if ml is not None and str(ml) not in ("", "nan", "None"):
            try:
                demand["max_latency_ms"] = float(ml)
            except (TypeError, ValueError):
                pass
        avoid = str(row.get("avoid_cells", "") or "").strip()
        if avoid:
            demand["avoid_cells"] = [
                int(x.strip()) for x in avoid.split(",") if x.strip()
            ]
        preferred = str(row.get("preferred_cells", "") or "").strip()
        if preferred:
            demand["preferred_cells"] = [
                int(x.strip()) for x in preferred.split(",") if x.strip()
            ]
            demand["preference_weight"] = float(
                row.get("preference_weight", 0.5) or 0.5
            )
        demands.append(demand)
    return demands


def apply_bulk_policy(demands: list, policy: str) -> list:
    out = deepcopy(demands)
    for d in out:
        d["routing_policy"] = policy
        if policy == "geo_avoid" and not d.get("avoid_cells"):
            # Demo avoid set so geo_avoid is visibly different from SP
            d["avoid_cells"] = [28, 29, 39, 50]
            src, dst = int(d["source"]), int(d["destination"])
            d["avoid_cells"] = [c for c in d["avoid_cells"] if c not in (src, dst)]
        if policy == "oceanic_offload" and not d.get("preferred_cells"):
            d["preferred_cells"] = [22, 32, 43, 54, 65, 76]
            d["preference_weight"] = 0.3
        if policy == "shortest_path" or policy == "multipath":
            d.pop("avoid_cells", None)
            d.pop("preferred_cells", None)
            if policy == "shortest_path":
                d.pop("max_latency_ms", None)
    return out


def policy_trap_warnings(demands: list) -> list[str]:
    warns = []
    pols = {d.get("routing_policy", "qos_priority") for d in demands}
    if pols == {"shortest_path"}:
        warns.append("All demands use shortest_path — every path is hop-minimal (no QoS contrast).")
    if "oceanic_offload" in pols:
        missing = sum(1 for d in demands if d.get("routing_policy") == "oceanic_offload" and not d.get("preferred_cells"))
        if missing:
            warns.append(
                f"{missing} oceanic_offload demand(s) have empty preferred_cells → identical to shortest_path."
            )
    if "geo_avoid" in pols:
        missing = sum(1 for d in demands if d.get("routing_policy") == "geo_avoid" and not d.get("avoid_cells"))
        if missing:
            warns.append(
                f"{missing} geo_avoid demand(s) have empty avoid_cells → identical to shortest_path."
            )
    if "multipath" in pols:
        warns.append(
            "multipath is listed for TinyLEO parity but is NOT implemented — "
            "it equals shortest_path, so comparisons will look identical. Use qos_priority for Part 2."
        )
    return warns


def load_northbound_api():
    """
    Always reload northbound.py from disk.

    Streamlit keeps Python modules cached across button clicks. An old session
    started before qos_priority existed will treat every policy as shortest_path
    and all scenario results look identical.
    """
    sys.path.insert(0, str(ORCH_DIR))
    os.chdir(TEST_DIR)
    import northbound as nb

    nb = importlib.reload(nb)
    if not hasattr(nb.TinyLEONorthboundAPI, "find_qos_priority_path"):
        raise RuntimeError(
            f"Stale northbound loaded from {nb.__file__}: missing find_qos_priority_path. "
            "Stop the GUI (Ctrl+C) and restart start_routing_gui.bat."
        )
    return nb.TinyLEONorthboundAPI, nb


def run_northbound(config_path: Path, output_dir: Path | None = None) -> dict:
    """Run northbound steps 1–4 against the given config; return paths/connectivity."""
    TinyLEONorthboundAPI, nb = load_northbound_api()

    out = output_dir or OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    api = TinyLEONorthboundAPI(str(config_path))
    traffic_matrix, isl_matrix = api.generate_and_save_traffic_matrices(
        grid_satellites_file=str(GRID_MAP),
        output_dir=str(out),
    )
    paths = api.get_and_save_paths(output_dir=str(out))
    connectivity = api.analyze_and_save_connectivity(output_dir=str(out))
    status = {
        f"{s}-{d}": meta for (s, d), meta in getattr(api, "path_status", {}).items()
    }
    return {
        "traffic_shape": list(traffic_matrix.shape),
        "traffic_total_gbps": float(traffic_matrix.sum() / 2),
        "isl_total": float(isl_matrix.sum() / 2),
        "paths": paths,
        "path_status": status,
        "connectivity": connectivity,
        "mean_hops": float(
            sum(max(len(p) - 1, 0) for p in paths.values()) / max(len(paths), 1)
        ),
        "northbound_file": str(Path(nb.__file__).resolve()),
        "has_qos": hasattr(api, "find_qos_priority_path"),
    }


def path_length_table(paths: dict, path_status: dict | None = None) -> pd.DataFrame:
    rows = []
    path_status = path_status or {}
    for key, path in paths.items():
        meta = path_status.get(key, {})
        rows.append(
            {
                "demand": key,
                "path": " -> ".join(str(x) for x in path),
                "hops": max(len(path) - 1, 0),
                "cells": len(path),
                "budget_violated": meta.get("budget_violated", False),
                "used_fallback": meta.get("used_fallback", False),
                "est_latency_ms": meta.get("estimated_latency_ms"),
                "max_latency_ms": meta.get("max_latency_ms"),
            }
        )
    return pd.DataFrame(rows)


st.set_page_config(
    page_title="TinyLEO Routing GUI",
    page_icon=None,
    layout="wide",
)

st.title("TinyLEO Part 2 — Routing Configuration GUI")
st.caption(
    "Edit northbound geographic routing policies, save config, and re-run path computation. "
    "Default Part 2 algorithm is qos_priority (centralized QoS / mission-priority routing)."
)

# Fingerprint so a stale Streamlit session is obvious
try:
    _Api, _nb = load_northbound_api()
    _nb_path = Path(_nb.__file__).resolve()
    _has_qos = hasattr(_Api, "find_qos_priority_path")
    if _has_qos:
        st.success(f"Loaded QoS-capable northbound: `{_nb_path.name}`")
    else:
        st.error(
            "Stale northbound without qos_priority. "
            "Close this tab, run start_routing_gui.bat again (it kills the old process)."
        )
except Exception as _e:
    st.error(f"Could not load northbound: {_e}")

with st.sidebar:
    st.header("Files")
    st.code(str(CONFIG_PATH), language=None)
    st.code(str(GEO_POLICY_PATH), language=None)
    st.markdown(
        """
**Policies that actually differ**
- `qos_priority` — Part 2 QoS / mission priority
- `shortest_path` — classic Dijkstra

**Need extra fields or they collapse to SP**
- `oceanic_offload` — needs `preferred_cells`
- `geo_avoid` — needs `avoid_cells`

**Same as shortest_path today**
- `multipath` — listed for TinyLEO parity; **not implemented** (falls back to SP)

**Priority:** 5=C2, 4=ISR, 3=telemetry, 2=bulk, 1=best effort
"""
    )
    if st.button("Reload config from disk"):
        st.session_state.pop("config", None)
        st.session_state.pop("geo_policy_text", None)
        st.session_state.pop("demands_editor", None)
        st.rerun()

if "config" not in st.session_state:
    st.session_state.config = load_json(CONFIG_PATH)
if "geo_policy_text" not in st.session_state:
    st.session_state.geo_policy_text = GEO_POLICY_PATH.read_text(encoding="utf-8")
if "last_result" not in st.session_state:
    st.session_state.last_result = None

config = st.session_state.config
demands = config.get("traffic_demands", [])

# Live trap detection
for w in policy_trap_warnings(demands):
    st.warning(w)

tab_demands, tab_geo, tab_run, tab_compare, tab_help = st.tabs(
    [
        "Traffic demands & routing",
        "Geographic segment policy",
        "Run northbound",
        "Compare scenarios",
        "Help",
    ]
)

with tab_demands:
    st.subheader("Bulk actions")
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        bulk_policy = st.selectbox("Set ALL demands to policy", POLICIES, index=0)
    with c2:
        if st.button("Apply bulk policy", use_container_width=True):
            config["traffic_demands"] = apply_bulk_policy(demands, bulk_policy)
            st.session_state.config = config
            st.success(f"All demands set to `{bulk_policy}`")
            st.rerun()
    with c3:
        if st.button("Restore Part-2 QoS defaults", use_container_width=True):
            st.session_state.config = load_json(CONFIG_PATH)
            # Force qos even if disk was wrong before this session wrote it
            cfg = st.session_state.config
            for d in cfg.get("traffic_demands", []):
                d["routing_policy"] = "qos_priority"
            save_json(CONFIG_PATH, cfg)
            st.success("Restored qos_priority on all demands and saved.")
            st.rerun()

    st.subheader("Edit demands")
    st.caption(
        "For geo_avoid, put cell IDs in avoid_cells (comma-separated). "
        "For oceanic_offload, use preferred_cells and preference_weight. "
        "Bulk-apply fills demo cells automatically."
    )
    df = demands_to_df(config.get("traffic_demands", []))
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "routing_policy": st.column_config.SelectboxColumn(
                "routing_policy",
                options=POLICIES,
                required=True,
            ),
            "priority": st.column_config.NumberColumn(min_value=1, max_value=5, step=1),
            "source": st.column_config.NumberColumn(min_value=0, max_value=120, step=1),
            "destination": st.column_config.NumberColumn(min_value=0, max_value=120, step=1),
            "demand_gbps": st.column_config.NumberColumn(min_value=0.0, step=1.0),
            "max_latency_ms": st.column_config.NumberColumn(min_value=0.0, step=10.0),
            "preference_weight": st.column_config.NumberColumn(
                min_value=0.05, max_value=1.0, step=0.05
            ),
        },
        key="demands_editor",
    )
    # Keep session in sync with the live editor so Run tab never uses stale policies
    try:
        st.session_state.config["traffic_demands"] = df_to_demands(edited)
        config = st.session_state.config
    except Exception:
        pass

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Apply table edits to session", type="primary", use_container_width=True):
            try:
                config["traffic_demands"] = df_to_demands(edited)
                st.session_state.config = config
                st.success("Session config updated from table.")
            except Exception as e:
                st.error(f"Could not parse table: {e}")
    with b2:
        if st.button("Save to mpc_config.json", use_container_width=True):
            try:
                config["traffic_demands"] = df_to_demands(edited)
                st.session_state.config = config
                save_json(CONFIG_PATH, config)
                st.success(f"Saved {CONFIG_PATH}")
            except Exception as e:
                st.error(f"Save failed: {e}")
    with b3:
        if st.button("Reset session to disk", use_container_width=True):
            st.session_state.config = load_json(CONFIG_PATH)
            st.rerun()

    with st.expander("Raw mpc_config.json preview"):
        st.json(st.session_state.config)

with tab_geo:
    st.subheader("Emulation geographic segment list")
    st.caption(
        "Used by southbound/SRv6 container runs (Linux). "
        'Format: "[row, col]->[row, col]": [[cell steps...]]'
    )
    geo_text = st.text_area(
        "geopraphic_routing_policy.json",
        value=st.session_state.geo_policy_text,
        height=220,
    )
    st.session_state.geo_policy_text = geo_text
    g1, g2 = st.columns(2)
    with g1:
        if st.button("Validate JSON", use_container_width=True):
            try:
                json.loads(geo_text)
                st.success("Valid JSON")
            except Exception as e:
                st.error(f"Invalid JSON: {e}")
    with g2:
        if st.button("Save geographic policy", use_container_width=True):
            try:
                parsed = json.loads(geo_text)
                save_json(GEO_POLICY_PATH, parsed)
                st.session_state.geo_policy_text = json.dumps(parsed, indent=2) + "\n"
                st.success(f"Saved {GEO_POLICY_PATH}")
            except Exception as e:
                st.error(f"Save failed: {e}")

with tab_run:
    st.subheader("Run northbound")
    st.caption(
        "Runs path computation using the routing_policy on each demand in the current config. "
        "For side-by-side scenario diffs, use the **Compare scenarios** tab."
    )
    pols = sorted(
        {
            str(d.get("routing_policy", "qos_priority"))
            for d in st.session_state.config.get("traffic_demands", [])
        }
    )
    st.write("Selected policies in config:", ", ".join(f"`{p}`" for p in pols) or "(none)")

    save_before = st.checkbox("Save current session config before run", value=True)
    if st.button("Run northbound (steps 1–4)", type="primary"):
        try:
            if save_before:
                save_json(CONFIG_PATH, st.session_state.config)
            for w in policy_trap_warnings(st.session_state.config.get("traffic_demands", [])):
                st.warning(w)
            with st.spinner("Computing traffic matrices and paths..."):
                result = run_northbound(CONFIG_PATH)
            st.session_state.last_result = result
            st.success(
                f"Done. mean_hops={result['mean_hops']:.3f}, ISL={result['isl_total']:.1f}"
            )
        except Exception:
            st.error("Northbound run failed")
            st.code(traceback.format_exc())

    result = st.session_state.last_result
    if result:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Demands / paths", len(result["paths"]))
        m2.metric("Traffic total (Gbps)", f"{result['traffic_total_gbps']:.1f}")
        m3.metric("ISL req. total", f"{result['isl_total']:.1f}")
        m4.metric("Mean hops", f"{result['mean_hops']:.3f}")
        status = result.get("path_status") or {}
        n_bad = sum(
            1
            for m in status.values()
            if m.get("budget_violated") or m.get("used_fallback")
        )
        if n_bad:
            st.warning(
                f"{n_bad} demand(s) used fallback and/or violated latency budget "
                "(see budget_violated / used_fallback columns)."
            )
        st.dataframe(
            path_length_table(result["paths"], status),
            use_container_width=True,
        )
        st.caption(f"Artifacts written to {OUTPUT_DIR}")

with tab_compare:
    st.subheader("Compare multiple scenarios")
    st.info(
        "Always include **A_shortest_path** + **B_qos_priority**. "
        "Look at **paths_changed_vs_first** (not only hop counts)."
    )
    scenario_options = [
        "A_shortest_path",
        "B_qos_priority",
        "C_oceanic_offload",
        "D_geo_avoid_mid",
        "E_strict_C2_latency",
        "F_equal_priority",
        "G_inverted_priority",
    ]
    chosen = st.multiselect(
        "Scenarios to run",
        options=scenario_options,
        default=["A_shortest_path", "B_qos_priority", "D_geo_avoid_mid", "F_equal_priority"],
    )
    if st.button("Run scenario comparison", type="primary"):
        if len(chosen) < 2:
            st.warning("Select at least two scenarios.")
        else:
            try:
                sys.path.insert(0, str(TEST_DIR))
                import compare_scenarios as cs

                cs = importlib.reload(cs)
                save_json(CONFIG_PATH, st.session_state.config)
                with st.spinner("Running scenarios..."):
                    agg, hops = cs.compare(chosen)
                st.session_state.compare_agg = agg
                st.session_state.compare_hops = hops
                st.session_state.compare_out = str(cs.OUT)
                st.success(f"Wrote results under {cs.OUT}")
            except Exception:
                st.error("Comparison failed")
                st.code(traceback.format_exc())

    if st.session_state.get("compare_agg") is not None:
        agg = st.session_state.compare_agg
        hops = st.session_state.compare_hops
        st.subheader("Aggregate KPIs")
        st.dataframe(agg, use_container_width=True)
        if "paths_changed_vs_first" in agg.columns:
            total_changed = int(agg["paths_changed_vs_first"].max())
            if total_changed == 0:
                st.warning("No path differences — include A_shortest_path + B_qos_priority.")
            else:
                st.success(
                    f"Up to **{total_changed}** demands changed route vs `{agg.iloc[0]['scenario']}`."
                )
        hop_cols = [
            c
            for c in hops.columns
            if c.startswith("hops__")
            or c
            in (
                "demand",
                "priority",
                "service_class",
                "path_changed_vs_first",
                "hops_changed_vs_first",
            )
        ]
        st.subheader("Per-demand hops")
        st.dataframe(hops[hop_cols], use_container_width=True)
        path_cols = [
            c
            for c in hops.columns
            if c.startswith("path__")
            or c in ("demand", "priority", "service_class", "path_changed_vs_first")
        ]
        st.subheader("Full geographic paths")
        st.dataframe(hops[path_cols], use_container_width=True)

with tab_help:
    st.markdown(
        f"""
### Tabs
- **Traffic demands & routing** — edit policies / priorities, save config
- **Run northbound** — compute paths for the **selected** policies in the current config only
- **Compare scenarios** — side-by-side A/B (e.g. shortest_path vs qos_priority)

### Policy traps
1. **`multipath` = shortest_path** in upstream TinyLEO (not implemented).
2. **`oceanic_offload` / `geo_avoid`** without preferred/avoid cells also collapse to shortest path.
3. Hop counts can match even when the **route cells** change — compare path strings in the Compare tab.

### Config file
`{CONFIG_PATH}`
"""
    )
