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
from localization import intersect_with_sector

ARENA_RADIUS = 1800.0
MAX_RECEIVE_RADIUS = 1500.0
CLEAR_RADIUS = 20.0
SAFE_CLEAR_RADIUS = 18.0
CHANNELS = range(1, 21)
PROBLEM3 = 3
PROBLEM4 = 4
PROBLEM4_GRID_SPACING = 700.0
ROBOT_SEARCH_RADIUS = 2800.0
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
            detail = f"direction {bearing_deg:.2f} deg"
        else:
            detail = outcome
        print(
            f"MEASURE ch={channel:02d} pos={_format_position(position)} "
            f"-> {detail}; t={virtual_time}s",
            flush=True,
        )
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

        # A square lattice extending beyond the source arena.  Every possible
        # source lies in the convex hull of nearby scan points no farther than
        # 1000 m, so an arbitrary 180-degree emission half-plane contains at
        # least one of those points.  Rows are snaked to shorten the route.
        coordinates = np.arange(-2100.0, 2100.1, PROBLEM4_GRID_SPACING)
        points: list[np.ndarray] = []
        for row_index, y in enumerate(coordinates):
            row = [
                np.array([x, y])
                for x in coordinates
                if math.hypot(float(x), float(y)) <= ROBOT_SEARCH_RADIUS
            ]
            if row_index % 2:
                row.reverse()
            points.extend(row)
        return points

    def scan_coverage_points(self) -> None:
        points = self._coverage_points()
        for point_index, point in enumerate(points, start=1):
            print(
                f"\n[coverage {point_index}/{len(points)}] {_format_position(point)}",
                flush=True,
            )
            for channel in CHANNELS:
                if not self.states[channel].cleared:
                    self._measure(point, channel)

    def _region_summary(
        self, channel: int
    ) -> tuple[np.ndarray | None, float | None]:
        observations = self.states[channel].observations
        if not observations:
            return None, None
        region = belief_region(observations)
        if len(region) == 0:
            print(f"WARNING ch={channel:02d}: bearing intersection is empty")
            return None, None
        center, radius = smallest_enclosing_circle(region)
        print(
            f"LOCATE  ch={channel:02d}: {len(observations)} bearings, "
            f"center={_format_position(center)}, uncertainty={radius:.2f}m",
            flush=True,
        )
        return center, radius

    def refine_and_clear(self, channel: int) -> bool:  # noqa: C901, PLR0912
        state = self.states[channel]
        if state.cleared or not state.observations:
            return state.cleared

        # Existing coverage bearings are often already enough to clear safely.
        for step in range(10):
            center, radius = self._region_summary(channel)
            if (
                center is not None
                and radius is not None
                and radius <= SAFE_CLEAR_RADIUS
                and self._clear(center, channel)
            ):
                return True

            if step == 0 and len(state.observations) == 1:
                first_position, first_bearing = state.observations[0]
                forward = direction_vector(first_bearing)
                left = np.array([-forward[1], forward[0]])
                if self.problem == PROBLEM4:
                    # Move toward the source to remain in range.  Trying both
                    # lateral signs guarantees that at least one stays in the
                    # emitting half-plane when the first point is on its edge.
                    targets = (
                        first_position + 500.0 * forward + 350.0 * left,
                        first_position + 500.0 * forward - 350.0 * left,
                    )
                else:
                    targets = (
                        first_position + 750.0 * forward + 500.0 * left,
                        first_position + 750.0 * forward - 500.0 * left,
                    )
                target = targets[0]
            elif step == 1 and len(state.observations) <= 2:  # noqa: PLR2004
                first_position, first_bearing = state.observations[0]
                forward = direction_vector(first_bearing)
                left = np.array([-forward[1], forward[0]])
                if self.problem == PROBLEM4:
                    target = first_position + 500.0 * forward - 350.0 * left
                else:
                    target = first_position + 750.0 * forward - 500.0 * left
            elif center is not None:
                # Surround the current estimate with well-separated viewpoints.
                view_radius = 450.0 if radius is None else max(250.0, 850.0 - radius)
                view_radius = min(view_radius, 650.0)
                target = center + view_radius * direction_vector(step * math.pi / 2)
            else:
                first_position, first_bearing = state.observations[0]
                target = first_position + (500.0 + 50.0 * step) * direction_vector(
                    first_bearing
                )

            outcome = self._measure(_inside_arena(target), channel)
            if state.cleared:
                return True
            if outcome not in {"direction", "near"}:
                print(f"REFINE  ch={channel:02d}: no bearing at this viewpoint")

        center, radius = self._region_summary(channel)
        if center is not None and radius is not None and radius <= CLEAR_RADIUS:
            return self._clear(center, channel)
        return False

    def run(self) -> tuple[list[int], list[int]]:
        self.scan_coverage_points()
        detected = [
            channel
            for channel, state in self.states.items()
            if state.observations or state.cleared
        ]
        print(f"\nDetected active channels: {detected}", flush=True)
        for channel in detected:
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
