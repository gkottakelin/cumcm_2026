"""Run the complete client against isolated, ground-truthed local cases."""

# The CLI prints concise case and failure summaries.
# ruff: noqa: CPY001, EM101, T201, TRY003

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Final

from local_test_simulator import (
    DEFAULT_LOCAL_PORT,
    OFFICIAL_PORT,
    PROBLEM3,
    PROBLEM4,
    LocalSimulator,
    LocalSimulatorServer,
    create_practice_evidence,
)

LOCAL_TEAM: Final = "LOCAL-REGRESSION"
MAX_PORT: Final = 65535


def _run_case(
    problem: int,
    seed: int,
    port: int,
    client_path: Path,
    *,
    verbose: bool,
) -> dict[str, Any]:
    simulator = LocalSimulator(problem, seed)
    directional_count = sum(
        jammer.source_type == "directional" for jammer in simulator.jammers
    )

    with tempfile.TemporaryDirectory(prefix="jammers-local-test-") as temporary:
        state_directory = Path(temporary)
        create_practice_evidence(state_directory, problem, seed)
        server = LocalSimulatorServer(("127.0.0.1", port), simulator)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        command = [
            sys.executable,
            str(client_path),
            "--team",
            LOCAL_TEAM,
            "--problem",
            str(problem),
            "--port",
            str(port),
            "--simulator-data-dir",
            str(state_directory),
        ]
        client_started = time.monotonic()
        try:
            completed = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            client_wall_time_s = time.monotonic() - client_started
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

    state = simulator.public_state()
    all_cleared = simulator.cleared_count == len(simulator.jammers)
    passed = completed.returncode == 0 and all_cleared and simulator.exited
    result: dict[str, Any] = {
        "case_id": f"p{problem}-seed{seed}",
        "problem": problem,
        "seed": seed,
        "source_count": len(simulator.jammers),
        "directional_count": directional_count,
        "cleared_count": simulator.cleared_count,
        "missed_channels": [
            jammer.channel for jammer in simulator.jammers if not jammer.cleared
        ],
        "client_exit_code": completed.returncode,
        "client_exited": simulator.exited,
        "client_wall_time_s": client_wall_time_s,
        "passed": passed,
        "statistics": state["statistics"],
        "channel_summary": state["channel_summary"],
        "truth_jammers": state["jammers"],
        "trajectory": state["trajectory"],
        "command_log": state["command_log"],
        "client_stdout": completed.stdout,
        "client_stderr": completed.stderr,
    }
    if verbose:
        print(f"\n--- {result['case_id']} client stdout ---")
        print(completed.stdout.rstrip())
        if completed.stderr:
            print(f"\n--- {result['case_id']} client stderr ---", file=sys.stderr)
            print(completed.stderr.rstrip(), file=sys.stderr)
    return result


def _write_case_artifacts(result: dict[str, Any], directory: Path) -> None:
    """Write one complete case plus event and trajectory analysis files."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = str(result["case_id"])
    case_path = directory / f"{stem}.json"
    case_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    events_path = directory / f"{stem}-events.jsonl"
    with events_path.open("w", encoding="utf-8") as stream:
        for event in result["command_log"]:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    trajectory_path = directory / f"{stem}-trajectory.csv"
    fieldnames = [
        "event_sequence",
        "action",
        "channel",
        "x",
        "y",
        "segment_distance_m",
        "cumulative_distance_m",
        "arrival_virtual_time_s",
    ]
    with trajectory_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result["trajectory"])


def parse_args() -> argparse.Namespace:
    """Parse regression-suite options."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate local Problem 3/4 cases and run simulator_client.py "
            "against an isolated loopback server."
        )
    )
    parser.add_argument(
        "--problem",
        choices=("3", "4", "both"),
        default="both",
    )
    parser.add_argument("--cases", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--port", type=int, default=DEFAULT_LOCAL_PORT)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help=(
            "directory for per-case JSON, JSONL events and trajectory CSV; "
            "defaults beside --output when that option is used"
        ),
    )
    return parser.parse_args()


def main() -> int:
    """Run all requested local cases and report truth-based pass rates."""
    args = parse_args()
    if args.cases < 1:
        raise SystemExit("--cases must be at least 1")
    if args.port == OFFICIAL_PORT:
        raise SystemExit("Refusing port 2026: it is reserved for the official EXE.")
    if not 1 <= args.port <= MAX_PORT:
        raise SystemExit("--port must be between 1 and 65535")

    client_path = Path(__file__).with_name("simulator_client.py")
    problems = (PROBLEM3, PROBLEM4) if args.problem == "both" else (int(args.problem),)
    results: list[dict[str, Any]] = []
    for problem in problems:
        for case_index in range(args.cases):
            case_seed = args.seed + problem * 100_000 + case_index
            result = _run_case(
                problem,
                case_seed,
                args.port,
                client_path,
                verbose=args.verbose,
            )
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"{status} p{problem} seed={case_seed} "
                f"cleared={result['cleared_count']}/{result['source_count']} "
                f"virtual={result['statistics']['virtual_time_s']:.1f}s"
            )

    artifacts_directory = args.artifacts_dir
    if artifacts_directory is None and args.output is not None:
        resolved_output = args.output.resolve()
        artifacts_directory = resolved_output.parent / f"{resolved_output.stem}-cases"
    if artifacts_directory is not None:
        artifacts_directory = artifacts_directory.resolve()
        for result in results:
            _write_case_artifacts(result, artifacts_directory)
        print(f"ARTIFACTS {artifacts_directory}")

    passed_count = sum(bool(result["passed"]) for result in results)
    report = {
        "local_only": True,
        "official_exe_used": False,
        "official_port_used": False,
        "base_seed": args.seed,
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "results": results,
    }
    if args.output is not None:
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"REPORT  {output_path}")

    print(
        f"SUMMARY passed={passed_count}/{len(results)} "
        f"failed={len(results) - passed_count}"
    )
    return 0 if passed_count == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
