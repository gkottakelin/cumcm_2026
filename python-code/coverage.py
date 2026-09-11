from typing import Any

import numpy as np
from geometry import Vec2, smallest_enclosing_circle
from localization import (
    CLEAR_RADIUS,
    OMEGA,
    apply_no_signal,
    compute_region,
    intersect_with_sector,
    region_metrics,
    simulate_bearing,
)

SEVEN_POINT_RADIUS: float = 1150.0
SPEED: float = 5.0
MEASURE_TIME: float = 5.0
SWITCH_TIME: float = 1.0
CLEAR_FAIL_TIME: float = 3.0
CLEAR_SUCCESS_TIME: float = 5.0


def seven_cover_points(r: float = SEVEN_POINT_RADIUS) -> list[Vec2]:
    pts = [np.array([0.0, 0.0])]
    for k in range(6):
        ang = k * np.pi / 3
        pts.append(np.array([r * np.cos(ang), r * np.sin(ang)]))
    return pts


def shortest_tour(points: list[Vec2], start: Vec2 | None = None) -> list[Vec2]:
    if not points:
        return []
    remaining = list(points)
    tour = [start] if start is not None else [remaining.pop(0)]
    while remaining:
        idx = int(np.argmin([np.linalg.norm(tour[-1] - p) for p in remaining]))
        tour.append(remaining.pop(idx))
    return tour


def path_length(path: list[Vec2]) -> float:
    return sum(
        float(np.linalg.norm(path[i] - path[i + 1])) for i in range(len(path) - 1)
    )


class SourceSimulator:
    def __init__(
        self,
        true_pos: Vec2,
        source_type: str = "omni",
        receive_radius: float = 1250.0,
        direction_angle: float = 0.0,
    ) -> None:
        self.true_pos = true_pos
        self.source_type = source_type
        self.receive_radius = receive_radius
        self.direction_angle = direction_angle
        self.cleared = False
        self.clear_failures = 0

    def can_detect(self, sensor_pos: Vec2) -> bool:
        dist = float(np.linalg.norm(sensor_pos - self.true_pos))
        if dist > self.receive_radius:
            return False
        if self.source_type == "directional":
            d = np.array([np.cos(self.direction_angle), np.sin(self.direction_angle)])
            return float(np.dot(d, sensor_pos - self.true_pos)) >= 0
        return True

    def measure(self, sensor_pos: Vec2) -> str | None:
        if not self.can_detect(sensor_pos):
            return "no_signal"
        dist = float(np.linalg.norm(sensor_pos - self.true_pos))
        if dist <= 5.0:
            return "near"
        return "direction"

    def try_clear(self, sensor_pos: Vec2, region_poly: np.ndarray) -> bool:
        dist = float(np.linalg.norm(sensor_pos - self.true_pos))
        if dist <= 5.0:
            self.cleared = True
            return True
        if len(region_poly) == 0:
            return False
        center, radius = smallest_enclosing_circle(region_poly)
        if radius <= CLEAR_RADIUS:
            if float(np.linalg.norm(self.true_pos - center)) <= CLEAR_RADIUS:
                self.cleared = True
                return True
            self.clear_failures += 1
        return False


class ChannelState:
    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id
        self.region_poly = OMEGA.copy()
        self.measurements: list[tuple[Vec2, float]] = []
        self.detected = False
        self.cleared = False
        self.measure_count = 0
        self.last_scan_point: Vec2 | None = None
        self.clear_failures = 0
        self.source: SourceSimulator | None = None

    def add_measurement(self, s: Vec2, theta: float | None) -> None:
        if theta is not None:
            self.measurements.append((s, theta))
            self.region_poly = compute_region(self.measurements)
            self.detected = True
            self.measure_count += 1
            self.last_scan_point = s

    def add_no_signal(self, s: Vec2) -> None:
        self.region_poly = apply_no_signal(self.region_poly, s)
        self.last_scan_point = s

    def add_near(self, s: Vec2) -> None:
        self.region_poly = intersect_with_sector(
            self.region_poly,
            s,
            0.0,
            np.deg2rad(90.0),
        )

    def format_metrics(self) -> dict[str, Any]:
        m = region_metrics(self.region_poly)
        m["detected"] = self.detected
        m["cleared"] = self.cleared
        m["channel"] = self.channel_id
        m["measure_count"] = self.measure_count
        return m


class PathScheduler:
    def __init__(self, cover_points: list[Vec2] | None = None) -> None:
        if cover_points is None:
            cover_points = seven_cover_points()
        self.cover_tour = shortest_tour(cover_points)
        self.current_pos: Vec2 = np.array([0.0, 0.0])
        self.remaining_cover = list(self.cover_tour)
        self.pending_tasks: list[tuple[Vec2, str, int]] = []
        self.total_move_dist = 0.0
        self.total_measures = 0
        self.total_switches = 0
        self.total_clear_fails = 0
        self.total_clear_success = 0

    def distance_to(self, pt: Vec2) -> float:
        return float(np.linalg.norm(self.current_pos - pt))

    def travel_to(self, pt: Vec2) -> float:
        d = self.distance_to(pt)
        self.total_move_dist += d
        self.current_pos = pt
        return d

    def insert_clear_point(self, clear_pt: Vec2) -> None:
        best_idx = 0
        best_cost = float("inf")
        for i in range(len(self.remaining_cover) + 1):
            prev = self.current_pos if i == 0 else self.remaining_cover[i - 1]
            next_pt = self.remaining_cover[i] if i < len(self.remaining_cover) else None
            if next_pt is None:
                cost = float(np.linalg.norm(prev - clear_pt))
            else:
                cost = (
                    float(np.linalg.norm(prev - clear_pt))
                    + float(np.linalg.norm(clear_pt - next_pt))
                    - float(np.linalg.norm(prev - next_pt))
                )
            if cost < best_cost:
                best_cost = cost
                best_idx = i
        self.remaining_cover.insert(best_idx, clear_pt)

    def next_action(self) -> Vec2 | None:
        if not self.remaining_cover:
            return None
        return self.remaining_cover[0]


