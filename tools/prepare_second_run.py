"""Export a second-sampled 96-satellite window and precompute TinyLEO MPC."""
import argparse
import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'network_synthesizer'), str(ROOT / 'network_orchestrator')]
import numpy as np
from scipy.sparse import csr_matrix
from second_orbits import propagate, period_seconds
from utils import coverage_eta
from orbital_texture_generator import TextureGenerator
from canada_parity_artifacts import build_canada_traffic_matrix
from sn_orchestrator_mpc import predict_all_topologies, generate_topology_for_timestamp


def prepare(source, output, duration, anchor):
    if output.exists():
        raise ValueError('Use a new output directory to preserve previous experiments')
    output.mkdir(parents=True)
    artifacts = output / 'artifacts'
    artifacts.mkdir()
    topology = output / 'topology'
    topology.mkdir()
    original = np.load(source / 'artifacts/canada_parity_satellite_data.npy', allow_pickle=True)
    if len(original) != 96 or any(abs(float(row[0][0]) - 573.0) > 1e-6 for row in original):
        raise ValueError('This importer requires the archived 96-satellite, 573-km profile')
    rows = np.empty(original.shape, dtype=object)
    times = np.arange(duration + 1, dtype=float)
    mapping = {i: {g: [] for g in range(121)} for i in range(len(times))}
    grid = TextureGenerator.__new__(TextureGenerator)
    max_jump = 0.
    for sid, row in enumerate(original):
        height, inc, _ = row[0]
        step = 2 * coverage_eta(period_seconds(height))
        # Match the archived anchor exactly; do not reuse its incorrect Earth rotation.
        total_slots = 308  # Archived 573-km texture period; guarded above.
        phase = ((int(row[1][0]) + anchor) % total_slots) * step
        anchor_lon, anchor_lat = row[3][anchor]
        positions = propagate(height, inc, phase, anchor_lon, times)
        if abs(positions[0][1] - anchor_lat) > 1e-8:
            raise ValueError('Archived phase/latitude mismatch')
        cells = [grid._create_new_grid_satellites(p) for p in positions]
        columns = [i * 121 + g for i, g in enumerate(cells)]
        coverage = csr_matrix((np.ones(len(times)), ([0] * len(times), columns)), shape=(1, len(times) * 121))
        # alpha0 now expresses the Earth-fixed orbital-plane orientation at t=0.
        theta = math.atan2(math.cos(inc) * math.sin(phase), math.cos(phase))
        rows[sid] = [[height, inc, anchor_lon - theta], [phase / step], coverage, positions, 1]
        for i, g in enumerate(cells):
            mapping[i][g].append(sid)
        for a, b in zip(positions, positions[1:]):
            delta = math.acos(min(1., max(-1., math.sin(a[1])*math.sin(b[1])+math.cos(a[1])*math.cos(b[1])*math.cos(a[0]-b[0]))))
            max_jump = max(max_jump, delta * (6371 + height))
    np.save(artifacts / 'satellites.npy', rows)
    np.save(artifacts / 'grids.npy', mapping)
    np.save(artifacts / 'traffic.npy', build_canada_traffic_matrix())
    shutil.copy2(source / 'artifacts/block_positions.json', artifacts / 'block_positions.json')
    meta = {'sample_interval_s': 1.0, 'duration_s': duration, 'num_epochs': len(times),
            'simulation_times_s': times.tolist(), 'anchor_epoch': anchor,
            'source': str(source.resolve()), 'satellites': len(rows),
            'max_one_second_displacement_km': max_jump,
            'orbit_model': 'circular Kepler, spherical Earth, 86400-second Earth rotation'}
    (output / 'time-axis.json').write_text(json.dumps(meta, indent=2))
    kwargs = dict(satellite_file=str(artifacts / 'satellites.npy'),
                  traffic_matrix_file=str(artifacts / 'traffic.npy'),
                  grid_satellites_file=str(artifacts / 'grids.npy'), num_processes=6, start_epoch=0)
    predict_all_topologies(duration=len(times), result_output_dir=str(topology), **kwargs)
    for epoch in range(len(times)):
        generate_topology_for_timestamp(timestamp=epoch, output_dir=str(topology),
            block_positions_file=str(artifacts / 'block_positions.json'), num_epochs=len(times), **kwargs)
    print(json.dumps(meta))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path, help='Archived scale-96 directory')
    p.add_argument('output', type=Path)
    p.add_argument('--duration', type=int, default=300)
    p.add_argument('--anchor', type=int, default=5)
    args = p.parse_args()
    if args.duration < 1 or not 0 <= args.anchor < 12:
        p.error('duration must be positive and anchor in 0..11')
    prepare(args.source, args.output, args.duration, args.anchor)
