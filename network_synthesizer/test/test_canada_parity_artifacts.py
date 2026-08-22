"""Contract tests for Canada parity-scale orchestrator input exports."""

from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from canada_parity_artifacts import (
    build_canada_backbone_demand,
    build_canada_traffic_matrix,
    build_grid_satellites,
    export_satellite_data,
    save_canada_parity_artifacts,
)


FIXTURE_PATH = Path(__file__).parent / "data" / "canada_parity_backbone_demand.npy"


def candidate_array():
    candidates = np.empty((3, 3), dtype=object)
    candidates[0] = [
        np.asarray([500.0, 0.1, 0.2]),
        4,
        np.asarray([[-2.0, 0.7], [-1.9, 0.8]]),
    ]
    candidates[1] = [
        np.asarray([510.0, 0.3, 0.4]),
        5,
        np.asarray([[-1.8, 0.9], [-1.7, 1.0]]),
    ]
    candidates[2] = [
        np.asarray([520.0, 0.5, 0.6]),
        6,
        np.asarray([[-1.6, 1.1], [-1.5, 1.2]]),
    ]
    return candidates


def coverage_rows():
    return csr_matrix(
        (
            [1.0, 2.0, 1.0, 1.0, 3.0],
            (
                [0, 0, 1, 2, 2],
                [12, 121 + 23, 14, 13, 121 + 24],
            ),
        ),
        shape=(3, 2 * 121),
    )


# Regression: reconstructing selected rows loses their exact weights and candidate metadata.
def test_satellite_export_retains_selected_candidate_records_and_real_csr_rows():
    candidates = candidate_array()
    coverage = coverage_rows()

    exported = export_satellite_data([2, 0], candidates, coverage)

    assert exported.shape == (2, 5)
    assert exported.dtype == object
    assert exported[0, 0] == [520.0, 0.5, 0.6]
    assert exported[0, 1] == [6]
    np.testing.assert_array_equal(
        exported[0, 2].toarray(), coverage.getrow(2).toarray()
    )
    assert exported[0, 3] == [[-1.6, 1.1], [-1.5, 1.2]]
    assert exported[0, 4] == 1
    assert exported[1, 0] == [500.0, 0.1, 0.2]
    assert exported[1, 1] == [4]
    np.testing.assert_array_equal(
        exported[1, 2].toarray(), coverage.getrow(0).toarray()
    )
    assert exported[1, 3] == [[-2.0, 0.7], [-1.9, 0.8]]


# Regression: preserving sparse candidate IDs exposes nonexistent physical satellite IDs.
def test_grid_mapping_remaps_selection_order_across_epochs_and_keeps_empty_cells():
    mapping = build_grid_satellites([2, 0], coverage_rows())

    assert set(mapping) == {0, 1}
    assert set(mapping[0]) == set(range(121))
    assert set(mapping[1]) == set(range(121))
    assert mapping[0][13] == [0]
    assert mapping[0][12] == [1]
    assert mapping[1][24] == [0]
    assert mapping[1][23] == [1]
    assert mapping[0][0] == []
    assert mapping[1][120] == []
    assert all(
        0 <= physical_id < 2
        for epoch in mapping.values()
        for physical_ids in epoch.values()
        for physical_id in physical_ids
    )


# Regression: duplicate sparse entries can append the same physical satellite more than once.
def test_grid_mapping_lists_unique_physical_ids_in_ascending_order():
    coverage = csr_matrix((2, 121), dtype=float)
    coverage.indices = np.asarray([12, 12, 12], dtype=np.int32)
    coverage.data = np.asarray([1.0, 2.0, 1.0])
    coverage.indptr = np.asarray([0, 2, 3], dtype=np.int32)

    mapping = build_grid_satellites([1, 0], coverage)

    assert mapping[0][12] == [0, 1]


# Regression: adding regional diagonals or one-way links changes the Canada workload.
def test_canada_traffic_contains_only_the_fourteen_directed_unit_entries():
    traffic = build_canada_traffic_matrix()
    expected_nonzero = {
        (12, 13),
        (13, 12),
        (13, 14),
        (14, 13),
        (23, 24),
        (24, 23),
        (24, 25),
        (25, 24),
        (12, 23),
        (23, 12),
        (13, 24),
        (24, 13),
        (14, 25),
        (25, 14),
    }

    assert traffic.shape == (121, 121)
    assert traffic.dtype == np.float64
    assert set(zip(*np.nonzero(traffic))) == expected_nonzero
    assert set(traffic[np.nonzero(traffic)]) == {1.0}
    assert traffic.sum() == 14.0


