"""Noninteractive Canada parity-scale emulation scenario.

Heavy controller operations stay behind ``controller_factory`` so the input,
schedule, cleanup, and artifact contracts can be verified without root or
network access.  The default factory lazily imports and constructs the real
``RemoteController``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
CONFIG_DIR = Path(__file__).resolve().parent / "config"

GS_NAMES = ("GS1", "GS2", "GS3", "GS4", "GS5", "GS6")
GS_LAT_LONG = [
    [60.7212, -135.0568],
    [62.4540, -114.3718],
    [63.7467, -68.5170],
    [49.2827, -123.1207],
    [51.0447, -114.0719],
    [43.6532, -79.3832],
]
GS_CELL = [[2, 2], [2, 3], [2, 4], [3, 2], [3, 3], [3, 4]]

ROUTE_KEY = "[3, 2]->[3, 4]"
SOUTH_POLICY = {ROUTE_KEY: [[3, 3]]}
NORTH_POLICY = {ROUTE_KEY: [[2, 2], [2, 3], [2, 4]]}
ACTIVE_GRID_IDS = (12, 13, 14, 23, 24, 25)
OBSERVATION_EPOCHS = (0, 5, 6, 7, 11)
FAILURE_EPOCH = 6
RECOVERY_OBSERVATION_EPOCH = 7
SOURCE_GS = "GS4"
DESTINATION_GS = "GS6"

DEFAULT_CONFIGURATION = CONFIG_DIR / "tinyleo_canada_parity.json"
DEFAULT_SOUTH_POLICY = CONFIG_DIR / "geographic_routing_policy_canada_south.json"
DEFAULT_NORTH_POLICY = CONFIG_DIR / "geographic_routing_policy_canada_north.json"
DEFAULT_BACKBONE_DEMAND = (
    REPOSITORY_ROOT
    / "network_synthesizer"
    / "test"
    / "data"
    / "canada_parity_backbone_demand.npy"
)
DEFAULT_VALIDATION_REPORT = (
    PROJECT_ROOT / "result" / "canada_parity_validation" / "validation_report.json"
)
DEFAULT_RESULT_DIR = PROJECT_ROOT / "result" / "canada_parity"

IPERF_FIELDS = (
    "epoch",
    "phase",
    "source",
    "destination",
    "status",
    "source_path",
    "artifact_path",
    "size_bytes",
)
RESOURCE_FIELDS = (
    "epoch",
    "process_rss_bytes",
    "system_memory_total_bytes",
    "system_memory_available_bytes",
    "system_memory_used_bytes",
    "system_memory_percent",
    "swap_total_bytes",
    "swap_used_bytes",
    "swap_free_bytes",
    "swap_percent",
    "scope",
)
TOPOLOGY_FIELDS = ("epoch", "duration_seconds", "status")
RESOURCE_SCOPE = (
    "controller process RSS plus host memory/swap counters; not n2 VM acceptance"
)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def validate_path_diversity(
    report: Any,
    minimum_ratio: float = 0.8,
    required_epochs: int | None = None,
) -> dict:
    """Validate reported and independently observed edge-disjoint path coverage."""
    if not 0 <= minimum_ratio <= 1:
        raise ValueError("minimum_ratio must be between 0 and 1")
    if _field(report, "valid", True) is False:
        raise ValueError("offline topology validation report is not valid")

    reported_ratio = _field(report, "path_epoch_ratio")
    if (
        isinstance(reported_ratio, bool)
        or not isinstance(reported_ratio, (int, float))
        or not math.isfinite(float(reported_ratio))
    ):
        raise ValueError("report.path_epoch_ratio must be a finite number")
    reported_ratio = float(reported_ratio)
    if reported_ratio < minimum_ratio:
        raise ValueError(
            f"report.path_epoch_ratio {reported_ratio:.3f} is below {minimum_ratio:.3f}"
        )

    epochs = list(_field(report, "epochs", ()))
    expected_epochs = _field(report, "expected_epochs", len(epochs))
    if (
        isinstance(expected_epochs, bool)
        or not isinstance(expected_epochs, int)
        or expected_epochs <= 0
    ):
        raise ValueError("report.expected_epochs must be a positive integer")
    if required_epochs is not None:
        if (
            isinstance(required_epochs, bool)
            or not isinstance(required_epochs, int)
            or required_epochs <= 0
        ):
            raise ValueError("required_epochs must be a positive integer")
        if expected_epochs != required_epochs:
            raise ValueError(
                "report.expected_epochs must equal configured num_epochs "
                f"({required_epochs})"
            )
    else:
        required_epochs = expected_epochs
    if len(epochs) != required_epochs:
        raise ValueError(
            f"report must contain exactly {required_epochs} epoch metrics"
        )

    passing_epochs = 0
    epoch_ids = []
    for epoch in epochs:
        epoch_id = _field(epoch, "epoch")
        if isinstance(epoch_id, bool) or not isinstance(epoch_id, int):
            raise ValueError("each epoch metric must have an integer epoch ID")
        epoch_ids.append(epoch_id)
        path_count = _field(epoch, "edge_disjoint_paths")
        if isinstance(path_count, bool) or not isinstance(path_count, int):
            raise ValueError("each epoch must report integer edge_disjoint_paths")
        if path_count >= 2:
            passing_epochs += 1
    expected_ids = list(range(required_epochs))
    if sorted(epoch_ids) != expected_ids:
        raise ValueError(
            "epoch metrics must have unique IDs exactly "
            f"0..{required_epochs - 1}"
        )
    observed_ratio = passing_epochs / required_epochs
    if observed_ratio < minimum_ratio:
        raise ValueError(
            "edge-disjoint Vancouver-Toronto paths passed in "
            f"{observed_ratio:.1%} of epochs; required {minimum_ratio:.1%}"
        )
    if not math.isclose(reported_ratio, observed_ratio, rel_tol=0, abs_tol=1e-12):
        raise ValueError(
            "report.path_epoch_ratio must equal the ratio computed from the exact "
            "per-epoch edge-disjoint metrics"
        )
    return {
        "reported_ratio": reported_ratio,
        "observed_ratio": observed_ratio,
        "passing_epochs": passing_epochs,
        "expected_epochs": required_epochs,
    }


def _route_cells(policy: dict, label: str) -> list[list[int]]:
    if not isinstance(policy, dict) or set(policy) != {ROUTE_KEY}:
        raise ValueError(f"{label} policy must contain only endpoint {ROUTE_KEY}")
    waypoints = policy[ROUTE_KEY]
    if not isinstance(waypoints, list):
        raise ValueError(f"{label} policy waypoints must be a list")
    route = [[3, 2], *waypoints, [3, 4]]
    for cell in route:
        if (
            not isinstance(cell, list)
            or len(cell) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in cell)
        ):
            raise ValueError(f"{label} policy cells must be integer [row, column] pairs")
    for left, right in zip(route, route[1:]):
        if abs(left[0] - right[0]) + abs(left[1] - right[1]) != 1:
            raise ValueError(f"{label} policy route steps must be adjacent")
    return route


def _grid_id_for_cell(block_positions: dict, cell: list[int]) -> int:
    matches = [
        int(grid_id)
        for grid_id, metadata in block_positions.items()
        if metadata.get("row_col") == cell
    ]
    if len(matches) != 1:
        raise ValueError(f"grid mapping must map cell {cell} exactly once")
    return matches[0]


def validate_scenario_inputs(
    gs_lat_long: Any,
    gs_cell: Any,
    south_policy: Any,
    north_policy: Any,
    block_positions: Any,
    backbone_demand: Any,
    traffic_matrix: Any,
    report: Any,
    minimum_ratio: float = 0.8,
    configured_num_epochs: int | None = None,
) -> dict:
    """Pure validation gate for the fixed Canada routing scenario inputs."""
    if gs_lat_long != GS_LAT_LONG:
        raise ValueError("ground-station coordinates or order are not the fixed scenario")
    if gs_cell != GS_CELL:
        raise ValueError("ground-station cells or order are not the fixed scenario")

    south_route = _route_cells(south_policy, "south")
    north_route = _route_cells(north_policy, "north")
    if south_policy != SOUTH_POLICY:
        raise ValueError("south policy does not match the fixed scenario")
    if north_policy != NORTH_POLICY:
        raise ValueError("north policy does not match the fixed scenario")
    if not isinstance(block_positions, dict):
        raise ValueError("grid mapping must be a JSON object")

    cell_to_grid = {
        tuple(cell): _grid_id_for_cell(block_positions, cell)
        for cell in GS_CELL
    }
    active_grid_ids = tuple(cell_to_grid[tuple(cell)] for cell in GS_CELL)
    if active_grid_ids != ACTIVE_GRID_IDS:
        raise ValueError(
            f"grid mapping resolved {active_grid_ids}, expected {ACTIVE_GRID_IDS}"
        )

    if (
        isinstance(configured_num_epochs, bool)
        or not isinstance(configured_num_epochs, int)
        or configured_num_epochs <= 0
    ):
        raise ValueError("configured num_epochs must be a positive integer")

    demand = np.asarray(backbone_demand)
    if demand.ndim != 2 or demand.shape[0] == 0 or demand.shape[1] <= max(ACTIVE_GRID_IDS):
        raise ValueError("backbone demand must be a nonempty epoch-by-grid matrix")
    if demand.shape[0] != configured_num_epochs:
        raise ValueError(
            f"demand rows must equal configured num_epochs ({configured_num_epochs})"
        )
    if not np.isfinite(demand[:, ACTIVE_GRID_IDS]).all() or not np.all(
        demand[:, ACTIVE_GRID_IDS] > 0
    ):
        raise ValueError("backbone demand must be nonzero for every active grid and epoch")

    routes = (south_route, north_route)
    traffic_edges: list[tuple[int, int]] = []
    for route in routes:
        route_grid_ids = [cell_to_grid[tuple(cell)] for cell in route]
        for left, right in zip(route_grid_ids, route_grid_ids[1:]):
            edge = tuple(sorted((left, right)))
            if edge not in traffic_edges:
                traffic_edges.append(edge)

    traffic = np.asarray(traffic_matrix)
    if (
        traffic.ndim != 2
        or traffic.shape[0] != traffic.shape[1]
        or traffic.shape[0] <= max(ACTIVE_GRID_IDS)
    ):
        raise ValueError("traffic matrix must be a square global-grid matrix")
    for left, right in traffic_edges:
        values = (traffic[left, right], traffic[right, left])
        if not all(np.isfinite(value) and value > 0 for value in values):
            raise ValueError(
                f"traffic support must be nonzero in both directions for edge {left}-{right}"
            )

    diversity = validate_path_diversity(
        report,
        minimum_ratio=minimum_ratio,
        required_epochs=configured_num_epochs,
    )
    return {
        "active_grid_ids": active_grid_ids,
        "traffic_edges": tuple(traffic_edges),
        "path_diversity": diversity,
    }


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _configured_path(config_path: Path, config: dict, key: str) -> Path:
    raw_path = config.get(key)
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"configuration is missing {key}")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _configured_num_epochs(config: dict) -> int:
    value = config.get("num_epochs", config.get("Duration (s)"))
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("configuration num_epochs must be a positive integer")
    return value


def _default_controller_factory(configuration_file_path, coordinates, cells):
    from southbound.sn_controller import RemoteController

    runner_argv = sys.argv
    try:
        sys.argv = runner_argv[:1]
        return RemoteController(str(configuration_file_path), coordinates, cells)
    finally:
        sys.argv = runner_argv


def _default_resource_sample(_epoch: int) -> dict:
    import psutil

    process = psutil.Process()
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "process_rss_bytes": process.memory_info().rss,
        "system_memory_total_bytes": memory.total,
        "system_memory_available_bytes": memory.available,
        "system_memory_used_bytes": memory.used,
        "system_memory_percent": memory.percent,
        "swap_total_bytes": swap.total,
        "swap_used_bytes": swap.used,
        "swap_free_bytes": swap.free,
        "swap_percent": swap.percent,
    }


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_events(path: Path, events: list[dict]) -> None:
    payload = {
        "failure_epoch": FAILURE_EPOCH,
        "recovery_observation_epoch": RECOVERY_OBSERVATION_EPOCH,
        "events": events,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _phase(epoch: int) -> str:
    return {
        0: "normal",
        5: "pre_failure",
        6: "failure_injection",
        7: "recovery_observation",
        11: "final",
    }[epoch]


def _validate_srv6_acknowledgement(value: Any, *, expected_total: int) -> dict:
    if not isinstance(value, dict):
        raise ValueError("SRv6 deployment acknowledgement must be an object")
    acknowledgements = value.get("remote_acknowledgements")
    if not isinstance(acknowledgements, list) or not acknowledgements:
        raise ValueError("SRv6 deployment acknowledgement must list remote results")
    remote_ids = set()
    agent_names = set()
    started_total = 0
    for acknowledgement in acknowledgements:
        if not isinstance(acknowledgement, dict):
            raise ValueError("each SRv6 remote acknowledgement must be an object")
        remote_id = acknowledgement.get("remote_id")
        expected = acknowledgement.get("expected_count")
        started = acknowledgement.get("started_count")
        agents = acknowledgement.get("agents")
        if (
            isinstance(remote_id, bool)
            or not isinstance(remote_id, int)
            or remote_id < 0
            or remote_id in remote_ids
            or isinstance(expected, bool)
            or not isinstance(expected, int)
            or expected <= 0
            or isinstance(started, bool)
            or not isinstance(started, int)
            or started != expected
        ):
            raise ValueError("SRv6 deployment did not start every expected agent")
        if not isinstance(agents, list) or len(agents) != expected:
            raise ValueError("SRv6 acknowledgement must identify every agent")
        remote_ids.add(remote_id)
        started_total += started
        namespace_pids = set()
        for agent in agents:
            if not isinstance(agent, dict):
                raise ValueError("SRv6 agent identity must be an object")
            name = agent.get("name")
            namespace_pid = agent.get("namespace_pid")
            if (
                not isinstance(name, str)
                or not name
                or name in agent_names
                or isinstance(namespace_pid, bool)
                or not isinstance(namespace_pid, int)
                or namespace_pid <= 0
                or namespace_pid in namespace_pids
            ):
                raise ValueError("SRv6 agent identity is invalid or duplicated")
            agent_names.add(name)
            namespace_pids.add(namespace_pid)
    if started_total != expected_total:
        raise ValueError(
            f"SRv6 started {started_total} agents; expected exactly {expected_total}"
        )
    return value


def _validate_failure_acknowledgement(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("failure acknowledgement must be an object")
    failed_link = value.get("failed_link")
    removed = value.get("removed_satellite")
    replacement = value.get("replacement_satellite")
    updated = value.get("updated_satellites")
    remote_id = value.get("remote_id")
    if (
        not isinstance(failed_link, list)
        or len(failed_link) != 2
        or any(not isinstance(node, str) or not node for node in failed_link)
        or failed_link[0] == failed_link[1]
    ):
        raise ValueError("failure acknowledgement must identify one physical link")
    if removed not in failed_link:
        raise ValueError("failure acknowledgement removed satellite must be on failed link")
    if (
        not isinstance(replacement, str)
        or not replacement
        or replacement in failed_link
        or replacement == removed
    ):
        raise ValueError("failure acknowledgement replacement identity is invalid")
    if (
        not isinstance(updated, list)
        or removed not in updated
        or replacement not in updated
    ):
        raise ValueError("failure acknowledgement must include removed and replacement nodes")
    if isinstance(remote_id, bool) or not isinstance(remote_id, int) or remote_id < 0:
        raise ValueError("failure acknowledgement remote_id must be nonnegative")
    return value


def _measurement_paths(controller: Any, result_dir: Path, kind: str, epoch: int):
    name = f"{kind}-epoch-{epoch}.txt"
    source = Path(controller.local_dir) / "result" / name
    return source, result_dir / name


def _prepare_measurement(controller: Any, result_dir: Path, kind: str, epoch: int):
    source, target = _measurement_paths(controller, result_dir, kind, epoch)
    if source.exists():
        source.unlink()
    if target != source and target.exists():
        target.unlink()
    return source, target


def _measurement_error(target: Path, source: Path, exc: Exception) -> None:
    target.write_text(
        "STATUS: ERROR\n"
        f"source: {source}\n"
        f"error: {type(exc).__name__}: {exc}\n",
        encoding="utf-8",
    )


def _write_missing_measurement(target: Path, source: Path, reason: str) -> None:
    target.write_text(
        "STATUS: MISSING\n"
        f"source: {source}\n"
        f"{reason}\n",
        encoding="utf-8",
    )


def _finalize_measurement(source: Path, target: Path) -> tuple[str, int]:
    if source.is_file():
        if source != target:
            shutil.copyfile(source, target)
        return "captured", source.stat().st_size
    _write_missing_measurement(
        target,
        source,
        "No underlying controller command output was produced.",
    )
    return "missing", 0


def _measurement_metadata(status: str, source: Path, target: Path, size: int) -> dict:
    return {
        "status": status,
        "source_path": str(source),
        "artifact_path": str(target),
        "size_bytes": size,
    }


def _initialize_scheduled_measurements(
    controller: Any, result_dir: Path, scheduled_epochs: list[int]
) -> list[dict]:
    iperf_rows = []
    for epoch in scheduled_epochs:
        paths = {}
        for kind in ("ping", "traceroute", "iperf"):
            source, target = _measurement_paths(controller, result_dir, kind, epoch)
            if source.exists():
                source.unlink()
            _write_missing_measurement(
                target,
                source,
                "Measurement was scheduled but not attempted before the run ended.",
            )
            paths[kind] = (source, target)
        source, target = paths["iperf"]
        iperf_rows.append(
            {
                "epoch": epoch,
                "phase": _phase(epoch),
                "source": SOURCE_GS,
                "destination": DESTINATION_GS,
                **_measurement_metadata("missing", source, target, 0),
            }
        )
    return iperf_rows


def _collect_measurements(
    controller: Any,
    epoch: int,
    result_dir: Path,
    sleep: Callable[[float], None],
    measurement_wait_s: float,
) -> tuple[dict[str, dict], Exception | None]:
    prepared = {
        kind: _prepare_measurement(controller, result_dir, kind, epoch)
        for kind in ("ping", "traceroute", "iperf")
    }
    methods = {
        "ping": controller.set_ping,
        "traceroute": controller.set_traceroute,
        "iperf": controller.set_iperf,
    }
    results = {}
    handles = {}
    command_error = None
    for kind, method in methods.items():
        source, target = prepared[kind]
        try:
            handles[kind] = method(
                SOURCE_GS, DESTINATION_GS, f"epoch-{epoch}"
            )
        except Exception as exc:
            _measurement_error(target, source, exc)
            results[kind] = _measurement_metadata(
                "error", source, target, target.stat().st_size
            )
            command_error = exc
            break
    if command_error is None and measurement_wait_s:
        sleep(measurement_wait_s)

    for kind, handle in handles.items():
        result = getattr(handle, "result", None)
        if not callable(result):
            continue
        source, target = prepared[kind]
        try:
            result()
        except Exception as exc:
            _measurement_error(target, source, exc)
            results[kind] = _measurement_metadata(
                "error", source, target, target.stat().st_size
            )
            if command_error is None:
                command_error = exc

    for kind, (source, target) in prepared.items():
        if kind in results:
            continue
        status, size = _finalize_measurement(source, target)
        results[kind] = _measurement_metadata(status, source, target, size)
    return results, command_error


def run_canada_parity(
    configuration_file_path: str | Path = DEFAULT_CONFIGURATION,
    south_policy_path: str | Path = DEFAULT_SOUTH_POLICY,
    north_policy_path: str | Path = DEFAULT_NORTH_POLICY,
    backbone_demand_path: str | Path = DEFAULT_BACKBONE_DEMAND,
    validation_report: Any = DEFAULT_VALIDATION_REPORT,
    result_dir: str | Path = DEFAULT_RESULT_DIR,
    minimum_path_ratio: float = 0.8,
    controller_factory: Callable = _default_controller_factory,
    failure_injector: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    resource_sampler: Callable[[int], dict] = _default_resource_sample,
    measurement_wait_s: float = 15.0,
    routing_mode: str = "shortest",
) -> Path:
    """Run the fixed Canada scenario and return its result directory."""
    if measurement_wait_s < 0:
        raise ValueError("measurement_wait_s must be nonnegative")
    if routing_mode not in {"shortest", "geographic"}:
        raise ValueError("routing_mode must be shortest or geographic")

    configuration_file_path = Path(configuration_file_path).resolve()
    south_policy_path = Path(south_policy_path).resolve()
    north_policy_path = Path(north_policy_path).resolve()
    backbone_demand_path = Path(backbone_demand_path).resolve()
    result_dir = Path(result_dir).resolve()
    report = (
        _load_json(Path(validation_report).resolve())
        if isinstance(validation_report, (str, Path))
        else validation_report
    )
    config = _load_json(configuration_file_path)
    configured_num_epochs = _configured_num_epochs(config)
    south_policy = _load_json(south_policy_path)
    north_policy = _load_json(north_policy_path)
    block_positions = _load_json(
        _configured_path(configuration_file_path, config, "block_positions_file")
    )
    backbone_demand = np.load(backbone_demand_path, allow_pickle=False)
    traffic_matrix = np.load(
        _configured_path(configuration_file_path, config, "traffic_matrix_file"),
        allow_pickle=False,
    )
    validate_scenario_inputs(
        GS_LAT_LONG,
        GS_CELL,
        south_policy,
        north_policy,
        block_positions,
        backbone_demand,
        traffic_matrix,
        report,
        minimum_ratio=minimum_path_ratio,
        configured_num_epochs=configured_num_epochs,
    )
    satellite_count = report.get("satellite_count")
    if (
        isinstance(satellite_count, bool)
        or not isinstance(satellite_count, int)
        or satellite_count <= 0
    ):
        raise ValueError("validation report satellite_count must be positive")
    expected_agent_total = satellite_count + len(GS_LAT_LONG)
    applied_policy = south_policy if routing_mode == "shortest" else north_policy

    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "scenario-metadata.json").write_text(
        json.dumps(
            {
                "routing_mode": routing_mode,
                "applied_policy": applied_policy,
                "source": SOURCE_GS,
                "destination": DESTINATION_GS,
                "num_epochs": configured_num_epochs,
                "failure_epoch": FAILURE_EPOCH,
                "recovery_observation_epoch": RECOVERY_OBSERVATION_EPOCH,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for epoch in OBSERVATION_EPOCHS:
        for kind in ("ping", "traceroute", "iperf"):
            path = result_dir / f"{kind}-epoch-{epoch}.txt"
            if path.exists():
                path.unlink()

    iperf_rows: list[dict] = []
    resource_rows: list[dict] = []
    topology_rows: list[dict] = []
    events: list[dict] = []
    controller = None
    try:
        controller = controller_factory(
            configuration_file_path, GS_LAT_LONG, GS_CELL
        )
        if controller.num_epochs != configured_num_epochs:
            raise ValueError(
                "controller num_epochs must equal configured num_epochs "
                f"({configured_num_epochs})"
            )
        scheduled_epochs = [
            epoch for epoch in OBSERVATION_EPOCHS if epoch < configured_num_epochs
        ]
        iperf_rows = _initialize_scheduled_measurements(
            controller, result_dir, scheduled_epochs
        )
        iperf_rows_by_epoch = {row["epoch"]: row for row in iperf_rows}
        controller.init_remote_machine()
        controller.geopraphic_routing_policy = applied_policy
        controller.create_nodes()
        controller.create_links()
        if controller.enable_failure_recovery:
            controller.start_link_faliure_server()

        for epoch in range(controller.num_epochs):
            epoch_start = monotonic()
            try:
                controller.update_tinyleo_topology(epoch)
            except Exception:
                topology_rows.append(
                    {
                        "epoch": epoch,
                        "duration_seconds": monotonic() - epoch_start,
                        "status": "raised",
                    }
                )
                raise
            topology_rows.append(
                {
                    "epoch": epoch,
                    "duration_seconds": monotonic() - epoch_start,
                    "status": "returned",
                }
            )
            if epoch == 0:
                deployment_event = {
                    "epoch": epoch,
                    "event": "srv6_deployment",
                    "status": "returned",
                    "error": None,
                }
                try:
                    deployment_ack = _validate_srv6_acknowledgement(
                        controller.deploy_tinyleo_srv6_agent(),
                        expected_total=expected_agent_total,
                    )
                    deployment_event["acknowledgement"] = deployment_ack
                except Exception as exc:
                    deployment_event["status"] = "raised"
                    deployment_event["error"] = f"{type(exc).__name__}: {exc}"
                    events.append(deployment_event)
                    raise
                events.append(deployment_event)

            if epoch == FAILURE_EPOCH:
                failure_event = {
                    "epoch": epoch,
                    "event": "failure_injection",
                    "status": "returned",
                    "error": None,
                }
                failure_started = monotonic()
                try:
                    if failure_injector is None:
                        acknowledgement = controller.tinyleo_fault_test()
                    else:
                        acknowledgement = failure_injector(controller, epoch)
                    failure_event["acknowledgement"] = (
                        _validate_failure_acknowledgement(acknowledgement)
                    )
                except Exception as exc:
                    failure_event["status"] = "raised"
                    failure_event["error"] = f"{type(exc).__name__}: {exc}"
                    failure_event["interruption_seconds"] = (
                        monotonic() - failure_started
                    )
                    events.append(failure_event)
                    raise
                failure_event["interruption_seconds"] = (
                    monotonic() - failure_started
                )
                events.append(failure_event)

            if epoch in OBSERVATION_EPOCHS:
                measurements, command_error = _collect_measurements(
                    controller,
                    epoch,
                    result_dir,
                    sleep,
                    measurement_wait_s,
                )
                iperf_rows_by_epoch[epoch].update(measurements["iperf"])
                if command_error is not None:
                    raise command_error
                if epoch == RECOVERY_OBSERVATION_EPOCH:
                    events.append(
                        {
                            "epoch": epoch,
                            "event": "recovery_observation",
                            "status": "measurement_attempted",
                            "measurement_statuses": {
                                kind: metadata["status"]
                                for kind, metadata in measurements.items()
                            },
                            "note": "Observation status does not assert network recovery.",
                        }
                    )

            sample = resource_sampler(epoch)
            resource_rows.append(
                {"epoch": epoch, **sample, "scope": RESOURCE_SCOPE}
            )
            if epoch != controller.num_epochs - 1:
                elapsed = monotonic() - epoch_start
                sleep(max(0.0, controller.topology_update_interval_s - elapsed))
    finally:
        try:
            if controller is not None:
                controller.clean()
        finally:
            _write_csv(
                result_dir / "iperf-normal-and-recovery.csv",
                IPERF_FIELDS,
                iperf_rows,
            )
            _write_events(result_dir / "failure-recovery-events.json", events)
            _write_csv(result_dir / "resource-usage.csv", RESOURCE_FIELDS, resource_rows)
            _write_csv(
                result_dir / "topology-update-times.csv",
                TOPOLOGY_FIELDS,
                topology_rows,
            )
    return result_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the noninteractive six-station Canada parity scenario"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIGURATION)
    parser.add_argument("--south-policy", type=Path, default=DEFAULT_SOUTH_POLICY)
    parser.add_argument("--north-policy", type=Path, default=DEFAULT_NORTH_POLICY)
    parser.add_argument("--backbone-demand", type=Path, default=DEFAULT_BACKBONE_DEMAND)
    parser.add_argument(
        "--validation-report", type=Path, default=DEFAULT_VALIDATION_REPORT
    )
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    parser.add_argument("--minimum-path-ratio", type=float, default=0.8)
    parser.add_argument("--measurement-wait-s", type=float, default=15.0)
    parser.add_argument(
        "--routing-mode",
        choices=("shortest", "geographic"),
        default="shortest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_canada_parity(
        configuration_file_path=args.config,
        south_policy_path=args.south_policy,
        north_policy_path=args.north_policy,
        backbone_demand_path=args.backbone_demand,
        validation_report=args.validation_report,
        result_dir=args.result_dir,
        minimum_path_ratio=args.minimum_path_ratio,
        measurement_wait_s=args.measurement_wait_s,
        routing_mode=args.routing_mode,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
