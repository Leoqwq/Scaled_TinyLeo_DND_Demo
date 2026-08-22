"""Focused tests for finite-window candidate generation and merged coverage."""

import math

import numpy as np
from scipy.sparse import csr_matrix, load_npz

from orbital_texture_generator import TextureGenerator
from utils import approximate_ratio, coverage_eta, satellite_period
from window_config import WindowConfig


CANADA_GRID_IDS = (12, 13, 14, 23, 24, 25)


def window_config():
    return WindowConfig.from_dict(
        {
            "start_epoch": 0,
            "num_epochs": 8,
            "region_grid_ids": list(CANADA_GRID_IDS),
            "target_satellites": 64,
            "max_satellites": 64,
            "num_processes": 1,
            "random_seed": 20260821,
        }
    )


def candidate_record(parameters, initial_phase_index, positions):
    record = np.empty(3, dtype=object)
    record[:] = [np.asarray(parameters), initial_phase_index, np.asarray(positions)]
    return record


def candidate_array(*records):
    candidates = np.empty((len(records), 3), dtype=object)
    for index, record in enumerate(records):
        candidates[index] = record
    return candidates


def legacy_orbit(parameters):
    height_km, inclination, raan = parameters
    period = satellite_period(height_km * 1e3)
    p, q = approximate_ratio(int(period), precision=1e-3)
    eta = coverage_eta(period)
    generator = TextureGenerator.__new__(TextureGenerator)
    return generator._cal_supply_all_cell_backbone(
        [[height_km, period, q, p, eta], inclination, raan]
    )[3]


def test_window_selection_matches_consecutive_legacy_orbit_slots():
    from windowed_texture import generate_candidate_states

    parameters = (573.0, math.radians(60), math.radians(-132))
    candidates = generate_candidate_states(
        window_config(), candidate_orbits=[parameters], phase_slots=[0]
    )
    legacy_positions = np.asarray(
        [[slot[1], slot[2]] for slot in legacy_orbit(parameters)]
    )

    assert len(candidates) == 1
    np.testing.assert_allclose(candidates[0, 2], legacy_positions[:8])


def test_generated_positions_stay_in_geographic_radian_bounds():
    from windowed_texture import generate_candidate_states

    candidates = generate_candidate_states(
        window_config(),
        candidate_orbits=[(573.0, math.radians(60), math.radians(-132))],
        phase_slots=[0],
    )
    positions = candidates[0, 2]

    assert np.all((-np.pi <= positions[:, 0]) & (positions[:, 0] <= np.pi))
    assert np.all(
        (-np.pi / 2 <= positions[:, 1]) & (positions[:, 1] <= np.pi / 2)
    )


def test_candidate_generation_is_deterministic_for_profile_seed():
    from windowed_texture import generate_candidate_states

    config = window_config()
    bounded_orbits = [
        (573.0, math.radians(60), math.radians(-132)),
        (573.0, math.radians(60), math.radians(-100)),
    ]
    first = generate_candidate_states(
        config, candidate_orbits=bounded_orbits, phase_slots=[0, 1]
    )
    second = generate_candidate_states(
        config, candidate_orbits=bounded_orbits, phase_slots=[0, 1]
    )

    assert config.random_seed == 20260821
    assert len(first) == len(second)
    for first_record, second_record in zip(first, second):
        np.testing.assert_allclose(first_record[0], second_record[0])
        assert first_record[1] == second_record[1]
        np.testing.assert_allclose(first_record[2], second_record[2])


def test_candidates_that_never_enter_canada_cells_are_removed():
    from windowed_texture import generate_candidate_states

    canada_crossing = (573.0, math.radians(60), math.radians(-132))
    equatorial = (573.0, 0.0, 0.0)
    candidates = generate_candidate_states(
        window_config(),
        candidate_orbits=[canada_crossing, equatorial],
        phase_slots=[0],
    )

    assert len(candidates) == 1
    np.testing.assert_allclose(candidates[0, 0], canada_crossing)


def test_phase_indices_advance_linearly_with_modulo_wrap():
    from orbital_texture_generator import phase_indices

    assert phase_indices(initial_slot=7, count=4, modulo=10) == [7, 8, 9, 0]


def test_legacy_recovery_uses_linear_phases_and_returns_all_positions():
    generator = TextureGenerator.__new__(TextureGenerator)
    generator.time_split = 4
    generator.demand_list = [None]
    cover = [
        [[[0, 1.0]], 0.0, 10.0],
        [[[0, 1.0]], 1.0, 11.0],
        [[[0, 1.0]], 2.0, 12.0],
        [[[0, 1.0]], 3.0, 13.0],
    ]

    selected_cover, positions = generator._recover_fulltime([3, cover, 4, 1])

    np.testing.assert_array_equal(selected_cover.toarray(), [[1.0, 1.0, 1.0, 1.0]])
    assert positions == [[3.0, 13.0], [0.0, 10.0], [1.0, 11.0], [2.0, 12.0]]


def test_merged_csr_keeps_global_epoch_columns_and_one_hot_geometry():
    from windowed_texture import build_windowed_texture

    config = window_config()
    canada_position = [math.radians(-132), math.radians(66)]  # grid 12
    equator_position = [0.0, 0.0]  # grid 60
    candidates = candidate_array(
        candidate_record([573.0, 1.0, 2.0], 0, [canada_position] * 8),
        candidate_record([573.0, 1.1, 2.1], 1, [equator_position] * 8),
    )

    texture = build_windowed_texture(config, np.zeros((8, 121)), candidates)

    assert texture.format == "csr"
    assert texture.shape == (len(candidates), config.num_epochs * 121)
    assert texture.nnz == len(candidates) * config.num_epochs
    for epoch in range(config.num_epochs):
        first_block = texture[0, epoch * 121 : (epoch + 1) * 121].toarray()[0]
        second_block = texture[1, epoch * 121 : (epoch + 1) * 121].toarray()[0]
        assert first_block[12] == 1.0
        assert second_block[60] == 1.0
        assert np.count_nonzero(first_block) == np.count_nonzero(second_block) == 1


def test_saved_empty_positions_preserve_the_window_axis(tmp_path):
    from windowed_texture import save_windowed_artifacts

    texture_path = tmp_path / "coverage.npz"
    candidate_path = tmp_path / "candidates.npy"
    position_path = tmp_path / "positions.npy"
    candidates = np.empty((0, 3), dtype=object)
    coverage = csr_matrix((0, 8 * 121))

    save_windowed_artifacts(
        texture_path, candidate_path, position_path, coverage, candidates
    )

    assert load_npz(texture_path).shape == (0, 8 * 121)
    assert np.load(candidate_path, allow_pickle=True).shape == (0, 3)
    assert np.load(position_path).shape == (0, 8, 2)