# Regression: an opaque checked-in demand can drift from the reproducible Canada literal.
def test_canada_demand_builder_and_checked_in_artifact_are_exact():
    expected_row = np.zeros(121, dtype=np.float64)
    expected_row[[12, 14, 23, 25]] = 6.0
    expected_row[[13, 24]] = 8.0

    demand = build_canada_backbone_demand(12)
    saved = np.load(FIXTURE_PATH)

    assert demand.shape == (12, 121)
    assert demand.dtype == np.float64
    np.testing.assert_array_equal(demand, np.tile(expected_row, (12, 1)))
    np.testing.assert_array_equal(saved, np.tile(expected_row, (12, 1)))


# Regression: alternate filenames or pickle-incompatible shapes break the orchestrator loader.
def test_saved_inputs_round_trip_with_orchestrator_field_access(tmp_path):
    paths = save_canada_parity_artifacts(
        tmp_path, [2, 0], candidate_array(), coverage_rows()
    )

    assert {path.name for path in paths} == {
        "canada_parity_satellite_data.npy",
        "canada_parity_grid_satellites.npy",
        "canada_parity_traffic_matrix.npy",
    }
    supply_data = np.load(
        tmp_path / "canada_parity_satellite_data.npy", allow_pickle=True
    )
    grid_satellites = np.load(
        tmp_path / "canada_parity_grid_satellites.npy", allow_pickle=True
    ).item()
    traffic_matrix = np.load(tmp_path / "canada_parity_traffic_matrix.npy")

    satellite_locations = {0: {}, 1: {}}
    satellite_params = {}
    for physical_id, data in enumerate(supply_data):
        parameters, phase, selected_coverage, positions, marker = data
        satellite_params[physical_id] = {
            "height": parameters[0],
            "inclination": parameters[1],
            "alpha0": parameters[2],
            "initial_slot": phase,
        }
        for epoch in range(2):
            satellite_locations[epoch][physical_id] = positions[epoch]
        assert selected_coverage.shape == (1, 242)
        assert marker == 1

    assert satellite_params[0]["height"] == 520.0
    assert satellite_params[1]["initial_slot"] == [4]
    assert satellite_locations[1][0] == [-1.5, 1.2]
    assert grid_satellites[1][23] == [1]
    assert traffic_matrix[12, 13] == 1.0


@pytest.mark.parametrize(
    ("selected", "message"),
    [
        ([0, 0], "selected candidate IDs must be unique"),
        ([3], "selected candidate ID 3 is out of range"),
        ([-1], "selected candidate ID -1 is out of range"),
    ],
)
def test_invalid_selected_candidate_ids_fail_clearly(selected, message):
    with pytest.raises(ValueError, match=message):
        export_satellite_data(selected, candidate_array(), coverage_rows())

    with pytest.raises(ValueError, match=message):
        build_grid_satellites(selected, coverage_rows())


# Regression: mismatched candidate/coverage counts can silently export the wrong row metadata.
def test_candidate_and_coverage_row_count_mismatch_fails_clearly():
    with pytest.raises(
        ValueError, match="candidate count must equal coverage row count"
    ):
        export_satellite_data([0], candidate_array()[:2], coverage_rows())


@pytest.mark.parametrize("column_count", [241, 243])
def test_coverage_width_not_divisible_by_global_grid_count_fails_clearly(column_count):
    coverage = csr_matrix((3, column_count), dtype=float)

    with pytest.raises(ValueError, match="coverage columns must be divisible by 121"):
        export_satellite_data([0], candidate_array(), coverage)

    with pytest.raises(ValueError, match="coverage columns must be divisible by 121"):
        build_grid_satellites([0], coverage)


# Regression: exporting a shorter position history makes downstream timestamp access fail late.
def test_candidate_position_count_mismatch_fails_clearly():
    candidates = candidate_array()
    candidates[1, 2] = np.asarray([[-1.8, 0.9]])

    with pytest.raises(ValueError, match=r"candidate 1 positions must have shape \(2, 2\)"):
        export_satellite_data([2], candidates, coverage_rows())


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([np.nan], "coverage entries must be finite"),
        ([np.inf], "coverage entries must be finite"),
        ([-1.0], "coverage entries must be nonnegative"),
    ],
)
def test_invalid_coverage_values_fail_clearly(data, message):
    coverage = csr_matrix((data, ([0], [12])), shape=(1, 121))

    with pytest.raises(ValueError, match=message):
        build_grid_satellites([0], coverage)


@pytest.mark.parametrize("bad_index", [-1, 121])
def test_coverage_entries_outside_declared_layout_fail_clearly(bad_index):
    coverage = csr_matrix(([1.0], ([0], [12])), shape=(1, 121))
    coverage.indices[0] = bad_index

    with pytest.raises(ValueError, match="coverage entry column is outside declared layout"):
        build_grid_satellites([0], coverage)
