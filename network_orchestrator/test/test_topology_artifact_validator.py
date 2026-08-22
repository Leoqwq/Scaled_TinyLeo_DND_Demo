import csv
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from topology_artifact_validator import (
    ValidationConfig,
    _gateway_assignments,
    validate_artifact_bundle,
)


ACTIVE_GRIDS = (23, 24, 25)
GRID_ROWS = {23: [3, 2], 24: [3, 3], 25: [3, 4]}
GRID_NODES = {23: [0, 1], 24: [2, 3, 4, 5], 25: [6, 7]}
INTER_EDGES = [
    ((0, 2), (23, 24)),
    ((1, 3), (23, 24)),
    ((4, 6), (24, 25)),
    ((5, 7), (24, 25)),
]
INTRA_EDGES = {23: [(0, 1)], 24: [(2, 4), (3, 5)], 25: [(6, 7)]}


def _position(satellite_id, epoch):
    return [
        -2.1 + satellite_id * 0.01 + epoch * 0.001,
        0.8 + satellite_id * 0.005,
    ]


def _physical_edges(inter_edges=INTER_EDGES, intra_edges=INTRA_EDGES):
    return {
        tuple(sorted(edge))
        for edge, _ in inter_edges
    } | {
        tuple(sorted(edge))
        for edges in intra_edges.values()
        for edge in edges
    }


def write_valid_bundle(
    root: Path,
    epochs=2,
    inter_edges_by_epoch=None,
    satellite_count=8,
    intra_edges=INTRA_EDGES,
):
    satellite_file = root / "satellite_data.npy"
    grid_file = root / "grid_satellites.npy"
    traffic_file = root / "traffic_matrix.npy"
    block_file = root / "block_positions.json"
    topology_dir = root / "topology"

    satellite_rows = []
    for satellite_id in range(satellite_count):
        positions = [_position(satellite_id, epoch) for epoch in range(epochs)]
        satellite_rows.append(
            [[573.0, 1.2, 0.3], [satellite_id], None, positions, 1]
        )
    np.save(satellite_file, np.asarray(satellite_rows, dtype=object))

    grid_mapping = {
        epoch: {
            grid_id: list(nodes)
            for grid_id, nodes in GRID_NODES.items()
        }
        for epoch in range(epochs)
    }
    np.save(grid_file, grid_mapping)

    traffic = np.zeros((121, 121), dtype=np.float64)
    traffic[23, 24] = traffic[24, 23] = 1
    traffic[24, 25] = traffic[25, 24] = 1
    np.save(traffic_file, traffic)

    block_positions = {
        str(grid_id): {"lat_lon": [0, 0], "row_col": row_col}
        for grid_id, row_col in GRID_ROWS.items()
    }
    block_file.write_text(json.dumps(block_positions), encoding="utf-8")

    for dirname in (
        "inter_topology",
        "intra_topology",
        "sat_cells",
        "inter_cell_isls",
        "all_isl_positions",
    ):
        (topology_dir / dirname).mkdir(parents=True, exist_ok=True)

    consolidated = {"timeslots": []}
    for epoch in range(epochs):
        epoch_inter_edges = (
            inter_edges_by_epoch[epoch]
            if inter_edges_by_epoch is not None
            else INTER_EDGES
        )
        np.save(
            topology_dir / "inter_topology" / f"{epoch}.npy",
            np.asarray(epoch_inter_edges, dtype=object),
        )
        np.save(
            topology_dir / "intra_topology" / f"{epoch}.npy",
            intra_edges,
        )

        sat_cells = {}
        inter_cell_isls = {}
        for (left, right), (left_grid, right_grid) in epoch_inter_edges:
            left_name = f"SH1SAT{left + 1}"
            right_name = f"SH1SAT{right + 1}"
            sat_cells[left_name] = GRID_ROWS[left_grid]
            sat_cells[right_name] = GRID_ROWS[right_grid]
            inter_cell_isls[left_name] = {
                "near_sat": right_name,
                "near_cell": GRID_ROWS[right_grid],
            }
            inter_cell_isls[right_name] = {
                "near_sat": left_name,
                "near_cell": GRID_ROWS[left_grid],
            }

        (topology_dir / "sat_cells" / f"{epoch}.json").write_text(
            json.dumps(sat_cells), encoding="utf-8"
        )
        (topology_dir / "inter_cell_isls" / f"{epoch}.json").write_text(
            json.dumps(inter_cell_isls), encoding="utf-8"
        )

        timeslot = {
            "position": [
                {
                    "latitude": float(np.degrees(_position(sat, epoch)[1])),
                    "longitude": float(np.degrees(_position(sat, epoch)[0])),
                    "altitude": 573.0,
                }
                for sat in range(satellite_count)
            ],
            "links": [
                {"sat1": left, "sat2": right}
                for left, right in sorted(
                    _physical_edges(epoch_inter_edges, intra_edges)
                )
            ],
        }
        (topology_dir / "all_isl_positions" / f"{epoch}.json").write_text(
            json.dumps(timeslot), encoding="utf-8"
        )
        consolidated["timeslots"].append(timeslot)

    (topology_dir / "predict_isl_position_all.json").write_text(
        json.dumps(consolidated), encoding="utf-8"
    )

    return ValidationConfig(
        satellite_file=satellite_file,
        grid_satellites_file=grid_file,
        traffic_matrix_file=traffic_file,
        block_positions_file=block_file,
        topology_dir=topology_dir,
        expected_epochs=epochs,
        active_grids=ACTIVE_GRIDS,
        min_satellites=1,
        max_satellites=128,
        min_edge_disjoint_paths=2,
        min_path_epoch_ratio=1.0,
        source_grid=23,
        destination_grid=25,
    )


