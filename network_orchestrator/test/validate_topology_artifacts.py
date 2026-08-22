"""Command-line entry point for offline TinyLEO topology validation."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from topology_artifact_validator import ValidationConfig, ValidationReport, validate_artifact_bundle


def _active_grids(value: str) -> tuple[int, ...]:
    try:
        grids = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("active grids must be comma-separated integers") from exc
    if not grids:
        raise argparse.ArgumentTypeError("at least one active grid is required")
    return grids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate TinyLEO topology output without starting an emulation"
    )
    parser.add_argument("--satellite-file", type=Path, required=True)
    parser.add_argument("--grid-satellites-file", type=Path, required=True)
    parser.add_argument("--traffic-matrix-file", type=Path, required=True)
    parser.add_argument("--block-positions-file", type=Path, required=True)
    parser.add_argument("--topology-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-epochs", type=int, required=True)
    parser.add_argument("--active-grids", type=_active_grids, required=True)
    parser.add_argument("--min-satellites", type=int, default=64)
    parser.add_argument("--max-satellites", type=int, default=128)
    parser.add_argument("--min-edge-disjoint-paths", type=int, default=2)
    parser.add_argument("--min-path-epoch-ratio", type=float, default=0.8)
    parser.add_argument("--source-grid", type=int, default=23)
    parser.add_argument("--destination-grid", type=int, default=25)
    parser.add_argument("--min-largest-component-ratio", type=float, default=0.9)
    parser.add_argument("--min-topology-changes", type=int, default=0)
    parser.add_argument("--min-gateway-handovers", type=int, default=0)
    return parser


def _write_reports(report: ValidationReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "validation_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )

    fieldnames = [
        "epoch",
        "satellite_count",
        "link_count",
        "inter_link_count",
        "intra_link_count",
        "component_count",
        "largest_component_ratio",
        "edge_disjoint_paths",
        "average_degree",
        "min_degree",
        "max_degree",
        "added_links",
        "removed_links",
        "gateway_handovers",
        "active_grid_counts",
    ]
    with (output_dir / "epoch_metrics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as metrics_file:
        writer = csv.DictWriter(metrics_file, fieldnames=fieldnames)
        writer.writeheader()
        for epoch in report.epochs:
            row = {
                name: getattr(epoch, name)
                for name in fieldnames
                if name != "active_grid_counts"
            }
            row["active_grid_counts"] = json.dumps(
                epoch.active_grid_counts, sort_keys=True
            )
            writer.writerow(row)

    churn_fields = [
        "epoch",
        "added_links",
        "removed_links",
        "gateway_handovers",
    ]
    with (output_dir / "topology_churn.csv").open(
        "w", newline="", encoding="utf-8"
    ) as churn_file:
        writer = csv.DictWriter(churn_file, fieldnames=churn_fields)
        writer.writeheader()
        for epoch in report.epochs:
            writer.writerow({name: getattr(epoch, name) for name in churn_fields})

    status = "PASS" if report.valid else "FAIL"
    lines = [
        f"Topology artifact validation: {status}",
        f"Satellites: {report.satellite_count}",
        f"Validated epochs: {len(report.epochs)}/{report.expected_epochs}",
        f"Path-quality epoch ratio: {report.path_epoch_ratio:.1%}",
        f"Topology changes: {report.topology_change_count}",
        f"Gateway handovers: {report.gateway_handover_count}",
        f"Errors: {len(report.errors)}",
    ]
    lines.extend(
        f"- [{error.code}]"
        f"{' epoch ' + str(error.epoch) if error.epoch is not None else ''}: "
        f"{error.message}"
        for error in report.errors
    )
    (output_dir / "validation_summary.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = ValidationConfig(
        satellite_file=args.satellite_file,
        grid_satellites_file=args.grid_satellites_file,
        traffic_matrix_file=args.traffic_matrix_file,
        block_positions_file=args.block_positions_file,
        topology_dir=args.topology_dir,
        expected_epochs=args.expected_epochs,
        active_grids=args.active_grids,
        min_satellites=args.min_satellites,
        max_satellites=args.max_satellites,
        min_edge_disjoint_paths=args.min_edge_disjoint_paths,
        min_path_epoch_ratio=args.min_path_epoch_ratio,
        source_grid=args.source_grid,
        destination_grid=args.destination_grid,
        min_largest_component_ratio=args.min_largest_component_ratio,
        min_topology_changes=args.min_topology_changes,
        min_gateway_handovers=args.min_gateway_handovers,
    )
    report = validate_artifact_bundle(config)
    _write_reports(report, args.output_dir)
    print((args.output_dir / "validation_summary.txt").read_text(encoding="utf-8"), end="")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
