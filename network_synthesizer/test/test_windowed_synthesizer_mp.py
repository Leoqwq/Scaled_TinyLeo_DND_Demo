"""Behavior tests for bounded finite-horizon matching pursuit."""

from dataclasses import replace

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from synthesizer_mp import coverage_gain
from window_config import WindowConfig
from windowed_synthesizer_mp import save_synthesis_result, synthesize_windowed


def make_config(**overrides):
    config = WindowConfig.from_dict({"start_epoch": 0, "num_epochs": 8})
    return replace(config, **overrides)


def empty_demand():
    return np.zeros((8, 121), dtype=float)


def sparse_rows(entries, row_count):
    rows = []
    columns = []
    values = []
    for row_id, row_entries in enumerate(entries):
        for column_id, value in row_entries:
            rows.append(row_id)
            columns.append(column_id)
            values.append(value)
    return csr_matrix((values, (rows, columns)), shape=(row_count, 8 * 121))


# Regression: transposing time/cell flattening or changing legacy dot-product scoring selects row 0.
def test_first_selection_matches_legacy_gain_with_row_major_time_columns():
    demand = empty_demand()
    demand[0, 0] = 2.0
    demand[1, 0] = 3.0
    coverage = sparse_rows([[(0, 2.0)], [(121, 3.0)]], row_count=2)

    residual = demand.reshape(-1)
    assert coverage_gain(coverage.getrow(0), residual) == 4.0
    assert coverage_gain(coverage.getrow(1), residual) == 9.0

    result = synthesize_windowed(
        demand, coverage, make_config(coverage_target=0.6)
    )

    assert result.selected_candidate_ids == (1,)
    assert result.coverage_ratio == pytest.approx(0.6)
    assert result.residual_by_time[0, 0] == 2.0
    assert result.residual_by_time[1, 0] == 0.0


# Regression: using an unstable max reduction lets equal-gain row 1 beat lower row 0.
def test_equal_gain_tie_selects_lowest_candidate_id():
    demand = empty_demand()
    demand[0, 0] = 1.0
    coverage = sparse_rows([[(0, 1.0)], [(0, 1.0)]], row_count=2)

    result = synthesize_windowed(demand, coverage, make_config(coverage_target=1.0))

    assert result.selected_candidate_ids == (0,)
    assert result.stop_reason == "coverage_target_reached"


# Regression: checking the target only after another selection overshoots the requested coverage.
def test_selection_stops_as_soon_as_coverage_target_is_reached():
    demand = empty_demand()
    demand[0, 0] = 2.0
    demand[0, 1] = 1.0
    coverage = sparse_rows([[(0, 2.0)], [(1, 1.0)]], row_count=2)

    result = synthesize_windowed(
        demand, coverage, make_config(coverage_target=0.6)
    )

    assert result.selected_candidate_ids == (0,)
    assert result.coverage_ratio == pytest.approx(2.0 / 3.0)
    assert result.stop_reason == "coverage_target_reached"
    np.testing.assert_array_equal(result.residual_by_time[0, :2], [0.0, 1.0])


# Regression: treating target_satellites as a stop or omitting the cap allows 129 selections.
def test_profile_defaults_to_target_80_and_selection_never_exceeds_max_128():
    config = make_config(coverage_target=1.0)
    demand = empty_demand()
    demand.reshape(-1)[:129] = 1.0
    coverage = csr_matrix(
        (np.ones(129), (np.arange(129), np.arange(129))),
        shape=(129, 8 * 121),
    )

    result = synthesize_windowed(demand, coverage, config)

    assert config.target_satellites == 80
    assert config.max_satellites == 128
    assert len(result.selected_candidate_ids) == 128
    assert result.selected_candidate_ids == tuple(range(128))
    assert result.stop_reason == "satellite_cap_reached"


# Regression: failing to mask exhausted candidates can duplicate selections instead of stopping.
def test_impossible_demand_stops_without_positive_gain_or_duplicates():
    demand = empty_demand()
    demand[0, 0] = 2.0
    demand[0, 1] = 1.0
    coverage = sparse_rows([[(0, 1.0)], [(2, 2.0)]], row_count=2)

    result = synthesize_windowed(demand, coverage, make_config(coverage_target=1.0))

    assert result.selected_candidate_ids == (0,)
    assert result.coverage_ratio == pytest.approx(1.0 / 3.0)
    assert result.stop_reason == "no_positive_gain"
    np.testing.assert_array_equal(result.residual_by_time[0, :3], [1.0, 1.0, 0.0])


# Regression: evaluating no-positive-gain before the configured cap reports the wrong termination.
def test_low_satellite_cap_stops_with_exact_cap_count():
    demand = empty_demand()
    demand[0, :3] = 1.0
    coverage = sparse_rows(
        [[(0, 1.0)], [(1, 1.0)], [(2, 1.0)]], row_count=3
    )

    result = synthesize_windowed(
        demand,
        coverage,
        make_config(coverage_target=1.0, target_satellites=2, max_satellites=2),
    )

    assert result.selected_candidate_ids == (0, 1)
    assert result.coverage_ratio == pytest.approx(2.0 / 3.0)
    assert result.stop_reason == "satellite_cap_reached"


# Regression: subtracting dense rows or omitting the clamp produces a flat or negative residual.
def test_residual_retains_time_cell_shape_and_is_finite_nonnegative():
    demand = empty_demand()
    demand[7, 120] = 2.0
    coverage = sparse_rows([[(8 * 121 - 1, 3.0)]], row_count=1)

    result = synthesize_windowed(demand, coverage, make_config(coverage_target=1.0))

    assert result.residual_by_time.shape == (8, 121)
    assert np.isfinite(result.residual_by_time).all()
    assert (result.residual_by_time >= 0).all()
    assert result.residual_by_time[7, 120] == 0.0


# Regression: dividing by zero demand yields NaN and the wrong stop reason.
def test_zero_total_demand_is_already_fully_covered():
    demand = empty_demand()
    coverage = csr_matrix((3, 8 * 121), dtype=float)

    result = synthesize_windowed(demand, coverage, make_config())

    assert result.selected_candidate_ids == ()
    assert result.coverage_ratio == 1.0
    assert result.stop_reason == "coverage_target_reached"
    np.testing.assert_array_equal(result.residual_by_time, demand)


# Regression: accepting a CSR with a different flattened width misaligns candidate coverage.
def test_coverage_width_mismatch_raises_clear_value_error():
    demand = empty_demand()
    coverage = csr_matrix((2, 8 * 121 - 1), dtype=float)

    with pytest.raises(ValueError, match="coverage must have 968 columns"):
        synthesize_windowed(demand, coverage, make_config())


# Regression: omitting one result field makes the saved artifact unusable downstream.
def test_saved_result_round_trips_all_fields(tmp_path):
    demand = empty_demand()
    demand[0, 0] = 1.0
    coverage = sparse_rows([[(0, 1.0)]], row_count=1)
    result = synthesize_windowed(demand, coverage, make_config(coverage_target=1.0))
    output_path = tmp_path / "synthesis.npy"

    save_synthesis_result(output_path, result)
    saved = np.load(output_path, allow_pickle=True).item()

    assert set(saved) == {
        "selected_candidate_ids",
        "coverage_ratio",
        "residual_by_time",
        "stop_reason",
    }
    assert tuple(saved["selected_candidate_ids"]) == (0,)
    assert saved["coverage_ratio"] == 1.0
    np.testing.assert_array_equal(saved["residual_by_time"], np.zeros((8, 121)))
    assert saved["stop_reason"] == "coverage_target_reached"
