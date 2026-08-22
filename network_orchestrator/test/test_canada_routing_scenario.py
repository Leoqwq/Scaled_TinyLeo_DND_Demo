import csv
import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
SCENARIO_PATH = Path(__file__).with_name("example_canada_parity.py")
SOUTH_POLICY_PATH = Path(__file__).parent / "config" / (
    "geographic_routing_policy_canada_south.json"
)
NORTH_POLICY_PATH = Path(__file__).parent / "config" / (
    "geographic_routing_policy_canada_north.json"
)


def _load_scenario_module(module_name="example_canada_parity_for_test"):
    assert SCENARIO_PATH.is_file(), "Canada parity scenario runner is missing"
    spec = importlib.util.spec_from_file_location(module_name, SCENARIO_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_scenario_inputs(root: Path, epochs=12):
    root.mkdir(parents=True, exist_ok=True)
    block_positions = {
        str(grid_id): {"row_col": row_col, "lat_lon": [0, 0]}
        for grid_id, row_col in {
            12: [2, 2],
            13: [2, 3],
            14: [2, 4],
            23: [3, 2],
            24: [3, 3],
            25: [3, 4],
        }.items()
    }
    block_path = root / "block_positions.json"
    block_path.write_text(json.dumps(block_positions), encoding="utf-8")

    demand = np.zeros((epochs, 121), dtype=np.float64)
    demand[:, [12, 14, 23, 25]] = 6.0
    demand[:, [13, 24]] = 8.0
    demand_path = root / "canada_parity_backbone_demand.npy"
    np.save(demand_path, demand)

    traffic = np.zeros((121, 121), dtype=np.float64)
    for left, right in (
        (12, 13),
        (13, 14),
        (23, 24),
        (24, 25),
        (12, 23),
        (13, 24),
        (14, 25),
    ):
        traffic[left, right] = traffic[right, left] = 1.0
    traffic_path = root / "canada_parity_traffic_matrix.npy"
    np.save(traffic_path, traffic)

    south_path = root / "south.json"
    south_path.write_text(
        json.dumps({"[3, 2]->[3, 4]": [[3, 3]]}), encoding="utf-8"
    )
    north_path = root / "north.json"
    north_path.write_text(
        json.dumps({"[3, 2]->[3, 4]": [[2, 2], [2, 3], [2, 4]]}),
        encoding="utf-8",
    )

    config_path = root / "tinyleo_canada_parity.json"
    config_path.write_text(
        json.dumps(
            {
                "num_epochs": epochs,
                "traffic_matrix_file": traffic_path.name,
                "block_positions_file": block_path.name,
            }
        ),
        encoding="utf-8",
    )
    report = {
        "valid": True,
        "satellite_count": 80,
        "expected_epochs": epochs,
        "path_epoch_ratio": 1.0,
        "epochs": [
            {"epoch": epoch, "edge_disjoint_paths": 2}
            for epoch in range(epochs)
        ],
    }
    return {
        "block_positions": block_positions,
        "demand": demand,
        "demand_path": demand_path,
        "traffic": traffic,
        "traffic_path": traffic_path,
        "south_path": south_path,
        "north_path": north_path,
        "config_path": config_path,
        "report": report,
    }


class FakeController:
    def __init__(
        self,
        local_dir: Path,
        num_epochs=12,
        write_measurements=True,
        raise_on=None,
    ):
        self.local_dir = str(local_dir)
        self.num_epochs = num_epochs
        self.topology_update_interval_s = 20.0
        self.enable_failure_recovery = True
        self.write_measurements = write_measurements
        self.raise_on = raise_on
        self.raised_exception = None
        self.calls = []

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if self.raise_on == name:
            self.raised_exception = RuntimeError(f"{name} failed")
            raise self.raised_exception

    def init_remote_machine(self):
        self._call("init")

    def create_nodes(self):
        self._call("create_nodes")

    def create_links(self):
        self._call("create_links")

    def start_link_faliure_server(self):
        self._call("start_failure_server")

    def update_tinyleo_topology(self, epoch):
        self._call("update", epoch)

    def deploy_tinyleo_srv6_agent(self):
        self._call("deploy")
        return {
            "remote_acknowledgements": [
                {
                    "remote_id": 0,
                    "expected_count": 86,
                    "started_count": 86,
                    "agents": [
                        {"name": f"node-{index}", "namespace_pid": 1000 + index}
                        for index in range(86)
                    ],
                }
            ]
        }

    def tinyleo_fault_test(self):
        self._call("failure")
        return {
            "failed_link": ["SH1SAT10", "SH1SAT11"],
            "removed_satellite": "SH1SAT10",
            "replacement_satellite": "SH1SAT12",
            "updated_satellites": ["SH1SAT10", "SH1SAT12"],
            "remote_id": 0,
        }

    def _measure(self, kind, source, destination, filename):
        self._call(kind, source, destination, filename)
        if self.write_measurements:
            output = Path(self.local_dir) / "result" / f"{kind}-{filename}.txt"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                f"real fake-boundary {kind} output {source}->{destination}\n",
                encoding="utf-8",
            )

    def set_ping(self, source, destination, filename):
        self._measure("ping", source, destination, filename)

    def set_traceroute(self, source, destination, filename):
        self._measure("traceroute", source, destination, filename)

    def set_iperf(self, source, destination, filename):
        self._measure("iperf", source, destination, filename)

    def clean(self):
        self.calls.append(("clean",))


class IncrementingClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        self.value += 0.125
        return self.value


def test_async_measurement_worker_failure_propagates(tmp_path):
    module = _load_scenario_module("example_canada_parity_async_failure_test")
    (tmp_path / "controller" / "result").mkdir(parents=True)
    (tmp_path / "results").mkdir()

    class FailedHandle:
        def result(self):
            raise RuntimeError("remote ping exited nonzero")

    class Controller:
        local_dir = str(tmp_path / "controller")

        def set_ping(self, *_args):
            return FailedHandle()

        def set_traceroute(self, *_args):
            return None

        def set_iperf(self, *_args):
            return None

    _measurements, error = module._collect_measurements(
        Controller(),
        0,
        tmp_path / "results",
        lambda _seconds: None,
        0,
    )

    assert isinstance(error, RuntimeError)
    assert str(error) == "remote ping exited nonzero"


def _resource_sample(_epoch):
    return {
        "process_rss_bytes": 1234,
        "system_memory_total_bytes": 10000,
        "system_memory_available_bytes": 7000,
        "system_memory_used_bytes": 3000,
        "system_memory_percent": 30.0,
        "swap_total_bytes": 2000,
        "swap_used_bytes": 100,
        "swap_free_bytes": 1900,
        "swap_percent": 5.0,
    }


def _run(module, inputs, controller, result_dir, **overrides):
    factory_calls = []

    def controller_factory(config_path, coordinates, cells):
        factory_calls.append((Path(config_path), coordinates, cells))
        return controller

    kwargs = {
        "configuration_file_path": inputs["config_path"],
        "south_policy_path": inputs["south_path"],
        "north_policy_path": inputs["north_path"],
        "backbone_demand_path": inputs["demand_path"],
        "validation_report": inputs["report"],
        "result_dir": result_dir,
        "controller_factory": controller_factory,
        "sleep": lambda _seconds: None,
        "monotonic": IncrementingClock(),
        "resource_sampler": _resource_sample,
        "measurement_wait_s": 0,
    }
    kwargs.update(overrides)
    module.run_canada_parity(**kwargs)
    return factory_calls


def test_fixed_station_policy_and_workload_inputs_are_exact_and_supported(tmp_path):
    module = _load_scenario_module()
    inputs = _write_scenario_inputs(tmp_path)

    assert module.GS_NAMES == (
        "GS1",
        "GS2",
        "GS3",
        "GS4",
        "GS5",
        "GS6",
    )
    assert module.GS_LAT_LONG == [
        [60.7212, -135.0568],
        [62.4540, -114.3718],
        [63.7467, -68.5170],
        [49.2827, -123.1207],
        [51.0447, -114.0719],
        [43.6532, -79.3832],
    ]
    assert module.GS_CELL == [[2, 2], [2, 3], [2, 4], [3, 2], [3, 3], [3, 4]]
    assert json.loads(SOUTH_POLICY_PATH.read_text(encoding="utf-8")) == {
        "[3, 2]->[3, 4]": [[3, 3]]
    }
    assert json.loads(NORTH_POLICY_PATH.read_text(encoding="utf-8")) == {
        "[3, 2]->[3, 4]": [[2, 2], [2, 3], [2, 4]]
    }

    validated = module.validate_scenario_inputs(
        module.GS_LAT_LONG,
        module.GS_CELL,
        json.loads(inputs["south_path"].read_text(encoding="utf-8")),
        json.loads(inputs["north_path"].read_text(encoding="utf-8")),
        inputs["block_positions"],
        inputs["demand"],
        inputs["traffic"],
        inputs["report"],
        configured_num_epochs=12,
    )

    assert validated["active_grid_ids"] == (12, 13, 14, 23, 24, 25)
    assert validated["traffic_edges"] == (
        (23, 24),
        (24, 25),
        (12, 23),
        (12, 13),
        (13, 14),
        (14, 25),
    )


