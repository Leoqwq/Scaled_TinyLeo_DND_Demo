"""Absolute monotonic schedule. Emit deadline evidence instead of slowing time."""
import time


def run_seconds(count, apply, emit, interval=1.0, clock=time.monotonic, sleep=time.sleep):
    if count < 1 or interval <= 0:
        raise ValueError('positive count and interval required')
    origin = clock()
    for epoch in range(count):
        target = origin + epoch * interval
        sleep(max(0, target - clock()))
        start = clock()
        apply(epoch)
        end = clock()
        emit({'epoch': epoch, 'simulation_time_s': epoch * interval,
              'wall_elapsed_s': end - origin, 'start_lateness_s': start - target,
              'apply_duration_s': end - start,
              'deadline_missed': end > target + interval})
