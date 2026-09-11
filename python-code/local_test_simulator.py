"""Local, deterministic simulator for Problem 3 and Problem 4 regression tests.

This program is intentionally isolated from the official simulator.  It binds
only to loopback, refuses the official port 2026, and exposes ground truth so a
test harness can detect missed (rather than merely uncleared) jammers.
"""

# The CLI prints operator-facing status information.
# ruff: noqa: CPY001, EM101, T201, TRY003

from __future__ import annotations

import argparse
import hashlib
import json
import math
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, Final

import numpy as np

OFFICIAL_PORT: Final = 2026
DEFAULT_LOCAL_PORT: Final = 2027
PROBLEM3: Final = 3
PROBLEM4: Final = 4
ARENA_RADIUS: Final = 1800.0
MIN_RECEIVE_RADIUS: Final = 1000.0
MAX_RECEIVE_RADIUS: Final = 1500.0
NEAR_RADIUS: Final = 5.0
CLEAR_RADIUS: Final = 20.0
ROBOT_SPEED: Final = 5.0
MEASURE_DURATION: Final = 5.0
CHANNEL_SWITCH_DURATION: Final = 1.0
CLEAR_SUCCESS_DURATION: Final = 5.0
CLEAR_FAILURE_DURATION: Final = 3.0
BEARING_ERROR_LIMIT_DEG: Final = 1.0
FLOAT_TOLERANCE: Final = 1e-9
CHANNELS: Final = tuple(range(1, 21))


class LocalSimulatorError(RuntimeError):
    """Raised when a local test request violates the simulator protocol."""


@dataclass
class Jammer:
    """Ground-truth state for one radio jammer."""

    channel: int
    x: float
    y: float
    receive_radius: float
    source_type: str
    emission_direction_deg: float | None
    cleared: bool = False

    @property
    def position(self) -> np.ndarray:
        """Return the jammer position as a two-dimensional vector."""
        return np.array([self.x, self.y], dtype=float)

    def can_be_received_at(self, robot_position: np.ndarray) -> bool:
        """Apply the range and, for directional sources, half-plane tests."""
        displacement = robot_position - self.position
        if float(np.linalg.norm(displacement)) > self.receive_radius + FLOAT_TOLERANCE:
            return False
        if self.source_type == "directional":
            if self.emission_direction_deg is None:
                raise LocalSimulatorError("directional jammer has no direction")
            angle = math.radians(self.emission_direction_deg)
            direction = np.array([math.cos(angle), math.sin(angle)])
            return float(np.dot(direction, displacement)) >= -FLOAT_TOLERANCE
        return True


@dataclass
class SimulationStatistics:
    """Command and virtual-time counters for one generated case."""

    measure_count: int = 0
    clear_success_count: int = 0
    clear_failure_count: int = 0
    channel_switch_count: int = 0
    movement_distance: float = 0.0
    movement_time_s: float = 0.0
    measurement_time_s: float = 0.0
    channel_switch_time_s: float = 0.0
    clear_time_s: float = 0.0
    virtual_time_s: float = 0.0


def _random_point_in_disk(rng: np.random.Generator) -> tuple[float, float]:
    radius = ARENA_RADIUS * math.sqrt(float(rng.random()))
    angle = float(rng.uniform(0.0, 2.0 * math.pi))
    return radius * math.cos(angle), radius * math.sin(angle)