def test_scenario_validation_rejects_nonadjacent_policy_step(tmp_path):
    module = _load_scenario_module("example_canada_parity_bad_route")
    inputs = _write_scenario_inputs(tmp_path)
    bad_north = {"[3, 2]->[3, 4]": [[2, 2], [2, 4]]}

    with pytest.raises(ValueError, match="adjacent"):
        module.validate_scenario_inputs(
            module.GS_LAT_LONG,
            module.GS_CELL,
            json.loads(inputs["south_path"].read_text(encoding="utf-8")),
            bad_north,
            inputs["block_positions"],
            inputs["demand"],
            inputs["traffic"],
            inputs["report"],
            configured_num_epochs=12,
        )


@pytest.mark.parametrize("missing_support", ["demand", "traffic", "grid_mapping"])
def test_scenario_validation_rejects_missing_grid_or_workload_support(
    tmp_path, missing_support
):
    module = _load_scenario_module(f"example_canada_parity_{missing_support}")
    inputs = _write_scenario_inputs(tmp_path)
    blocks = json.loads(json.dumps(inputs["block_positions"]))
    demand = inputs["demand"].copy()
    traffic = inputs["traffic"].copy()
    if missing_support == "demand":
        demand[:, 13] = 0
    elif missing_support == "traffic":
        traffic[12, 13] = traffic[13, 12] = 0
    else:
        blocks["13"]["row_col"] = [9, 9]

    with pytest.raises(ValueError, match=missing_support.replace("_", " ")):
        module.validate_scenario_inputs(
            module.GS_LAT_LONG,
            module.GS_CELL,
            json.loads(inputs["south_path"].read_text(encoding="utf-8")),
            json.loads(inputs["north_path"].read_text(encoding="utf-8")),
            blocks,
            demand,
            traffic,
            inputs["report"],
            configured_num_epochs=12,
        )


def test_path_diversity_rejects_low_reported_or_observed_ratio():
    module = _load_scenario_module("example_canada_parity_diversity")

    with pytest.raises(ValueError, match="path_epoch_ratio"):
        module.validate_path_diversity(
            {
                "path_epoch_ratio": 0.79,
                "expected_epochs": 1,
                "epochs": [{"epoch": 0, "edge_disjoint_paths": 2}],
            },
            required_epochs=1,
        )

    with pytest.raises(ValueError, match="edge-disjoint"):
        module.validate_path_diversity(
            {
                "path_epoch_ratio": 0.8,
                "expected_epochs": 5,
                "epochs": [
                    {"epoch": 0, "edge_disjoint_paths": 2},
                    {"epoch": 1, "edge_disjoint_paths": 2},
                    {"epoch": 2, "edge_disjoint_paths": 2},
                    {"epoch": 3, "edge_disjoint_paths": 1},
                    {"epoch": 4, "edge_disjoint_paths": 1},
                ],
            },
            required_epochs=5,
        )


def test_scenario_gate_rejects_report_epoch_count_different_from_config(tmp_path):
    module = _load_scenario_module("example_canada_parity_report_count")
    inputs = _write_scenario_inputs(tmp_path, epochs=12)
    one_epoch_report = {
        "valid": True,
        "expected_epochs": 1,
        "path_epoch_ratio": 1.0,
        "epochs": [{"epoch": 0, "edge_disjoint_paths": 2}],
    }

    with pytest.raises(ValueError, match="expected_epochs.*configured"):
        module.validate_scenario_inputs(
            module.GS_LAT_LONG,
            module.GS_CELL,
            json.loads(inputs["south_path"].read_text(encoding="utf-8")),
            json.loads(inputs["north_path"].read_text(encoding="utf-8")),
            inputs["block_positions"],
            inputs["demand"],
            inputs["traffic"],
            one_epoch_report,
            configured_num_epochs=12,
        )


