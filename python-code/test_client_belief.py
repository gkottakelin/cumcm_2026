"""Property tests for the non-convex Problem 3 belief region.

Covers the acceptance criteria from
tuning-reports/optimization-directions-after-simulator-alignment.md:
a single bearing plus several no-signal points must strictly shrink the
feasible region, the true source must always remain inside the enclosing
geometry, and the clear certificate must cover every connected component.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simulator_client import (  # noqa: E402
    belief_region_p3,
    shapely_hull_vertices,
)
from geometry import smallest_enclosing_circle  # noqa: E402


def _point(x: float, y: float) -> np.ndarray:
    return np.array([x, y])


def _bearing_to(source: np.ndarray, sensor: np.ndarray, error_deg: float) -> float:
    """Reported bearing with a bounded deterministic error."""
    true_bearing = math.atan2(source[1] - sensor[1], source[0] - sensor[0])
    return true_bearing + math.radians(error_deg)


class BeliefRegionP3Tests(unittest.TestCase):
    def test_true_source_stays_inside_with_many_no_signal_points(self) -> None:
        rng = np.random.default_rng(2026)
        for trial in range(200):
            source = _point(
                float(rng.uniform(-1700, 1700)), float(rng.uniform(-1700, 1700))
            )
            if float(np.linalg.norm(source)) > 1780.0:
                continue
            # A direction observation requires the source inside the
            # sensor's reception disk, so keep the sensor within 1400 m.
            heading = float(rng.uniform(0, 2 * math.pi))
            sensor_distance = float(rng.uniform(100.0, 1400.0))
            sensor = source + sensor_distance * np.array(
                [math.cos(heading), math.sin(heading)]
            )
            if float(np.linalg.norm(sensor)) > 2400.0:
                continue
            error = float(rng.uniform(-1.0, 1.0))
            observations = [
                (sensor, _bearing_to(source, sensor, error))
            ]
            no_signal = []
            for _ in range(int(rng.integers(1, 8))):
                probe = sensor + float(rng.uniform(300, 2000)) * np.array(
                    [
                        math.cos(float(rng.uniform(0, 2 * math.pi))),
                        math.sin(float(rng.uniform(0, 2 * math.pi))),
                    ]
                )
                if float(np.linalg.norm(probe)) > 2400.0:
                    continue
                if float(np.linalg.norm(probe - source)) <= 1000.0:
                    continue  # would have heard the source
                no_signal.append(probe)
            geometry = belief_region_p3(observations, no_signal)
            self.assertIsNotNone(geometry, f"trial {trial}: region empty")
            from shapely.geometry import Point  # noqa: PLC0415

            self.assertTrue(
                geometry.covers(Point(source)),
                f"trial {trial}: true source excluded "
                f"(source={source.tolist()})",
            )

    def test_no_signal_strictly_shrinks_region(self) -> None:
        sensor = _point(-1200.0, 300.0)
        source = _point(600.0, -400.0)
        observations = [(sensor, _bearing_to(source, sensor, 0.4))]
        wide = belief_region_p3(observations, [])
        cut = belief_region_p3(
            observations, [sensor + _point(1800.0, 0.0)]
        )
        self.assertIsNotNone(wide)
        self.assertIsNotNone(cut)
        self.assertLess(cut.area, wide.area)
        self.assertGreater(wide.area, 0.0)

    def test_multi_component_enclosing_circle_covers_all(self) -> None:
        """Two disjoint lobes must yield one MEC covering both."""
        sensor = _point(-1500.0, 0.0)
        source = _point(-100.0, 5.0)
        observations = [(sensor, _bearing_to(source, sensor, 0.3))]
        # The 1500 m disk around the sensor confines the region to roughly
        # x in [-1500, 0]; a no-signal disk at (-750, 800) severs the thin
        # wedge there (its y=0 chord spans x in [-1350, -150]), leaving two
        # lobes near the sensor and near the disk boundary.
        no_signal = [_point(-750.0, 800.0)]
        geometry = belief_region_p3(observations, no_signal)
        self.assertIsNotNone(geometry)
        components = getattr(geometry, "geoms", (geometry,))
        self.assertGreater(
            len(components), 1, "expected a split multi-component region"
        )
        vertices = shapely_hull_vertices(geometry)
        center, radius = smallest_enclosing_circle(vertices)
        for lobe in components:
            representative = lobe.representative_point()
            distance = float(
                np.linalg.norm(
                    np.array([representative.x, representative.y]) - center
                )
            )
            self.assertLessEqual(
                distance,
                radius + 1e-6,
                "lobe representative outside enclosing circle",
            )


if __name__ == "__main__":
    unittest.main()
