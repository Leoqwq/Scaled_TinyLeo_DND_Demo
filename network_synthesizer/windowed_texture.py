"""Finite-window candidate states and merged backbone coverage texture."""

import math

import numpy as np
from scipy.sparse import csr_matrix, save_npz

from orbital_texture_generator import TextureGenerator
from utils import approximate_ratio, coverage_eta, satellite_period
from window_config import WindowConfig


LEGACY_INCLINATION_COUNT = 45
LEGACY_RAAN_COUNT = 90
GLOBAL_GRID_COUNT = 121


def slice_legacy_positions(candidate, epoch_indices):
    """Select legacy position slots from a compact candidate record."""
    positions = np.asarray(candidate[2], dtype=float)
    return positions[np.asarray(epoch_indices, dtype=int)]


def _legacy_candidate_orbits(config):
    inclinations = np.linspace(0.0, math.pi, LEGACY_INCLINATION_COUNT)
    raans = np.linspace(0.0, 2 * math.pi, LEGACY_RAAN_COUNT)
    return (
        (config.satellite_height_km, inclination, raan)
        for inclination in inclinations
        for raan in raans
    )


def _legacy_positions(parameters):
    height_km, inclination, raan = parameters
    period = satellite_period(height_km * 1e3)
    p, q = approximate_ratio(int(period), precision=1e-3)
    eta = coverage_eta(period)
    generator = TextureGenerator.__new__(TextureGenerator)
    coverage = generator._cal_supply_all_cell_backbone(
        [[height_km, period, q, p, eta], inclination, raan]
    )[3]
    return np.asarray([[slot[1], slot[2]] for slot in coverage], dtype=float)


def _candidate_array(records):
    candidates = np.empty((len(records), 3), dtype=object)
    for index, record in enumerate(records):
        candidates[index] = record
    return candidates


def _grid_ids(positions):
    generator = TextureGenerator.__new__(TextureGenerator)
    return [generator._create_new_grid_satellites(position) for position in positions]


def generate_candidate_states(
    config: WindowConfig, *, candidate_orbits=None, phase_slots=None
) -> np.ndarray:
    """Generate and retain finite-window candidates that cross the active ROI."""
    orbits = (
        _legacy_candidate_orbits(config)
        if candidate_orbits is None
        else candidate_orbits
    )
    records = []

    for parameters in orbits:
        parameters = np.asarray(parameters, dtype=float)
        legacy_positions = _legacy_positions(parameters)
        slots = range(len(legacy_positions)) if phase_slots is None else phase_slots
        for initial_phase_index in slots:
            indices = (
                initial_phase_index + np.asarray(config.epoch_indices, dtype=int)
            ) % len(legacy_positions)
            legacy_candidate = np.empty(3, dtype=object)
            legacy_candidate[:] = [parameters, initial_phase_index, legacy_positions]
            positions = slice_legacy_positions(legacy_candidate, indices)
            if not set(_grid_ids(positions)).intersection(config.active_grid_ids):
                continue
            candidate_record = np.empty(3, dtype=object)
            candidate_record[:] = [parameters.copy(), initial_phase_index, positions]
            records.append(candidate_record)

    return _candidate_array(records)


def build_windowed_texture(config, demand, candidates) -> csr_matrix:
    """Build merged one-hot global-grid coverage for all retained candidates."""
    demand = np.asarray(demand)
    expected_shape = (config.num_epochs, GLOBAL_GRID_COUNT)
    if demand.shape != expected_shape:
        raise ValueError(f"demand must have shape {expected_shape}")

    rows = []
    columns = []
    for row_index, candidate in enumerate(candidates):
        positions = np.asarray(candidate[2], dtype=float)
        if positions.shape != (config.num_epochs, 2):
            raise ValueError(
                f"candidate positions must have shape ({config.num_epochs}, 2)"
            )
        for epoch, grid_id in enumerate(_grid_ids(positions)):
            rows.append(row_index)
            columns.append(epoch * GLOBAL_GRID_COUNT + grid_id)

    values = np.ones(len(rows), dtype=float)
    return csr_matrix(
        (values, (rows, columns)),
        shape=(len(candidates), config.num_epochs * GLOBAL_GRID_COUNT),
    )


def save_windowed_artifacts(
    texture_path, candidate_path, position_path, coverage_csr, candidate_states
):
    """Save one coverage, candidate metadata, and position artifact."""
    if len(candidate_states):
        positions = np.stack(candidate_states[:, 2]).astype(float, copy=False)
    else:
        num_epochs = coverage_csr.shape[1] // GLOBAL_GRID_COUNT
        positions = np.empty((0, num_epochs, 2), dtype=float)
    save_npz(texture_path, coverage_csr)
    np.save(candidate_path, candidate_states)
    np.save(position_path, positions)
