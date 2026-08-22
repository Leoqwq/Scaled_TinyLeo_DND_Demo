"""
Runner for TinyLEO's official northbound example on Windows.

Fixes:
  - import path (repo uses `tinyleo.northbound` but ships `northbound.py`)
  - data paths (files live under test/data/topo_data/)
  - missing/broken satellite_constellation_for_backbone stub → use available eval supply npy
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
ORCH_DIR = TEST_DIR.parent
REPO_ROOT = ORCH_DIR.parent

# Make `import northbound` work
sys.path.insert(0, str(ORCH_DIR))

os.chdir(TEST_DIR)

from northbound import TinyLEONorthboundAPI  # noqa: E402

# Official-ish paths, corrected to this checkout layout
config_file = "config/mpc_config.json"
grid_satellites_file = "data/topo_data/grid_satellites_map_for_backbone.npy"
# Upstream example names satellite_constellation_for_backbone.npy, but that file is a
# 2-byte stub in this clone. Use the available supply dump instead.
satellite_data_file = "data/topo_data/eval1_573_jinyao_24k_half.npy"

os.makedirs("result/output_nbi", exist_ok=True)
os.makedirs("result/output_scaled_nbi", exist_ok=True)
os.makedirs("result/output_all_nbi", exist_ok=True)

print("Working directory:", TEST_DIR)
print("Config:", config_file)
print("Grid map:", grid_satellites_file)
print("Satellite supply:", satellite_data_file)

# Infer timestamps from supply file when possible
import numpy as np

supply = np.load(satellite_data_file, allow_pickle=True)
_, _, _, sat_location0, _ = supply[0]
num_timestamps = len(sat_location0)
num_satellites = len(supply)
print(f"Inferred num_satellites={num_satellites}, num_timestamps={num_timestamps}")

print("\n1. Initializing TinyLEO Northbound API...")
api = TinyLEONorthboundAPI(config_file)

print("\n2. Generating and saving traffic matrices...")
traffic_matrix, isl_matrix = api.generate_and_save_traffic_matrices(
    grid_satellites_file=grid_satellites_file,
    output_dir="result/output_nbi",
)
print(f"Generated traffic matrix of shape: {traffic_matrix.shape}")
print(f"Total traffic: {traffic_matrix.sum() / 2:.2f} Gbps")

print("\n3. Getting and saving path information...")
paths = api.get_and_save_paths(output_dir="result/output_nbi")
print(f"Found {len(paths)} paths")
# Print a few paths for the demo
for i, (key, path) in enumerate(list(paths.items())[:5]):
    print(f"  path[{i}] {key}: {path}")

print("\n4. Analyzing and saving network connectivity...")
connectivity = api.analyze_and_save_connectivity(output_dir="result/output_nbi")
print(f"Network is connected: {connectivity['is_connected']}")
print(
    f"Path reachability analysis completed for "
    f"{len(connectivity['path_reachability'])} demand pairs"
)

print("\n5. Scaling and saving traffic matrices based on satellite constraints...")
try:
    scaled_matrix, scaled_isl_matrix, scaling_factor = api.scale_and_save_traffic_matrices(
        satellite_data_file=satellite_data_file,
        grid_satellite_file=grid_satellites_file,
        num_satellites=num_satellites,
        num_timestamps=num_timestamps,
        output_dir="result/output_scaled_nbi",
    )
    print(f"Scaling factor: {scaling_factor:.4f}")
    print(f"Scaled traffic total: {scaled_matrix.sum() / 2:.2f} Gbps")
    print(f"Scaled ISLs total: {scaled_isl_matrix.sum() / 2}")
except Exception as e:
    print(f"Error in scaling traffic matrices: {type(e).__name__}: {e}")

print("\n6. Saving all results with one method call...")
try:
    api.save_all_results(
        output_dir="result/output_all_nbi",
        grid_satellites_file=grid_satellites_file,
        satellite_data_file=satellite_data_file,
        num_satellites=num_satellites,
        num_timestamps=num_timestamps,
    )
    print("All results saved to 'result/output_all_nbi' directory")
except Exception as e:
    print(f"Error in save_all_results: {type(e).__name__}: {e}")

print("\nDone.")
