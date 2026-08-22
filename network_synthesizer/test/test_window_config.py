"""Tests for the Canada parity-scale synthesizer window profile."""

import json
import unittest
from pathlib import Path

from window_config import WindowConfig


CONFIG_PATH = Path(__file__).parent / "config" / "canada_parity_windowed.json"


def valid_config():
    with CONFIG_PATH.open() as config_file:
        return json.load(config_file)


class WindowConfigTests(unittest.TestCase):
    def test_canada_window_has_twelve_consecutive_legacy_epochs(self):
        config = WindowConfig.from_dict(valid_config())

        self.assertEqual(
            config.epoch_indices.tolist(),
            list(range(config.start_epoch, config.start_epoch + 12)),
        )

    def test_rejects_satellite_cap_above_parity_limit(self):
        raw = valid_config() | {"max_satellites": 129}

        with self.assertRaisesRegex(ValueError, "max_satellites must be <= 128"):
            WindowConfig.from_dict(raw)

    def test_rejects_grid_outside_global_grid(self):
        raw = valid_config() | {"region_grid_ids": [23, 121]}

        with self.assertRaisesRegex(ValueError, "grid ID"):
            WindowConfig.from_dict(raw)

    def test_uses_canada_profile_defaults(self):
        config = WindowConfig.from_dict(valid_config())

        self.assertEqual(config.num_epochs, 12)
        self.assertEqual(config.region_grid_ids, (12, 13, 14, 23, 24, 25))
        self.assertEqual(config.satellite_height_km, 573.0)
        self.assertEqual(config.coverage_target, 0.95)
        self.assertEqual(config.target_satellites, 80)
        self.assertEqual(config.max_satellites, 128)
        self.assertEqual(config.num_processes, 6)
        self.assertEqual(config.memory_threshold_gb, 20.0)
        self.assertEqual(config.random_seed, 20260821)

    def test_rejects_invalid_window_and_resource_bounds(self):
        for overrides, message in (
            ({"num_epochs": 7}, "num_epochs must be >= 8"),
            ({"start_epoch": 297}, "legacy_time_split"),
            ({"coverage_target": 0}, "coverage_target"),
            ({"num_processes": 7}, "num_processes must be <= 6"),
            ({"target_satellites": 63}, "target_satellites must be >= 64"),
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    WindowConfig.from_dict(valid_config() | overrides)


if __name__ == "__main__":
    unittest.main()