def generate_case(
    problem: int,
    seed: int,
    source_count: int | None = None,
    directional_count: int | None = None,
) -> list[Jammer]:
    """Generate a reproducible case satisfying the stated geometric rules."""
    if problem not in {PROBLEM3, PROBLEM4}:
        raise ValueError("problem must be 3 or 4")
    rng = np.random.default_rng(seed)
    if source_count is None:
        source_count = 13 if problem == PROBLEM3 else 16
    if not 1 <= source_count <= len(CHANNELS):
        raise ValueError("source_count must be between 1 and 20")
    if directional_count is None:
        directional_count = 0 if problem == PROBLEM3 else 5
    if problem == PROBLEM3 and directional_count != 0:
        raise ValueError("Problem 3 may contain only omnidirectional sources")
    if not 0 <= directional_count <= source_count:
        raise ValueError("directional_count must be between 0 and source_count")

    selected_channels = rng.choice(CHANNELS, size=source_count, replace=False)
    source_types = ["directional"] * directional_count + ["omnidirectional"] * (
        source_count - directional_count
    )
    rng.shuffle(source_types)
    jammers: list[Jammer] = []
    for channel, source_type in zip(selected_channels, source_types, strict=True):
        x, y = _random_point_in_disk(rng)
        emission_direction = (
            float(rng.uniform(0.0, 360.0)) if source_type == "directional" else None
        )
        jammers.append(
            Jammer(
                channel=int(channel),
                x=x,
                y=y,
                receive_radius=float(
                    rng.uniform(MIN_RECEIVE_RADIUS, MAX_RECEIVE_RADIUS)
                ),
                source_type=source_type,
                emission_direction_deg=emission_direction,
            )
        )
    return sorted(jammers, key=lambda jammer: jammer.channel)