def test_scenario_gate_rejects_demand_rows_different_from_config(tmp_path):
    module = _load_scenario_module("example_canada_parity_demand_count")
    inputs = _write_scenario_inputs(tmp_path, epochs=12)

    with pytest.raises(ValueError, match="demand rows.*configured"):
        module.validate_scenario_inputs(
            module.GS_LAT_LONG,
            module.GS_CELL,
            json.loads(inputs["south_path"].read_text(encoding="utf-8")),
            json.loads(inputs["north_path"].read_text(encoding="utf-8")),
            inputs["block_positions"],
            inputs["demand"][:1],
            inputs["traffic"],
            inputs["report"],
            configured_num_epochs=12,
        )


def test_path_diversity_rejects_duplicate_or_missing_epoch_ids():
    module = _load_scenario_module("example_canada_parity_epoch_ids")
    report = {
        "valid": True,
        "expected_epochs": 12,
        "path_epoch_ratio": 1.0,
        "epochs": [
            {"epoch": epoch if epoch < 11 else 0, "edge_disjoint_paths": 2}
            for epoch in range(12)
        ],
    }

    with pytest.raises(ValueError, match="unique.*0.*11"):
        module.validate_path_diversity(report, required_epochs=12)


def test_runner_rejects_controller_epoch_count_different_from_config(tmp_path):
    module = _load_scenario_module("example_canada_parity_controller_count")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=12)
    controller = FakeController(tmp_path / "controller", num_epochs=1)

    with pytest.raises(ValueError, match="controller num_epochs.*configured"):
        _run(module, inputs, controller, tmp_path / "result")

    assert controller.calls == [("clean",)]


def _install_offline_controller_import_surface(monkeypatch):
    fake_link_failure_pb2 = types.ModuleType("link_failure_grpc.link_failure_pb2")
    fake_link_failure_pb2.LinkFailureResponse = object
    fake_link_failure_pb2_grpc = types.ModuleType(
        "link_failure_grpc.link_failure_pb2_grpc"
    )
    fake_link_failure_pb2_grpc.LinkFailureServiceServicer = object
    fake_link_failure_pb2_grpc.add_LinkFailureServiceServicer_to_server = (
        lambda *args, **kwargs: None
    )
    monkeypatch.setitem(
        sys.modules, "link_failure_grpc.link_failure_pb2", fake_link_failure_pb2
    )
    monkeypatch.setitem(
        sys.modules,
        "link_failure_grpc.link_failure_pb2_grpc",
        fake_link_failure_pb2_grpc,
    )


