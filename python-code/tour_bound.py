"""Offline TSP lower bound for the post-tour stop set (OR-Tools).

For each iter-009b case this extracts the realized post-tour stop sequence
(every command after "Detected active channels"), computes the length the
client actually flew, and compares it with the optimal TSP tour over the
same stop set (OR-Tools CP-SAT / routing).  The gap shows how much of the
remaining post-tour travel is routing quality versus stop-set structure.
Offline analysis only: the client never imports this module.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

MEASURE_RE = re.compile(r"(MEASURE|CLEAR)\s+ch=(\d+) pos=\(([-\d.eE+]+), ([-\d.eE+]+)\)")


def optimal_tour_length(points: list[np.ndarray]) -> float:
    """Exact-ish TSP over small stop sets with OR-Tools routing."""
    n = len(points)
    if n <= 1:
        return 0.0
    if n == 2:
        return float(np.linalg.norm(points[0] - points[1])) * 2
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(i, j):
        a = points[manager.IndexToNode(i)]
        b = points[manager.IndexToNode(j)]
        return int(round(float(np.linalg.norm(a - b)) * 10))

    transit = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)
    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search.time_limit.FromMilliseconds(300)
    solution = routing.SolveWithParameters(search)
    if solution is None:
        return float("nan")
    return solution.ObjectiveValue() / 10.0


def main() -> None:
    for directory in sys.argv[1:]:
        gaps = []
        actuals = []
        optima = []
        for path in sorted(Path(directory).glob("p[34]-seed*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            stdout = data["client_stdout"]
            # realized post-tour commands in order
            after = stdout.split("Detected active channels", 1)
            if len(after) < 2:
                continue
            stops = []
            for line in after[1].splitlines():
                match = MEASURE_RE.match(line)
                if match:
                    stops.append(
                        np.array([float(match.group(3)), float(match.group(4))])
                    )
            # dedupe consecutive duplicates (batch probes at same point)
            dedup = []
            for p in stops:
                if not dedup or float(np.linalg.norm(dedup[-1] - p)) > 1e-6:
                    dedup.append(p)
            if len(dedup) < 3:
                continue
            # actual flown length: from current position at tour end
            # (last coverage/refine command) through the post-tour stops
            trajectory = data["trajectory"]
            tour_end_pos = None
            phase_seen_detect = False
            for line in after[1].splitlines():
                pass
            # position at detection time = last command before "Detected"
            pre = stdout.split("Detected active channels")[0]
            pre_stops = [
                np.array([float(m.group(3)), float(m.group(4))])
                for m in (
                    MEASURE_RE.match(line) for line in pre.splitlines()
                )
                if m
            ]
            tour_end_pos = pre_stops[-1] if pre_stops else np.array([0.0, 0.0])
            actual = sum(
                float(np.linalg.norm(dedup[i] - dedup[i + 1]))
                for i in range(len(dedup) - 1)
            )
            actual += float(np.linalg.norm(tour_end_pos - dedup[0]))
            # closed-vs-closed: OR-Tools returns to the depot, so add the
            # return leg to the flown path for a fair comparison
            actual += float(np.linalg.norm(dedup[-1] - tour_end_pos))
            optimal = optimal_tour_length(dedup)
            if optimal != optimal or optimal <= 0:
                continue
            actuals.append(actual)
            optima.append(optimal)
            gaps.append((actual - optimal) / optimal * 100.0)
        if not gaps:
            print(f"{directory}: no usable cases")
            continue
        print(
            f"{directory}: n={len(gaps)}  actual mean={statistics.mean(actuals):.0f}m  "
            f"optimal mean={statistics.mean(optima):.0f}m  "
            f"gap mean={statistics.mean(gaps):.1f}%  "
            f"gap P90={sorted(gaps)[int(len(gaps) * 0.9)]:.1f}%  "
            f"gap max={max(gaps):.1f}%"
        )


if __name__ == "__main__":
    main()