class LocalSimulator:
    """State machine implementing the four loopback JSON endpoints."""

    def __init__(
        self,
        problem: int,
        seed: int,
        source_count: int | None = None,
        directional_count: int | None = None,
        event_log_path: Path | None = None,
    ) -> None:
        self.problem = problem
        self.seed = seed
        self.jammers = generate_case(
            problem,
            seed,
            source_count=source_count,
            directional_count=directional_count,
        )
        self.statistics = SimulationStatistics()
        self.entered = False
        self.exited = False
        self.robot_id: str | None = None
        self.robot_position = np.array([0.0, 0.0])
        self.current_channel: int | None = None
        self.seen_request_ids: set[str] = set()
        self.command_log: list[dict[str, Any]] = []
        self.trajectory: list[dict[str, Any]] = [
            {
                "event_sequence": 0,
                "action": "start",
                "channel": None,
                "x": 0.0,
                "y": 0.0,
                "segment_distance_m": 0.0,
                "cumulative_distance_m": 0.0,
                "arrival_virtual_time_s": 0.0,
            }
        ]
        self.event_log_path = event_log_path.resolve() if event_log_path else None
        self.event_log_finalized = False
        self.lock = threading.Lock()
        if self.event_log_path is not None:
            self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
            session_record = {
                "record_type": "session_start",
                "log_schema_version": 1,
                "recorded_at_utc": self._utc_now(),
                "local_test": True,
                "problem_no": self.problem,
                "seed": self.seed,
                "initial_position": {"x": 0.0, "y": 0.0},
                "jammers": [asdict(jammer) for jammer in self.jammers],
            }
            self.event_log_path.write_text(
                json.dumps(session_record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds")

    @staticmethod
    def _position_dict(position: np.ndarray) -> dict[str, float]:
        return {"x": float(position[0]), "y": float(position[1])}

    @property
    def jammer_by_channel(self) -> dict[int, Jammer]:
        """Map active and cleared jammer channels to their ground truth."""
        return {jammer.channel: jammer for jammer in self.jammers}

    @property
    def cleared_count(self) -> int:
        """Return the number of ground-truth sources that were cleared."""
        return sum(jammer.cleared for jammer in self.jammers)

    def public_state(self) -> dict[str, Any]:
        """Return local-only ground truth and metrics for regression checks."""
        with self.lock:
            return {
                "log_schema_version": 1,
                "local_test": True,
                "problem_no": self.problem,
                "seed": self.seed,
                "entered": self.entered,
                "exited": self.exited,
                "robot_id": self.robot_id,
                "robot_position": self._position_dict(self.robot_position),
                "current_channel": self.current_channel,
                "jammer_count": len(self.jammers),
                "cleared_count": self.cleared_count,
                "statistics": asdict(self.statistics),
                "channel_summary": self._channel_summary_unlocked(),
                "jammers": [asdict(jammer) for jammer in self.jammers],
                "trajectory": list(self.trajectory),
                "command_log": list(self.command_log),
            }

    def _channel_summary_unlocked(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for channel in CHANNELS:
            jammer = self.jammer_by_channel.get(channel)
            events = [
                event
                for event in self.command_log
                if event.get("channel") == channel and event.get("accepted")
            ]
            measurement_events = [
                event for event in events if event["action"] == "measure"
            ]
            clear_events = [event for event in events if event["action"] == "clear"]
            signal_events = [
                event
                for event in measurement_events
                if event.get("outcome") in {"direction", "near"}
            ]
            summaries.append(
                {
                    "channel": channel,
                    "has_jammer": jammer is not None,
                    "source_type": jammer.source_type if jammer else None,
                    "true_position": (
                        {"x": jammer.x, "y": jammer.y} if jammer else None
                    ),
                    "receive_radius": jammer.receive_radius if jammer else None,
                    "emission_direction_deg": (
                        jammer.emission_direction_deg if jammer else None
                    ),
                    "cleared": jammer.cleared if jammer else False,
                    "measure_count": len(measurement_events),
                    "direction_count": sum(
                        event.get("outcome") == "direction"
                        for event in measurement_events
                    ),
                    "near_count": sum(
                        event.get("outcome") == "near" for event in measurement_events
                    ),
                    "no_signal_count": sum(
                        event.get("outcome") == "no_signal"
                        for event in measurement_events
                    ),
                    "clear_attempt_count": len(clear_events),
                    "clear_success_count": sum(
                        event.get("outcome") == "success" for event in clear_events
                    ),
                    "clear_failure_count": sum(
                        event.get("outcome") == "failure" for event in clear_events
                    ),
                    "first_signal_sequence": (
                        signal_events[0]["sequence"] if signal_events else None
                    ),
                    "first_signal_virtual_time_s": (
                        signal_events[0]["virtual_time_after_s"]
                        if signal_events
                        else None
                    ),
                }
            )
        return summaries

    def _append_event_unlocked(self, event: dict[str, Any]) -> None:
        event["record_type"] = "command"
        event["sequence"] = len(self.command_log) + 1
        event["recorded_at_utc"] = self._utc_now()
        self.command_log.append(event)
        movement = event.get("movement")
        if isinstance(movement, dict):
            end = movement["end_position"]
            self.trajectory.append(
                {
                    "event_sequence": event["sequence"],
                    "action": event["action"],
                    "channel": event.get("channel"),
                    "x": end["x"],
                    "y": end["y"],
                    "segment_distance_m": movement["distance_m"],
                    "cumulative_distance_m": self.statistics.movement_distance,
                    "arrival_virtual_time_s": movement["virtual_time_after_movement_s"],
                }
            )
        if self.event_log_path is not None:
            with self.event_log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def record_rejected_request(
        self,
        action: str,
        payload: dict[str, Any] | None,
        error: str,
        http_status: int,
    ) -> None:
        """Preserve rejected local requests for protocol-debugging analysis."""
        with self.lock:
            self._append_event_unlocked(
                {
                    "action": action,
                    "accepted": False,
                    "channel": payload.get("channel") if payload else None,
                    "request": payload,
                    "error": error,
                    "http_status": http_status,
                    "robot_position": self._position_dict(self.robot_position),
                    "current_channel": self.current_channel,
                    "virtual_time_before_s": self.statistics.virtual_time_s,
                    "virtual_time_after_s": self.statistics.virtual_time_s,
                }
            )

    def finalize_event_log(self, reason: str) -> None:
        """Append a final snapshot to a standalone JSONL log exactly once."""
        with self.lock:
            if self.event_log_path is None or self.event_log_finalized:
                return
            final_record = {
                "record_type": "session_end",
                "log_schema_version": 1,
                "recorded_at_utc": self._utc_now(),
                "reason": reason,
                "entered": self.entered,
                "exited": self.exited,
                "robot_position": self._position_dict(self.robot_position),
                "current_channel": self.current_channel,
                "jammer_count": len(self.jammers),
                "cleared_count": self.cleared_count,
                "statistics": asdict(self.statistics),
                "channel_summary": self._channel_summary_unlocked(),
                "jammers": [asdict(jammer) for jammer in self.jammers],
            }
            with self.event_log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(final_record, ensure_ascii=False) + "\n")
            self.event_log_finalized = True

    def _validate_common(self, payload: dict[str, Any]) -> None:
        if payload.get("arena_id") != "default":
            raise LocalSimulatorError("arena_id must be 'default'")
        robot_id = payload.get("robot_id")
        request_id = payload.get("request_id")
        if not isinstance(robot_id, str) or not robot_id:
            raise LocalSimulatorError("robot_id must be a non-empty string")
        if not isinstance(request_id, str) or not request_id:
            raise LocalSimulatorError("request_id must be a non-empty string")
        if request_id in self.seen_request_ids:
            raise LocalSimulatorError("request_id must be unique")
        self.seen_request_ids.add(request_id)
        if self.robot_id is not None and robot_id != self.robot_id:
            raise LocalSimulatorError("robot_id changed during the test")

    def _require_active(self) -> None:
        if not self.entered:
            raise LocalSimulatorError("robot has not entered")
        if self.exited:
            raise LocalSimulatorError("test has already exited")

    @staticmethod
    def _parse_position(payload: dict[str, Any]) -> np.ndarray:
        position = payload.get("position")
        if not isinstance(position, dict):
            raise LocalSimulatorError("position must be an object")
        try:
            parsed = np.array([float(position["x"]), float(position["y"])])
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalSimulatorError("position requires numeric x and y") from exc
        if not bool(np.all(np.isfinite(parsed))):
            raise LocalSimulatorError("position must be finite")
        return parsed

    @staticmethod
    def _parse_channel(payload: dict[str, Any]) -> int:
        channel = payload.get("channel")
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise LocalSimulatorError("channel must be an integer")
        if channel not in CHANNELS:
            raise LocalSimulatorError("channel must be between 1 and 20")
        return channel

    def _move_and_switch(self, position: np.ndarray, channel: int) -> dict[str, Any]:
        virtual_time_before = self.statistics.virtual_time_s
        start_position = self.robot_position.copy()
        previous_channel = self.current_channel
        distance = float(np.linalg.norm(position - self.robot_position))
        movement_time = distance / ROBOT_SPEED
        self.statistics.movement_distance += distance
        self.statistics.movement_time_s += movement_time
        self.statistics.virtual_time_s += movement_time
        channel_switched = (
            self.current_channel is not None and channel != self.current_channel
        )
        if self.current_channel is not None and channel != self.current_channel:
            self.statistics.channel_switch_count += 1
            self.statistics.channel_switch_time_s += CHANNEL_SWITCH_DURATION
            self.statistics.virtual_time_s += CHANNEL_SWITCH_DURATION
        self.robot_position = position
        self.current_channel = channel
        return {
            "start_position": self._position_dict(start_position),
            "end_position": self._position_dict(position),
            "distance_m": distance,
            "movement_duration_s": movement_time,
            "previous_channel": previous_channel,
            "new_channel": channel,
            "channel_switched": channel_switched,
            "channel_switch_duration_s": (
                CHANNEL_SWITCH_DURATION if channel_switched else 0.0
            ),
            "virtual_time_before_s": virtual_time_before,
            "virtual_time_after_movement_s": self.statistics.virtual_time_s,
        }

    def _jammer_truth(
        self, jammer: Jammer | None, position: np.ndarray
    ) -> dict[str, Any]:
        if jammer is None:
            return {"jammer_exists": False}
        displacement = jammer.position - position
        distance = float(np.linalg.norm(displacement))
        true_bearing = (
            math.degrees(math.atan2(float(displacement[1]), float(displacement[0])))
            % 360.0
            if distance > FLOAT_TOLERANCE
            else None
        )
        return {
            "jammer_exists": True,
            "source_type": jammer.source_type,
            "jammer_position": {"x": jammer.x, "y": jammer.y},
            "receive_radius": jammer.receive_radius,
            "emission_direction_deg": jammer.emission_direction_deg,
            "distance_to_jammer_m": distance,
            "true_bearing_deg": true_bearing,
            "can_be_received": jammer.can_be_received_at(position),
            "within_near_radius": distance <= NEAR_RADIUS + FLOAT_TOLERANCE,
            "within_clear_radius": distance <= CLEAR_RADIUS + FLOAT_TOLERANCE,
            "cleared": jammer.cleared,
        }

    def _bearing_error_deg(self, position: np.ndarray, channel: int) -> float:
        # Same seed, channel and exact position always produce the same error,
        # matching the rule that repeated measurements at one point do not
        # average away the bounded error.
        key = (
            f"{self.seed}|{channel}|{position[0].hex()}|{position[1].hex()}"
        ).encode()
        integer = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
        unit_value = integer / ((1 << 64) - 1)
        return (2.0 * unit_value - 1.0) * BEARING_ERROR_LIMIT_DEG

    def enter(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Enter a freshly generated local test case."""
        with self.lock:
            self._validate_common(payload)
            if self.entered:
                raise LocalSimulatorError("robot has already entered")
            self.entered = True
            self.robot_id = str(payload["robot_id"])
            result = {
                "accepted": True,
                "remaining_real_duration_s": 1500.0,
                "virtual_time_s": self.statistics.virtual_time_s,
            }
            self._append_event_unlocked(
                {
                    "action": "enter",
                    "accepted": True,
                    "request_id": payload["request_id"],
                    "robot_id": self.robot_id,
                    "channel": None,
                    "robot_position": self._position_dict(self.robot_position),
                    "virtual_time_before_s": self.statistics.virtual_time_s,
                    "operation_duration_s": 0.0,
                    "virtual_time_after_s": self.statistics.virtual_time_s,
                    "response": dict(result),
                }
            )
            return result

    def measure(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Measure one channel from the requested robot position."""
        with self.lock:
            self._validate_common(payload)
            self._require_active()
            position = self._parse_position(payload)
            channel = self._parse_channel(payload)
            movement = self._move_and_switch(position, channel)
            self.statistics.measure_count += 1
            self.statistics.measurement_time_s += MEASURE_DURATION
            self.statistics.virtual_time_s += MEASURE_DURATION

            jammer = self.jammer_by_channel.get(channel)
            result: dict[str, Any] = {
                "accepted": True,
                "virtual_time_s": self.statistics.virtual_time_s,
            }
            if (
                jammer is None
                or jammer.cleared
                or not jammer.can_be_received_at(position)
            ):
                result["measure_result"] = "no_signal"
            else:
                displacement = jammer.position - position
                distance = float(np.linalg.norm(displacement))
                if distance <= NEAR_RADIUS + FLOAT_TOLERANCE:
                    result["measure_result"] = "near"
                else:
                    true_bearing = math.degrees(
                        math.atan2(float(displacement[1]), float(displacement[0]))
                    )
                    result["measure_result"] = "direction"
                    result["svd_deg"] = (
                        true_bearing + self._bearing_error_deg(position, channel)
                    ) % 360.0

            truth = self._jammer_truth(jammer, position)
            if result["measure_result"] == "direction":
                truth["reported_bearing_deg"] = result["svd_deg"]
                truth["bearing_error_deg"] = (
                    (result["svd_deg"] - truth["true_bearing_deg"] + 180.0) % 360.0
                ) - 180.0
            self._append_event_unlocked(
                {
                    "action": "measure",
                    "accepted": True,
                    "request_id": payload["request_id"],
                    "robot_id": self.robot_id,
                    "channel": channel,
                    "movement": movement,
                    "operation_duration_s": MEASURE_DURATION,
                    "virtual_time_before_s": movement["virtual_time_before_s"],
                    "virtual_time_after_s": self.statistics.virtual_time_s,
                    "outcome": result["measure_result"],
                    "truth": truth,
                    "response": dict(result),
                }
            )
            return result

    def clear(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Attempt to clear the selected channel within the 20 m radius."""
        with self.lock:
            self._validate_common(payload)
            self._require_active()
            position = self._parse_position(payload)
            channel = self._parse_channel(payload)
            movement = self._move_and_switch(position, channel)
            jammer = self.jammer_by_channel.get(channel)
            cleared_before = jammer.cleared if jammer else False
            success = (
                jammer is not None
                and not jammer.cleared
                and float(np.linalg.norm(jammer.position - position))
                <= CLEAR_RADIUS + FLOAT_TOLERANCE
            )
            if success:
                jammer.cleared = True
                self.statistics.clear_success_count += 1
                self.statistics.clear_time_s += CLEAR_SUCCESS_DURATION
                self.statistics.virtual_time_s += CLEAR_SUCCESS_DURATION
                clear_result = "success"
            else:
                self.statistics.clear_failure_count += 1
                self.statistics.clear_time_s += CLEAR_FAILURE_DURATION
                self.statistics.virtual_time_s += CLEAR_FAILURE_DURATION
                clear_result = "failure"
            result = {
                "accepted": True,
                "clear_result": clear_result,
                "virtual_time_s": self.statistics.virtual_time_s,
            }
            truth = self._jammer_truth(jammer, position)
            truth["cleared_before"] = cleared_before
            truth["cleared_after"] = jammer.cleared if jammer else False
            operation_duration = (
                CLEAR_SUCCESS_DURATION if success else CLEAR_FAILURE_DURATION
            )
            self._append_event_unlocked(
                {
                    "action": "clear",
                    "accepted": True,
                    "request_id": payload["request_id"],
                    "robot_id": self.robot_id,
                    "channel": channel,
                    "movement": movement,
                    "operation_duration_s": operation_duration,
                    "virtual_time_before_s": movement["virtual_time_before_s"],
                    "virtual_time_after_s": self.statistics.virtual_time_s,
                    "outcome": clear_result,
                    "truth": truth,
                    "response": dict(result),
                }
            )
            return result

    def exit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """End the local test and preserve its ground-truth summary."""
        with self.lock:
            self._validate_common(payload)
            self._require_active()
            self.exited = True
            result = {
                "accepted": True,
                "exit_reason": "user_exit",
                "virtual_time_s": self.statistics.virtual_time_s,
                "cleared_count": self.cleared_count,
                "jammer_count": len(self.jammers),
            }
            self._append_event_unlocked(
                {
                    "action": "exit",
                    "accepted": True,
                    "request_id": payload["request_id"],
                    "robot_id": self.robot_id,
                    "channel": None,
                    "robot_position": self._position_dict(self.robot_position),
                    "virtual_time_before_s": self.statistics.virtual_time_s,
                    "operation_duration_s": 0.0,
                    "virtual_time_after_s": self.statistics.virtual_time_s,
                    "response": dict(result),
                }
            )
            return result


class LocalSimulatorServer(ThreadingHTTPServer):
    """HTTP server carrying one local simulation state machine."""

    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        simulator: LocalSimulator,
    ) -> None:
        self.simulator = simulator
        super().__init__(address, LocalRequestHandler)


class LocalRequestHandler(BaseHTTPRequestHandler):
    """Serve the official-style JSON API and local read-only diagnostics."""

    server: LocalSimulatorServer
    routes: ClassVar = {
        "/enter": "enter",
        "/measure": "measure",
        "/clear": "clear",
        "/exit": "exit",
    }

    def log_message(self, format_: str, *args: object) -> None:
        """Suppress default access logging; the client already logs commands."""

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_object(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode())
        if not isinstance(payload, dict):
            raise LocalSimulatorError("JSON body must be an object")
        return payload

    def do_GET(self) -> None:
        """Expose local-only health and ground-truth inspection endpoints."""
        if self.path == "/health":
            self._write_json(200, {"ok": True, "local_test": True})
        elif self.path == "/state":
            self._write_json(200, self.server.simulator.public_state())
        else:
            self._write_json(404, {"accepted": False, "error": "unknown path"})

    def do_POST(self) -> None:
        """Dispatch one official-style robot request."""
        method_name = self.routes.get(self.path)
        if method_name is None:
            error = "unknown path"
            self.server.simulator.record_rejected_request(
                self.path.lstrip("/") or "unknown",
                None,
                error,
                404,
            )
            self._write_json(404, {"accepted": False, "error": error})
            return
        payload: dict[str, Any] | None = None
        try:
            payload = self._read_json_object()
            method = getattr(self.server.simulator, method_name)
            result = method(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            error = str(exc)
            self.server.simulator.record_rejected_request(
                method_name,
                payload,
                error,
                400,
            )
            self._write_json(400, {"accepted": False, "error": error})
            return
        except LocalSimulatorError as exc:
            error = str(exc)
            self.server.simulator.record_rejected_request(
                method_name,
                payload,
                error,
                200,
            )
            self._write_json(200, {"accepted": False, "error": error})
            return
        self._write_json(200, result)


def create_practice_evidence(data_directory: Path, problem: int, seed: int) -> Path:
    """Create isolated practice evidence understood by the guarded client."""
    run_directory = data_directory.resolve() / "behavior-runs"
    run_directory.mkdir(parents=True, exist_ok=True)
    evidence_path = run_directory / f"practice-local-p{problem}-{seed}.json"
    evidence_path.write_text(
        json.dumps(
            {
                "mode": "practice",
                "ticket_type": "practice_ticket_v1",
                "problem_no": problem,
                "local_test": True,
                "seed": seed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return evidence_path


def parse_args() -> argparse.Namespace:
    """Parse the standalone local simulator command line."""
    parser = argparse.ArgumentParser(
        description="Run an isolated local Problem 3/4 test API."
    )
    parser.add_argument(
        "--problem", type=int, choices=(PROBLEM3, PROBLEM4), required=True
    )
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--port", type=int, default=DEFAULT_LOCAL_PORT)
    parser.add_argument("--source-count", type=int)
    parser.add_argument("--directional-count", type=int)
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="isolated directory in which practice evidence is created",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help=(
            "JSON Lines event log; defaults to local-simulator-p<problem>-"
            "<seed>.jsonl under --state-dir"
        ),
    )
    return parser.parse_args()


def main() -> int:
    """Run one standalone local case until interrupted."""
    args = parse_args()
    if args.port == OFFICIAL_PORT:
        raise SystemExit("Refusing port 2026: it is reserved for the official EXE.")
    event_log_path = args.log_file or (
        args.state_dir / f"local-simulator-p{args.problem}-{args.seed}.jsonl"
    )
    simulator = LocalSimulator(
        args.problem,
        args.seed,
        source_count=args.source_count,
        directional_count=args.directional_count,
        event_log_path=event_log_path,
    )
    evidence = create_practice_evidence(args.state_dir, args.problem, args.seed)
    server = LocalSimulatorServer(("127.0.0.1", args.port), simulator)
    print(
        f"LOCAL   problem={args.problem} seed={args.seed} "
        f"sources={len(simulator.jammers)} port={args.port}"
    )
    print(f"STATE   {evidence}")
    print(f"TRUTH   http://127.0.0.1:{args.port}/state")
    print(f"LOG     {event_log_path.resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("LOCAL   stopped")
    finally:
        simulator.finalize_event_log("server_stopped")
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
