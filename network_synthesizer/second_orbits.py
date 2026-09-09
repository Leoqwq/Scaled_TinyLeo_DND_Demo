"""Circular-orbit propagation on an explicit SI-second time axis.

Coordinates use the same spherical Earth as TinyLEO (6371 km). Earth-fixed
longitude advances with orbital motion and subtracts Earth's rotation, not
orbital angular velocity. This model does not claim TLE/SGP4 perturbations.
"""
import math

MU = 3.986e14
EARTH_RADIUS_M = 6371e3
EARTH_DAY_S = 86400.0


def period_seconds(height_km):
    return 2 * math.pi * math.sqrt((EARTH_RADIUS_M + height_km * 1000) ** 3 / MU)


def propagate(height_km, inclination, phase_rad, longitude_rad, times_s):
    """Anchor at an existing longitude and orbital phase, then advance in seconds."""
    n = 2 * math.pi / period_seconds(height_km)
    theta0 = math.atan2(math.cos(inclination) * math.sin(phase_rad), math.cos(phase_rad))
    raan0 = longitude_rad - theta0
    result = []
    for seconds in times_s:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('times must be finite nonnegative seconds')
        phase = phase_rad + n * seconds
        latitude = math.asin(math.sin(inclination) * math.sin(phase))
        theta = math.atan2(math.cos(inclination) * math.sin(phase), math.cos(phase))
        longitude = (raan0 + theta - 2 * math.pi * seconds / EARTH_DAY_S + math.pi) % (2 * math.pi) - math.pi
        result.append((longitude, latitude))
    return result
