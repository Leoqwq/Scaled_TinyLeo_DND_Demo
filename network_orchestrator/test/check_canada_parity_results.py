"""Fail-closed acceptance checker for a Canada parity emulation result bundle."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np


EXPECTED_EPOCHS = tuple(range(12))
ACTIVE_GRID_IDS = (12, 13, 14, 23, 24, 25)
GIB = 1024**3
GATE_REQUIREMENTS = {
    "validation_report": "valid == true, errors is empty, and report schema is valid",
    "satellite_count": "64 <= value <= 128",
    "coverage_ratio": "value >= 0.90",
    "runtime_epochs": "validation and both runtime CSVs contain epochs 0..11 exactly once",
    "peak_memory": "peak system_memory_used_bytes < 24 GiB",
    "swap_used": "maximum swap_used_bytes == 0",
    "topology_update_p95": "linear p95 of 12 returned updates < 15 seconds",
    "active_grids": "grids 12,13,14,23,24,25 have positive counts in every epoch",
    "path_diversity": "recomputed edge_disjoint_paths >= 2 ratio >= 0.80 and matches report",
    "topology_changes": "topology_change_count >= 3",
    "gateway_handovers": "gateway_handover_count >= 2",
    "ping_reply": "at least one Vancouver-to-Toronto ping artifact reports received > 0",
    "failure_recovery": "epoch-6 failure returned; epoch-7 captured ping/traceroute prove a changed live path",
}


def _gate(required: str) -> dict[str, Any]:
    return {
        "passed": False,
        "actual": None,
        "required": required,
        "evidence": "not evaluated",
    }


def _number(value: Any, name: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative, got {value!r}")
    if integer:
        if not number.is_integer():
            raise ValueError(f"{name} must be an integer, got {value!r}")
        return int(number)
    return number


def _ratio(value: Any, name: str) -> float:
    ratio = float(_number(value, name))
    if ratio > 1:
        raise ValueError(f"{name} must be at most 1, got {value!r}")
    return ratio


def _csv_number(value: str | None, name: str, *, integer: bool = False):
    if value is None or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is missing")
    text = value.strip()
    if text.lower() in {"true", "false"}:
        raise ValueError(f"{name} must not be boolean")
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric, got {text!r}") from exc
    return _number(number, name, integer=integer)


def _json_object(path: Path, description: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {description} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must contain a JSON object")
    return payload


def _read_runtime_csv(path: Path, required_fields: set[str]) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            fields = set(reader.fieldnames or ())
            missing = required_fields - fields
            if missing:
                raise ValueError(f"{path.name} is missing columns {sorted(missing)}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not rows:
        raise ValueError(f"{path.name} has no data rows")
    return rows


def _epochs(rows: list[dict[str, Any]], source: str) -> tuple[list[int], bool]:
    values = [_csv_number(row.get("epoch"), f"{source}.epoch", integer=True) for row in rows]
    unique = len(set(values)) == len(values)
    exact = unique and tuple(sorted(values)) == EXPECTED_EPOCHS
    return values, exact


def _report_epoch(value: Any, name: str) -> int:
    return int(_number(value, name, integer=True))


def _active_counts(value: Any, epoch: int) -> dict[int, int]:
    if not isinstance(value, dict):
        raise ValueError(f"validation epoch {epoch} active_grid_counts must be an object")
    parsed: dict[int, int] = {}
    for raw_grid, raw_count in value.items():
        try:
            grid = int(raw_grid)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"validation epoch {epoch} has invalid grid {raw_grid!r}") from exc
        if str(grid) != str(raw_grid):
            raise ValueError(f"validation epoch {epoch} has noncanonical grid {raw_grid!r}")
        if grid in parsed:
            raise ValueError(f"validation epoch {epoch} repeats grid {grid}")
        parsed[grid] = int(
            _number(raw_count, f"validation epoch {epoch} grid {grid} count", integer=True)
        )
    return parsed


def _load_synthesis(path: Path) -> dict:
    try:
        loaded = np.load(path, allow_pickle=True)
    except Exception as exc:
        raise ValueError(f"cannot read synthesis result {path}: {exc}") from exc
    if not isinstance(loaded, np.ndarray) or loaded.shape != () or loaded.dtype != object:
        raise ValueError("synthesis result must be a zero-dimensional NumPy object array")
    payload = loaded.item()
    if not isinstance(payload, dict):
        raise ValueError("synthesis result object must be a dictionary")

    selected = payload.get("selected_candidate_ids")
    residual = payload.get("residual_by_time")
    stop_reason = payload.get("stop_reason")
    if (
        not isinstance(selected, np.ndarray)
        or selected.ndim != 1
        or selected.dtype.kind not in "iu"
        or np.any(selected < 0)
        or len(np.unique(selected)) != len(selected)
    ):
        raise ValueError("selected_candidate_ids must be a nonnegative 1-D integer array")
    if (
        not isinstance(residual, np.ndarray)
        or residual.shape != (12, 121)
        or residual.dtype.kind not in "iuf"
        or not np.all(np.isfinite(residual))
        or np.any(residual < 0)
    ):
        raise ValueError("residual_by_time must be a finite nonnegative (12, 121) array")
    if not isinstance(stop_reason, str) or not stop_reason:
        raise ValueError("stop_reason must be a nonempty string")
    _ratio(payload.get("coverage_ratio"), "coverage_ratio")
    return payload


_PING_RECEIVED = re.compile(r",\s*(\d+)\s+(?:packets\s+)?received\b", re.IGNORECASE)
_HOP_LINE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def _ping_received(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    upper = text.upper()
    if "STATUS: ERROR" in upper or "STATUS: MISSING" in upper:
        return None
    matches = _PING_RECEIVED.findall(text)
    return max((int(value) for value in matches), default=None)


def _traceroute_path(path: Path) -> tuple[str, ...] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    upper = text.upper()
    if "STATUS: ERROR" in upper or "STATUS: MISSING" in upper:
        return None
    hops: list[str] = []
    for line in text.splitlines():
        match = _HOP_LINE.match(line)
        if not match:
            continue
        payload = match.group(2)
        addresses = _IPV4.findall(payload)
        if addresses:
            hops.append(addresses[0])
            continue
        tokens = [token.strip("()[]") for token in payload.split() if token != "*"]
        if tokens and tokens[0] and tokens[0].lower() not in {"ms", "request", "timed"}:
            hops.append(tokens[0])
    return tuple(hops) or None


def _set(gates: dict[str, dict], name: str, passed: bool, actual: Any, evidence: str) -> None:
    gates[name].update(passed=bool(passed), actual=actual, evidence=evidence)


def check_results(
    result_dir: str | Path,
    validation_report: str | Path,
    synthesis_result: str | Path,
) -> dict:
    """Evaluate all gates, write ``acceptance_summary.json``, and return it."""
    result_dir = Path(result_dir)
    validation_path = Path(validation_report)
    synthesis_path = Path(synthesis_result)
    gates = {name: _gate(requirement) for name, requirement in GATE_REQUIREMENTS.items()}
    errors: list[str] = []

    validation_epochs_exact = False
    validation_satellite_count: int | None = None
    try:
        report = _json_object(validation_path, "validation report")
        report_errors = report.get("errors")
        report_valid = report.get("valid") is True
        errors_empty = isinstance(report_errors, list) and not report_errors
        _set(
            gates,
            "validation_report",
            report_valid and errors_empty,
            {"valid": report.get("valid"), "error_count": len(report_errors) if isinstance(report_errors, list) else None},
            str(validation_path),
        )

        satellite_count = _report_epoch(report.get("satellite_count"), "satellite_count")
        validation_satellite_count = satellite_count
        _set(
            gates,
            "satellite_count",
            64 <= satellite_count <= 128,
            satellite_count,
            "validation_report.satellite_count",
        )
        expected_epochs = _report_epoch(report.get("expected_epochs"), "expected_epochs")
        epoch_metrics = report.get("epochs")
        if not isinstance(epoch_metrics, list):
            raise ValueError("validation_report.epochs must be a list")
        epoch_ids = [
            _report_epoch(metric.get("epoch"), "validation epoch")
            if isinstance(metric, dict)
            else (_ for _ in ()).throw(ValueError("validation epoch must be an object"))
            for metric in epoch_metrics
        ]
        validation_epochs_exact = (
            expected_epochs == 12
            and len(set(epoch_ids)) == len(epoch_ids)
            and tuple(sorted(epoch_ids)) == EXPECTED_EPOCHS
        )

        grids_ok = validation_epochs_exact
        passing_paths = 0
        metrics_by_epoch = dict(zip(epoch_ids, epoch_metrics))
        for epoch in EXPECTED_EPOCHS:
            metric = metrics_by_epoch.get(epoch)
            if not isinstance(metric, dict):
                grids_ok = False
                continue
            disjoint = _report_epoch(
                metric.get("edge_disjoint_paths"), f"epoch {epoch} edge_disjoint_paths"
            )
            passing_paths += disjoint >= 2
            counts = _active_counts(metric.get("active_grid_counts"), epoch)
            if any(counts.get(grid, 0) <= 0 for grid in ACTIVE_GRID_IDS):
                grids_ok = False
        _set(
            gates,
            "active_grids",
            grids_ok,
            {"required_grids": list(ACTIVE_GRID_IDS), "epochs_checked": len(epoch_metrics)},
            "validation_report.epochs[*].active_grid_counts",
        )
        recomputed_ratio = passing_paths / 12 if validation_epochs_exact else None
        reported_ratio = _ratio(report.get("path_epoch_ratio"), "path_epoch_ratio")
        ratio_consistent = recomputed_ratio is not None and math.isclose(
            reported_ratio, recomputed_ratio, rel_tol=0.0, abs_tol=1e-12
        )
        _set(
            gates,
            "path_diversity",
            ratio_consistent and recomputed_ratio >= 0.8,
            {"reported": reported_ratio, "recomputed": recomputed_ratio},
            "validation report and independent per-epoch recomputation",
        )
        topology_changes = _report_epoch(
            report.get("topology_change_count"), "topology_change_count"
        )
        gateway_handovers = _report_epoch(
            report.get("gateway_handover_count"), "gateway_handover_count"
        )
        _set(
            gates,
            "topology_changes",
            topology_changes >= 3,
            topology_changes,
            "validation_report.topology_change_count",
        )
        _set(
            gates,
            "gateway_handovers",
            gateway_handovers >= 2,
            gateway_handovers,
            "validation_report.gateway_handover_count",
        )
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))
        _set(
            gates,
            "validation_report",
            False,
            gates["validation_report"]["actual"],
            f"validation schema error: {exc}",
        )

    try:
        synthesis = _load_synthesis(synthesis_path)
        coverage = _ratio(synthesis["coverage_ratio"], "coverage_ratio")
        selected_count = len(synthesis["selected_candidate_ids"])
        _set(
            gates,
            "coverage_ratio",
            coverage >= 0.90,
            coverage,
            str(synthesis_path),
        )
        if validation_satellite_count is not None and selected_count != validation_satellite_count:
            _set(
                gates,
                "satellite_count",
                False,
                {
                    "validation_report": validation_satellite_count,
                    "synthesis_result": selected_count,
                },
                "validation and synthesis artifacts must describe the same constellation",
            )
    except (KeyError, ValueError, TypeError) as exc:
        errors.append(str(exc))

    resource_epochs_exact = False
    try:
        resource_rows = _read_runtime_csv(
            result_dir / "resource-usage.csv",
            {"epoch", "system_memory_used_bytes", "swap_used_bytes"},
        )
        _, resource_epochs_exact = _epochs(resource_rows, "resource-usage.csv")
        memory_values = [
            float(_csv_number(row.get("system_memory_used_bytes"), "system_memory_used_bytes"))
            for row in resource_rows
        ]
        swap_values = [
            float(_csv_number(row.get("swap_used_bytes"), "swap_used_bytes"))
            for row in resource_rows
        ]
        peak_memory = max(memory_values)
        peak_swap = max(swap_values)
        _set(
            gates,
            "peak_memory",
            resource_epochs_exact and peak_memory < 24 * GIB,
            {"bytes": int(peak_memory), "gib": peak_memory / GIB},
            "maximum system_memory_used_bytes across resource-usage.csv",
        )
        _set(
            gates,
            "swap_used",
            resource_epochs_exact and peak_swap == 0,
            int(peak_swap),
            "maximum swap_used_bytes across resource-usage.csv",
        )
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))

    topology_epochs_exact = False
    try:
        topology_rows = _read_runtime_csv(
            result_dir / "topology-update-times.csv",
            {"epoch", "duration_seconds", "status"},
        )
        _, topology_epochs_exact = _epochs(topology_rows, "topology-update-times.csv")
        statuses_ok = all(row.get("status") == "returned" for row in topology_rows)
        durations = [
            float(_csv_number(row.get("duration_seconds"), "duration_seconds"))
            for row in topology_rows
        ]
        p95 = float(np.percentile(durations, 95, method="linear"))
        _set(
            gates,
            "topology_update_p95",
            topology_epochs_exact and statuses_ok and p95 < 15,
            p95,
            "NumPy linear percentile over topology-update-times.csv",
        )
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))

    runtime_ok = validation_epochs_exact and resource_epochs_exact and topology_epochs_exact
    _set(
        gates,
        "runtime_epochs",
        runtime_ok,
        {
            "validation": validation_epochs_exact,
            "resource": resource_epochs_exact,
            "topology_updates": topology_epochs_exact,
        },
        "independent exact epoch-ID checks",
    )

    ping_evidence = []
    for path in sorted(result_dir.glob("ping-epoch-*.txt")):
        received = _ping_received(path)
        ping_evidence.append({"artifact": path.name, "received": received})
    _set(
        gates,
        "ping_reply",
        any(item["received"] is not None and item["received"] > 0 for item in ping_evidence),
        ping_evidence,
        "parsed received-reply counts; STATUS ERROR/MISSING is rejected",
    )

    try:
        events_payload = _json_object(
            result_dir / "failure-recovery-events.json", "failure/recovery events"
        )
        if _report_epoch(events_payload.get("failure_epoch"), "failure_epoch") != 6:
            raise ValueError("failure_epoch must be 6")
        if _report_epoch(events_payload.get("recovery_observation_epoch"), "recovery_observation_epoch") != 7:
            raise ValueError("recovery_observation_epoch must be 7")
        events = events_payload.get("events")
        if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
            raise ValueError("failure/recovery events must be a list of objects")
        failures = [
            event
            for event in events
            if event.get("epoch") == 6 and event.get("event") == "failure_injection"
        ]
        recoveries = [
            event
            for event in events
            if event.get("epoch") == 7 and event.get("event") == "recovery_observation"
        ]
        if len(failures) != 1 or failures[0].get("status") != "returned":
            raise ValueError("exactly one returned epoch-6 failure_injection is required")
        if len(recoveries) != 1:
            raise ValueError("exactly one epoch-7 recovery_observation is required")
        statuses = recoveries[0].get("measurement_statuses")
        captured = isinstance(statuses, dict) and all(
            statuses.get(kind) == "captured" for kind in ("ping", "traceroute")
        )
        epoch7_received = _ping_received(result_dir / "ping-epoch-7.txt")
        before_path = _traceroute_path(result_dir / "traceroute-epoch-5.txt")
        recovery_path = _traceroute_path(result_dir / "traceroute-epoch-7.txt")
        recovery_ok = (
            captured
            and epoch7_received is not None
            and epoch7_received > 0
            and before_path is not None
            and recovery_path is not None
            and before_path != recovery_path
        )
        _set(
            gates,
            "failure_recovery",
            recovery_ok,
            {
                "failure_status": failures[0].get("status"),
                "measurement_statuses": statuses,
                "epoch7_received": epoch7_received,
                "pre_failure_path": list(before_path) if before_path else None,
                "recovery_path": list(recovery_path) if recovery_path else None,
            },
            "events plus independently parsed epoch-5/7 network artifacts",
        )
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))

    for name, gate in gates.items():
        if not gate["passed"]:
            failure = f"{name}: acceptance gate failed"
            if failure not in errors:
                errors.append(failure)
    summary = {
        "valid": not errors and all(gate["passed"] for gate in gates.values()),
        "gates": gates,
        "errors": errors,
    }
    try:
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "acceptance_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        summary["valid"] = False
        summary["errors"].append(f"cannot write acceptance summary: {exc}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--synthesis-result", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = check_results(
        args.result_dir, args.validation_report, args.synthesis_result
    )
    for name, gate in summary["gates"].items():
        print(f"{name}: {'PASS' if gate['passed'] else 'FAIL'}")
    print(f"OVERALL: {'PASS' if summary['valid'] else 'FAIL'}")
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
