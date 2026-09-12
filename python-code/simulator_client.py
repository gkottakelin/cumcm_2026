"""Problem 3/4 client for the official jammer simulator.

The simulator accepts JSON POST requests on /enter, /measure, /clear and /exit.
This module deliberately takes the team number from the command line instead of
embedding it in source code.
"""

# The prints are the operator-visible command log of this CLI.
# ruff: noqa: T201

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
from geometry import (
    clip_convex_polygon_by_halfplane,
    direction_vector,
    regular_polygon_vertices,
    smallest_enclosing_circle,
)
from localization import intersect_with_sector, worst_case_diameter_after_second

ARENA_RADIUS = 1800.0
MAX_RECEIVE_RADIUS = 1500.0
MIN_RECEIVE_RADIUS = 1000.0
CLEAR_RADIUS = 20.0
SAFE_CLEAR_RADIUS = 18.0
VIEWPOINT_MOVE_WEIGHT = 1.0
VIEWPOINT_RING_FACTORS = (0.5, 0.75, 1.0, 1.3)
VIEWPOINT_ANGLES = 16
DIRECTIONAL_WALK_OFFSETS = (350.0, 700.0, 1050.0)
DIRECTIONAL_LATERAL_FRACTIONS = (0.35, 0.65)
DIRECTIONAL_LATERAL_OFFSETS = (250.0, 450.0)
SAME_SIDE_PENALTY = 800.0
MEASURE_PLUS_SWITCH_SECONDS = 6.0
CHANNELS = range(1, 21)
PROBLEM3 = 3
PROBLEM4 = 4
PROBLEM4_INTERIOR_STEP = 870.0
PROBLEM4_POLAR_RADIUS = 1850.0
DEFAULT_SIMULATOR_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "Jammers-simulator-win64"
    / "Jammers-simulator"
    / "JammersSimulatorData"
)


class SimulatorError(RuntimeError):
    """Raised when the simulator cannot accept an API operation."""


def require_active_practice(data_dir: Path, expected_problem: int) -> list[Path]:
    """Prove that the simulator's active recovery state is a practice test.

    This check is deliberately fail-closed: missing, unreadable or ambiguous
    state prevents all robot API calls.  Historical files under behavior-logs
    are not considered; only unfinished state under behavior-runs is inspected.
    """
    run_dir = data_dir.resolve() / "behavior-runs"
    if not run_dir.is_dir():
        message = f"practice guard cannot find active-run directory: {run_dir}"
        raise SimulatorError(message)

    files = sorted(path for path in run_dir.rglob("*") if path.is_file())
    if not files:
        message = (
            "practice guard found no active test. Start a practice test in the "
            "simulator first; no API request was sent."
        )
        raise SimulatorError(message)

    practice_proof = False
    formal_proof = False
    problem_numbers: set[int] = set()
    for path in files:
        name = path.name.lower()
        practice_proof |= name.startswith("practice-")
        formal_proof |= name.startswith(("formal-", ".formal-"))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            message = f"practice guard cannot read active state {path}: {exc}"
            raise SimulatorError(message) from exc

        compact = "".join(text.lower().split())
        practice_proof |= any(
            marker in compact
            for marker in (
                '"mode":"practice"',
                '"ticket_type":"practice_ticket_v1"',
                '"package_type":"practice_behavior_log"',
            )
        )
        formal_proof |= any(
            marker in compact
            for marker in (
                '"mode":"formal"',
                '"ticket_type":"activation_ticket_v1"',
                '"package_type":"formal_behavior_log"',
            )
        )
        formal_proof |= any(
            f'"formal_index":{index}' in compact for index in (1, 2, 3)
        )
        for problem in (PROBLEM3, PROBLEM4):
            if f'"problem_no":{problem}' in compact:
                problem_numbers.add(problem)

    if formal_proof:
        message = (
            "PRACTICE GUARD BLOCKED: active simulator state is formal or contains "
            "formal-test evidence. No API request was sent."
        )
        raise SimulatorError(message)
    if not practice_proof:
        message = (
            "PRACTICE GUARD BLOCKED: active state does not contain unambiguous "
            "practice-test evidence. No API request was sent."
        )
        raise SimulatorError(message)
    if problem_numbers != {expected_problem}:
        message = (
            "PRACTICE GUARD BLOCKED: active problem evidence is "
            f"{sorted(problem_numbers)}, but --problem is {expected_problem}. "
            "No API request was sent."
        )
        raise SimulatorError(message)
    return files


