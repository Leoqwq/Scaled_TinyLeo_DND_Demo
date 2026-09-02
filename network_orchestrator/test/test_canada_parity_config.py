import inspect
import importlib.util
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
from failure_recovery_mpc import MPCFaultHandler
from southbound import sn_utils
from southbound import sn_remote
from southbound.sn_controller import RemoteController, RemoteMachine


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


class CanadaParityRunbookTests(unittest.TestCase):
    def test_synthesis_summary_converts_numpy_epoch_ids_to_builtin_ints(self):
        runbook = (REPOSITORY_ROOT / "docs" / "canada-parity-runbook.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"window": [int(value) for value in config.epoch_indices]',
            runbook,
        )
        self.assertNotIn('"window": list(config.epoch_indices)', runbook)


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


class RuntimeAcknowledgementTests(unittest.TestCase):
    def test_fault_handler_uses_explicit_artifacts_and_source_epoch(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            topology = root / "runtime topology"
            (topology / "inter_topology").mkdir(parents=True)
            (topology / "intra_topology").mkdir()
            np.save(
                topology / "inter_topology" / "1.npy",
                np.asarray([], dtype=object),
                allow_pickle=True,
            )
            np.save(
                topology / "intra_topology" / "1.npy",
                {},
                allow_pickle=True,
            )
            satellite_file = root / "custom satellites.npy"
            satellites = np.empty((1, 5), dtype=object)
            satellites[0] = [
                [573.0, 1.0, 0.0],
                [0],
                None,
                [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]],
                1,
            ]
            np.save(satellite_file, satellites, allow_pickle=True)
            grid_file = root / "custom grid.npy"
            np.save(grid_file, {3: {23: [0]}}, allow_pickle=True)

            handler = MPCFaultHandler(
                topology_dir=topology,
                satellite_file=satellite_file,
                grid_satellites_file=grid_file,
                runtime_epoch=1,
                source_epoch=3,
            )

        self.assertEqual(handler.timestamp, 1)
        self.assertEqual(handler.source_epoch, 3)
        self.assertEqual(handler.satellite_locations[1][0], [3.0, 3.0])
        self.assertEqual(handler.grid_satellites, {23: [0]})

    def test_fault_handler_source_has_no_legacy_artifact_defaults(self):
        source = (PROJECT_ROOT / "failure_recovery_mpc.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("eval1_573_jinyao_24k_half.npy", source)
        self.assertNotIn("new_grid_satellites.npy", source)
        self.assertNotIn("test/tinyleo-Arbitrary-LeastDelay", source)

    def test_controller_passes_explicit_failure_artifact_mapping(self):
        controller = RemoteController.__new__(RemoteController)
        controller.local_dir = "/tmp/runtime topology"
        controller.satellite_file = "/tmp/custom satellites.npy"
        controller.grid_satellites_file = "/tmp/custom grid.npy"
        controller.start_epoch = 4
        controller.ts = 6

        with mock.patch(
            "southbound.sn_controller.MPCFaultHandler"
        ) as handler_type:
            handler_type.return_value.handle_link_failure.side_effect = RuntimeError(
                "stop after constructor"
            )
            with self.assertRaisesRegex(RuntimeError, "stop after constructor"):
                controller.handle_link_failure("SH1SAT1", "SH1SAT2")

        handler_type.assert_called_once_with(
            topology_dir=controller.local_dir,
            satellite_file=controller.satellite_file,
            grid_satellites_file=controller.grid_satellites_file,
            runtime_epoch=6,
            source_epoch=10,
        )

    def test_container_creation_passes_dynamic_controller_mount_source(self):
        calls = []

        class Pyctr:
            @staticmethod
            def container_run(
                base_dir, hostname, controller_source, venv_source
            ):
                calls.append(
                    (base_dir, hostname, controller_source, venv_source)
                )
                return 101 + len(calls)

        with tempfile.TemporaryDirectory(prefix="tinyleo workdir ") as tempdir:
            controller_source = Path(tempdir) / "controller"
            controller_source.mkdir()
            venv_source = Path(tempdir) / "venv with spaces"
            venv_source.mkdir()
            with (
                mock.patch.object(sn_remote, "pyctr", Pyctr, create=True),
                mock.patch.object(sn_remote, "machine_id", 0, create=True),
                mock.patch.object(sn_remote.subprocess, "check_call"),
                mock.patch.object(sn_remote, "sn_operate_every_node"),
            ):
                sn_remote.sn_init_nodes(
                    tempdir,
                    [{"SH1SAT1": 0}],
                    {"GS1": 0},
                    controller_source=str(controller_source),
                    venv_source=str(venv_source),
                )

        self.assertEqual(len(calls), 2)
        self.assertTrue(
            all(call[2] == str(controller_source) for call in calls)
        )
        self.assertTrue(all(call[3] == str(venv_source) for call in calls))
        pyctr_source = (
            PROJECT_ROOT / "southbound" / "pyctr.c"
        ).read_text(encoding="utf-8")
        self.assertNotIn("/root/tinyleo-Arbitrary-LeastDelay", pyctr_source)
        self.assertIn('"ssss:container_run', pyctr_source)
        self.assertIn('"%s/venv", resources_dst', pyctr_source)
        self.assertIn("mount(venv_src, venv_dst", pyctr_source)

    def test_remote_python_layout_resolves_configured_venv_for_target_root(self):
        machine = RemoteMachine.__new__(RemoteMachine)
        machine.ssh = object()
        machine.dir = "/root/experiment"
        machine.remote_python = "/tmp/venv with spaces/bin/python"
        response = {
            "executable": "/tmp/venv with spaces/bin/python",
            "prefix": "/tmp/venv with spaces",
            "base_prefix": "/usr",
        }

        with mock.patch(
            "southbound.sn_controller.sn_remote_wait_output",
            return_value="TINYLEO_PYTHON_LAYOUT=" + json.dumps(response),
        ) as run:
            machine._resolve_remote_python_layout()

        command = run.call_args.args[1]
        self.assertIn("'/tmp/venv with spaces/bin/python'", command)
        self.assertIn("'import json", command)
        self.assertEqual(machine.venv_source, "/tmp/venv with spaces")
        self.assertEqual(
            machine.container_python, "/resources/venv/bin/python"
        )
        self.assertEqual(
            machine.remote_python_source,
            "/tmp/venv with spaces/bin/python",
        )

    def test_remote_python_layout_allows_only_resolved_absolute_system_fallback(self):
        machine = RemoteMachine.__new__(RemoteMachine)
        machine.ssh = object()
        machine.dir = "/root/experiment"
        machine.remote_python = "python3"
        valid = {
            "executable": "/usr/bin/python3",
            "prefix": "/usr",
            "base_prefix": "/usr",
        }

        with mock.patch(
            "southbound.sn_controller.sn_remote_wait_output",
            return_value="TINYLEO_PYTHON_LAYOUT=" + json.dumps(valid),
        ):
            machine._resolve_remote_python_layout()

        self.assertEqual(machine.venv_source, "")
        self.assertEqual(machine.container_python, "/usr/bin/python3")

        invalid = {**valid, "executable": "python3"}
        with mock.patch(
            "southbound.sn_controller.sn_remote_wait_output",
            return_value="TINYLEO_PYTHON_LAYOUT=" + json.dumps(invalid),
        ):
            with self.assertRaisesRegex(RuntimeError, "layout is invalid"):
                machine._resolve_remote_python_layout()

    def test_pyctr_compile_uses_running_interpreter_without_shell_escaping(self):
        with (
            mock.patch.object(
                sn_remote.sysconfig,
                "get_config_var",
                return_value="-O2 -DTEST_VALUE='two words'",
            ),
            mock.patch.object(
                sn_remote.sysconfig,
                "get_paths",
                return_value={"include": "/tmp/python include"},
            ),
            mock.patch.object(sn_remote.subprocess, "check_call") as check_call,
        ):
            sn_remote._compile_pyctr("/tmp/tinyleo workdir")

        command = check_call.call_args.args[0]
        self.assertEqual(check_call.call_args.kwargs["cwd"], "/tmp/tinyleo workdir")
        self.assertIn("-I/tmp/python include", command)
        self.assertIn("-DTEST_VALUE=two words", command)
        self.assertNotIn("shell", check_call.call_args.kwargs)

    def test_remote_fault_uses_requested_real_link_and_returns_sdn_identity_ack(self):
        loaded = []
        acknowledgement = {
            "failed_link": ["SH1SAT1", "SH1SAT2"],
            "removed_satellite": "SH1SAT1",
            "replacement_satellite": "SH1SAT9",
            "updated_satellites": ["SH1SAT1", "SH1SAT9"],
        }

        def load_state(name):
            loaded.append(name)
            peer = "SH1SAT2" if name == "SH1SAT1" else "SH1SAT1"
            return {"isls": {peer: []}}

        with (
            mock.patch.object(sn_remote, "load_topo_from_shm", side_effect=load_state),
            mock.patch.object(sn_remote, "replace_shared_memory"),
            mock.patch.object(sn_remote, "sat_link_change"),
            mock.patch.object(sn_remote, "_failure_report", return_value=acknowledgement),
            mock.patch.object(sn_remote, "update_link_state"),
            mock.patch.object(sn_remote, "sn_update_network_muti"),
        ):
            actual = sn_remote.fault_test(
                "/tmp/work",
                6,
                [],
                {},
                [],
                200,
                0,
                96,
                0,
                "SH1SAT1",
                "SH1SAT2",
                remote_id=7,
            )

        self.assertEqual(loaded, ["SH1SAT1", "SH1SAT2"])
        self.assertEqual(actual["remote_id"], 7)
        self.assertNotIn("remote_id", acknowledgement)

    def test_remote_python_is_configured_and_reaches_remote_machine(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = _write_config(
                tempdir,
                _base_config(
                    remote_python="/tmp/tinyleo venv/bin/python",
                    failure_controller_endpoint="127.0.0.1:50051",
                ),
            )
            args = _load_config(config_path)
            self.assertEqual(args.remote_python, "/tmp/tinyleo venv/bin/python")
            self.assertEqual(
                args.failure_controller_endpoint, "127.0.0.1:50051"
            )

            with mock.patch.object(sys, "argv", ["test"]):
                controller = RemoteController(str(config_path), [], {})
            self.assertEqual(controller.remote_python, "/tmp/tinyleo venv/bin/python")
            self.assertEqual(
                controller.failure_controller_endpoint, "127.0.0.1:50051"
            )

    def test_ssh_nonzero_exit_is_never_silently_accepted(self):
        class Channel:
            def recv_exit_status(self):
                return 17

        class Stream:
            channel = Channel()

            def __init__(self, value):
                self.value = value

            def read(self):
                return self.value

            def __iter__(self):
                return iter(self.value.decode().splitlines(keepends=True))

        class SSH:
            def exec_command(self, command, **kwargs):
                return Stream(b""), Stream(b"partial output\n"), Stream(b"boom\n")

        with self.assertRaisesRegex(RuntimeError, "exit 17.*boom"):
            sn_utils.sn_remote_cmd(SSH(), "false")
        with self.assertRaisesRegex(RuntimeError, "exit 17"):
            sn_utils.sn_remote_wait_output(SSH(), "false")

    def test_remote_machine_commands_use_configured_python(self):
        commands = []
        machine = RemoteMachine.__new__(RemoteMachine)
        machine.id = 0
        machine.dir = "/root/experiment with spaces"
        machine.remote_python = "/tmp/venv with spaces/bin/python"
        machine.failure_controller_endpoint = "127.0.0.1:50051"
        machine.controller_source = "/root/experiment with spaces/controller"
        machine.venv_source = "/tmp/venv with spaces"
        machine.container_python = "/resources/venv/bin/python"
        machine.remote_python_source = "/tmp/venv with spaces/bin/python"
        machine.ssh = object()
        machine.local_dir = "/tmp/local"

        class SFTP:
            def get(self, remote, local):
                pass

        machine.sftp = SFTP()
        def run(_ssh, command):
            commands.append(command)
            if " fault_test " in command:
                return "TINYLEO_FAILURE_ACK=" + json.dumps(
                    {
                        "failed_link": ["SH1SAT1", "SH1SAT2"],
                        "removed_satellite": "SH1SAT1",
                        "replacement_satellite": "SH1SAT9",
                        "updated_satellites": ["SH1SAT1", "SH1SAT9"],
                        "remote_id": 0,
                    }
                )
            if "deploy_srv6_agent.py" in command:
                return "TINYLEO_SRV6_DEPLOY_ACK=" + json.dumps(
                    {
                        "remote_id": 0,
                        "expected_count": 1,
                        "started_count": 1,
                        "agents": [
                            {"name": "SH1SAT1", "namespace_pid": 101}
                        ],
                    }
                )
            return ""

        with mock.patch(
            "southbound.sn_controller.sn_remote_wait_output", side_effect=run
        ):
            machine.init_nodes()
            acknowledgement = machine.fault_test(
                6, 200, 0, 96, 0, ("SH1SAT1", "SH1SAT2")
            )
            deploy_acknowledgement = machine.deploy_tinyleo_srv6_agent()

        self.assertIn("'/tmp/venv with spaces/bin/python'", commands[0])
        self.assertIn("'/root/experiment with spaces/sn_remote.py'", commands[0])
        self.assertIn(
            "'/root/experiment with spaces/controller'", commands[0]
        )
        self.assertIn("'/tmp/venv with spaces'", commands[0])
        self.assertIn("127.0.0.1:50051", commands[1])
        self.assertEqual(acknowledgement["remote_id"], 0)
        deploy_command = commands[2]
        self.assertIn("--agent-source", deploy_command)
        self.assertIn(
            "'/root/experiment with spaces/controller/geographic_srv6_anycast/srv6_agent.py'",
            deploy_command,
        )
        self.assertIn("--agent-target /resources/controller/geographic_srv6_anycast/srv6_agent.py", deploy_command)
        self.assertIn("--python-executable /resources/venv/bin/python", deploy_command)
        self.assertIn(
            "--python-source '/tmp/venv with spaces/bin/python'", deploy_command
        )
        self.assertEqual(deploy_acknowledgement["remote_id"], 0)

    def test_remote_machine_rejects_fault_ack_without_remote_identity(self):
        machine = RemoteMachine.__new__(RemoteMachine)
        machine.id = 4
        machine.dir = "/tmp/work"
        machine.remote_python = "/tmp/venv/bin/python"
        machine.failure_controller_endpoint = "127.0.0.1:50051"
        machine.ssh = object()

        with mock.patch(
            "southbound.sn_controller.sn_remote_wait_output",
            return_value=(
                "TINYLEO_FAILURE_ACK="
                + json.dumps(
                    {
                        "failed_link": ["SH1SAT1", "SH1SAT2"],
                        "removed_satellite": "SH1SAT1",
                        "replacement_satellite": "SH1SAT9",
                        "updated_satellites": ["SH1SAT1", "SH1SAT9"],
                    }
                )
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "different remote"):
                machine.fault_test(6, 200, 0, 96, 0, ("SH1SAT1", "SH1SAT2"))

    def test_fault_target_is_deterministic_and_worker_ack_propagates(self):
        calls = []

        class Remote:
            id = 0

            def fault_test(self, *args):
                calls.append(args)
                failed_link = list(args[-1])
                return {
                    "failed_link": failed_link,
                    "removed_satellite": failed_link[0],
                    "replacement_satellite": "SH1SAT9",
                    "updated_satellites": [failed_link[0], "SH1SAT9"],
                    "remote_id": 0,
                }

        controller = RemoteController.__new__(RemoteController)
        controller.remote_lst = [Remote()]
        controller.nodes = {
            "SH1SAT1": controller.remote_lst[0],
            "SH1SAT2": controller.remote_lst[0],
            "SH1SAT3": controller.remote_lst[0],
        }
        controller.all_node_states = {
            "SH1SAT3": {"isls": {"SH1SAT2": []}},
            "SH1SAT1": {"isls": {"SH1SAT3": [], "SH1SAT2": []}},
            "SH1SAT2": {"isls": {"SH1SAT1": [], "SH1SAT3": []}},
        }
        controller.ts = 6
        controller.sat_bandwidth = 200
        controller.sat_loss = 0
        controller.sat_ground_bandwidth = 96
        controller.sat_ground_loss = 0

        first = controller.tinyleo_fault_test()
        second = controller.tinyleo_fault_test()

        self.assertEqual(first["failed_link"], ["SH1SAT1", "SH1SAT2"])
        self.assertEqual(second["failed_link"], first["failed_link"])
        self.assertEqual(tuple(calls[0][-1]), ("SH1SAT1", "SH1SAT2"))

    def test_fault_target_does_not_remove_a_ground_station_gateway(self):
        calls = []

        class Remote:
            id = 0

            def fault_test(self, *args):
                calls.append(args)
                failed_link = list(args[-1])
                return {
                    "failed_link": failed_link,
                    "removed_satellite": failed_link[0],
                    "replacement_satellite": "SH1SAT9",
                    "updated_satellites": [failed_link[0], "SH1SAT9"],
                    "remote_id": 0,
                }

        remote = Remote()
        controller = RemoteController.__new__(RemoteController)
        controller.remote_lst = [remote]
        controller.nodes = {
            "SH1SAT1": remote,
            "SH1SAT2": remote,
            "SH1SAT3": remote,
        }
        controller.all_node_states = {
            "SH1SAT1": {
                "gsls": {"GS6": ["ce::6", "00:00:00:00:00:06", 1.0]},
                "isls": {"SH1SAT2": []},
            },
            "SH1SAT2": {
                "gsls": {},
                "isls": {"SH1SAT1": [], "SH1SAT3": []},
            },
            "SH1SAT3": {"gsls": {}, "isls": {"SH1SAT2": []}},
        }
        controller.ts = 6
        controller.sat_bandwidth = 200
        controller.sat_loss = 0
        controller.sat_ground_bandwidth = 96
        controller.sat_ground_loss = 0

        acknowledgement = controller.tinyleo_fault_test()

        self.assertEqual(
            acknowledgement["failed_link"], ["SH1SAT2", "SH1SAT3"]
        )
        self.assertEqual(tuple(calls[0][-1]), ("SH1SAT2", "SH1SAT3"))

    def test_fault_and_srv6_worker_failures_propagate(self):
        class Remote:
            id = 0

            def fault_test(self, *args):
                raise RuntimeError("remote fault failed")

            def deploy_tinyleo_srv6_agent(self):
                raise RuntimeError("agent exited")

        controller = RemoteController.__new__(RemoteController)
        controller.remote_lst = [Remote()]
        controller.nodes = {"SH1SAT1": controller.remote_lst[0], "SH1SAT2": controller.remote_lst[0]}
        controller.all_node_states = {
            "SH1SAT1": {"isls": {"SH1SAT2": []}},
            "SH1SAT2": {"isls": {"SH1SAT1": []}},
        }
        controller.ts = 6
        controller.sat_bandwidth = 200
        controller.sat_loss = 0
        controller.sat_ground_bandwidth = 96
        controller.sat_ground_loss = 0

        with self.assertRaisesRegex(RuntimeError, "remote fault failed"):
            controller.tinyleo_fault_test()
        with self.assertRaisesRegex(RuntimeError, "agent exited"):
            controller.deploy_tinyleo_srv6_agent()

    def test_controller_rejects_duplicate_namespace_pid_in_remote_ack(self):
        class Remote:
            id = 0

            def deploy_tinyleo_srv6_agent(self):
                return {
                    "remote_id": 0,
                    "expected_count": 2,
                    "started_count": 2,
                    "agents": [
                        {"name": "SH1SAT1", "namespace_pid": 101},
                        {"name": "GS1", "namespace_pid": 101},
                    ],
                }

        controller = RemoteController.__new__(RemoteController)
        controller.remote_lst = [Remote()]

        with self.assertRaisesRegex(RuntimeError, "duplicate namespace PID"):
            controller.deploy_tinyleo_srv6_agent()

    def test_link_create_and_topology_update_worker_failures_propagate(self):
        class Remote:
            def init_network(self, *_args):
                raise RuntimeError("link creation failed")

            def update_network(self, *_args):
                raise RuntimeError("topology update failed")

        controller = RemoteController.__new__(RemoteController)
        controller.remote_lst = [Remote()]
        controller.sat_bandwidth = 200
        controller.sat_loss = 0
        controller.sat_ground_bandwidth = 96
        controller.sat_ground_loss = 0
        controller.ts = 3

        with self.assertRaisesRegex(RuntimeError, "link creation failed"):
            controller.create_links()
        with self.assertRaisesRegex(RuntimeError, "topology update failed"):
            controller.update_remote_topology()

    def test_remote_failure_recovery_process_error_prevents_acknowledgement(self):
        class Future:
            def result(self):
                raise RuntimeError("namespace link mutation failed")

        class Executor:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def submit(self, *_args):
                return Future()

        with tempfile.TemporaryDirectory() as tempdir:
            shell = Path(tempdir) / "shell0" / "isl"
            shell.mkdir(parents=True)
            (shell / "6.txt").write_text("SH1SAT1|SH1SAT2||\n", encoding="utf-8")
            with (
                mock.patch.object(sn_remote, "ProcessPoolExecutor", Executor),
                mock.patch.object(sn_remote, "machine_id", 0, create=True),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "namespace link mutation failed"
                ):
                    sn_remote.sn_update_network_muti(
                        tempdir,
                        6,
                        [{"SH1SAT1": 0, "SH1SAT2": 0}],
                        {},
                        ["127.0.0.1"],
                        200,
                        0,
                        96,
                        0,
                        failure=True,
                    )

    def test_srv6_deployer_uses_dynamic_workdir_and_checks_agent_liveness(self):
        module_path = (
            PROJECT_ROOT
            / "geographic_srv6_anycast"
            / "deploy_srv6_agent.py"
        )
        spec = importlib.util.spec_from_file_location("deploy_srv6_agent_test", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "container_pid.txt").write_text(
                "SH1SAT1:101 NA GS1:102\n", encoding="utf-8"
            )
            agent_path = (
                root
                / "controller"
                / "geographic_srv6_anycast"
                / "srv6_agent.py"
            )
            agent_path.parent.mkdir(parents=True)
            agent_path.write_text("# agent\n", encoding="utf-8")
            commands = []

            class Process:
                def __init__(self, command, **kwargs):
                    commands.append(command)

                def poll(self):
                    return None

            ack = module.deploy_agents(
                root,
                "/resources/venv/bin/python",
                remote_id=3,
                agent_source=agent_path,
                agent_target=(
                    "/resources/controller/geographic_srv6_anycast/srv6_agent.py"
                ),
                python_source=Path("/bin/sh"),
                process_factory=Process,
                sleeper=lambda _seconds: None,
            )

        self.assertEqual(ack["expected_count"], 2)
        self.assertEqual(ack["started_count"], 2)
        self.assertEqual(ack["remote_id"], 3)
        self.assertTrue(
            all(
                command
                == [
                    "nsenter",
                    "--mount",
                    "--uts",
                    "--ipc",
                    "--net",
                    "--pid",
                    "--target",
                    command[7],
                    f"--root=/proc/{command[7]}/root",
                    "/resources/venv/bin/python",
                    "/resources/controller/geographic_srv6_anycast/srv6_agent.py",
                ]
                for command in commands
            )
        )
        self.assertTrue(all("/root/tinyleo-Arbitrary-LeastDelay" not in " ".join(command) for command in commands))

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "container_pid.txt").write_text(
                "SH1SAT1:101 GS1:101\n", encoding="utf-8"
            )
            agent_path = root / "srv6_agent.py"
            agent_path.write_text("# agent\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate namespace PID"):
                module.deploy_agents(
                    root,
                    "/resources/venv/bin/python",
                    remote_id=0,
                    agent_source=agent_path,
                    agent_target="/resources/controller/srv6_agent.py",
                    python_source=Path("/bin/sh"),
                    process_factory=Process,
                    sleeper=lambda _seconds: None,
                )

        class ExitedProcess:
            def __init__(self, command, **kwargs):
                pass

            def poll(self):
                return 1

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "container_pid.txt").write_text("SH1SAT1:101\n", encoding="utf-8")
            agent_path = (
                root
                / "controller"
                / "geographic_srv6_anycast"
                / "srv6_agent.py"
            )
            agent_path.parent.mkdir(parents=True)
            agent_path.write_text("# agent\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exited during startup"):
                module.deploy_agents(
                    root,
                    "/tmp/runtime/bin/python",
                    remote_id=0,
                    python_source=Path("/bin/sh"),
                    process_factory=ExitedProcess,
                    sleeper=lambda _seconds: None,
                )

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "container_pid.txt").write_text("SH1SAT1:101\n", encoding="utf-8")
            with self.assertRaisesRegex(FileNotFoundError, "agent source"):
                module.deploy_agents(
                    root,
                    "/tmp/runtime/bin/python",
                    remote_id=0,
                    process_factory=Process,
                    sleeper=lambda _seconds: None,
                )


if __name__ == "__main__":
    unittest.main()