def test_main_nondefault_options_are_hidden_only_during_real_factory_construction(
    tmp_path, monkeypatch
):
    module = _load_scenario_module("example_canada_parity_main_factory")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=1)
    production_config = json.loads(
        (PROJECT_ROOT / "test" / "config" / "tinyleo_canada_parity.json").read_text(
            encoding="utf-8"
        )
    )
    production_config.update(
        {
            "Duration (s)": 1,
            "num_epochs": 1,
            "traffic_matrix_file": str(inputs["traffic_path"]),
            "block_positions_file": str(tmp_path / "inputs" / "block_positions.json"),
            "satellite_file": str(tmp_path / "satellites.npy"),
            "grid_satellites_file": str(tmp_path / "grids.npy"),
            "topo_dir": str(tmp_path / "topology"),
            "Machines": [],
        }
    )
    config_path = tmp_path / "runner-config.json"
    config_path.write_text(json.dumps(production_config), encoding="utf-8")
    report_path = tmp_path / "validation-report.json"
    report_path.write_text(json.dumps(inputs["report"]), encoding="utf-8")
    _install_offline_controller_import_surface(monkeypatch)

    from southbound.sn_controller import RemoteController

    cleanup_calls = []
    monkeypatch.setattr(RemoteController, "init_remote_machine", lambda self: None)
    monkeypatch.setattr(RemoteController, "create_nodes", lambda self: None)
    monkeypatch.setattr(RemoteController, "create_links", lambda self: None)
    monkeypatch.setattr(
        RemoteController, "start_link_faliure_server", lambda self: None
    )
    monkeypatch.setattr(
        RemoteController, "update_tinyleo_topology", lambda self, epoch: None
    )
    monkeypatch.setattr(
        RemoteController,
        "deploy_tinyleo_srv6_agent",
        lambda self: {
            "remote_acknowledgements": [
                {
                    "remote_id": 0,
                    "expected_count": 86,
                    "started_count": 86,
                    "agents": [
                        {"name": f"node-{index}", "namespace_pid": 1000 + index}
                        for index in range(86)
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(RemoteController, "set_ping", lambda *args: None)
    monkeypatch.setattr(RemoteController, "set_traceroute", lambda *args: None)
    monkeypatch.setattr(RemoteController, "set_iperf", lambda *args: None)
    monkeypatch.setattr(
        RemoteController, "clean", lambda self: cleanup_calls.append(self)
    )
    import psutil

    monkeypatch.setattr(
        psutil,
        "Process",
        lambda: types.SimpleNamespace(
            memory_info=lambda: types.SimpleNamespace(rss=1234)
        ),
    )
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: types.SimpleNamespace(
            total=10000, available=7000, used=3000, percent=30.0
        ),
    )
    monkeypatch.setattr(
        psutil,
        "swap_memory",
        lambda: types.SimpleNamespace(
            total=2000, used=100, free=1900, percent=5.0
        ),
    )

    runner_argv = [
        str(SCENARIO_PATH),
        "--config",
        str(config_path),
        "--south-policy",
        str(inputs["south_path"]),
        "--north-policy",
        str(inputs["north_path"]),
        "--backbone-demand",
        str(inputs["demand_path"]),
        "--validation-report",
        str(report_path),
        "--result-dir",
        str(tmp_path / "custom-result"),
        "--measurement-wait-s",
        "0",
    ]
    monkeypatch.setattr(sys, "argv", runner_argv)

    assert module.main() == 0
    assert sys.argv == runner_argv
    assert len(cleanup_calls) == 1


def test_import_is_noninteractive_and_has_no_runtime_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("interactive input is forbidden")
        ),
    )
    before = set(tmp_path.iterdir())

    module = _load_scenario_module("example_canada_parity_import_safe")

    assert callable(module.run_canada_parity)
    assert callable(module.main)
    assert set(tmp_path.iterdir()) == before


def test_runner_uses_real_controller_sequence_and_vancouver_to_toronto_calls(tmp_path):
    module = _load_scenario_module("example_canada_parity_sequence")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=8)
    controller = FakeController(tmp_path / "controller", num_epochs=8)

    factory_calls = _run(module, inputs, controller, tmp_path / "result")

    assert factory_calls == [
        (inputs["config_path"], module.GS_LAT_LONG, module.GS_CELL)
    ]
    lifecycle = [
        call
        for call in controller.calls
        if call[0]
        in {
            "init",
            "create_nodes",
            "create_links",
            "start_failure_server",
            "update",
            "deploy",
            "failure",
            "clean",
        }
    ]
    assert lifecycle == [
        ("init",),
        ("create_nodes",),
        ("create_links",),
        ("start_failure_server",),
        ("update", 0),
        ("deploy",),
        ("update", 1),
        ("update", 2),
        ("update", 3),
        ("update", 4),
        ("update", 5),
        ("update", 6),
        ("failure",),
        ("update", 7),
        ("clean",),
    ]
    measurements = [
        call for call in controller.calls if call[0] in {"ping", "traceroute", "iperf"}
    ]
    assert {call[1:3] for call in measurements} == {("GS4", "GS6")}
    assert [call for call in controller.calls if call[0] == "failure"] == [
        ("failure",)
    ]


def test_runner_writes_observations_and_metadata_schemas(tmp_path):
    module = _load_scenario_module("example_canada_parity_artifacts")
    inputs = _write_scenario_inputs(tmp_path / "inputs")
    controller = FakeController(tmp_path / "controller")
    result_dir = tmp_path / "result"

    _run(module, inputs, controller, result_dir)

    observation_epochs = (0, 5, 6, 7, 11)
    assert {
        path.name for path in result_dir.glob("ping-epoch-*.txt")
    } == {f"ping-epoch-{epoch}.txt" for epoch in observation_epochs}
    assert {
        path.name for path in result_dir.glob("traceroute-epoch-*.txt")
    } == {f"traceroute-epoch-{epoch}.txt" for epoch in observation_epochs}

    with (result_dir / "iperf-normal-and-recovery.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        iperf_rows = list(csv.DictReader(stream))
        assert tuple(iperf_rows[0]) == (
            "epoch",
            "phase",
            "source",
            "destination",
            "status",
            "source_path",
            "artifact_path",
            "size_bytes",
        )
    assert [int(row["epoch"]) for row in iperf_rows] == list(observation_epochs)
    assert {row["status"] for row in iperf_rows} == {"captured"}

    events = json.loads(
        (result_dir / "failure-recovery-events.json").read_text(encoding="utf-8")
    )
    assert events["failure_epoch"] == 6
    assert events["recovery_observation_epoch"] == 7
    assert events["events"][0]["event"] == "srv6_deployment"
    assert events["events"][0]["status"] == "returned"
    assert events["events"][0]["acknowledgement"]["remote_acknowledgements"][0][
        "started_count"
    ] == 86
    assert events["events"][1]["event"] == "failure_injection"
    assert events["events"][1]["interruption_seconds"] > 0
    assert events["events"][1]["acknowledgement"]["failed_link"] == [
        "SH1SAT10",
        "SH1SAT11",
    ]
    assert events["events"][2]["event"] == "recovery_observation"
    assert events["events"][2]["status"] == "measurement_attempted"

    metadata = json.loads(
        (result_dir / "scenario-metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["routing_mode"] == "shortest"
    assert metadata["applied_policy"] == {"[3, 2]->[3, 4]": [[3, 3]]}
    assert metadata["source"] == "GS4"
    assert metadata["destination"] == "GS6"

    with (result_dir / "resource-usage.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        resource_rows = list(csv.DictReader(stream))
    assert len(resource_rows) == 12
    assert tuple(resource_rows[0]) == (
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
    assert all("not n2 VM acceptance" in row["scope"] for row in resource_rows)

    with (result_dir / "topology-update-times.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        update_rows = list(csv.DictReader(stream))
    assert tuple(update_rows[0]) == ("epoch", "duration_seconds", "status")
    assert [int(row["epoch"]) for row in update_rows] == list(range(12))
    assert {row["status"] for row in update_rows} == {"returned"}


def test_runner_marks_missing_measurements_without_fabricating_success(tmp_path):
    module = _load_scenario_module("example_canada_parity_missing")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=1)
    controller = FakeController(
        tmp_path / "controller", num_epochs=1, write_measurements=False
    )
    result_dir = tmp_path / "result"

    _run(module, inputs, controller, result_dir)

    ping = (result_dir / "ping-epoch-0.txt").read_text(encoding="utf-8")
    traceroute = (result_dir / "traceroute-epoch-0.txt").read_text(
        encoding="utf-8"
    )
    assert "STATUS: MISSING" in ping
    assert "STATUS: MISSING" in traceroute
    assert "PASS" not in ping + traceroute
    with (result_dir / "iperf-normal-and-recovery.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["status"] == "missing"
    assert "PASS" not in json.dumps(rows)


def test_cleanup_and_failure_event_survive_failure_injection_exception(tmp_path):
    module = _load_scenario_module("example_canada_parity_failure_error")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=7)
    controller = FakeController(
        tmp_path / "controller", num_epochs=7, raise_on="failure"
    )
    result_dir = tmp_path / "result"

    with pytest.raises(RuntimeError, match="failure failed"):
        _run(module, inputs, controller, result_dir)

    assert controller.calls[-1] == ("clean",)
    assert len([call for call in controller.calls if call[0] == "failure"]) == 1
    events = json.loads(
        (result_dir / "failure-recovery-events.json").read_text(encoding="utf-8")
    )
    assert events["events"][-1]["event"] == "failure_injection"
    assert events["events"][-1]["status"] == "raised"
    assert "failure failed" in events["events"][-1]["error"]


def test_noop_failure_without_remote_ack_is_rejected(tmp_path):
    module = _load_scenario_module("example_canada_parity_noop_failure")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=7)
    controller = FakeController(tmp_path / "controller", num_epochs=7)
    result_dir = tmp_path / "result"

    with pytest.raises(ValueError, match="failure acknowledgement"):
        _run(
            module,
            inputs,
            controller,
            result_dir,
            failure_injector=lambda _controller, _epoch: None,
        )

    events = json.loads(
        (result_dir / "failure-recovery-events.json").read_text(encoding="utf-8")
    )
    assert events["events"][-1]["event"] == "failure_injection"
    assert events["events"][-1]["status"] == "raised"


@pytest.mark.parametrize(
    "acknowledgements",
    [
        [
            {
                "remote_id": 0,
                "expected_count": 85,
                "started_count": 85,
                "agents": [
                    {"name": f"node-{index}", "namespace_pid": 1000 + index}
                    for index in range(85)
                ],
            }
        ],
        [
            {
                "remote_id": 0,
                "expected_count": 43,
                "started_count": 43,
                "agents": [
                    {"name": f"a-{index}", "namespace_pid": 1000 + index}
                    for index in range(43)
                ],
            },
            {
                "remote_id": 0,
                "expected_count": 43,
                "started_count": 43,
                "agents": [
                    {"name": f"b-{index}", "namespace_pid": 2000 + index}
                    for index in range(43)
                ],
            },
        ],
    ],
)
def test_srv6_ack_rejects_partial_or_duplicate_remote_results(
    acknowledgements,
):
    module = _load_scenario_module("example_canada_parity_bad_srv6_ack")

    with pytest.raises(ValueError, match="SRv6"):
        module._validate_srv6_acknowledgement(
            {"remote_acknowledgements": acknowledgements},
            expected_total=86,
        )


def test_routing_modes_apply_exact_fixed_policies_and_write_metadata(tmp_path):
    module = _load_scenario_module("example_canada_parity_routing_modes")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=1)

    observed = {}
    for mode, expected in (
        ("shortest", module.SOUTH_POLICY),
        ("geographic", module.NORTH_POLICY),
    ):
        controller = FakeController(tmp_path / f"controller-{mode}", num_epochs=1)
        result_dir = tmp_path / f"result-{mode}"
        _run(module, inputs, controller, result_dir, routing_mode=mode)
        metadata = json.loads(
            (result_dir / "scenario-metadata.json").read_text(encoding="utf-8")
        )
        assert metadata["routing_mode"] == mode
        assert metadata["applied_policy"] == expected
        assert controller.geopraphic_routing_policy == expected
        observed[mode] = metadata

    assert observed["shortest"]["num_epochs"] == observed["geographic"][
        "num_epochs"
    ] == 1


def test_cleanup_survives_network_command_exception(tmp_path):
    module = _load_scenario_module("example_canada_parity_network_error")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=12)
    controller = FakeController(
        tmp_path / "controller", num_epochs=12, raise_on="ping"
    )
    result_dir = tmp_path / "result"

    with pytest.raises(RuntimeError, match="ping failed") as raised:
        _run(module, inputs, controller, result_dir)

    assert raised.value is controller.raised_exception
    assert controller.calls[-1] == ("clean",)
    for epoch in (0, 5, 6, 7, 11):
        for kind in ("ping", "traceroute"):
            artifact = result_dir / f"{kind}-epoch-{epoch}.txt"
            assert artifact.is_file()
            assert (
                "STATUS: ERROR" in artifact.read_text(encoding="utf-8")
                or "STATUS: MISSING" in artifact.read_text(encoding="utf-8")
            )
    with (result_dir / "iperf-normal-and-recovery.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        iperf_rows = list(csv.DictReader(stream))
    assert [int(row["epoch"]) for row in iperf_rows] == [0, 5, 6, 7, 11]
    assert {row["status"] for row in iperf_rows} <= {"error", "missing"}
    assert (result_dir / "failure-recovery-events.json").is_file()
    assert (result_dir / "resource-usage.csv").is_file()
    assert (result_dir / "topology-update-times.csv").is_file()


def test_short_run_emits_only_in_range_observation_epochs(tmp_path):
    module = _load_scenario_module("example_canada_parity_short")
    inputs = _write_scenario_inputs(tmp_path / "inputs", epochs=6)
    controller = FakeController(tmp_path / "controller", num_epochs=6)
    result_dir = tmp_path / "result"

    _run(module, inputs, controller, result_dir)

    assert {path.name for path in result_dir.glob("ping-epoch-*.txt")} == {
        "ping-epoch-0.txt",
        "ping-epoch-5.txt",
    }
    assert not [call for call in controller.calls if call[0] == "failure"]
