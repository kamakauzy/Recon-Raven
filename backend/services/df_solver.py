"""
DF Solver — Direction Finding triangulation from bearing measurements.

Takes 2+ bearing measurements from different GPS positions and estimates
the transmitter location via least-squares intersection.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger("raven.df")

EARTH_RADIUS_M = 6_371_000


@dataclass
class DFMeasurement:
    """A single DF bearing measurement."""

    latitude: float  # observer lat
    longitude: float  # observer lon
    bearing_deg: float  # bearing to transmitter (true north)
    power_db: float  # received power
    freq_mhz: float
    timestamp: Optional[datetime] = None
    confidence: float = 1.0  # weight for solver


@dataclass
class DFEstimate:
    """Estimated transmitter location."""

    latitude: float
    longitude: float
    cep_m: float  # Circular Error Probable (50% confidence radius)
    num_bearings: int
    residual: float  # optimization residual


def _bearing_line_distance(
    tx_lat: float, tx_lon: float, obs_lat: float, obs_lon: float, bearing_deg: float
) -> float:
    """
    Compute perpendicular distance from a point (tx) to a bearing line
    originating from (obs) at the given bearing.
    Uses flat-earth approximation (fine for <50 km distances).
    """
    # Convert to radians
    lat1 = math.radians(obs_lat)
    lon1 = math.radians(obs_lon)
    lat2 = math.radians(tx_lat)
    lon2 = math.radians(tx_lon)
    bearing = math.radians(bearing_deg)

    # Flat-earth delta in meters
    dlat = (lat2 - lat1) * EARTH_RADIUS_M
    dlon = (lon2 - lon1) * EARTH_RADIUS_M * math.cos(lat1)

    # Bearing line direction vector
    bx = math.sin(bearing)
    by = math.cos(bearing)

    # Cross product gives perpendicular distance
    cross = dlat * bx - dlon * by
    return abs(cross)


def solve_triangulation(measurements: List[DFMeasurement]) -> Optional[DFEstimate]:
    """
    Find transmitter location from 2+ bearing measurements.
    Uses weighted least-squares minimization of perpendicular distances
    from candidate TX position to each bearing line.
    """
    if len(measurements) < 2:
        logger.warning("Need at least 2 measurements for triangulation")
        return None

    # Initial guess: centroid of observer positions
    lat0 = np.mean([m.latitude for m in measurements])
    lon0 = np.mean([m.longitude for m in measurements])

    # Offset initial guess along average bearing
    avg_bearing = np.mean([m.bearing_deg for m in measurements])
    # Move 500m in average bearing direction
    lat0 += 500 * math.cos(math.radians(avg_bearing)) / EARTH_RADIUS_M * (180 / math.pi)
    lon0 += (
        500
        * math.sin(math.radians(avg_bearing))
        / (EARTH_RADIUS_M * math.cos(math.radians(lat0)))
        * (180 / math.pi)
    )

    def cost(params):
        tx_lat, tx_lon = params
        total = 0
        for m in measurements:
            dist = _bearing_line_distance(
                tx_lat, tx_lon, m.latitude, m.longitude, m.bearing_deg
            )
            total += (dist * m.confidence) ** 2
        return total

    result = minimize(
        cost,
        [lat0, lon0],
        method="Nelder-Mead",
        options={"xatol": 1e-7, "fatol": 1.0, "maxiter": 5000},
    )

    if not result.success:
        logger.warning("Triangulation solver did not converge: %s", result.message)

    tx_lat, tx_lon = result.x
    residual = math.sqrt(result.fun / len(measurements))

    # CEP estimate from residual (rough: residual ≈ average error in meters)
    cep = max(residual, 10)  # minimum 10m

    estimate = DFEstimate(
        latitude=round(tx_lat, 7),
        longitude=round(tx_lon, 7),
        cep_m=round(cep, 1),
        num_bearings=len(measurements),
        residual=round(residual, 1),
    )

    logger.info(
        "DF estimate: %.6f, %.6f (CEP %.0fm from %d bearings)",
        estimate.latitude,
        estimate.longitude,
        estimate.cep_m,
        estimate.num_bearings,
    )

    return estimate


def compute_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute bearing from point 1 to point 2 in degrees."""
    lat1, lon1 = math.radians(lat1), math.radians(lon1)
    lat2, lon2 = math.radians(lat2), math.radians(lon2)

    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        dlon
    )

    bearing = math.atan2(x, y)
    return (math.degrees(bearing) + 360) % 360


def compute_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute distance between two points in meters (haversine)."""
    lat1, lon1 = math.radians(lat1), math.radians(lon1)
    lat2, lon2 = math.radians(lat2), math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(a))
