"""Export Canada parity-scale inputs for the network orchestrator."""

from numbers import Integral
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix


GLOBAL_GRID_COUNT = 121
CANADA_TRAFFIC_EDGES = (
    (12, 13),
    (13, 14),
    (23, 24),
    (24, 25),
    (12, 23),
    (13, 24),
    (14, 25),
)


def _validate_coverage(coverage):
    if not isinstance(coverage, csr_matrix) or coverage.ndim != 2:
        raise ValueError("coverage must be a two-dimensional CSR matrix")
    if coverage.shape[1] % GLOBAL_GRID_COUNT:
        raise ValueError("coverage columns must be divisible by 121")
    if not np.isfinite(coverage.data).all():
        raise ValueError("coverage entries must be finite")
    if np.any(coverage.data < 0):
        raise ValueError("coverage entries must be nonnegative")
    if np.any(coverage.indices < 0) or np.any(coverage.indices >= coverage.shape[1]):
        raise ValueError("coverage entry column is outside declared layout")
    return coverage.shape[1] // GLOBAL_GRID_COUNT


def _validate_selected_ids(selected_candidate_ids, candidate_count):
    selected = list(selected_candidate_ids)
    if any(not isinstance(candidate_id, Integral) for candidate_id in selected):
        raise ValueError("selected candidate IDs must be integers")
    selected = [int(candidate_id) for candidate_id in selected]
    if len(set(selected)) != len(selected):
        raise ValueError("selected candidate IDs must be unique")
    for candidate_id in selected:
        if candidate_id < 0 or candidate_id >= candidate_count:
            raise ValueError(f"selected candidate ID {candidate_id} is out of range")
    return selected


def export_satellite_data(selected_candidate_ids, candidates, coverage):
    """Convert selected candidate rows to the orchestrator's legacy object layout."""
    num_epochs = _validate_coverage(coverage)
    candidates = np.asarray(candidates, dtype=object)
    if candidates.ndim != 2 or candidates.shape[1] != 3:
        raise ValueError("candidates must have shape (candidate_count, 3)")
    if len(candidates) != coverage.shape[0]:
        raise ValueError("candidate count must equal coverage row count")

    for candidate_id, candidate in enumerate(candidates):
        if np.asarray(candidate[0]).shape != (3,):
            raise ValueError(f"candidate {candidate_id} parameters must have shape (3,)")
        if np.asarray(candidate[2]).shape != (num_epochs, 2):
            raise ValueError(
                f"candidate {candidate_id} positions must have shape ({num_epochs}, 2)"
            )

    selected = _validate_selected_ids(selected_candidate_ids, len(candidates))
    exported = np.empty((len(selected), 5), dtype=object)
    for physical_id, candidate_id in enumerate(selected):
        parameters, initial_phase_index, positions = candidates[candidate_id]
        exported[physical_id] = [
            np.asarray(parameters).tolist(),
            [initial_phase_index],
            coverage.getrow(candidate_id),
            np.asarray(positions).tolist(),
            1,
        ]
    return exported


def build_grid_satellites(selected_candidate_ids, coverage):
    """Map every epoch and global grid cell to selected physical satellite IDs."""
    num_epochs = _validate_coverage(coverage)
    selected = _validate_selected_ids(selected_candidate_ids, coverage.shape[0])
    mapping = {
        epoch: {grid_id: [] for grid_id in range(GLOBAL_GRID_COUNT)}
        for epoch in range(num_epochs)
    }

    for physical_id, candidate_id in enumerate(selected):
        row = coverage.getrow(candidate_id)
        for column in np.unique(row.indices[row.data > 0]):
            epoch, grid_id = divmod(int(column), GLOBAL_GRID_COUNT)
            mapping[epoch][grid_id].append(physical_id)
    return mapping


def build_canada_traffic_matrix():
    """Build the seven-edge bidirectional Canada backbone workload."""
    traffic = np.zeros((GLOBAL_GRID_COUNT, GLOBAL_GRID_COUNT), dtype=np.float64)
    for left_grid, right_grid in CANADA_TRAFFIC_EDGES:
        traffic[left_grid, right_grid] = 1.0
        traffic[right_grid, left_grid] = 1.0
    return traffic


def build_canada_backbone_demand(num_epochs=12):
    """Build the reproducible per-epoch Canada synthesis demand."""
    demand = np.zeros((num_epochs, GLOBAL_GRID_COUNT), dtype=np.float64)
    demand[:, [12, 14, 23, 25]] = 6.0
    demand[:, [13, 24]] = 8.0
    return demand


def save_canada_parity_artifacts(
    output_directory, selected_candidate_ids, candidates, coverage
):
    """Save the three stable Canada parity-scale orchestrator inputs."""
    output_directory = Path(output_directory)
    paths = (
        output_directory / "canada_parity_satellite_data.npy",
        output_directory / "canada_parity_grid_satellites.npy",
        output_directory / "canada_parity_traffic_matrix.npy",
    )
    np.save(
        paths[0],
        export_satellite_data(selected_candidate_ids, candidates, coverage),
        allow_pickle=True,
    )
    np.save(
        paths[1],
        build_grid_satellites(selected_candidate_ids, coverage),
        allow_pickle=True,
    )
    np.save(paths[2], build_canada_traffic_matrix())
    return paths