def run_omni_simulation(
    sources: list[SourceSimulator],
    n_freq: int = 16,
    seed: int = 42,
    epsilon: float = 2.0,
) -> dict[str, Any]:
    channels = [ChannelState(i) for i in range(n_freq)]
    for i, src in enumerate(sources):
        channels[i].source = src
    scheduler = PathScheduler()
    cover_points = seven_cover_points()
    scan_order = shortest_tour(cover_points)
    clear_threshold = CLEAR_RADIUS - epsilon
    time = 0.0

    for scan_pt in scan_order:
        d = scheduler.travel_to(scan_pt)
        time += d / SPEED
        for ch in channels:
            if ch.cleared:
                continue
            src = ch.source
            if src is None:
                continue
            scheduler.total_switches += 1
            time += SWITCH_TIME
            result = src.measure(scan_pt)
            scheduler.total_measures += 1
            time += MEASURE_TIME
            if result == "direction":
                theta = simulate_bearing(src.true_pos, scan_pt)
                ch.add_measurement(scan_pt, theta)
                ch.detected = True
            elif result == "no_signal":
                if ch.detected:
                    ch.add_no_signal(scan_pt)
            elif result == "near":
                src.cleared = True
                ch.cleared = True
                scheduler.total_clear_success += 1
                time += CLEAR_SUCCESS_TIME
            met = region_metrics(ch.region_poly)
            if (
                ch.detected
                and not ch.cleared
                and met["min_enclosing_radius"] <= clear_threshold
            ):
                c = met["min_enclosing_center"]
                d2 = scheduler.travel_to(c)
                time += d2 / SPEED
                if src.try_clear(c, ch.region_poly):
                    ch.cleared = True
                    scheduler.total_clear_success += 1
                    time += CLEAR_SUCCESS_TIME
                else:
                    scheduler.total_clear_fails += 1
                    time += CLEAR_FAIL_TIME

    cleared_count = sum(1 for ch in channels if ch.cleared)
    return {
        "cleared": cleared_count,
        "total": len(sources),
        "ratio": cleared_count / max(len(sources), 1),
        "time": time,
        "move_dist": scheduler.total_move_dist,
        "measures": scheduler.total_measures,
        "switches": scheduler.total_switches,
        "clear_fails": scheduler.total_clear_fails,
    }


def run_directional_simulation(
    sources: list[SourceSimulator],
    n_freq: int = 16,
    seed: int = 42,
    epsilon: float = 2.0,
) -> dict[str, Any]:
    channels = [ChannelState(i) for i in range(n_freq)]
    for i, src in enumerate(sources):
        channels[i].source = src
    scheduler = PathScheduler()
    clear_threshold = CLEAR_RADIUS - epsilon
    time = 0.0
    cover_points = seven_cover_points()
    scan_order = shortest_tour(cover_points)

    for scan_pt in scan_order:
        d = scheduler.travel_to(scan_pt)
        time += d / SPEED
        for ch in channels:
            if ch.cleared:
                continue
            src = ch.source
            if src is None:
                continue
            scheduler.total_switches += 1
            time += SWITCH_TIME
            result = src.measure(scan_pt)
            scheduler.total_measures += 1
            time += MEASURE_TIME
            if result == "direction":
                theta = simulate_bearing(src.true_pos, scan_pt)
                ch.add_measurement(scan_pt, theta)
                ch.detected = True
            elif result == "near":
                src.cleared = True
                ch.cleared = True
                scheduler.total_clear_success += 1
                time += CLEAR_SUCCESS_TIME
            met = region_metrics(ch.region_poly)
            if (
                ch.detected
                and not ch.cleared
                and met["min_enclosing_radius"] <= clear_threshold
            ):
                c = met["min_enclosing_center"]
                d2 = scheduler.travel_to(c)
                time += d2 / SPEED
                if src.try_clear(c, ch.region_poly):
                    ch.cleared = True
                    scheduler.total_clear_success += 1
                    time += CLEAR_SUCCESS_TIME
                else:
                    scheduler.total_clear_fails += 1
                    time += CLEAR_FAIL_TIME

    cleared_count = sum(1 for ch in channels if ch.cleared)
    return {
        "cleared": cleared_count,
        "total": len(sources),
        "ratio": cleared_count / max(len(sources), 1),
        "time": time,
        "move_dist": scheduler.total_move_dist,
        "measures": scheduler.total_measures,
        "switches": scheduler.total_switches,
        "clear_fails": scheduler.total_clear_fails,
    }
