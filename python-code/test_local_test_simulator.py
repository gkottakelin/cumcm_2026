"""Protocol and physics regression tests for the local simulator."""

# ruff: noqa: ANN401, CPY001, PLR2004, PT009, PT027

from __future__ import annotations

import http.client
import json
import math
import threading
import unittest
from typing import Any

from local_test_simulator import (
    BusinessRuleError,
    Jammer,
    LocalSimulator,
    LocalSimulatorServer,
    ProtocolValidationError,
    RequestConflictError,
    generate_case,
)


def request_payload(request_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "arena_id": "default",
        "robot_id": "LOCAL-TEST",
        "request_id": request_id,
        **fields,
    }


class CaseGenerationTests(unittest.TestCase):
    def test_generated_cases_obey_problem_source_rules(self) -> None:
        p3_counts: set[int] = set()
        p4_counts: set[int] = set()
        p4_directional_counts: set[int] = set()
        for seed in range(100):
            p3 = generate_case(3, seed)
            p4 = generate_case(4, seed)
            p3_counts.add(len(p3))
            p4_counts.add(len(p4))
            directional_count = sum(
                jammer.source_type == "directional" for jammer in p4
            )
            p4_directional_counts.add(directional_count)
            self.assertTrue(10 <= len(p3) <= 16)
            self.assertTrue(10 <= len(p4) <= 16)
            self.assertTrue(
                all(jammer.source_type == "omnidirectional" for jammer in p3)
            )
            self.assertTrue(1 <= directional_count < len(p4))
            for case in (p3, p4):
                self.assertEqual(len({jammer.channel for jammer in case}), len(case))
                self.assertTrue(all(1 <= jammer.channel <= 20 for jammer in case))
                self.assertTrue(
                    all(math.hypot(jammer.x, jammer.y) <= 1800 for jammer in case)
                )
                self.assertTrue(
                    all(1000 <= jammer.receive_radius <= 1500 for jammer in case)
                )
        self.assertGreater(len(p3_counts), 1)
        self.assertGreater(len(p4_counts), 1)
        self.assertGreater(len(p4_directional_counts), 1)

    def test_explicit_case_constraints_are_enforced(self) -> None:
        for count in (9, 17):
            with self.assertRaises(ValueError):
                generate_case(3, 1, source_count=count)
        for directional_count in (0, 10):
            with self.assertRaises(ValueError):
                generate_case(
                    4,
                    1,
                    source_count=10,
                    directional_count=directional_count,
                )


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.simulator = LocalSimulator(3, 2026, source_count=10)

    def test_enter_response_and_initial_channel_match_protocol(self) -> None:
        response = self.simulator.enter(request_payload("enter"))
        self.assertEqual(self.simulator.current_channel, 1)
        self.assertEqual(response["virtual_time_s"], 0)
        self.assertEqual(response["max_virtual_duration_s"], 360000)
        self.assertEqual(response["max_real_duration_s"], 1200)
        self.assertEqual(response["remaining_real_duration_s"], 1200)
        self.assertEqual(
            set(response),
            {
                "accepted",
                "real_timestamp_ms",
                "virtual_time_s",
                "max_virtual_duration_s",
                "max_real_duration_s",
                "remaining_real_duration_s",
            },
        )

    def test_clear_does_not_switch_receiver_channel(self) -> None:
        self.simulator.enter(request_payload("enter"))
        self.simulator.measure(
            request_payload("measure", position={"x": 0, "y": 0}, channel=2.0)
        )
        absent_channel = next(
            channel
            for channel in range(1, 21)
            if channel not in self.simulator.jammer_by_channel
        )
        response = self.simulator.clear(
            request_payload(
                "clear",
                position={"x": 0, "y": 0},
                channel=absent_channel,
            )
        )
        self.assertEqual(response["clear_result"], "no_target_in_range")
        self.assertEqual(self.simulator.current_channel, 2)
        self.assertEqual(self.simulator.statistics.channel_switch_count, 1)
        self.assertEqual(response["virtual_time_s"], 9)

    def test_attachment_timing_example_totals_199_seconds(self) -> None:
        self.simulator.jammers = []
        self.simulator.enter(request_payload("enter"))
        first = self.simulator.measure(
            request_payload("m1", position={"x": 300, "y": 400}, channel=1)
        )
        second = self.simulator.measure(
            request_payload("m2", position={"x": 300, "y": 400}, channel=2)
        )
        cleared = self.simulator.clear(
            request_payload("c1", position={"x": 300, "y": 0}, channel=3)
        )
        final = self.simulator.measure(
            request_payload("m3", position={"x": 300, "y": 0}, channel=2)
        )
        self.assertEqual(first["virtual_time_s"], 105)
        self.assertEqual(second["virtual_time_s"], 111)
        self.assertEqual(cleared["virtual_time_s"], 194)
        self.assertEqual(final["virtual_time_s"], 199)
        self.assertEqual(self.simulator.current_channel, 2)

    def test_clear_ignores_directional_coverage_and_includes_20m_boundary(self) -> None:
        self.simulator.jammers = [Jammer(1, 20.0, 0.0, 1000.0, "directional", 0.0)]
        self.simulator.enter(request_payload("enter"))
        response = self.simulator.clear(
            request_payload("clear", position={"x": 0, "y": 0}, channel=1)
        )
        self.assertEqual(response["clear_result"], "success")

    def test_successful_requests_are_idempotent(self) -> None:
        payload = request_payload("enter")
        first = self.simulator.enter(payload)
        second = self.simulator.enter(dict(payload))
        self.assertEqual(first, second)
        self.assertEqual(len(self.simulator.command_log), 1)
        with self.assertRaises(RequestConflictError):
            self.simulator.enter({**payload, "robot_id": "DIFFERENT"})

    def test_bearing_is_stable_normalized_and_rounded(self) -> None:
        self.simulator.jammers = [
            Jammer(1, 100.0, 0.0, 1000.0, "omnidirectional", None)
        ]
        self.simulator.enter(request_payload("enter"))
        first = self.simulator.measure(
            request_payload("m1", position={"x": 0, "y": 0}, channel=1)
        )
        second = self.simulator.measure(
            request_payload("m2", position={"x": 0.0, "y": 0.0}, channel=1)
        )
        self.assertEqual(first["measure_result"], "direction")
        self.assertEqual(first["svd_deg"], second["svd_deg"])
        self.assertEqual(first["svd_deg"], round(first["svd_deg"], 2))
        self.assertTrue(0 <= first["svd_deg"] < 360)

    def test_invalid_and_unknown_fields_use_documented_error_classes(self) -> None:
        with self.assertRaises(ProtocolValidationError):
            self.simulator.measure(
                request_payload(
                    "bad-coordinate",
                    position={"x": 2_000_001, "y": 0},
                    channel=1,
                )
            )
        with self.assertRaises(BusinessRuleError):
            self.simulator.enter({**request_payload("unknown"), "extra": True})
        with self.assertRaises(ProtocolValidationError):
            self.simulator.measure(
                request_payload("missing-y", position={"x": 0}, channel=1)
            )
        with self.assertRaises(BusinessRuleError):
            self.simulator.measure(
                request_payload(
                    "unknown-position-field",
                    position={"x": 0, "y": 0, "z": 0},
                    channel=1,
                )
            )


class HttpProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.simulator = LocalSimulator(3, 7, source_count=10)
        self.server = LocalSimulatorServer(("127.0.0.1", 0), self.simulator)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _request(
        self,
        method: str,
        path: str,
        body: str | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, dict[str, Any]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": content_type} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, payload

    def test_http_statuses_and_rejected_response_shape(self) -> None:
        enter_body = json.dumps(request_payload("enter"))
        status, entered = self._request("POST", "/enter", enter_body)
        self.assertEqual(status, 200)
        self.assertTrue(entered["accepted"])

        status, repeated = self._request("POST", "/enter", enter_body)
        self.assertEqual(status, 200)
        self.assertEqual(entered, repeated)

        conflict_body = json.dumps({**request_payload("enter"), "robot_id": "OTHER"})
        status, rejected = self._request("POST", "/enter", conflict_body)
        self.assertEqual(status, 409)
        self.assertEqual(
            set(rejected), {"accepted", "real_timestamp_ms", "virtual_time_s"}
        )
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["virtual_time_s"], 0)

        unknown_body = json.dumps({**request_payload("unknown"), "extra": 1})
        status, rejected = self._request("POST", "/enter", unknown_body)
        self.assertEqual(status, 200)
        self.assertFalse(rejected["accepted"])

        status, rejected = self._request("POST", "/enter", "{not-json")
        self.assertEqual(status, 400)
        self.assertFalse(rejected["accepted"])

        status, rejected = self._request(
            "POST", "/enter", enter_body, content_type="text/plain"
        )
        self.assertEqual(status, 415)
        self.assertFalse(rejected["accepted"])

        status, rejected = self._request("GET", "/enter")
        self.assertEqual(status, 405)
        self.assertFalse(rejected["accepted"])

    def test_duplicate_json_key_returns_http_400(self) -> None:
        duplicate = (
            '{"arena_id":"default","robot_id":"LOCAL-TEST",'
            '"request_id":"one","request_id":"two"}'
        )
        status, rejected = self._request("POST", "/enter", duplicate)
        self.assertEqual(status, 400)
        self.assertFalse(rejected["accepted"])


if __name__ == "__main__":
    unittest.main()
