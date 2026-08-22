import inspect
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

# The generated link-failure gRPC modules are deployment artifacts, not checked-in
# Python sources.  Keep these configuration tests offline by supplying only the
# import-time surface used by sn_utils.
fake_link_failure_pb2 = types.ModuleType("link_failure_grpc.link_failure_pb2")
fake_link_failure_pb2.LinkFailureResponse = object
fake_link_failure_pb2_grpc = types.ModuleType(
    "link_failure_grpc.link_failure_pb2_grpc"
)
fake_link_failure_pb2_grpc.LinkFailureServiceServicer = object
fake_link_failure_pb2_grpc.add_LinkFailureServiceServicer_to_server = (
    lambda *args, **kwargs: None
)
sys.modules.setdefault("link_failure_grpc.link_failure_pb2", fake_link_failure_pb2)
sys.modules.setdefault(
    "link_failure_grpc.link_failure_pb2_grpc", fake_link_failure_pb2_grpc
)

import sn_orchestrator_mpc
from southbound import sn_utils
from southbound.sn_controller import RemoteController


def _base_config(**overrides):
    config = {
        "Name": "test",
        "Satellite link": "Arbitrary",
        "Duration (s)": 5,
        'satellite link bandwidth ("X" Gbps)': 200,
        'sat-ground bandwidth ("X" Gbps)': 96,
        'satellite link loss ("X"% )': 0,
        'sat-ground loss ("X"% )': 0,
        "antenna number": 1,
        "antenna elevation angle": 25,
        "Link policy": "LeastDelay",
        "topo_dir": "data/topo_data/",
        "Machines": [],
    }
    config.update(overrides)
    return config


def _write_config(root, payload, filename="config.json"):
    path = Path(root) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _load_config(path):
    with mock.patch.object(sys, "argv", ["test"]):
        return sn_utils.sn_load_file(str(path))


def _write_epoch_artifacts(root, epochs=4):
    root = Path(root)
    satellite_file = root / "satellites.npy"
    traffic_file = root / "traffic.npy"
    grid_file = root / "grid.npy"
    block_file = root / "blocks.json"

    satellite_rows = np.empty((2, 5), dtype=object)
    for satellite_id in range(2):
        satellite_rows[satellite_id] = [
            [573.0, 1.2, 0.3],
            [satellite_id],
            None,
            [
                [epoch + 0.1 + satellite_id * 0.01, epoch + 0.2]
                for epoch in range(epochs)
            ],
            1,
        ]
    np.save(satellite_file, satellite_rows, allow_pickle=True)
    np.save(traffic_file, np.zeros((121, 121), dtype=np.float64))
    np.save(
        grid_file,
        {epoch: {23: [epoch % 2]} for epoch in range(epochs)},
        allow_pickle=True,
    )
    block_file.write_text("{}", encoding="utf-8")
    return satellite_file, traffic_file, grid_file, block_file


class _InlinePool:
    def __init__(self, processes):
        self.processes = processes

    def map(self, function, tasks):
        return [function(task) for task in tasks]

    def close(self):
        pass

    def join(self):
        pass


