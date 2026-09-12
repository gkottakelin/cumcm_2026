from typing import Any

import numpy as np
from geometry import (
    Vec2,
    clip_convex_polygon_by_halfplane,
    direction_vector,
    polygon_area,
    polygon_diameter,
    regular_polygon_vertices,
    smallest_enclosing_circle,
)

OMEGA_RADIUS: float = 1800.0
OMEGA: np.ndarray = regular_polygon_vertices(256, OMEGA_RADIUS)
DELTA_DEG: float = 1.0
DELTA_RAD: float = np.deg2rad(DELTA_DEG)
CLEAR_RADIUS: float = 20.0


def sector_halfplanes(
    s: Vec2,
    theta: float,
    delta: float = DELTA_RAD,
) -> tuple[Vec2, Vec2, Vec2, Vec2]:
    u_left = direction_vector(theta - delta)
    u_right = direction_vector(theta + delta)
    n_left = np.array([-u_left[1], u_left[0]])
    n_right = np.array([u_right[1], -u_right[0]])
    return s, n_left, s, n_right


def intersect_with_sector(
    polygon: np.ndarray,
    s: Vec2,
    theta: float,
    delta: float = DELTA_RAD,
) -> np.ndarray:
    _, n_left, _, n_right = sector_halfplanes(s, theta, delta)
    poly = clip_convex_polygon_by_halfplane(polygon, s, n_left)
    if len(poly) == 0:
        return poly
    return clip_convex_polygon_by_halfplane(poly, s, n_right)


def compute_region(
    measurements: list[tuple[Vec2, float]], omega: np.ndarray | None = None
) -> np.ndarray:
    if omega is None:
        omega = OMEGA.copy()
    poly = omega.copy()
    for s, theta in measurements:
        poly = intersect_with_sector(poly, s, theta)
        if len(poly) == 0:
            break
    return poly


def simulate_bearing(
    true_pos: Vec2, sensor_pos: Vec2, delta_deg: float = DELTA_DEG
) -> float:
    true_bearing = np.arctan2(true_pos[1] - sensor_pos[1], true_pos[0] - sensor_pos[0])
    error = np.random.uniform(-np.deg2rad(delta_deg), np.deg2rad(delta_deg))
    return (true_bearing + error) % (2 * np.pi)


def region_metrics(poly: np.ndarray) -> dict[str, Any]:
    if len(poly) == 0:
        return {
            "area": 0.0,
            "diameter": 0.0,
            "min_enclosing_radius": 0.0,
            "min_enclosing_center": np.array([0.0, 0.0]),
            "vertex_count": 0,
            "is_empty": True,
            "is_degenerate": False,
            "r_le_d_over_2": True,
            "clearable": False,
        }
    if len(poly) < 3:
        d = polygon_diameter(poly)
        if len(poly) == 2:
            c = (poly[0] + poly[1]) / 2
            r = d / 2
        else:
            c = poly[0]
            r = 0.0
        return {
            "area": 0.0,
            "diameter": d,
            "min_enclosing_radius": r,
            "min_enclosing_center": c,
            "vertex_count": len(poly),
            "is_empty": False,
            "is_degenerate": True,
            "r_le_d_over_2": True,
            "clearable": r <= CLEAR_RADIUS,
        }
    center, radius = smallest_enclosing_circle(poly)
    d = polygon_diameter(poly)
    return {
        "area": polygon_area(poly),
        "diameter": d,
        "min_enclosing_radius": radius,
        "min_enclosing_center": center,
        "vertex_count": len(poly),
        "is_empty": False,
        "is_degenerate": False,
        "r_le_d_over_2": radius <= d / 2 + 1e-12,
        "clearable": radius <= CLEAR_RADIUS,
    }


def candidate_grid_for_second_point(
    first_s: Vec2,
    first_theta: float,
    grid_spacing: float = 50.0,
    max_distance: float = 2500.0,
) -> np.ndarray:
    u = direction_vector(first_theta)
    n = np.array([-u[1], u[0]])
    candidates: list[Vec2] = []
    for a in np.arange(-max_distance, max_distance + grid_spacing, grid_spacing):
        for b in np.arange(-max_distance, max_distance + grid_spacing, grid_spacing):
            pt = first_s + a * u + b * n
            dist = float(np.linalg.norm(pt - first_s))
            if 100 <= dist <= max_distance and np.linalg.norm(pt) <= 2800:
                candidates.append(pt)
    return np.array(candidates) if candidates else np.empty((0, 2))


def worst_case_diameter_after_second(
    region_poly: np.ndarray,
    candidate_s: Vec2,
    delta: float = DELTA_RAD,
    n_angle_samples: int = 36,
) -> float:
    """Worst-case remaining diameter when measuring at `candidate_s`.

    For every representative source position in the region, the reported
    bearing may deviate by up to +-delta, so the score takes the maximum
    remaining diameter over the error endpoints and the error-free line.
    This is a conservative *ranking* heuristic; clear certificates never
    use it.
    """
    if len(region_poly) < 2:
        return 0.0
    test_points = list(region_poly)
    for i in range(len(region_poly)):
        for t in np.linspace(0.2, 0.8, 3):
            pt = region_poly[i] + t * (
                region_poly[(i + 1) % len(region_poly)] - region_poly[i]
            )
            test_points.append(pt)
    max_d = 0.0
    for g in test_points:
        theta_g = float(np.arctan2(g[1] - candidate_s[1], g[0] - candidate_s[0]))
        for error in (-delta, 0.0, delta):
            poly = intersect_with_sector(region_poly, candidate_s, theta_g + error)
            d = polygon_diameter(poly) if len(poly) >= 2 else 0.0
            max_d = max(max_d, d)
    return max_d


def no_signal_constraint(s: Vec2) -> tuple[np.ndarray, np.ndarray]:
    return s, np.array([0.0, 0.0])


def apply_no_signal(
    polygon: np.ndarray, s: Vec2, exclude_radius: float = 1000.0
) -> np.ndarray:
    if len(polygon) == 0:
        return polygon
    n_pts = 64
    angles = np.linspace(0, 2 * np.pi, n_pts, endpoint=False)
    circle_pts = s + exclude_radius * np.column_stack([np.cos(angles), np.sin(angles)])
    for pt in circle_pts:
        outward = pt - s
        n_len = float(np.linalg.norm(outward))
        if n_len < 1e-12:
            continue
        polygon = clip_convex_polygon_by_halfplane(polygon, pt, outward / n_len)
        if len(polygon) == 0:
            break
    return polygon
