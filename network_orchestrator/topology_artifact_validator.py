"""Offline validation for TinyLEO topology artifacts.

This module deliberately avoids container, namespace, and SRv6 operations.  It
validates the files produced by ``sn_orchestrator_mpc`` before an emulation is
allowed to consume them.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class ValidationConfig:
    satellite_file: Path
    grid_satellites_file: Path
    traffic_matrix_file: Path
    block_positions_file: Path
    topology_dir: Path
    expected_epochs: int
    active_grids: tuple[int, ...]
    min_satellites: int = 64
    max_satellites: int = 128
    min_edge_disjoint_paths: int = 2
    min_path_epoch_ratio: float = 0.8
    source_grid: int = 23
    destination_grid: int = 25
    min_largest_component_ratio: float = 0.9
    max_virtual_copies: int = 3
    min_topology_changes: int = 0
    min_gateway_handovers: int = 0


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    epoch: int | None = None


@dataclass
class EpochMetrics:
    epoch: int
    satellite_count: int
    link_count: int
    inter_link_count: int
    intra_link_count: int
    component_count: int
    participating_satellite_count: int
    largest_component_ratio: float
    constellation_largest_component_ratio: float
    edge_disjoint_paths: int
    active_grid_counts: dict[int, int]
    average_degree: float
    min_degree: int
    max_degree: int
    added_links: int = 0
    removed_links: int = 0
    gateway_handovers: int = 0


@dataclass
class ValidationReport:
    satellite_count: int = 0
    expected_epochs: int = 0
    epochs: list[EpochMetrics] = field(default_factory=list)
    errors: list[ValidationError] = field(default_factory=list)
    topology_change_count: int = 0
    gateway_handover_count: int = 0
    path_epoch_ratio: float = 0.0

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["valid"] = self.valid
        return payload


def _error(
    errors: list[ValidationError], code: str, message: str, epoch: int | None = None
) -> None:
    errors.append(ValidationError(code=code, message=message, epoch=epoch))


def _require_file(path: Path, errors: list[ValidationError], epoch=None) -> bool:
    if path.is_file():
        return True
    _error(errors, "missing_file", f"Required artifact is missing: {path}", epoch)
    return False


def _as_int(value) -> int:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"Satellite/grid identifier must be an integer, got {value!r}")
    return int(value)


def _normalize_endpoint(
    raw_id,
    satellite_count: int,
    max_virtual_copies: int,
    errors: list[ValidationError],
    epoch: int,
) -> int | None:
    try:
        node_id = _as_int(raw_id)
    except TypeError as exc:
        _error(errors, "invalid_satellite_id", str(exc), epoch)
        return None
    if node_id < 0 or node_id >= satellite_count * max_virtual_copies:
        _error(
            errors,
            "invalid_satellite_id",
            f"Epoch {epoch}: satellite ID {node_id} is outside 0.."
            f"{satellite_count * max_virtual_copies - 1}",
            epoch,
        )
        return None
    return node_id % satellite_count


def _load_inter_topology(path: Path) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    payload = np.load(path, allow_pickle=True)
    records = payload.tolist()
    result = []
    for record in records:
        nodes, grids = record
        result.append(
            (
                (_as_int(nodes[0]), _as_int(nodes[1])),
                (_as_int(grids[0]), _as_int(grids[1])),
            )
        )
    return result


def _load_intra_topology(path: Path) -> dict[int, list[tuple[int, int]]]:
    payload = np.load(path, allow_pickle=True)
    value = payload.item() if payload.shape == () else payload.tolist()
    if not isinstance(value, dict):
        raise TypeError(f"Intra topology must be a dict, got {type(value).__name__}")
    return {
        _as_int(grid_id): [(_as_int(edge[0]), _as_int(edge[1])) for edge in edges]
        for grid_id, edges in value.items()
    }


def _physical_edges(
    raw_edges: Iterable[tuple[int, int]],
    satellite_count: int,
    max_virtual_copies: int,
    errors: list[ValidationError],
    epoch: int,
) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for raw_left, raw_right in raw_edges:
        left = _normalize_endpoint(
            raw_left, satellite_count, max_virtual_copies, errors, epoch
        )
        right = _normalize_endpoint(
            raw_right, satellite_count, max_virtual_copies, errors, epoch
        )
        if left is None or right is None:
            continue
        if left == right:
            _error(
                errors,
                "self_loop",
                f"Epoch {epoch}: link {raw_left}-{raw_right} maps to self-loop {left}",
                epoch,
            )
            continue
        edge = tuple(sorted((left, right)))
        if edge in result:
            _error(
                errors,
                "duplicate_link",
                f"Epoch {epoch}: duplicate physical link {edge}",
                epoch,
            )
        result.add(edge)
    return result


def _json_edges(timeslot: dict, satellite_count: int, errors, epoch):
    edges: set[tuple[int, int]] = set()
    for link in timeslot.get("links", []):
        try:
            left = _as_int(link["sat1"])
            right = _as_int(link["sat2"])
        except (KeyError, TypeError) as exc:
            _error(errors, "invalid_json_link", f"Epoch {epoch}: {exc}", epoch)
            continue
        if not (0 <= left < satellite_count and 0 <= right < satellite_count):
            _error(
                errors,
                "invalid_satellite_id",
                f"Epoch {epoch}: JSON link endpoint {left}-{right} is invalid",
                epoch,
            )
            continue
        if left == right:
            _error(errors, "self_loop", f"Epoch {epoch}: JSON self-loop {left}", epoch)
            continue
        edge = tuple(sorted((left, right)))
        if edge in edges:
            _error(errors, "duplicate_link", f"Epoch {epoch}: duplicate JSON link {edge}", epoch)
        edges.add(edge)
    return edges


def _satellite_name_id(
    name, satellite_count: int, max_virtual_copies: int
) -> int:
    prefix = "SH1SAT"
    if not isinstance(name, str) or not name.startswith(prefix):
        raise ValueError(f"invalid satellite name {name!r}")
    try:
        satellite_id = int(name[len(prefix) :]) - 1
    except ValueError as exc:
        raise ValueError(f"invalid satellite name {name!r}") from exc
    if not 0 <= satellite_id < satellite_count * max_virtual_copies:
        raise ValueError(f"satellite name {name!r} is outside the virtual constellation")
    return satellite_id % satellite_count


def _inter_json_edges(
    inter_json, satellite_count: int, max_virtual_copies: int, errors, epoch
):
    if not isinstance(inter_json, dict):
        _error(
            errors,
            "invalid_inter_cell_json",
            f"Epoch {epoch}: inter-cell ISLs must be a JSON object",
            epoch,
        )
        return set()
    edges: set[tuple[int, int]] = set()
    for name, relation in inter_json.items():
        try:
            if not isinstance(relation, dict):
                raise ValueError(f"relation for {name!r} must be an object")
            left = _satellite_name_id(name, satellite_count, max_virtual_copies)
            right = _satellite_name_id(
                relation.get("near_sat"), satellite_count, max_virtual_copies
            )
        except ValueError as exc:
            _error(errors, "invalid_inter_cell_json", f"Epoch {epoch}: {exc}", epoch)
            continue
        if left == right:
            _error(
                errors,
                "self_loop",
                f"Epoch {epoch}: inter-cell JSON self-loop for {name}",
                epoch,
            )
            continue
        edges.add(tuple(sorted((left, right))))
    return edges


def _gateway_assignments(inter, satellite_count: int):
    """Return physical gateway identities while preserving their cell assignments."""
    assignments = set()
    for (left, right), (left_grid, right_grid) in inter:
        endpoints = tuple(
            sorted(
                (
                    (left % satellite_count, left_grid),
                    (right % satellite_count, right_grid),
                )
            )
        )
        assignments.add(endpoints)
    return assignments


def _components(node_count: int, edges: set[tuple[int, int]]) -> list[set[int]]:
    adjacency = {node: set() for node in range(node_count)}
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    unseen = set(adjacency)
    components = []
    while unseen:
        root = unseen.pop()
        component = {root}
        queue = [root]
        while queue:
            node = queue.pop()
            for neighbor in adjacency[node]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def _degree_metrics(node_count: int, edges: set[tuple[int, int]]) -> tuple[float, int, int]:
    degrees = [0] * node_count
    for left, right in edges:
        degrees[left] += 1
        degrees[right] += 1
    if not degrees:
        return 0.0, 0, 0
    return sum(degrees) / len(degrees), min(degrees), max(degrees)


def _edge_disjoint_paths(
    edges: set[tuple[int, int]], source_nodes: set[int], destination_nodes: set[int]
) -> int:
    if not source_nodes or not destination_nodes:
        return 0
    graph_nodes = {node for edge in edges for node in edge} | source_nodes | destination_nodes
    source = max(graph_nodes, default=-1) + 1
    sink = source + 1
    capacity: dict[tuple[int, int], int] = {}
    adjacency: dict[int, set[int]] = {node: set() for node in graph_nodes | {source, sink}}

    def add_arc(left: int, right: int, amount: int) -> None:
        capacity[(left, right)] = capacity.get((left, right), 0) + amount
        capacity.setdefault((right, left), 0)
        adjacency[left].add(right)
        adjacency[right].add(left)

    for left, right in edges:
        add_arc(left, right, 1)
        add_arc(right, left, 1)
    infinite = max(1, len(edges) + 1)
    for node in source_nodes:
        add_arc(source, node, infinite)
    for node in destination_nodes:
        add_arc(node, sink, infinite)

    flow = 0
    while True:
        parent = {source: None}
        queue = deque([source])
        while queue and sink not in parent:
            node = queue.popleft()
            for neighbor in adjacency[node]:
                if neighbor not in parent and capacity[(node, neighbor)] > 0:
                    parent[neighbor] = node
                    queue.append(neighbor)
        if sink not in parent:
            return flow
        cursor = sink
        amount = infinite
        while parent[cursor] is not None:
            previous = parent[cursor]
            amount = min(amount, capacity[(previous, cursor)])
            cursor = previous
        cursor = sink
        while parent[cursor] is not None:
            previous = parent[cursor]
            capacity[(previous, cursor)] -= amount
            capacity[(cursor, previous)] += amount
            cursor = previous
        flow += amount


def _grid_nodes(grid_mapping: dict, epoch: int, grid_id: int, satellite_count: int):
    epoch_mapping = grid_mapping.get(epoch, {})
    return {_as_int(node) % satellite_count for node in epoch_mapping.get(grid_id, [])}


def _validate_positions(timeslot, satellite_rows, epoch, errors):
    json_positions = timeslot.get("position", [])
    if len(json_positions) != len(satellite_rows):
        _error(
            errors,
            "position_count_mismatch",
            f"Epoch {epoch}: JSON has {len(json_positions)} positions; expected {len(satellite_rows)}",
            epoch,
        )
        return
    for satellite_id, row in enumerate(satellite_rows):
        try:
            positions = row[3]
        except (IndexError, TypeError):
            continue
        try:
            position_count = len(positions)
        except TypeError:
            continue
        if epoch >= position_count:
            continue
        try:
            lon_rad, lat_rad = positions[epoch]
            expected = (
                math.degrees(float(lat_rad)),
                math.degrees(float(lon_rad)),
                float(row[0][0]),
            )
        except (IndexError, TypeError, ValueError):
            continue
        actual_position = json_positions[satellite_id]
        try:
            if not isinstance(actual_position, dict):
                raise TypeError("position must be an object")
            actual = tuple(
                float(actual_position[name])
                for name in ("latitude", "longitude", "altitude")
            )
        except (KeyError, TypeError, ValueError) as exc:
            _error(
                errors,
                "invalid_json_position",
                f"Epoch {epoch}: satellite {satellite_id} position is malformed: {exc}",
                epoch,
            )
            continue
        if any(
            not math.isfinite(value)
            or not math.isclose(value, wanted, abs_tol=1e-7)
            for value, wanted in zip(actual, expected)
        ):
            _error(
                errors,
                "position_mismatch",
                f"Epoch {epoch}: satellite {satellite_id} position differs from satellite data",
                epoch,
            )


def validate_artifact_bundle(config: ValidationConfig) -> ValidationReport:
    report = ValidationReport(expected_epochs=config.expected_epochs)
    errors = report.errors
    required_inputs = (
        config.satellite_file,
        config.grid_satellites_file,
        config.traffic_matrix_file,
        config.block_positions_file,
        config.topology_dir / "predict_isl_position_all.json",
    )
    if not all(_require_file(path, errors) for path in required_inputs):
        return report

    try:
        satellite_rows = np.load(config.satellite_file, allow_pickle=True)
        grid_mapping = np.load(config.grid_satellites_file, allow_pickle=True).item()
        traffic_matrix = np.load(config.traffic_matrix_file)
        block_positions = json.loads(config.block_positions_file.read_text(encoding="utf-8"))
        consolidated = json.loads(
            (config.topology_dir / "predict_isl_position_all.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        _error(errors, "load_error", str(exc))
        return report

    satellite_count = len(satellite_rows)
    report.satellite_count = satellite_count
    if not config.min_satellites <= satellite_count <= config.max_satellites:
        _error(
            errors,
            "satellite_count_out_of_range",
            f"Satellite count {satellite_count} is outside "
            f"{config.min_satellites}..{config.max_satellites}",
        )
    if satellite_count == 0:
        _error(errors, "empty_constellation", "Satellite data contains no satellites")
        return report
    if traffic_matrix.shape != (121, 121):
        _error(errors, "invalid_traffic_shape", f"Traffic matrix shape is {traffic_matrix.shape}")
    if np.any(~np.isfinite(traffic_matrix)) or np.any(traffic_matrix < 0):
        _error(errors, "invalid_traffic_value", "Traffic matrix must be finite and non-negative")
    if not isinstance(grid_mapping, dict):
        _error(errors, "invalid_grid_mapping", "Grid-satellite mapping must be a dict")
        return report
    if not isinstance(block_positions, dict):
        _error(errors, "invalid_block_positions", "Block positions must be a JSON object")
        return report
    if not isinstance(consolidated, dict) or not isinstance(
        consolidated.get("timeslots"), list
    ):
        _error(
            errors,
            "invalid_consolidated_topology",
            "Consolidated topology must contain a timeslots list",
        )
        return report
    if len(consolidated["timeslots"]) != config.expected_epochs:
        _error(
            errors,
            "epoch_count_mismatch",
            "Consolidated topology timeslot count differs from expected epochs",
        )

    for satellite_id, row in enumerate(satellite_rows):
        try:
            positions = row[3]
        except (IndexError, TypeError):
            _error(errors, "invalid_satellite_row", f"Satellite {satellite_id} row is malformed")
            continue
        try:
            position_count = len(positions)
        except TypeError:
            _error(
                errors,
                "invalid_satellite_row",
                f"Satellite {satellite_id} position history is not a sequence",
            )
            continue
        if position_count != config.expected_epochs:
            _error(
                errors,
                "satellite_epoch_count_mismatch",
                f"Satellite {satellite_id} has {position_count} positions; "
                f"expected {config.expected_epochs}",
            )
        for epoch, position in enumerate(positions):
            try:
                lon_rad, lat_rad = float(position[0]), float(position[1])
            except (IndexError, TypeError, ValueError):
                _error(
                    errors,
                    "invalid_position",
                    f"Satellite {satellite_id} epoch {epoch} position is malformed",
                    epoch,
                )
                continue
            if (
                not math.isfinite(lon_rad)
                or not math.isfinite(lat_rad)
                or not -math.pi <= lon_rad <= math.pi
                or not -math.pi / 2 <= lat_rad <= math.pi / 2
            ):
                _error(
                    errors,
                    "invalid_position",
                    f"Satellite {satellite_id} epoch {epoch} has invalid radians "
                    f"[{lon_rad}, {lat_rad}]",
                    epoch,
                )

    for epoch in range(config.expected_epochs):
        if epoch not in grid_mapping:
            _error(
                errors,
                "missing_grid_epoch",
                f"Grid-satellite mapping has no epoch {epoch}",
                epoch,
            )
            continue
        epoch_mapping = grid_mapping[epoch]
        if not isinstance(epoch_mapping, dict):
            _error(
                errors,
                "invalid_grid_mapping",
                f"Grid-satellite mapping epoch {epoch} must be a dict",
                epoch,
            )
            continue
        for grid_id, nodes in epoch_mapping.items():
            try:
                normalized_grid_id = _as_int(grid_id)
            except TypeError as exc:
                _error(errors, "invalid_grid_id", str(exc), epoch)
                continue
            if not 0 <= normalized_grid_id < 121:
                _error(
                    errors,
                    "invalid_grid_id",
                    f"Epoch {epoch}: grid ID {normalized_grid_id} is outside 0..120",
                    epoch,
                )
            if not isinstance(nodes, (list, tuple, np.ndarray, set)):
                _error(
                    errors,
                    "invalid_grid_mapping",
                    f"Epoch {epoch}: satellites for grid {normalized_grid_id} must be a sequence",
                    epoch,
                )
                continue
            for node in nodes:
                _normalize_endpoint(
                    node,
                    satellite_count,
                    config.max_virtual_copies,
                    errors,
                    epoch,
                )

    previous_edges: set[tuple[int, int]] | None = None
    previous_gateway_assignments = None
    passing_path_epochs = 0
    for epoch in range(config.expected_epochs):
        paths = {
            "inter": config.topology_dir / "inter_topology" / f"{epoch}.npy",
            "intra": config.topology_dir / "intra_topology" / f"{epoch}.npy",
            "cells": config.topology_dir / "sat_cells" / f"{epoch}.json",
            "inter_json": config.topology_dir / "inter_cell_isls" / f"{epoch}.json",
            "positions": config.topology_dir / "all_isl_positions" / f"{epoch}.json",
        }
        if not all(_require_file(path, errors, epoch) for path in paths.values()):
            continue
        try:
            inter = _load_inter_topology(paths["inter"])
            intra = _load_intra_topology(paths["intra"])
            sat_cells = json.loads(paths["cells"].read_text(encoding="utf-8"))
            inter_json = json.loads(paths["inter_json"].read_text(encoding="utf-8"))
            timeslot = json.loads(paths["positions"].read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            _error(errors, "load_error", f"Epoch {epoch}: {exc}", epoch)
            continue
        if not isinstance(timeslot, dict):
            _error(
                errors,
                "invalid_timeslot",
                f"Epoch {epoch}: per-epoch topology must be a JSON object",
                epoch,
            )
            continue

        inter_edges = _physical_edges(
            (nodes for nodes, _ in inter),
            satellite_count,
            config.max_virtual_copies,
            errors,
            epoch,
        )
        intra_edges = _physical_edges(
            (edge for edges in intra.values() for edge in edges),
            satellite_count,
            config.max_virtual_copies,
            errors,
            epoch,
        )
        all_edges = inter_edges | intra_edges
        json_edges = _json_edges(timeslot, satellite_count, errors, epoch)
        if all_edges != json_edges:
            _error(
                errors,
                "link_set_mismatch",
                f"Epoch {epoch}: NPY links and all_isl_positions links differ; "
                f"missing={sorted(all_edges - json_edges)}, extra={sorted(json_edges - all_edges)}",
                epoch,
            )

        inter_json_edges = _inter_json_edges(
            inter_json,
            satellite_count,
            config.max_virtual_copies,
            errors,
            epoch,
        )
        if inter_edges != inter_json_edges:
            _error(
                errors,
                "inter_cell_link_set_mismatch",
                f"Epoch {epoch}: inter topology and inter-cell JSON links differ; "
                f"missing={sorted(inter_edges - inter_json_edges)}, "
                f"extra={sorted(inter_json_edges - inter_edges)}",
                epoch,
            )

        if epoch < len(consolidated.get("timeslots", [])):
            if consolidated["timeslots"][epoch] != timeslot:
                _error(
                    errors,
                    "consolidated_timeslot_mismatch",
                    f"Epoch {epoch}: consolidated and per-epoch JSON differ",
                    epoch,
                )
        _validate_positions(timeslot, satellite_rows, epoch, errors)

        expected_sat_cells = {}
        expected_inter_relations = {}
        epoch_grid_nodes = {
            grid_id: set(nodes)
            for grid_id, nodes in grid_mapping.get(epoch, {}).items()
            if isinstance(nodes, (list, tuple, np.ndarray, set))
        }
        for (left, right), (left_grid, right_grid) in inter:
            left_name = f"SH1SAT{left + 1}"
            right_name = f"SH1SAT{right + 1}"
            left_cell = block_positions.get(str(left_grid), {}).get("row_col")
            right_cell = block_positions.get(str(right_grid), {}).get("row_col")
            expected_sat_cells[left_name] = left_cell
            expected_sat_cells[right_name] = right_cell
            expected_inter_relations.setdefault(
                left_name, {"near_sat": right_name, "near_cell": right_cell}
            )
            expected_inter_relations.setdefault(
                right_name, {"near_sat": left_name, "near_cell": left_cell}
            )

            for raw_node, grid_id in ((left, left_grid), (right, right_grid)):
                node = _normalize_endpoint(
                    raw_node,
                    satellite_count,
                    config.max_virtual_copies,
                    errors,
                    epoch,
                )
                if node is None:
                    continue
                if raw_node not in epoch_grid_nodes.get(grid_id, set()):
                    _error(
                        errors,
                        "endpoint_grid_mismatch",
                        f"Epoch {epoch}: node {raw_node} is not listed in grid {grid_id}",
                        epoch,
                    )
            if (
                0 <= left_grid < traffic_matrix.shape[0]
                and 0 <= right_grid < traffic_matrix.shape[1]
                and traffic_matrix[left_grid, right_grid] <= 0
                and traffic_matrix[right_grid, left_grid] <= 0
            ):
                _error(
                    errors,
                    "unsupported_grid_link",
                    f"Epoch {epoch}: grid link {left_grid}-{right_grid} has no traffic demand",
                    epoch,
                )

        if sat_cells != expected_sat_cells:
            _error(
                errors,
                "sat_cell_mismatch",
                f"Epoch {epoch}: satellite-cell JSON differs from inter topology",
                epoch,
            )
        if inter_json != expected_inter_relations:
            _error(
                errors,
                "inter_cell_relation_mismatch",
                f"Epoch {epoch}: inter-cell JSON differs from inter topology",
                epoch,
            )

        active_counts = {
            grid_id: len(_grid_nodes(grid_mapping, epoch, grid_id, satellite_count))
            for grid_id in config.active_grids
        }
        for grid_id, count in active_counts.items():
            if count == 0:
                _error(
                    errors,
                    "empty_active_grid",
                    f"Epoch {epoch}: active grid {grid_id} has no satellites",
                    epoch,
                )

        components = _components(satellite_count, all_edges)
        average_degree, min_degree, max_degree = _degree_metrics(
            satellite_count, all_edges
        )
        participating_nodes = {node for edge in all_edges for node in edge}
        largest_participating_component = max(
            (
                len(component & participating_nodes)
                for component in components
                if component & participating_nodes
            ),
            default=0,
        )
        largest_component_ratio = (
            largest_participating_component / len(participating_nodes)
            if participating_nodes
            else 0.0
        )
        constellation_largest_component_ratio = (
            max((len(component) for component in components), default=0)
            / satellite_count
            if satellite_count
            else 0.0
        )
        if largest_component_ratio < config.min_largest_component_ratio:
            _error(
                errors,
                "insufficient_connected_component",
                f"Epoch {epoch}: participating-satellite largest component ratio "
                f"{largest_component_ratio:.3f} "
                f"is below {config.min_largest_component_ratio:.3f}",
                epoch,
            )
        disjoint_paths = _edge_disjoint_paths(
            all_edges,
            _grid_nodes(grid_mapping, epoch, config.source_grid, satellite_count),
            _grid_nodes(grid_mapping, epoch, config.destination_grid, satellite_count),
        )
        if disjoint_paths >= config.min_edge_disjoint_paths:
            passing_path_epochs += 1

        added = len(all_edges - previous_edges) if previous_edges is not None else 0
        removed = len(previous_edges - all_edges) if previous_edges is not None else 0
        gateway_assignments = _gateway_assignments(inter, satellite_count)
        gateway_handovers = 0
        if previous_gateway_assignments is not None:
            added_gateways = gateway_assignments - previous_gateway_assignments
            removed_gateways = previous_gateway_assignments - gateway_assignments
            gateway_handovers = max(len(added_gateways), len(removed_gateways))
        if previous_edges is not None and all_edges != previous_edges:
            report.topology_change_count += 1
        report.gateway_handover_count += gateway_handovers
        report.epochs.append(
            EpochMetrics(
                epoch=epoch,
                satellite_count=satellite_count,
                link_count=len(all_edges),
                inter_link_count=len(inter_edges),
                intra_link_count=len(intra_edges),
                component_count=len(components),
                participating_satellite_count=len(participating_nodes),
                largest_component_ratio=largest_component_ratio,
                constellation_largest_component_ratio=(
                    constellation_largest_component_ratio
                ),
                edge_disjoint_paths=disjoint_paths,
                active_grid_counts=active_counts,
                average_degree=average_degree,
                min_degree=min_degree,
                max_degree=max_degree,
                added_links=added,
                removed_links=removed,
                gateway_handovers=gateway_handovers,
            )
        )
        previous_edges = all_edges
        previous_gateway_assignments = gateway_assignments

    path_epoch_ratio = passing_path_epochs / config.expected_epochs if config.expected_epochs else 0
    report.path_epoch_ratio = path_epoch_ratio
    if path_epoch_ratio < config.min_path_epoch_ratio:
        _error(
            errors,
            "insufficient_path_diversity",
            f"Edge-disjoint path gate passed in {path_epoch_ratio:.1%} of epochs; "
            f"required {config.min_path_epoch_ratio:.1%}",
        )
    if report.topology_change_count < config.min_topology_changes:
        _error(
            errors,
            "insufficient_topology_changes",
            f"Topology changed {report.topology_change_count} times; "
            f"required {config.min_topology_changes}",
        )
    if report.gateway_handover_count < config.min_gateway_handovers:
        _error(
            errors,
            "insufficient_gateway_handovers",
            f"Observed {report.gateway_handover_count} gateway handovers; "
            f"required {config.min_gateway_handovers}",
        )
    return report