class TopologyArtifactValidatorTests(unittest.TestCase):
    def test_component_gate_uses_only_satellites_participating_in_links(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir), satellite_count=99)

            report = validate_artifact_bundle(config)

            self.assertTrue(report.valid, report.errors)
            for epoch in report.epochs:
                self.assertEqual(epoch.participating_satellite_count, 8)
                self.assertEqual(epoch.largest_component_ratio, 1.0)
                self.assertAlmostEqual(
                    epoch.constellation_largest_component_ratio,
                    8 / 99,
                )

    def test_component_gate_still_rejects_disconnected_participating_topology(self):
        disconnected_inter = [
            ((0, 2), (23, 24)),
            ((4, 6), (24, 25)),
        ]
        disconnected_intra = {
            23: [(0, 1)],
            24: [(2, 3)],
            25: [(6, 7)],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            config = replace(
                write_valid_bundle(
                    Path(tempdir),
                    inter_edges_by_epoch=[disconnected_inter, disconnected_inter],
                    intra_edges=disconnected_intra,
                ),
                min_edge_disjoint_paths=0,
            )

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(
                    error.code == "insufficient_connected_component"
                    for error in report.errors
                )
            )

    def test_valid_bundle_passes_schema_consistency_and_path_checks(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))

            report = validate_artifact_bundle(config)

            self.assertTrue(report.valid, report.errors)
            self.assertEqual(report.satellite_count, 8)
            self.assertEqual(len(report.epochs), 2)
            self.assertTrue(
                all(epoch.edge_disjoint_paths == 2 for epoch in report.epochs)
            )
            self.assertTrue(all(epoch.average_degree == 2.0 for epoch in report.epochs))
            self.assertTrue(all(epoch.min_degree == 2 for epoch in report.epochs))
            self.assertTrue(all(epoch.max_degree == 2 for epoch in report.epochs))

    def test_out_of_range_topology_endpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = write_valid_bundle(root)
            bad_edges = list(INTER_EDGES) + [((0, 99), (23, 24))]
            np.save(
                config.topology_dir / "inter_topology" / "0.npy",
                np.asarray(bad_edges, dtype=object),
            )

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(error.code == "invalid_satellite_id" for error in report.errors)
            )

    def test_json_and_npy_link_set_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = write_valid_bundle(root)
            json_path = config.topology_dir / "all_isl_positions" / "0.json"
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            payload["links"].pop()
            json_path.write_text(json.dumps(payload), encoding="utf-8")

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(error.code == "link_set_mismatch" for error in report.errors)
            )

    def test_empty_inter_cell_json_is_rejected_when_npy_has_gateway_links(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))
            (config.topology_dir / "inter_cell_isls" / "0.json").write_text(
                "{}", encoding="utf-8"
            )

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(
                    error.code == "inter_cell_link_set_mismatch"
                    for error in report.errors
                )
            )

    def test_virtual_node_names_written_by_producer_are_accepted(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))
            virtual_edges = [((8, 2), (23, 24)), *INTER_EDGES[1:]]
            np.save(
                config.topology_dir / "inter_topology" / "0.npy",
                np.asarray(virtual_edges, dtype=object),
            )
            mapping = np.load(config.grid_satellites_file, allow_pickle=True).item()
            mapping[0][23] = [8, 1]
            np.save(config.grid_satellites_file, mapping)

            cells_path = config.topology_dir / "sat_cells" / "0.json"
            cells = json.loads(cells_path.read_text(encoding="utf-8"))
            cells["SH1SAT9"] = cells.pop("SH1SAT1")
            cells_path.write_text(json.dumps(cells), encoding="utf-8")

            relations_path = config.topology_dir / "inter_cell_isls" / "0.json"
            relations = json.loads(relations_path.read_text(encoding="utf-8"))
            relations["SH1SAT9"] = relations.pop("SH1SAT1")
            relations["SH1SAT3"]["near_sat"] = "SH1SAT9"
            relations_path.write_text(json.dumps(relations), encoding="utf-8")

            report = validate_artifact_bundle(config)

            self.assertTrue(report.valid, report.errors)

    def test_inter_endpoint_must_belong_to_its_declared_grid(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))
            bad_edges = [((0, 2), (25, 24)), *INTER_EDGES[1:]]
            np.save(
                config.topology_dir / "inter_topology" / "0.npy",
                np.asarray(bad_edges, dtype=object),
            )

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(error.code == "endpoint_grid_mismatch" for error in report.errors)
            )

    def test_short_satellite_history_is_reported_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))
            satellites = np.load(config.satellite_file, allow_pickle=True)
            satellites[0][3] = satellites[0][3][:-1]
            np.save(config.satellite_file, satellites)

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(
                    error.code == "satellite_epoch_count_mismatch"
                    for error in report.errors
                )
            )

    def test_non_sequence_satellite_history_is_reported_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))
            satellites = np.load(config.satellite_file, allow_pickle=True)
            satellites[0][3] = None
            np.save(config.satellite_file, satellites)

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(error.code == "invalid_satellite_row" for error in report.errors)
            )

    def test_non_object_consolidated_json_is_reported_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))
            (config.topology_dir / "predict_isl_position_all.json").write_text(
                "[]", encoding="utf-8"
            )

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(error.code == "invalid_consolidated_topology" for error in report.errors)
            )

    def test_gateway_assignment_identity_includes_grid_pair(self):
        before = _gateway_assignments([((0, 2), (23, 24))], 8)
        after = _gateway_assignments([((0, 2), (12, 24))], 8)

        self.assertNotEqual(before, after)

    def test_malformed_json_position_is_reported_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))
            json_path = config.topology_dir / "all_isl_positions" / "0.json"
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            payload["position"][0]["latitude"] = "not-a-number"
            json_path.write_text(json.dumps(payload), encoding="utf-8")

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(error.code == "invalid_json_position" for error in report.errors)
            )

    def test_out_of_range_grid_mapping_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = write_valid_bundle(root)
            mapping = np.load(config.grid_satellites_file, allow_pickle=True).item()
            mapping[0][23] = [99]
            np.save(config.grid_satellites_file, mapping)

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(error.code == "invalid_satellite_id" for error in report.errors)
            )

    def test_non_finite_satellite_position_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = write_valid_bundle(root)
            satellites = np.load(config.satellite_file, allow_pickle=True)
            satellites[0][3][0][0] = float("nan")
            np.save(config.satellite_file, satellites)

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(any(error.code == "invalid_position" for error in report.errors))

    def test_malformed_satellite_position_is_reported_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(Path(tempdir))
            satellites = np.load(config.satellite_file, allow_pickle=True)
            satellites[0][3][0] = ["bad-longitude", 0.8]
            np.save(config.satellite_file, satellites)

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(any(error.code == "invalid_position" for error in report.errors))

    def test_link_changes_are_reported_as_topology_changes_and_handovers(self):
        changed_inter_edges = [
            ((0, 3), (23, 24)),
            ((1, 2), (23, 24)),
            ((4, 7), (24, 25)),
            ((5, 6), (24, 25)),
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            config = write_valid_bundle(
                Path(tempdir),
                inter_edges_by_epoch=[INTER_EDGES, changed_inter_edges],
            )

            report = validate_artifact_bundle(config)

            self.assertTrue(report.valid, report.errors)
            self.assertEqual(report.topology_change_count, 1)
            self.assertEqual(report.gateway_handover_count, 4)
            self.assertEqual(report.epochs[1].added_links, 4)
            self.assertEqual(report.epochs[1].removed_links, 4)

    def test_topology_change_and_handover_quality_gates_fail_static_bundle(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = replace(
                write_valid_bundle(Path(tempdir)),
                min_topology_changes=1,
                min_gateway_handovers=1,
            )

            report = validate_artifact_bundle(config)

            self.assertFalse(report.valid)
            self.assertTrue(
                any(error.code == "insufficient_topology_changes" for error in report.errors)
            )
            self.assertTrue(
                any(error.code == "insufficient_gateway_handovers" for error in report.errors)
            )

    def test_cli_writes_machine_and_human_readable_reports(self):
        from network_orchestrator.test.validate_topology_artifacts import main

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config = write_valid_bundle(root)
            output_dir = root / "validation"

            exit_code = main(
                [
                    "--satellite-file",
                    str(config.satellite_file),
                    "--grid-satellites-file",
                    str(config.grid_satellites_file),
                    "--traffic-matrix-file",
                    str(config.traffic_matrix_file),
                    "--block-positions-file",
                    str(config.block_positions_file),
                    "--topology-dir",
                    str(config.topology_dir),
                    "--output-dir",
                    str(output_dir),
                    "--expected-epochs",
                    "2",
                    "--active-grids",
                    "23,24,25",
                    "--min-satellites",
                    "1",
                    "--min-path-epoch-ratio",
                    "1.0",
                ]
            )

            self.assertEqual(exit_code, 0)
            report = json.loads(
                (output_dir / "validation_report.json").read_text(encoding="utf-8")
            )
            self.assertTrue(report["valid"])
            with (output_dir / "epoch_metrics.csv").open(
                newline="", encoding="utf-8"
            ) as metrics_file:
                rows = list(csv.DictReader(metrics_file))
            self.assertEqual([row["epoch"] for row in rows], ["0", "1"])
            self.assertEqual([row["average_degree"] for row in rows], ["2.0", "2.0"])
            self.assertEqual(
                [row["participating_satellite_count"] for row in rows],
                ["8", "8"],
            )
            self.assertEqual(
                [row["largest_component_ratio"] for row in rows],
                ["1.0", "1.0"],
            )
            self.assertEqual(
                [row["constellation_largest_component_ratio"] for row in rows],
                ["1.0", "1.0"],
            )
            self.assertTrue((output_dir / "topology_churn.csv").is_file())
            summary = (output_dir / "validation_summary.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("PASS", summary)


if __name__ == "__main__":
    unittest.main()
