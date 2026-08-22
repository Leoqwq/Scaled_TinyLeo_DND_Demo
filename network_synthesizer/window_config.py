"""Immutable configuration for the Canada parity-scale synthesis window."""

from dataclasses import dataclass
from numbers import Integral

import numpy as np


legacy_time_split = 308
DEFAULT_REGION_GRID_IDS = (12, 13, 14, 23, 24, 25)


@dataclass(frozen=True)
class WindowConfig:
    start_epoch: int
    num_epochs: int
    region_grid_ids: tuple[int, ...]
    satellite_height_km: float
    coverage_target: float
    target_satellites: int
    max_satellites: int
    num_processes: int
    memory_threshold_gb: float
    random_seed: int

    @classmethod
    def from_dict(cls, raw: dict) -> "WindowConfig":
        if "start_epoch" not in raw:
            raise ValueError("start_epoch is required")

        config = cls(
            start_epoch=raw["start_epoch"],
            num_epochs=raw.get("num_epochs", 12),
            region_grid_ids=tuple(raw.get("region_grid_ids", DEFAULT_REGION_GRID_IDS)),
            satellite_height_km=raw.get("satellite_height_km", 573.0),
            coverage_target=raw.get("coverage_target", 0.95),
            target_satellites=raw.get("target_satellites", 80),
            max_satellites=raw.get("max_satellites", 128),
            num_processes=raw.get("num_processes", 6),
            memory_threshold_gb=raw.get("memory_threshold_gb", 20.0),
            random_seed=raw.get("random_seed", 20260821),
        )
        config._validate()
        return config

    def _validate(self) -> None:
        if isinstance(self.start_epoch, bool) or not isinstance(self.start_epoch, Integral):
            raise ValueError("start_epoch must be an integer")
        if self.start_epoch < 0:
            raise ValueError("start_epoch must be non-negative")
        if isinstance(self.num_epochs, bool) or not isinstance(self.num_epochs, Integral):
            raise ValueError("num_epochs must be an integer")
        if self.num_epochs < 8:
            raise ValueError("num_epochs must be >= 8")
        if self.start_epoch + self.num_epochs > legacy_time_split:
            raise ValueError("window must not exceed legacy_time_split")
        if not 0 < self.coverage_target <= 1:
            raise ValueError("coverage_target must be in (0, 1]")
        if self.num_processes < 1:
            raise ValueError("num_processes must be >= 1")
        if self.num_processes > 6:
            raise ValueError("num_processes must be <= 6")
        if self.target_satellites < 64:
            raise ValueError("target_satellites must be >= 64")
        if self.target_satellites > self.max_satellites:
            raise ValueError("target_satellites must be <= max_satellites")
        if self.max_satellites > 128:
            raise ValueError("max_satellites must be <= 128")
        for grid_id in self.region_grid_ids:
            if not 0 <= grid_id < 121:
                raise ValueError("grid ID must be between 0 and 120")
        if self.region_grid_ids != DEFAULT_REGION_GRID_IDS:
            raise ValueError("region_grid_ids must equal Canada profile grid IDs")

    @property
    def epoch_indices(self) -> np.ndarray:
        return np.arange(self.start_epoch, self.start_epoch + self.num_epochs)

    @property
    def active_grid_ids(self) -> tuple[int, ...]:
        return self.region_grid_ids
