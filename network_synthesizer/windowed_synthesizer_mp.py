"""Bounded in-memory matching pursuit for a finite synthesis window."""

from dataclasses import dataclass
from os import PathLike

import numpy as np
from scipy.sparse import csr_matrix

from synthesizer_mp import coverage_gain
from window_config import WindowConfig


@dataclass(frozen=True)
class SynthesisResult:
    selected_candidate_ids: tuple[int, ...]
    coverage_ratio: float
    residual_by_time: np.ndarray
    stop_reason: str


def synthesize_windowed(
    demand_by_time: np.ndarray,
    coverage: csr_matrix,
    config: WindowConfig,
) -> SynthesisResult:
    """Select finite-window coverage rows until the target or budget stops MP."""
    expected_shape = (config.num_epochs, 121)
    demand = np.asarray(demand_by_time, dtype=float)
    if demand.shape != expected_shape:
        raise ValueError(f"demand_by_time must have shape {expected_shape}")

    expected_columns = config.num_epochs * 121
    if coverage.ndim != 2 or coverage.shape[1] != expected_columns:
        raise ValueError(f"coverage must have {expected_columns} columns")

    residual = demand.reshape(-1).copy()
    initial_demand = float(residual.sum())
    if initial_demand == 0.0:
        return SynthesisResult(
            selected_candidate_ids=(),
            coverage_ratio=1.0,
            residual_by_time=residual.reshape(expected_shape),
            stop_reason="coverage_target_reached",
        )

    selected = []
    available = np.ones(coverage.shape[0], dtype=bool)

    while True:
        coverage_ratio = 1.0 - float(residual.sum()) / initial_demand
        if coverage_ratio >= config.coverage_target:
            stop_reason = "coverage_target_reached"
            break
        if len(selected) >= config.max_satellites:
            stop_reason = "satellite_cap_reached"
            break

        best_gain = 0.0
        best_candidate_id = -1
        for candidate_id in np.flatnonzero(available):
            gain = coverage_gain(coverage.getrow(candidate_id), residual)
            if gain > best_gain:
                best_gain = gain
                best_candidate_id = int(candidate_id)

        if best_gain <= 0.0:
            stop_reason = "no_positive_gain"
            break

        row = coverage.getrow(best_candidate_id)
        residual[row.indices] -= row.data
        residual[row.indices] = np.maximum(residual[row.indices], 0.0)
        selected.append(best_candidate_id)
        available[best_candidate_id] = False

    return SynthesisResult(
        selected_candidate_ids=tuple(selected),
        coverage_ratio=coverage_ratio,
        residual_by_time=residual.reshape(expected_shape),
        stop_reason=stop_reason,
    )


def save_synthesis_result(
    path: str | PathLike[str], result: SynthesisResult
) -> None:
    """Save all synthesis result fields in one stable NumPy artifact."""
    artifact = {
        "selected_candidate_ids": np.asarray(
            result.selected_candidate_ids, dtype=np.int64
        ),
        "coverage_ratio": result.coverage_ratio,
        "residual_by_time": result.residual_by_time,
        "stop_reason": result.stop_reason,
    }
    np.save(path, artifact, allow_pickle=True)
