"""Small geodesy helpers (spherical earth is plenty for mission-scale distances)."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Move a point by north/east metres."""
    dlat = north_m / EARTH_RADIUS_M
    dlon = east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]] | list[list[float]]) -> bool:
    """Ray casting on lat/lon; fine for fence-sized polygons away from the poles and antimeridian."""
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i][0], polygon[i][1]
        yj, xj = polygon[j][0], polygon[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def segment_inside_polygon(
    a: tuple[float, float], b: tuple[float, float], polygon: list[list[float]], step_m: float = 10.0
) -> bool:
    """Sample a leg every step_m metres and check each sample is inside the polygon."""
    d = distance_m(a[0], a[1], b[0], b[1])
    n = max(1, int(d // step_m))
    for i in range(n + 1):
        t = i / n
        if not point_in_polygon(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, polygon):
            return False
    return True