class CanadaParityConfigurationTests(unittest.TestCase):
    def test_explicit_artifact_paths_are_resolved_from_config_directory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_dir = Path(tempdir) / "configs"
            path = _write_config(
                config_dir,
                _base_config(
                    satellite_file="../artifacts/sat.npy",
                    traffic_matrix_file="../artifacts/traffic.npy",
                    grid_satellites_file="../artifacts/grid.npy",
                    block_positions_file="../artifacts/blocks.json",
                    start_epoch=7,
                    num_epochs=12,
                    topology_update_interval_s=20,
                    execution_mode="local",
                    enable_failure_recovery=False,
                    num_processes=4,
                ),
            )

            args = _load_config(path)

            artifact_dir = Path(tempdir) / "artifacts"
            self.assertEqual(args.satellite_file, str(artifact_dir / "sat.npy"))
            self.assertEqual(
                args.traffic_matrix_file, str(artifact_dir / "traffic.npy")
            )
            self.assertEqual(
                args.grid_satellites_file, str(artifact_dir / "grid.npy")
            )
            self.assertEqual(
                args.block_positions_file, str(artifact_dir / "blocks.json")
            )
            self.assertEqual(args.start_epoch, 7)
            self.assertEqual(args.num_epochs, 12)
            self.assertEqual(args.topology_update_interval_s, 20.0)
            self.assertEqual(args.execution_mode, "local")
            self.assertFalse(args.enable_failure_recovery)
            self.assertEqual(args.num_processes, 4)

    def test_missing_explicit_keys_keep_legacy_paths_and_defaults(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = _write_config(tempdir, _base_config())

            args = _load_config(path)

            self.assertEqual(
                args.satellite_file,
                "data/topo_data/eval1_573_jinyao_24k_half.npy",
            )
            self.assertEqual(
                args.traffic_matrix_file,
                "data/topo_data/traffic_matrix_max_24k_new.npy",
            )
            self.assertEqual(
                args.grid_satellites_file,
                "data/topo_data/new_grid_satellites.npy",
            )
            self.assertEqual(
                args.block_positions_file,
                "data/topo_data/block_positions.json",
            )
            self.assertEqual(args.start_epoch, 0)
            self.assertEqual(args.num_epochs, 5)
            self.assertEqual(args.duration, 5)
            self.assertEqual(args.topology_update_interval_s, 20.0)
            self.assertEqual(args.execution_mode, "remote")
            self.assertTrue(args.enable_failure_recovery)
            self.assertEqual(args.num_processes, 8)

    def test_num_epochs_is_distinct_from_update_interval_and_duration_fallback(self):
        with tempfile.TemporaryDirectory() as tempdir:
            explicit_path = _write_config(
                Path(tempdir) / "explicit",
                _base_config(
                    **{
                        "Duration (s)": 99,
                        "num_epochs": 12,
                        "topology_update_interval_s": 20,
                    }
                ),
            )
            fallback_path = _write_config(
                Path(tempdir) / "fallback", _base_config(**{"Duration (s)": 7})
            )

            explicit = _load_config(explicit_path)
            fallback = _load_config(fallback_path)

            self.assertEqual(explicit.num_epochs, 12)
            self.assertEqual(explicit.duration, 12)
            self.assertEqual(explicit.topology_update_interval_s, 20.0)
            self.assertEqual(fallback.num_epochs, 7)

    def test_parity_profile_rejects_more_than_six_workers(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = _write_config(
                tempdir,
                _base_config(Name="tinyleo_canada_parity", num_processes=7),
            )

            with self.assertRaisesRegex(ValueError, "at most 6"):
                _load_config(path)

    def test_existing_legacy_config_still_parses(self):
        path = PROJECT_ROOT / "test" / "config" / "tinyleo_config.json"

        args = _load_config(path)

        self.assertEqual(args.cons_name, "tinyleo")
        self.assertEqual(args.num_epochs, 5)
        self.assertEqual(args.machine_lst[0]["password"], "xxx")

    def test_canada_fixture_has_finite_horizon_local_key_configuration(self):
        path = PROJECT_ROOT / "test" / "config" / "tinyleo_canada_parity.json"
        self.assertTrue(path.is_file(), "Canada parity config fixture is missing")

        args = _load_config(path)

        self.assertEqual(args.start_epoch, 0)
        self.assertEqual(args.num_epochs, 12)
        self.assertEqual(args.topology_update_interval_s, 20.0)
        self.assertEqual(args.execution_mode, "local")
        self.assertTrue(args.enable_failure_recovery)
        self.assertEqual(args.num_processes, 6)
        self.assertEqual(args.machine_lst[0]["IP"], "127.0.0.1")
        self.assertEqual(args.machine_lst[0]["port"], 22)
        self.assertEqual(args.machine_lst[0]["key_filename"], "~/.ssh/id_ed25519")
        self.assertNotIn("password", args.machine_lst[0])

    def test_remaining_interval_uses_monotonic_elapsed_time_and_clamps_overrun(self):
        self.assertTrue(
            hasattr(sn_utils, "remaining_topology_interval"),
            "remaining_topology_interval helper is missing",
        )
        remaining = sn_utils.remaining_topology_interval

        self.assertEqual(remaining(20.0, 100.0, 107.25), 12.75)
        self.assertEqual(remaining(20.0, 100.0, 121.0), 0.0)


class EpochSliceTests(unittest.TestCase):
    def setUp(self):
        sn_orchestrator_mpc.GLOBAL_INTER_DOMAIN_TOPOLOGY_CACHE.clear()
        sn_orchestrator_mpc.GLOBAL_INTRA_DOMAIN_TOPOLOGY_CACHE.clear()

    def test_prediction_uses_continuous_source_slice_with_local_epoch_keys(self):
        signature = inspect.signature(sn_orchestrator_mpc.predict_all_topologies)
        self.assertIn("start_epoch", signature.parameters)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            satellite_file, traffic_file, grid_file, _ = _write_epoch_artifacts(root)
            output = root / "output"
            observed = []

            def first_timestamp(
                traffic,
                grid_satellites,
                satellite_params,
                satellite_locations,
                timestamp,
                num_satellites,
                pool,
            ):
                observed.append(
                    (
                        timestamp,
                        grid_satellites,
                        satellite_locations[timestamp][0],
                    )
                )
                return []

            def later_timestamp(
                traffic,
                grid_satellites,
                satellite_params,
                satellite_locations,
                timestamp,
                previous_topology,
                num_satellites,
                pool,
            ):
                return first_timestamp(
                    traffic,
                    grid_satellites,
                    satellite_params,
                    satellite_locations,
                    timestamp,
                    num_satellites,
                    pool,
                )

            with (
                mock.patch.object(sn_orchestrator_mpc, "Pool", _InlinePool),
                mock.patch.object(
                    sn_orchestrator_mpc,
                    "process_first_timestamp",
                    first_timestamp,
                ),
                mock.patch.object(
                    sn_orchestrator_mpc,
                    "process_timestamp_incremental",
                    later_timestamp,
                ),
                mock.patch.object(
                    sn_orchestrator_mpc,
                    "classify_satellites_to_grids",
                    return_value={},
                ),
                mock.patch.object(
                    sn_orchestrator_mpc,
                    "process_single_timestamp_topologies",
                    return_value={},
                ),
            ):
                sn_orchestrator_mpc.predict_all_topologies(
                    2,
                    str(satellite_file),
                    str(traffic_file),
                    str(grid_file),
                    result_output_dir=str(output),
                    num_processes=2,
                    start_epoch=1,
                )

            self.assertEqual([item[0] for item in observed], [0, 1])
            self.assertEqual(observed[0][1], {0: {23: [1]}})
            self.assertEqual(observed[1][1], {1: {23: [0]}})
            self.assertEqual(observed[0][2], [1.1, 1.2])
            self.assertEqual(observed[1][2], [2.1, 2.2])

            consolidated = json.loads(
                (output / "predict_isl_position_all.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(consolidated["timeslots"]), 2)
            self.assertAlmostEqual(
                consolidated["timeslots"][0]["position"][0]["longitude"],
                np.degrees(1.1),
            )
            self.assertAlmostEqual(
                consolidated["timeslots"][1]["position"][0]["longitude"],
                np.degrees(2.1),
            )

    def test_prediction_rejects_out_of_bounds_slice_before_creating_pool(self):
        signature = inspect.signature(sn_orchestrator_mpc.predict_all_topologies)
        self.assertIn("start_epoch", signature.parameters)

        with tempfile.TemporaryDirectory() as tempdir:
            satellite_file, traffic_file, grid_file, _ = _write_epoch_artifacts(
                tempdir, epochs=3
            )
            with mock.patch.object(sn_orchestrator_mpc, "Pool") as pool:
                with self.assertRaisesRegex(ValueError, "source epoch slice"):
                    sn_orchestrator_mpc.predict_all_topologies(
                        2,
                        str(satellite_file),
                        str(traffic_file),
                        str(grid_file),
                        num_processes=2,
                        start_epoch=2,
                    )
                pool.assert_not_called()

    def test_single_epoch_generation_reads_source_epoch_and_writes_local_filename(self):
        signature = inspect.signature(
            sn_orchestrator_mpc.generate_topology_for_timestamp
        )
        self.assertIn("start_epoch", signature.parameters)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            satellite_file, traffic_file, grid_file, block_file = (
                _write_epoch_artifacts(root)
            )
            output = root / "output"
            observed = {}

            def first_timestamp(
                traffic,
                grid_satellites,
                satellite_params,
                satellite_locations,
                timestamp,
                num_satellites,
                pool,
            ):
                observed["grid"] = grid_satellites
                observed["position"] = satellite_locations[timestamp][0]
                return []

            with (
                mock.patch.object(sn_orchestrator_mpc, "Pool", _InlinePool),
                mock.patch.object(
                    sn_orchestrator_mpc,
                    "process_first_timestamp",
                    first_timestamp,
                ),
                mock.patch.object(
                    sn_orchestrator_mpc,
                    "process_single_timestamp_topologies",
                    return_value={},
                ),
            ):
                sn_orchestrator_mpc.generate_topology_for_timestamp(
                    0,
                    str(satellite_file),
                    str(block_file),
                    str(traffic_file),
                    str(grid_file),
                    str(output),
                    2,
                    start_epoch=2,
                    num_epochs=1,
                )

            self.assertEqual(observed["grid"], {0: {23: [0]}})
            self.assertEqual(observed["position"], [2.1, 2.2])
            local_output = output / "all_isl_positions" / "0.json"
            self.assertTrue(local_output.is_file())
            timeslot = json.loads(local_output.read_text(encoding="utf-8"))
            self.assertAlmostEqual(
                timeslot["position"][0]["longitude"], np.degrees(2.1)
            )

    def test_generation_cache_isolated_by_artifacts_and_source_window(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "artifacts-a").mkdir()
            (root / "artifacts-b").mkdir()
            artifacts_a = _write_epoch_artifacts(root / "artifacts-a")
            artifacts_b = _write_epoch_artifacts(root / "artifacts-b")
            satellite_b = np.load(artifacts_b[0], allow_pickle=True)
            for row in satellite_b:
                row[3] = [
                    [position[0] + 10.0, position[1]] for position in row[3]
                ]
            np.save(artifacts_b[0], satellite_b, allow_pickle=True)
            observed = []

            def first_timestamp(
                traffic,
                grid_satellites,
                satellite_params,
                satellite_locations,
                timestamp,
                num_satellites,
                pool,
            ):
                observed.append(
                    (
                        satellite_locations[timestamp][0][0],
                        grid_satellites[timestamp][23],
                    )
                )
                return []

            with (
                mock.patch.object(sn_orchestrator_mpc, "Pool", _InlinePool),
                mock.patch.object(
                    sn_orchestrator_mpc,
                    "process_first_timestamp",
                    first_timestamp,
                ),
                mock.patch.object(
                    sn_orchestrator_mpc,
                    "process_single_timestamp_topologies",
                    return_value={},
                ),
            ):
                for artifacts, start_epoch, output_name in (
                    (artifacts_a, 0, "a-window-0"),
                    (artifacts_a, 1, "a-window-1"),
                    (artifacts_b, 1, "b-window-1"),
                ):
                    satellite, traffic, grid, blocks = artifacts
                    sn_orchestrator_mpc.generate_topology_for_timestamp(
                        0,
                        str(satellite),
                        str(blocks),
                        str(traffic),
                        str(grid),
                        str(root / output_name),
                        2,
                        start_epoch=start_epoch,
                        num_epochs=1,
                    )

            self.assertEqual(
                observed,
                [
                    (0.1, [0]),
                    (1.1, [1]),
                    (11.1, [1]),
                ],
            )

    def test_consolidated_serialization_reads_only_selected_source_slice(self):
        supply_data = np.empty((2, 5), dtype=object)
        supply_data[0] = [
            [573.0, 1.2, 0.3],
            [0],
            None,
            [[epoch * 0.1, 0.0] for epoch in range(5)],
            1,
        ]
        supply_data[1] = [
            [573.0, 1.2, 0.3],
            [1],
            None,
            [[1.0 + epoch * 0.1, 0.0] for epoch in range(3)],
            1,
        ]
        inter_topology = {0: [], 1: []}
        intra_topology = {0: {}, 1: {}}

        with tempfile.TemporaryDirectory() as tempdir:
            try:
                sn_orchestrator_mpc.create_all_isl_position_json(
                    supply_data,
                    inter_topology,
                    intra_topology,
                    tempdir,
                    start_epoch=1,
                )
            except IndexError as exc:
                self.fail(f"serializer read beyond selected source slice: {exc}")

            payload = json.loads(
                (Path(tempdir) / "predict_isl_position_all.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(len(payload["timeslots"]), 2)
        self.assertEqual(
            [
                [
                    timeslot["position"][satellite_id]["longitude"]
                    for satellite_id in range(2)
                ]
                for timeslot in payload["timeslots"]
            ],
            [
                [5.729577951308233, 63.02535746439056],
                [11.459155902616466, 68.75493541569878],
            ],
        )

    def test_consolidated_serialization_validates_selected_slice_per_satellite(self):
        supply_data = np.empty((2, 5), dtype=object)
        supply_data[0] = [
            [573.0, 1.2, 0.3],
            [0],
            None,
            [[epoch * 0.1, 0.0] for epoch in range(4)],
            1,
        ]
        supply_data[1] = [
            [573.0, 1.2, 0.3],
            [1],
            None,
            [[1.0 + epoch * 0.1, 0.0] for epoch in range(2)],
            1,
        ]

        with tempfile.TemporaryDirectory() as tempdir:
            with self.assertRaisesRegex(
                ValueError,
                "satellite 1.*selected source slice 1:3",
            ):
                sn_orchestrator_mpc.create_all_isl_position_json(
                    supply_data,
                    {0: [], 1: []},
                    {0: {}, 1: {}},
                    tempdir,
                    start_epoch=1,
                )


class ControllerPlumbingTests(unittest.TestCase):
    def test_controller_forwards_configured_paths_workers_and_epochs(self):
        signature = inspect.signature(RemoteController)
        self.assertIn("topology_predictor", signature.parameters)
        self.assertIn("topology_generator", signature.parameters)

        with tempfile.TemporaryDirectory() as tempdir:
            path = _write_config(
                tempdir,
                _base_config(
                    satellite_file="sat.npy",
                    traffic_matrix_file="traffic.npy",
                    grid_satellites_file="grid.npy",
                    block_positions_file="blocks.json",
                    start_epoch=2,
                    num_epochs=4,
                    num_processes=3,
                ),
            )
            calls = []

            def predictor(**kwargs):
                calls.append(("predict", kwargs))

            def generator(**kwargs):
                calls.append(("generate", kwargs))

            with mock.patch.object(sys, "argv", ["test"]):
                controller = RemoteController(
                    str(path),
                    [],
                    {},
                    topology_predictor=predictor,
                    topology_generator=generator,
                )

            controller._predict_topologies()
            controller._generate_topology_for_timestamp(3)

            artifact_dir = Path(tempdir)
            self.assertEqual(
                calls,
                [
                    (
                        "predict",
                        {
                            "duration": 4,
                            "satellite_file": str(artifact_dir / "sat.npy"),
                            "traffic_matrix_file": str(
                                artifact_dir / "traffic.npy"
                            ),
                            "grid_satellites_file": str(artifact_dir / "grid.npy"),
                            "result_output_dir": controller.local_dir,
                            "num_processes": 3,
                            "start_epoch": 2,
                        },
                    ),
                    (
                        "generate",
                        {
                            "timestamp": 3,
                            "satellite_file": str(artifact_dir / "sat.npy"),
                            "block_positions_file": str(
                                artifact_dir / "blocks.json"
                            ),
                            "traffic_matrix_file": str(
                                artifact_dir / "traffic.npy"
                            ),
                            "grid_satellites_file": str(artifact_dir / "grid.npy"),
                            "output_dir": controller.local_dir,
                            "num_processes": 3,
                            "start_epoch": 2,
                            "num_epochs": 4,
                        },
                    ),
                ],
            )

    def test_init_local_reads_configured_block_positions_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_dir = root / "config"
            legacy_topology_dir = root / "legacy-topology"
            configured_blocks = root / "configured-blocks.json"
            legacy_topology_dir.mkdir()
            configured_blocks.write_text(
                json.dumps({"source": "configured"}), encoding="utf-8"
            )
            (legacy_topology_dir / "block_positions.json").write_text(
                json.dumps({"source": "legacy"}), encoding="utf-8"
            )
            (config_dir / "geopraphic_routing_policy.json").parent.mkdir(
                parents=True, exist_ok=True
            )
            (config_dir / "geopraphic_routing_policy.json").write_text(
                "{}", encoding="utf-8"
            )
            config_path = _write_config(
                config_dir,
                _base_config(
                    topo_dir=str(legacy_topology_dir),
                    block_positions_file="../configured-blocks.json",
                ),
            )

            with mock.patch.object(sys, "argv", ["test"]):
                controller = RemoteController(str(config_path), [], {})
            controller.local_dir = str(root / "output")
            controller.shell_lst = []

            controller._init_local()

            self.assertEqual(controller.block_positions, {"source": "configured"})

    def test_local_machine_key_reaches_paramiko_without_a_password(self):
        remote_signature = inspect.signature(sn_utils.sn_connect_remote)
        self.assertIn("key_filename", remote_signature.parameters)

        fixture = PROJECT_ROOT / "test" / "config" / "tinyleo_canada_parity.json"
        self.assertTrue(fixture.is_file(), "Canada parity config fixture is missing")

        connect_calls = []

        class FakeStream:
            def __init__(self, value=b""):
                self.value = value

            def read(self):
                return self.value

        class FakeSFTP:
            def mkdir(self, path):
                pass

            def put(self, local_path, remote_path):
                pass

        class FakeSSH:
            def set_missing_host_key_policy(self, policy):
                pass

            def connect(self, **kwargs):
                connect_calls.append(kwargs)

            def open_sftp(self):
                return FakeSFTP()

            def exec_command(self, command, **kwargs):
                output = b"/tmp/tinyleo\n" if "echo ~/" in command else b""
                return FakeStream(), FakeStream(output), FakeStream()

        with tempfile.TemporaryDirectory() as tempdir:
            with (
                mock.patch.object(sys, "argv", ["test"]),
                mock.patch.object(sn_utils.paramiko, "SSHClient", FakeSSH),
            ):
                controller = RemoteController(str(fixture), [], {})
                controller.local_dir = tempdir
                controller.shell_lst = [{"name": "shell0"}]
                controller._assign_remote([["SH1SAT1"]], controller.machine_lst)

        self.assertEqual(
            connect_calls,
            [
                {
                    "hostname": "127.0.0.1",
                    "port": 22,
                    "username": "root",
                    "key_filename": os.path.expanduser("~/.ssh/id_ed25519"),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
