import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'network_synthesizer'), str(ROOT / 'network_orchestrator')]
from second_orbits import propagate, period_seconds
from second_clock import run_seconds


def test_orbit_inertial_period_has_earth_rotation():
    period = period_seconds(573)
    positions = propagate(573, math.radians(60), .3, -2, [0, 1, period])
    assert abs(positions[0][0] + 2) < 1e-12
    assert abs(positions[0][1] - positions[2][1]) < 1e-12
    assert abs((positions[2][0] - positions[0][0]) + 2 * math.pi * period / 86400) < 1e-12
    assert 0 < abs(positions[1][1] - positions[0][1]) < .002


def test_deadline_clock_does_not_accumulate_processing_time():
    now = [0.]
    rows = []
    def sleep(seconds):
        now[0] += seconds
    def apply(epoch):
        now[0] += 1.2 if epoch == 1 else .2
    run_seconds(4, apply, rows.append, clock=lambda: now[0], sleep=sleep)
    assert [round(r['wall_elapsed_s'], 1) for r in rows] == [.2, 2.2, 2.4, 3.2]
    assert [r['deadline_missed'] for r in rows] == [False, True, False, False]