class SimulatorClient:
    def __init__(self, port: int, robot_id: str, timeout: float = 10.0) -> None:
        self.base_url = f"http://127.0.0.1:{port}"
        self.robot_id = robot_id
        self.timeout = timeout

    def _post(self, path: str, **extra: object) -> dict[str, Any]:
        payload = {
            "arena_id": "default",
            "robot_id": self.robot_id,
            "request_id": uuid.uuid4().hex,
            **extra,
        }
        request = Request(  # noqa: S310 - URL is fixed to loopback HTTP.
            self.base_url + path,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(  # noqa: S310 - Request URL is fixed to loopback HTTP.
                request, timeout=self.timeout
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = f"POST {path} -> HTTP {exc.code}: {detail}"
            raise SimulatorError(message) from exc
        except (URLError, TimeoutError) as exc:
            message = f"POST {path} failed: {exc}"
            raise SimulatorError(message) from exc
        if not result.get("accepted", False):
            message = f"POST {path} was rejected: {result}"
            raise SimulatorError(message)
        return result

    def enter(self) -> dict[str, Any]:
        return self._post("/enter")

    def measure(self, position: np.ndarray, channel: int) -> dict[str, Any]:
        return self._post(
            "/measure",
            position={"x": float(position[0]), "y": float(position[1])},
            channel=int(channel),
        )

    def clear(self, position: np.ndarray, channel: int) -> dict[str, Any]:
        return self._post(
            "/clear",
            position={"x": float(position[0]), "y": float(position[1])},
            channel=int(channel),
        )

    def exit(self) -> dict[str, Any]:
        return self._post("/exit")


@dataclass
class ChannelState:
    observations: list[tuple[np.ndarray, float]] = field(default_factory=list)
    cleared: bool = False
    attempts: int = 0
    region: np.ndarray | None = None
    region_center: np.ndarray | None = None
    region_radius: float | None = None
    pending_clear: bool = False
    tried_viewpoints: list[np.ndarray] = field(default_factory=list)
    no_signal_viewpoints: list[np.ndarray] = field(default_factory=list)


def _inside_arena(point: np.ndarray, margin: float = 2.0) -> np.ndarray:
    radius = float(np.linalg.norm(point))
    limit = ARENA_RADIUS - margin
    if radius <= limit:
        return point
    return point * (limit / radius)


def _clip_with_disk_polygon(
    polygon: np.ndarray, center: np.ndarray, radius: float, sides: int = 128
) -> np.ndarray:
    """Intersect a convex polygon with a circumscribed polygon containing a disk."""
    circumscribed_radius = radius / math.cos(math.pi / sides)
    disk = regular_polygon_vertices(sides, circumscribed_radius, center)
    result = polygon
    for index, start in enumerate(disk):
        end = disk[(index + 1) % len(disk)]
        edge = end - start
        inward_normal = np.array([-edge[1], edge[0]])
        result = clip_convex_polygon_by_halfplane(result, start, inward_normal)
        if len(result) == 0:
            break
    return result


def belief_region(observations: list[tuple[np.ndarray, float]]) -> np.ndarray:
    sides = 256
    # Circumscribed boundaries avoid excluding a true point because of polygonisation.
    polygon = regular_polygon_vertices(
        sides, ARENA_RADIUS / math.cos(math.pi / sides)
    )
    for position, bearing in observations:
        polygon = intersect_with_sector(polygon, position, bearing)
        if len(polygon) == 0:
            return polygon
        polygon = _clip_with_disk_polygon(
            polygon, position, MAX_RECEIVE_RADIUS, sides=128
        )
        if len(polygon) == 0:
            return polygon
    return polygon


def _format_position(position: np.ndarray) -> str:
    return f"({position[0]:.1f}, {position[1]:.1f})"


def _nearest_neighbor_tour(points: list[np.ndarray]) -> list[np.ndarray]:
    """Order scan points by greedy nearest neighbour starting at the origin."""
    remaining = list(points)
    tour: list[np.ndarray] = []
    current = np.array([0.0, 0.0])
    while remaining:
        distances = [float(np.linalg.norm(current - p)) for p in remaining]
        index = int(np.argmin(distances))
        current = remaining.pop(index)
        tour.append(current)
    return tour


class PracticeRunner:
    def __init__(self, client: SimulatorClient, problem: int = 3) -> None:
        self.client = client
        self.problem = problem
        self.states = {channel: ChannelState() for channel in CHANNELS}
        self.command_count = 0
        self.current_position = np.array([0.0, 0.0])

    def _measure(self, position: np.ndarray, channel: int) -> str:
        if self.problem == PROBLEM3:
            position = _inside_arena(position)
        self.current_position = position.copy()
        result = self.client.measure(position, channel)
        self.command_count += 1
        outcome = str(result.get("measure_result", "unknown"))
        virtual_time = result.get("virtual_time_s", "?")
        if outcome == "direction":
            bearing_deg = float(result["svd_deg"])
            self.states[channel].observations.append(
                (position.copy(), math.radians(bearing_deg))
            )
            self._refresh_region(channel)
            detail = f"direction {bearing_deg:.2f} deg"
        else:
            detail = outcome
        print(
            f"MEASURE ch={channel:02d} pos={_format_position(position)} "
            f"-> {detail}; t={virtual_time}s",
            flush=True,
        )
        if outcome == "no_signal":
            self._apply_no_signal(channel, position)
        if outcome == "near":
            self._clear(position, channel)
        return outcome

    def _clear(self, position: np.ndarray, channel: int) -> bool:
        state = self.states[channel]
        state.attempts += 1
        position = _inside_arena(position)
        self.current_position = position.copy()
        result = self.client.clear(position, channel)
        self.command_count += 1
        success = result.get("clear_result") == "success"
        print(
            f"CLEAR   ch={channel:02d} pos={_format_position(position)} "
            f"-> {result.get('clear_result')}; t={result.get('virtual_time_s', '?')}s",
            flush=True,
        )
        state.cleared = success
        return success

    def _coverage_points(self) -> list[np.ndarray]:
        if self.problem == PROBLEM3:
            ring_radius = 1150.0
            points = [np.array([0.0, 0.0])]
            points.extend(
                ring_radius * direction_vector(math.radians(angle))
                for angle in (0, 60, 120, 180, 240, 300)
            )
            return points

        # Certified sparse layout for Problem 4 (tuning report iter-002):
        # a 5x5 square lattice with 870 m step (extent 1740 m) plus four
        # polar points at 1850 m.  Every arena position lies inside the
        # convex hull of scan points within 980 m (verified numerically on
        # a 5 m sampling grid plus a dense edge annulus), so by the convex
        # combination argument any 180-degree emission half-plane contains
        # a scan point within the 1000 m guaranteed reception radius.  A
        # nearest-neighbour tour from the origin shortens the route.
        step = PROBLEM4_INTERIOR_STEP
        coords = (-2.0 * step, -step, 0.0, step, 2.0 * step)
        points = [np.array([x, y]) for y in coords for x in coords]
        points.extend(
            np.array([sx * PROBLEM4_POLAR_RADIUS, 0.0]) for sx in (1.0, -1.0)
        )
        points.extend(
            np.array([0.0, sy * PROBLEM4_POLAR_RADIUS]) for sy in (1.0, -1.0)
        )
        return _nearest_neighbor_tour(points)

    def _refresh_region(self, channel: int) -> None:
        """Recompute the cached belief region from all stored observations."""
        state = self.states[channel]
        if not state.observations:
            return
        region = belief_region(state.observations)
        if len(region) == 0:
            print(f"WARNING ch={channel:02d}: bearing intersection is empty")
            state.region = region
            state.region_center = None
            state.region_radius = None
            return
        center, radius = smallest_enclosing_circle(region)
        state.region = region
        state.region_center = center
        state.region_radius = radius

    def _region_status(
        self, channel: int
    ) -> tuple[np.ndarray | None, float | None]:
        state = self.states[channel]
        if not state.observations:
            return None, None
        if state.region is None:
            self._refresh_region(channel)
        center, radius = state.region_center, state.region_radius
        if center is not None and radius is not None:
            print(
                f"LOCATE  ch={channel:02d}: {len(state.observations)} bearings, "
                f"center={_format_position(center)}, uncertainty={radius:.2f}m",
                flush=True,
            )
        return center, radius

    def _apply_no_signal(self, channel: int, position: np.ndarray) -> None:
        """Problem 3 only: a detected omnidirectional source must be > 1000 m away."""
        if self.problem != PROBLEM3:
            return
        state = self.states[channel]
        if not state.observations or state.region is None or len(state.region) == 0:
            return
        updated = self._exclude_reception_disk(state.region, position)
        if len(updated) == 0:
            print(
                f"WARNING ch={channel:02d}: no-signal exclusion emptied the "
                "region; keeping previous region"
            )
            return
        state.region = updated
        center, radius = smallest_enclosing_circle(updated)
        state.region_center = center
        state.region_radius = radius

    def _exclude_reception_disk(
        self,
        polygon: np.ndarray,
        center: np.ndarray,
        radius: float = MIN_RECEIVE_RADIUS,
        sides: int = 64,
    ) -> np.ndarray:
        """Remove the reception disk around `center` from a convex polygon.

        Tangent halfplanes sit on a ring whose circumscribed polygon has
        circumradius exactly `radius`, so only points strictly inside the disk
        are removed and the true source position cannot be excluded.
        """
        if len(polygon) == 0:
            return polygon
        ring_radius = radius * math.cos(math.pi / sides)
        result = polygon
        for k in range(sides):
            angle = 2.0 * math.pi * k / sides
            outward = np.array([math.cos(angle), math.sin(angle)])
            point = center + ring_radius * outward
            result = clip_convex_polygon_by_halfplane(result, point, outward)
            if len(result) == 0:
                break
        return result

    def _schedule_clears(self, route: list[tuple]) -> None:
        """Insert clear stops for every channel whose region is safe to clear."""
        for channel in CHANNELS:
            state = self.states[channel]
            if state.cleared or state.pending_clear or not state.observations:
                continue
            if state.region is None:
                self._refresh_region(channel)
            if state.region_center is None or state.region_radius is None:
                continue
            if state.region_radius <= SAFE_CLEAR_RADIUS:
                stop = ("clear", state.region_center.copy(), channel)
                self._insert_stop(route, stop)
                state.pending_clear = True
                print(
                    f"SCHEDULE ch={channel:02d} clear at "
                    f"{_format_position(state.region_center)} "
                    f"(uncertainty {state.region_radius:.1f}m)",
                    flush=True,
                )

    def _insert_stop(self, route: list[tuple], stop: tuple) -> None:
        """Insert a stop where the time detour minus saved scans is smallest."""
        point = stop[1]
        best_index = len(route)
        best_cost = None
        for index in range(len(route) + 1):
            previous = self.current_position if index == 0 else route[index - 1][1]
            if index < len(route):
                following = route[index][1]
                detour = (
                    float(np.linalg.norm(previous - point))
                    + float(np.linalg.norm(point - following))
                    - float(np.linalg.norm(previous - following))
                )
            else:
                detour = float(np.linalg.norm(previous - point))
            remaining_scans = sum(1 for item in route[index:] if item[0] == "scan")
            cost = detour / 5.0 - MEASURE_PLUS_SWITCH_SECONDS * remaining_scans
            if best_cost is None or cost < best_cost - 1e-9:
                best_cost = cost
                best_index = index
        route.insert(best_index, stop)

    def refine_and_clear(self, channel: int) -> bool:
        state = self.states[channel]
        if state.cleared or not state.observations:
            return state.cleared

        for _step in range(10):
            center, radius = self._region_status(channel)
            if (
                center is not None
                and radius is not None
                and radius <= SAFE_CLEAR_RADIUS
                and self._clear(center, channel)
            ):
                return True

            target = self._choose_viewpoint(channel)
            if target is None:
                break
            outcome = self._measure(target, channel)
            if state.cleared:
                return True
            if outcome == "no_signal":
                state.no_signal_viewpoints.append(target.copy())
                print(f"REFINE  ch={channel:02d}: no bearing at this viewpoint")

        center, radius = self._region_status(channel)
        if center is not None and radius is not None and radius <= CLEAR_RADIUS:
            return self._clear(center, channel)
        return False

    def _choose_viewpoint(self, channel: int) -> np.ndarray | None:
        """Pick the next measurement point by minimax shrink plus travel cost."""
        state = self.states[channel]
        if state.region is None or len(state.region) < 3:
            if state.observations:
                position, bearing = state.observations[-1]
                fallback = position + 600.0 * direction_vector(bearing)
                return _inside_arena(fallback) if self.problem == PROBLEM3 else fallback
            return None
        center = state.region_center
        distance = float(np.linalg.norm(self.current_position - center))
        base = min(max(0.6 * distance, 250.0), 800.0)
        # Safe candidates move from a proven observation point toward the
        # estimated source: staying near the observation-to-source line keeps
        # the robot inside a directional source's emitting half-plane.
        safe_candidates: list[np.ndarray] = []
        for observed_position, _ in state.observations[-3:]:
            for fraction in (0.35, 0.55, 0.75):
                candidate = observed_position + fraction * (
                    center - observed_position
                )
                if self.problem == PROBLEM3:
                    candidate = _inside_arena(candidate)
                safe_candidates.append(candidate)
        risky_candidates: list[np.ndarray] = [self.current_position.copy()]
        if self.problem == PROBLEM3:
            for factor in VIEWPOINT_RING_FACTORS:
                ring = base * factor
                for k in range(VIEWPOINT_ANGLES):
                    angle = 2.0 * math.pi * k / VIEWPOINT_ANGLES
                    candidate = center + ring * direction_vector(angle)
                    risky_candidates.append(_inside_arena(candidate))
        else:
            # Problem 4 structured probes: walking the latest bearing line
            # stays inside the emitting half-plane up to the source, and from
            # any safe point at least one of the two lateral offsets is
            # guaranteed receivable (max(x+y, x-y) >= x >= 0).
            latest_position, latest_bearing = state.observations[-1]
            forward = direction_vector(latest_bearing)
            lateral = np.array([-forward[1], forward[0]])
            for offset in DIRECTIONAL_WALK_OFFSETS:
                safe_candidates.append(latest_position + offset * forward)
            for fraction in DIRECTIONAL_LATERAL_FRACTIONS:
                anchor = latest_position + fraction * (
                    center - latest_position
                )
                for lateral_offset in DIRECTIONAL_LATERAL_OFFSETS:
                    safe_candidates.append(anchor + lateral_offset * lateral)
                    safe_candidates.append(anchor - lateral_offset * lateral)
        scored: list[tuple[np.ndarray, bool]] = [
            *[(candidate, False) for candidate in risky_candidates],
            *[(candidate, True) for candidate in safe_candidates],
        ]
        best: np.ndarray | None = None
        best_score = float("inf")
        for candidate, is_safe in scored:
            if any(
                float(np.linalg.norm(candidate - tried)) <= 50.0
                for tried in state.tried_viewpoints
            ):
                continue
            if any(
                float(np.linalg.norm(candidate - observed)) <= 50.0
                for observed, _ in state.observations
            ):
                continue
            penalty = 0.0
            if not is_safe:
                worst_receive = max(
                    float(np.linalg.norm(candidate - vertex)) for vertex in state.region
                )
                if worst_receive > 1150.0:
                    continue
                penalty += 0.5 * max(0.0, worst_receive - MIN_RECEIVE_RADIUS)
            if self.problem == PROBLEM4 and state.no_signal_viewpoints:
                # A no-signal probe marks its side of the region as likely
                # back-plane; prefer flipping to the opposite side.
                for failed in state.no_signal_viewpoints:
                    if float(np.dot(candidate - center, failed - center)) > 0.0:
                        penalty += SAME_SIDE_PENALTY
                        break
            move_time = float(np.linalg.norm(candidate - self.current_position)) / 5.0
            predicted = worst_case_diameter_after_second(state.region, candidate)
            score = predicted + VIEWPOINT_MOVE_WEIGHT * move_time + penalty
            if score < best_score:
                best = candidate
                best_score = score
        if best is None:
            return None
        state.tried_viewpoints.append(best.copy())
        return best

    def _refinement_order(self, detected: list[int]) -> list[int]:
        """Visit remaining channels nearest-region-center first from the robot."""
        remaining = [
            channel
            for channel in detected
            if not self.states[channel].cleared and self.states[channel].observations
        ]
        order: list[int] = []
        position = self.current_position.copy()
        while remaining:
            best_channel = None
            best_distance = float("inf")
            for channel in remaining:
                center = self.states[channel].region_center
                if center is None:
                    continue
                distance = float(np.linalg.norm(position - center))
                if distance < best_distance:
                    best_distance = distance
                    best_channel = channel
            if best_channel is None:
                best_channel = remaining[0]
            order.append(best_channel)
            remaining.remove(best_channel)
            center = self.states[best_channel].region_center
            if center is not None:
                position = center
        return order

    def run(self) -> tuple[list[int], list[int]]:
        coverage_points = self._coverage_points()
        total_points = len(coverage_points)
        route: list[tuple] = [("scan", point) for point in coverage_points]
        scan_index = 0
        while route:
            stop = route.pop(0)
            if stop[0] == "scan":
                scan_index += 1
                point = stop[1]
                print(
                    f"\n[coverage {scan_index}/{total_points}] "
                    f"{_format_position(point)}",
                    flush=True,
                )
                for channel in CHANNELS:
                    if not self.states[channel].cleared:
                        self._measure(point, channel)
                self._schedule_clears(route)
            else:
                _, point, channel = stop
                state = self.states[channel]
                state.pending_clear = False
                if not state.cleared:
                    print(
                        f"\n[route-clear ch={channel:02d}] "
                        f"{_format_position(point)}",
                        flush=True,
                    )
                    self._clear(point, channel)

        detected = [
            channel
            for channel, state in self.states.items()
            if state.observations or state.cleared
        ]
        print(f"\nDetected active channels: {detected}", flush=True)
        for channel in self._refinement_order(detected):
            if not self.states[channel].cleared:
                print(f"\n[localize channel {channel}]", flush=True)
                self.refine_and_clear(channel)
        cleared = [channel for channel in detected if self.states[channel].cleared]
        failed = [channel for channel in detected if not self.states[channel].cleared]
        return cleared, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the complete Problem 3 or 4 practice-test workflow."
    )
    parser.add_argument(
        "--team", required=True, help="team number (not stored in code)"
    )
    parser.add_argument("--port", type=int, default=2026)
    parser.add_argument(
        "--problem", type=int, choices=(PROBLEM3, PROBLEM4), default=PROBLEM3
    )
    parser.add_argument(
        "--simulator-data-dir",
        type=Path,
        default=DEFAULT_SIMULATOR_DATA_DIR,
        help="simulator data directory used by the fail-closed practice guard",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify active practice mode and problem number without sending API calls",
    )
    parser.add_argument(
        "--already-entered",
        action="store_true",
        help="skip /enter when the current session has already been entered",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="do not call /exit after the run (useful for inspecting failures)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = SimulatorClient(args.port, args.team)
    started = time.monotonic()
    try:
        evidence_files = require_active_practice(
            args.simulator_data_dir, args.problem
        )
        print(
            f"PREFLIGHT practice problem {args.problem} verified from "
            f"{len(evidence_files)} active-state file(s)",
            flush=True,
        )
        if args.check_only:
            print("CHECK   passed; no API request was sent", flush=True)
            return 0
        if not args.already_entered:
            entered = client.enter()
            print(
                "ENTER   accepted; "
                f"real remaining={entered.get('remaining_real_duration_s')}s",
                flush=True,
            )
        else:
            print("ENTER   skipped (session already entered)", flush=True)

        runner = PracticeRunner(client, problem=args.problem)
        cleared, failed = runner.run()
        print(
            f"\nSUMMARY detected={len(cleared) + len(failed)}, "
            f"cleared={len(cleared)}, failed={failed}, "
            f"commands={runner.command_count}, wall={time.monotonic() - started:.1f}s",
            flush=True,
        )
        if not args.keep_open:
            try:
                exited = client.exit()
                print(f"EXIT    {exited.get('exit_reason', 'accepted')}", flush=True)
            except SimulatorError as exc:
                print(f"EXIT    session already closed or rejected: {exc}", flush=True)
        return 0 if not failed else 2  # noqa: TRY300
    except (SimulatorError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
