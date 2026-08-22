import csv
import json
from pathlib import Path

import numpy as np
import pytest

from test import check_canada_parity_results as checker


EPOCHS = range(12)
ACTIVE_GRIDS = (12, 13, 14, 23, 24, 25)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _valid_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    validation_path = tmp_path / "validation_report.json"
    synthesis_path = tmp_path / "synthesis_result.npy"

    validation_path.write_text(
        json.dumps(
            {
                "valid": True,
                "errors": [],
                "satellite_count": 80,
                "expected_epochs": 12,
                "topology_change_count": 3,
                "gateway_handover_count": 2,
                "path_epoch_ratio": 1.0,
                "epochs": [
                    {
                        "epoch": epoch,
                        "edge_disjoint_paths": 2,
                        "active_grid_counts": {
                            str(grid): 1 for grid in ACTIVE_GRIDS
                        },
                    }
                    for epoch in EPOCHS
                ],
            }
        ),
        encoding="utf-8",
    )
    np.save(
        synthesis_path,
        {
            "selected_candidate_ids": np.arange(80, dtype=np.int64),
            "coverage_ratio": 0.95,
            "residual_by_time": np.zeros((12, 121), dtype=float),
            "stop_reason": "coverage_target_reached",
        },
        allow_pickle=True,
    )
    _write_csv(
        result_dir / "resource-usage.csv",
        ["epoch", "process_rss_bytes", "system_memory_used_bytes", "swap_used_bytes"],
        [
            {
                "epoch": epoch,
                "process_rss_bytes": (2 * 1024**3) + epoch,
                "system_memory_used_bytes": 20 * 1024**3,
                "swap_used_bytes": 0,
            }
            for epoch in EPOCHS
        ],
    )
    _write_csv(
        result_dir / "topology-update-times.csv",
        ["epoch", "duration_seconds", "status"],
        [
            {"epoch": epoch, "duration_seconds": 1 + epoch / 10, "status": "returned"}
            for epoch in EPOCHS
        ],
    )
    (result_dir / "scenario-metadata.json").write_text(
        json.dumps(
            {
                "routing_mode": "shortest",
                "source": "GS4",
                "destination": "GS6",
                "num_epochs": 12,
                "failure_epoch": 6,
                "recovery_observation_epoch": 7,
            }
        ),
        encoding="utf-8",
    )
    for epoch in (0, 5, 11):
        (result_dir / f"ping-epoch-{epoch}.txt").write_text(
            "4 packets transmitted, 4 received, 0% packet loss\n"
            "rtt min/avg/max/mdev = 1.0/2.0/3.0/0.1 ms\n",
            encoding="utf-8",
        )
    (result_dir / "ping-epoch-7.txt").write_text(
        "4 packets transmitted, 1 received, 75% packet loss\n"
        "rtt min/avg/max/mdev = 2.0/3.0/4.0/0.1 ms\n",
        encoding="utf-8",
    )
    (result_dir / "ping-epoch-6.txt").write_text(
        "4 packets transmitted, 0 received, 100% packet loss\n", encoding="utf-8"
    )
    (result_dir / "traceroute-epoch-5.txt").write_text(
        "traceroute to 10.0.0.9\n1 10.0.0.1 0.1 ms\n2 10.0.0.2 0.2 ms\n",
        encoding="utf-8",
    )
    (result_dir / "traceroute-epoch-7.txt").write_text(
        "traceroute to 10.0.0.9\n1 10.0.0.1 0.1 ms\n2 10.0.0.3 0.2 ms\n",
        encoding="utf-8",
    )
    (result_dir / "traceroute-epoch-6.txt").write_text(
        "traceroute to 10.0.0.9\n1 10.0.0.1 0.1 ms\n2 10.0.0.4 0.2 ms\n",
        encoding="utf-8",
    )
    for epoch in (0, 11):
        (result_dir / f"traceroute-epoch-{epoch}.txt").write_text(
            "traceroute to 10.0.0.9\n1 10.0.0.1 0.1 ms\n"
            "2 10.0.0.2 0.2 ms\n",
            encoding="utf-8",
        )
    (result_dir / "failure-recovery-events.json").write_text(
        json.dumps(
            {
                "failure_epoch": 6,
                "recovery_observation_epoch": 7,
                "events": [
                    {
                        "epoch": 0,
                        "event": "srv6_deployment",
                        "status": "returned",
                        "acknowledgement": {
                            "remote_acknowledgements": [
                                {
                                    "remote_id": 0,
                                    "expected_count": 86,
                                    "started_count": 86,
                                    "agents": [
                                        {
                                            "name": f"node-{index}",
                                            "namespace_pid": 1000 + index,
                                        }
                                        for index in range(86)
                                    ],
                                }
                            ]
                        },
                    },
                    {
                        "epoch": 6,
                        "event": "failure_injection",
                        "status": "returned",
                        "interruption_seconds": 2.5,
                        "acknowledgement": {
                            "failed_link": ["SH1SAT10", "SH1SAT11"],
                            "removed_satellite": "SH1SAT10",
                            "replacement_satellite": "SH1SAT12",
                            "updated_satellites": ["SH1SAT10", "SH1SAT12"],
                            "remote_id": 0,
                        },
                    },
                    {
                        "epoch": 7,
                        "event": "recovery_observation",
                        "status": "measurement_attempted",
                        "measurement_statuses": {
                            "ping": "captured",
                            "traceroute": "captured",
                            "iperf": "captured",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return result_dir, validation_path, synthesis_path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(paths: tuple[Path, Path, Path]) -> dict:
    result_dir, validation_path, synthesis_path = paths
    return checker.check_results(result_dir, validation_path, synthesis_path)


def test_complete_bundle_passes_and_writes_stable_summary(tmp_path):
    paths = _valid_bundle(tmp_path)

    summary = _run(paths)

    assert summary["valid"] is True
    assert summary["errors"] == []
    assert all(gate["passed"] for gate in summary["gates"].values())
    written = _load_json(paths[0] / "acceptance_summary.json")
    assert written == summary
    assert set(next(iter(written["gates"].values()))) == {
        "passed",
        "actual",
        "required",
        "evidence",
    }
    assert written["metrics"]["peak_process_rss_bytes"] == (2 * 1024**3) + 11
    assert written["metrics"]["ping_loss_percent_by_artifact"] == {
        "ping-epoch-0.txt": 0.0,
        "ping-epoch-5.txt": 0.0,
        "ping-epoch-6.txt": 100.0,
        "ping-epoch-7.txt": 75.0,
        "ping-epoch-11.txt": 0.0,
    }
    assert written["metrics"]["failure_recovery_interruption_seconds"] == 2.5


def _low_satellite(paths):
    report = _load_json(paths[1])
    report["satellite_count"] = 63
    _save_json(paths[1], report)


def _invalid_report(paths):
    report = _load_json(paths[1])
    report["valid"] = False
    report["errors"] = [{"code": "bad", "message": "bad topology"}]
    _save_json(paths[1], report)


def _low_coverage(paths):
    artifact = np.load(paths[2], allow_pickle=True).item()
    artifact["coverage_ratio"] = 0.89
    np.save(paths[2], artifact, allow_pickle=True)


def _high_memory(paths):
    rows = list(csv.DictReader(paths[0].joinpath("resource-usage.csv").open()))
    rows[3]["system_memory_used_bytes"] = str(24 * 1024**3)
    _write_csv(paths[0] / "resource-usage.csv", list(rows[0]), rows)


def _swap(paths):
    rows = list(csv.DictReader(paths[0].joinpath("resource-usage.csv").open()))
    rows[2]["swap_used_bytes"] = "1"
    _write_csv(paths[0] / "resource-usage.csv", list(rows[0]), rows)


def _slow_updates(paths):
    rows = list(csv.DictReader(paths[0].joinpath("topology-update-times.csv").open()))
    for row in rows:
        row["duration_seconds"] = "15"
    _write_csv(paths[0] / "topology-update-times.csv", list(rows[0]), rows)


def _incomplete_runtime(paths):
    rows = list(csv.DictReader(paths[0].joinpath("resource-usage.csv").open()))[:-1]
    _write_csv(paths[0] / "resource-usage.csv", list(rows[0]), rows)


def _inactive_grid(paths):
    report = _load_json(paths[1])
    report["epochs"][4]["active_grid_counts"]["14"] = 0
    _save_json(paths[1], report)


def _low_path_diversity(paths):
    report = _load_json(paths[1])
    for epoch in report["epochs"][0:3]:
        epoch["edge_disjoint_paths"] = 1
    report["path_epoch_ratio"] = 0.75
    _save_json(paths[1], report)


def _few_changes(paths):
    report = _load_json(paths[1])
    report["topology_change_count"] = 2
    _save_json(paths[1], report)


def _few_handovers(paths):
    report = _load_json(paths[1])
    report["gateway_handover_count"] = 1
    _save_json(paths[1], report)


def _no_ping(paths):
    paths[0].joinpath("ping-epoch-0.txt").write_text(
        "4 packets transmitted, 0 received, 100% packet loss\n", encoding="utf-8"
    )
    paths[0].joinpath("ping-epoch-7.txt").write_text(
        "STATUS: ERROR\n4 packets transmitted, 4 received\n", encoding="utf-8"
    )


def _no_recovery(paths):
    paths[0].joinpath("traceroute-epoch-7.txt").write_text(
        paths[0].joinpath("traceroute-epoch-6.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _no_srv6_ack(paths):
    event_path = paths[0] / "failure-recovery-events.json"
    events = _load_json(event_path)
    events["events"][0]["acknowledgement"]["remote_acknowledgements"][0][
        "started_count"
    ] = 85
    _save_json(event_path, events)


@pytest.mark.parametrize(
    ("mutate", "failed_gate"),
    [
        (_invalid_report, "validation_report"),
        (_low_satellite, "satellite_count"),
        (_low_coverage, "coverage_ratio"),
        (_high_memory, "peak_memory"),
        (_swap, "swap_used"),
        (_slow_updates, "topology_update_p95"),
        (_incomplete_runtime, "runtime_epochs"),
        (_inactive_grid, "active_grids"),
        (_low_path_diversity, "path_diversity"),
        (_few_changes, "topology_changes"),
        (_few_handovers, "gateway_handovers"),
        (_no_ping, "ping_reply"),
        (_no_srv6_ack, "srv6_deployment"),
        (_no_recovery, "failure_recovery"),
    ],
)
def test_each_acceptance_gate_can_fail(tmp_path, mutate, failed_gate):
    paths = _valid_bundle(tmp_path)
    mutate(paths)

    summary = _run(paths)

    assert summary["valid"] is False
    assert summary["gates"][failed_gate]["passed"] is False


@pytest.mark.parametrize("bad_value", ["nan", "inf", "-1", "true"])
def test_runtime_numeric_evidence_fails_closed(tmp_path, bad_value):
    paths = _valid_bundle(tmp_path)
    rows = list(csv.DictReader(paths[0].joinpath("resource-usage.csv").open()))
    rows[0]["system_memory_used_bytes"] = bad_value
    _write_csv(paths[0] / "resource-usage.csv", list(rows[0]), rows)

    assert _run(paths)["valid"] is False


@pytest.mark.parametrize("bad_value", ["nan", "inf", "-1", "true"])
def test_process_rss_is_required_and_validated(tmp_path, bad_value):
    paths = _valid_bundle(tmp_path)
    rows = list(csv.DictReader(paths[0].joinpath("resource-usage.csv").open()))
    rows[0]["process_rss_bytes"] = bad_value
    _write_csv(paths[0] / "resource-usage.csv", list(rows[0]), rows)

    summary = _run(paths)

    assert summary["valid"] is False
    assert summary["metrics"]["peak_process_rss_bytes"] is None


@pytest.mark.parametrize("case", ["missing", "malformed", "duplicate", "raised"])
def test_bad_or_incomplete_runtime_evidence_fails_closed(tmp_path, case):
    paths = _valid_bundle(tmp_path)
    topology_path = paths[0] / "topology-update-times.csv"
    if case == "missing":
        topology_path.unlink()
    elif case == "malformed":
        topology_path.write_text("not,the,expected,schema\n", encoding="utf-8")
    else:
        rows = list(csv.DictReader(topology_path.open()))
        if case == "duplicate":
            rows[-1]["epoch"] = "10"
        else:
            rows[0]["status"] = "raised"
        _write_csv(topology_path, list(rows[0]), rows)

    summary = _run(paths)

    assert summary["valid"] is False
    assert summary["gates"]["runtime_epochs"]["passed"] is False or summary["gates"][
        "topology_update_p95"
    ]["passed"] is False
    assert (paths[0] / "acceptance_summary.json").is_file()


def test_inconsistent_reported_path_ratio_fails_closed(tmp_path):
    paths = _valid_bundle(tmp_path)
    report = _load_json(paths[1])
    report["path_epoch_ratio"] = 0.8
    _save_json(paths[1], report)

    summary = _run(paths)

    assert summary["valid"] is False
    assert summary["gates"]["validation_report"]["passed"] is True
    assert summary["gates"]["path_diversity"]["passed"] is False


def test_malformed_synthesis_shape_fails_closed(tmp_path):
    paths = _valid_bundle(tmp_path)
    np.save(paths[2], np.array([0.95]), allow_pickle=True)

    summary = _run(paths)

    assert summary["valid"] is False
    assert summary["gates"]["coverage_ratio"]["passed"] is False


@pytest.mark.parametrize("coverage_ratio", [1.01, float("nan"), float("inf")])
def test_invalid_synthesis_ratio_fails_closed(tmp_path, coverage_ratio):
    paths = _valid_bundle(tmp_path)
    artifact = np.load(paths[2], allow_pickle=True).item()
    artifact["coverage_ratio"] = coverage_ratio
    np.save(paths[2], artifact, allow_pickle=True)

    assert _run(paths)["gates"]["coverage_ratio"]["passed"] is False


def test_synthesis_selection_must_match_validated_satellite_count(tmp_path):
    paths = _valid_bundle(tmp_path)
    artifact = np.load(paths[2], allow_pickle=True).item()
    artifact["selected_candidate_ids"] = artifact["selected_candidate_ids"][:-1]
    np.save(paths[2], artifact, allow_pickle=True)

    summary = _run(paths)

    assert summary["valid"] is False
    assert summary["gates"]["satellite_count"]["passed"] is False


@pytest.mark.parametrize(
    "content",
    [
        "STATUS: MISSING\n4 packets transmitted, 4 received\n",
        "STATUS: ERROR\n4 packets transmitted, 4 received\n",
        "4 packets transmitted, 0 received, 100% packet loss\n",
        "unparseable ping output\n",
    ],
)
def test_recovery_requires_real_positive_ping(tmp_path, content):
    paths = _valid_bundle(tmp_path)
    paths[0].joinpath("ping-epoch-7.txt").write_text(content, encoding="utf-8")

    summary = _run(paths)

    assert summary["gates"]["failure_recovery"]["passed"] is False


def test_attempted_recovery_without_captured_statuses_fails(tmp_path):
    paths = _valid_bundle(tmp_path)
    event_path = paths[0] / "failure-recovery-events.json"
    events = _load_json(event_path)
    events["events"][2]["measurement_statuses"]["traceroute"] = "missing"
    _save_json(event_path, events)

    summary = _run(paths)

    assert summary["gates"]["failure_recovery"]["passed"] is False


def test_natural_path_change_without_remote_failure_ack_cannot_pass(tmp_path):
    paths = _valid_bundle(tmp_path)
    event_path = paths[0] / "failure-recovery-events.json"
    events = _load_json(event_path)
    events["events"][1].pop("acknowledgement")
    _save_json(event_path, events)

    summary = _run(paths)

    assert summary["gates"]["failure_recovery"]["passed"] is False


def test_failure_recovery_requires_separately_timed_interruption(tmp_path):
    paths = _valid_bundle(tmp_path)
    event_path = paths[0] / "failure-recovery-events.json"
    events = _load_json(event_path)
    events["events"][1].pop("interruption_seconds")
    _save_json(event_path, events)

    summary = _run(paths)

    assert summary["gates"]["failure_recovery"]["passed"] is False
    assert summary["metrics"]["failure_recovery_interruption_seconds"] is None


@pytest.mark.parametrize(
    "mutation",
    ["partial", "duplicate_remote"],
)
def test_srv6_gate_rejects_partial_or_duplicate_remote_acknowledgements(
    tmp_path, mutation
):
    paths = _valid_bundle(tmp_path)
    event_path = paths[0] / "failure-recovery-events.json"
    payload = _load_json(event_path)
    acknowledgements = payload["events"][0]["acknowledgement"][
        "remote_acknowledgements"
    ]
    if mutation == "partial":
        acknowledgements[0]["expected_count"] = 85
        acknowledgements[0]["started_count"] = 85
        acknowledgements[0]["agents"] = acknowledgements[0]["agents"][:85]
    else:
        first = acknowledgements[0]
        first["expected_count"] = 43
        first["started_count"] = 43
        first["agents"] = first["agents"][:43]
        duplicate = {
            "remote_id": first["remote_id"],
            "expected_count": 43,
            "started_count": 43,
            "agents": [
                {"name": f"other-{index}", "namespace_pid": 2000 + index}
                for index in range(43)
            ],
        }
        acknowledgements.append(duplicate)
    _save_json(event_path, payload)

    summary = _run(paths)

    assert summary["gates"]["srv6_deployment"]["passed"] is False


@pytest.mark.parametrize("case", ["wrong_endpoint", "stray_artifact"])
def test_ping_gate_is_bound_to_fixed_machine_readable_flow(tmp_path, case):
    paths = _valid_bundle(tmp_path)
    if case == "wrong_endpoint":
        metadata_path = paths[0] / "scenario-metadata.json"
        metadata = _load_json(metadata_path)
        metadata["source"] = "GS1"
        _save_json(metadata_path, metadata)
    else:
        (paths[0] / "ping-epoch-99.txt").write_text(
            "4 packets transmitted, 4 received, 0% packet loss\n",
            encoding="utf-8",
        )

    summary = _run(paths)

    assert summary["gates"]["ping_reply"]["passed"] is False


def _valid_ab_root(tmp_path: Path) -> Path:
    ab_root = tmp_path / "formal-ab"
    ab_root.mkdir()
    (ab_root / "fixed-artifact-sha256.txt").write_text(
        "abc  fixed-input\n", encoding="utf-8"
    )
    for mode in ("shortest", "geographic"):
        mode_root = ab_root / mode
        mode_root.mkdir()
        paths = _valid_bundle(mode_root)
        metadata_path = paths[0] / "scenario-metadata.json"
        metadata = _load_json(metadata_path)
        metadata["routing_mode"] = mode
        _save_json(metadata_path, metadata)
        assert _run(paths)["valid"] is True
    return ab_root


def test_ab_comparison_accepts_epoch6_outage_and_uses_failure_timer(tmp_path):
    ab_root = _valid_ab_root(tmp_path)
    for mode in ("shortest", "geographic"):
        (ab_root / mode / "results" / "traceroute-epoch-6.txt").write_text(
            "traceroute to 10.0.0.9\n1 * * *\n2 * * *\n",
            encoding="utf-8",
        )

    comparison = checker.compare_routing_runs(ab_root)

    assert comparison["shortest"]["per_epoch"]["6"] == {
        "received": 0,
        "loss_percent": 100.0,
        "average_latency_ms": None,
        "traceroute_hops": None,
    }
    assert (
        comparison["shortest"]["failure_recovery_interruption_seconds"]
        == 2.5
    )
    assert comparison["shortest"]["validated_peak_process_rss_bytes"] > 0
    assert comparison["shortest"]["validated_recovery_ping_loss_percent"] == 75.0
    assert _load_json(ab_root / "routing_ab_comparison.json") == comparison


@pytest.mark.parametrize("mutation", ["no_recovery_reply", "missing_interruption"])
def test_ab_comparison_rejects_missing_recovery_evidence(tmp_path, mutation):
    ab_root = _valid_ab_root(tmp_path)
    result_dir = ab_root / "geographic" / "results"
    if mutation == "no_recovery_reply":
        (result_dir / "ping-epoch-7.txt").write_text(
            "4 packets transmitted, 0 received, 100% packet loss\n",
            encoding="utf-8",
        )
    else:
        event_path = result_dir / "failure-recovery-events.json"
        payload = _load_json(event_path)
        payload["events"][1].pop("interruption_seconds")
        _save_json(event_path, payload)

    with pytest.raises(ValueError, match="recovery|interruption"):
        checker.compare_routing_runs(ab_root)


def test_ping_received_count_without_packet_loss_cannot_pass(tmp_path):
    paths = _valid_bundle(tmp_path)
    paths[0].joinpath("ping-epoch-0.txt").write_text(
        "4 packets transmitted, 4 received\n", encoding="utf-8"
    )
    paths[0].joinpath("ping-epoch-7.txt").write_text(
        "4 packets transmitted, 4 received\n", encoding="utf-8"
    )

    summary = _run(paths)

    assert summary["gates"]["ping_reply"]["passed"] is False
    assert summary["gates"]["failure_recovery"]["passed"] is False


def test_cli_exit_code_is_zero_only_for_pass(tmp_path, capsys):
    paths = _valid_bundle(tmp_path)
    argv = [
        str(paths[0]),
        "--validation-report",
        str(paths[1]),
        "--synthesis-result",
        str(paths[2]),
    ]
    assert checker.main(argv) == 0
    assert "OVERALL: PASS" in capsys.readouterr().out

    _low_coverage(paths)
    assert checker.main(argv) != 0
    output = capsys.readouterr().out
    assert "coverage_ratio: FAIL" in output
    assert "OVERALL: FAIL" in output
