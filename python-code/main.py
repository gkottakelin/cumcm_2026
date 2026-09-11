from pathlib import Path
from typing import Any

import matplotlib as mpl

mpl.rcParams.update(
    {
        "backend": "Agg",
        "text.usetex": False,
        "savefig.bbox": "tight",
        "savefig.directory": "out",
        "savefig.format": "pdf",
    }
)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from coverage import (  # noqa: E402
    SourceSimulator,
    path_length,
    run_directional_simulation,
    run_omni_simulation,
    seven_cover_points,
    shortest_tour,
)
from geometry import (  # noqa: E402
    convex_hull,
    direction_vector,
    polygon_diameter,
    smallest_enclosing_circle,
)
from localization import (  # noqa: E402
    DELTA_RAD,
    OMEGA_RADIUS,
    candidate_grid_for_second_point,
    compute_region,
    region_metrics,
    simulate_bearing,
    worst_case_diameter_after_second,
)
from matplotlib.patches import Circle  # noqa: E402

OUT_DIR = Path("out")
OUT_DIR.mkdir(exist_ok=True)
rng = np.random.default_rng(2026)


def problem1_demo() -> dict[str, Any]:
    s1 = np.array([-800.0, 0.0])
    s2 = np.array([400.0, 800.0])
    s3 = np.array([600.0, -500.0])
    true_g = np.array([300.0, 200.0])

    theta1 = simulate_bearing(true_g, s1)
    theta2 = simulate_bearing(true_g, s2)
    theta3 = simulate_bearing(true_g, s3)

    P = compute_region([(s1, theta1), (s2, theta2), (s3, theta3)])
    met = region_metrics(P)
    fig, ax = plt.subplots(figsize=(8, 8))
    theta_grid = np.linspace(0, 2 * np.pi, 200)
    ax.plot(
        OMEGA_RADIUS * np.cos(theta_grid),
        OMEGA_RADIUS * np.sin(theta_grid),
        "k-",
        linewidth=1.5,
        label=r"$\Omega$",
    )

    for s, th, color, label in [
        (s1, theta1, "C0", "S1"),
        (s2, theta2, "C1", "S2"),
        (s3, theta3, "C2", "S3"),
    ]:
        ax.plot(s[0], s[1], "o", color=color, markersize=8)
        ax.annotate(label, (s[0] + 30, s[1] + 30), fontsize=12)
        for ang in [th - DELTA_RAD, th, th + DELTA_RAD]:
            u = direction_vector(ang)
            r = 2000
            ax.plot(
                [s[0], s[0] + r * u[0]],
                [s[1], s[1] + r * u[1]],
                "--",
                color=color,
                linewidth=1,
                alpha=0.5,
            )

    if len(P) > 0:
        hull = convex_hull(P) if len(P) > 0 else P
        ax.fill(hull[:, 0], hull[:, 1], alpha=0.3, color="C3", label="P")
        center, radius = smallest_enclosing_circle(hull)
        circle = Circle(
            (center[0], center[1]),
            radius,
            fill=False,
            color="C3",
            linestyle="--",
            linewidth=2,
        )
        ax.add_patch(circle)
        ax.plot(center[0], center[1], "x", color="C3", markersize=10)
        d = polygon_diameter(hull)
        ax.set_title(
            f"Problem 1: D(P)={d:.1f}m, R(P)={radius:.1f}m\n"
            f"R(P) ≤ D(P)/2: {met['r_le_d_over_2']}"
        )
    else:
        ax.set_title("Problem 1: Empty region (constraints inconsistent)")
    ax.plot(true_g[0], true_g[1], "r*", markersize=15, label="True source")
    ax.set_xlim(-2000, 2000)
    ax.set_ylim(-2000, 2000)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=10)
    fig.savefig(OUT_DIR / "problem1_sector_intersection.pdf", bbox_inches="tight")
    plt.close(fig)
    return met


def problem1_intersection_table() -> str:
    rows = []
    configs = [
        ([(-800, 0), (400, 800)], [(0, 0.1), (0, 0.1)]),
        ([(-800, 0), (400, 800), (600, -500)], [(0, 0.1), (0, 0.1), (0, 0.1)]),
        (
            [(-800, 0), (400, 800), (600, -500), (-200, -700)],
            [(0, 0.1), (0, 0.1), (0, 0.1), (0, 0.1)],
        ),
    ]
    target = np.array([300.0, 200.0])
    for sensors, offsets in configs:
        meas = []
        for s_pos, _ in zip(sensors, offsets, strict=False):
            s = np.array(s_pos, dtype=float)
            th = simulate_bearing(target, s)
            meas.append((s, th))
        P = compute_region(meas)
        met = region_metrics(P)
        rows.append(
            f"| {len(sensors)} | {met['vertex_count']} | {met['area']:.1f} | "
            f"{met['diameter']:.1f} | {met['min_enclosing_radius']:.1f} | "
            f"{met['r_le_d_over_2']} |"
        )
    return (
        "| 检测点数 | 顶点数 | 面积 | 直径 D(P) | 最小包围圆半径 R(P) | R(P) ≤ D(P)/2 |\n"
        "|---:|---:|---:|---:|---:|---|\n" + "\n".join(rows)
    )


def problem2_demo() -> dict[str, Any]:
    s1 = np.array([-500.0, 0.0])
    true_g = np.array([400.0, 200.0])
    theta1 = simulate_bearing(true_g, s1)
    P1 = compute_region([(s1, theta1)])
    met1 = region_metrics(P1)

    candidates = candidate_grid_for_second_point(
        s1, theta1, grid_spacing=50.0, max_distance=2000.0
    )
    if len(candidates) == 0:
        return {"error": "no candidates"}
    scores = []
    best_d = float("inf")
    best_s = candidates[0]
    for cs in candidates:
        d = worst_case_diameter_after_second(P1, cs)
        scores.append(d)
        if d < best_d:
            best_d = d
            best_s = cs

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    ax = axes[0]
    theta_grid = np.linspace(0, 2 * np.pi, 200)
    ax.plot(
        OMEGA_RADIUS * np.cos(theta_grid),
        OMEGA_RADIUS * np.sin(theta_grid),
        "k-",
        linewidth=1.5,
    )
    if len(P1) > 0:
        hull = convex_hull(P1)
        ax.fill(hull[:, 0], hull[:, 1], alpha=0.3, color="C0", label="P1")
    ax.plot(s1[0], s1[1], "o", color="C0", markersize=8, label="S1")
    ax.annotate("S1", (s1[0] + 30, s1[1] + 30), fontsize=12)
    ax.plot(true_g[0], true_g[1], "r*", markersize=12, label="True source")
    sc = ax.scatter(
        candidates[:, 0], candidates[:, 1], c=scores, cmap="viridis_r", s=10, alpha=0.7
    )
    ax.plot(best_s[0], best_s[1], "rD", markersize=10, label="Best S2*")
    plt.colorbar(sc, ax=ax, label="Worst-case D(P2) (m)")
    ax.set_xlim(-2000, 2000)
    ax.set_ylim(-2000, 2000)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)
    ax.set_title(f"Problem 2: Candidate heatmap  |  P1: D={met1['diameter']:.0f}m")

    ax = axes[1]
    beta_vals = np.deg2rad(np.linspace(5, 175, 50))
    d_vals_500 = []
    d_vals_1000 = []
    d_vals_1500 = []
    for beta in beta_vals:
        test_s = s1 + 1000 * direction_vector(theta1 + beta)
        d_vals_500.append(
            worst_case_diameter_after_second(P1, test_s, n_angle_samples=12)
        )
        test_s = s1 + 1500 * direction_vector(theta1 + beta)
        d_vals_1000.append(
            worst_case_diameter_after_second(P1, test_s, n_angle_samples=12)
        )
        test_s = s1 + 2000 * direction_vector(theta1 + beta)
        d_vals_1500.append(
            worst_case_diameter_after_second(P1, test_s, n_angle_samples=12)
        )
    ax.plot(np.rad2deg(beta_vals), d_vals_500, label="d=1000m")
    ax.plot(np.rad2deg(beta_vals), d_vals_1000, label="d=1500m")
    ax.plot(np.rad2deg(beta_vals), d_vals_1500, label="d=2000m")
    ax.set_xlabel("Intersection angle β (deg)")
    ax.set_ylabel("Worst-case D(P2) (m)")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_title("Problem 2: Intersection angle vs localization error")

    fig.savefig(OUT_DIR / "problem2_candidate_heatmap.pdf", bbox_inches="tight")
    plt.close(fig)
    return {
        "P1_diameter": met1["diameter"],
        "P1_area": met1["area"],
        "best_s": best_s.tolist(),
        "best_diameter": best_d,
    }


def problem3_demo() -> dict[str, Any]:
    cover_pts = seven_cover_points()
    r_vals = np.linspace(1000, 1800, 100)
    max_dists = []
    for r in r_vals:
        min_dist = float("inf")
        for ang in np.linspace(0, 2 * np.pi, 200):
            pt = np.array([r * np.cos(ang), r * np.sin(ang)])
            d = min(float(np.linalg.norm(pt - cp)) for cp in cover_pts)
            min_dist = min(min_dist, d)
        max_dists.append(min_dist)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(r_vals, max_dists, "b-", linewidth=2)
    ax.axhline(
        1000, color="r", linestyle="--", label="Receive radius lower bound (1000m)"
    )
    ax.fill_between(
        r_vals,
        max_dists,
        1000,
        where=[d <= 1000 for d in max_dists],
        alpha=0.2,
        color="g",
    )
    ax.set_xlabel("Target distance from origin (m)")
    ax.set_ylabel("Distance to nearest cover point (m)")
    ax.set_title("Problem 3: Seven-point coverage verification")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.savefig(OUT_DIR / "problem3_coverage_verification.pdf", bbox_inches="tight")
    plt.close(fig)

    n_sources = 16
    sources = []
    for _ in range(n_sources):
        while True:
            pos = rng.uniform(-1800, 1800, 2).astype(float)
            if np.linalg.norm(pos) <= 1800:
                break
        r = rng.uniform(1000, 1500)
        sources.append(SourceSimulator(pos, "omni", r))

    tour = shortest_tour(cover_pts, start=np.array([0.0, 0.0]))
    tour_len = path_length(tour)
    results = run_omni_simulation(sources, n_freq=n_sources, seed=42, epsilon=2.0)

    fig, ax = plt.subplots(figsize=(8, 8))
    theta_grid = np.linspace(0, 2 * np.pi, 200)
    ax.plot(
        OMEGA_RADIUS * np.cos(theta_grid),
        OMEGA_RADIUS * np.sin(theta_grid),
        "k-",
        linewidth=1.5,
        label=r"$\Omega$",
    )
    tour_arr = np.array(tour)
    ax.plot(tour_arr[:, 0], tour_arr[:, 1], "b-", alpha=0.5, linewidth=2)
    for i, pt in enumerate(tour):
        marker = "s" if i == 0 else "o"
        ax.plot(pt[0], pt[1], marker, color="C0", markersize=8)
        if i == 0:
            ax.annotate("Start", (pt[0] + 30, pt[1] + 30), fontsize=10)
    for pt in cover_pts:
        circle = Circle(
            (pt[0], pt[1]), 1000, fill=False, color="C0", linestyle=":", alpha=0.3
        )
        ax.add_patch(circle)
    for src in sources:
        if src.cleared:
            ax.plot(src.true_pos[0], src.true_pos[1], "g*", markersize=8)
        else:
            ax.plot(src.true_pos[0], src.true_pos[1], "rx", markersize=8)
    ax.set_xlim(-2000, 2000)
    ax.set_ylim(-2000, 2000)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_title(
        f"Problem 3: Search trajectory  |  Cleared: {results['cleared']}/{results['total']}"
    )
    ax.legend(fontsize=9)
    fig.savefig(OUT_DIR / "problem3_search_trajectory.pdf", bbox_inches="tight")
    plt.close(fig)

    results["tour_length"] = tour_len
    return results


def problem4_demo() -> dict[str, Any]:
    n_sources = 16
    sources = []
    for _ in range(n_sources):
        while True:
            pos = rng.uniform(-1800, 1800, 2).astype(float)
            if np.linalg.norm(pos) <= 1800:
                break
        r = rng.uniform(1000, 1500)
        phi = rng.uniform(0, 2 * np.pi)
        sources.append(SourceSimulator(pos, "directional", r, phi))
    results = run_directional_simulation(
        sources, n_freq=n_sources, seed=42, epsilon=2.0
    )

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    ax = axes[0]
    theta_grid = np.linspace(0, 2 * np.pi, 200)
    ax.plot(
        OMEGA_RADIUS * np.cos(theta_grid),
        OMEGA_RADIUS * np.sin(theta_grid),
        "k-",
        linewidth=1.5,
        label=r"$\Omega$",
    )
    for src in sources:
        c = "g" if src.cleared else "r"
        marker = "*" if src.cleared else "x"
        ax.plot(src.true_pos[0], src.true_pos[1], c + marker, markersize=8)
        r_circle = Circle(
            (src.true_pos[0], src.true_pos[1]),
            src.receive_radius,
            fill=False,
            color=c,
            linestyle=":",
            alpha=0.2,
        )
        ax.add_patch(r_circle)
        if src.source_type == "directional":
            d_vec = np.array([np.cos(src.direction_angle), np.sin(src.direction_angle)])
            ax.arrow(
                src.true_pos[0],
                src.true_pos[1],
                d_vec[0] * src.receive_radius * 0.5,
                d_vec[1] * src.receive_radius * 0.5,
                head_width=50,
                head_length=50,
                fc=c,
                ec=c,
                alpha=0.4,
            )
    ax.set_xlim(-2000, 2000)
    ax.set_ylim(-2000, 2000)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_title(
        f"Problem 4: Directional sources  |  Cleared: {results['cleared']}/{results['total']}"
    )
    ax.legend(fontsize=9)

    ax = axes[1]
    phi_vals = np.array([0, 45, 90, 135])
    for phi_deg in phi_vals:
        phi = np.deg2rad(phi_deg)
        d_vec = np.array([np.cos(phi), np.sin(phi)])
        grid_size = 50
        xs = np.arange(-1800, 1801, grid_size)
        ys = np.arange(-1800, 1801, grid_size)
        X, Y = np.meshgrid(xs, ys)
        coverage = np.zeros_like(X, dtype=float)
        cover_pts = seven_cover_points()
        for i in range(X.shape[0]):
            for j in range(X.shape[1]):
                pos = np.array([X[i, j], Y[i, j]])
                if np.linalg.norm(pos) > 1800:
                    coverage[i, j] = np.nan
                else:
                    count = 0
                    for cp in cover_pts:
                        dist = float(np.linalg.norm(cp - pos))
                        if dist <= 1000 and float(np.dot(d_vec, cp - pos)) >= 0:
                            count += 1
                    coverage[i, j] = count
        if phi_deg == 0:
            im = ax.pcolormesh(X, Y, coverage, cmap="viridis", shading="auto")
            ax.plot(
                OMEGA_RADIUS * np.cos(theta_grid),
                OMEGA_RADIUS * np.sin(theta_grid),
                "k-",
                linewidth=1,
            )
            ax.set_aspect("equal")
            ax.set_title(f"Coverage at φ={phi_deg}°")
            ax.set_xlabel("x (m)")
            ax.set_ylabel("y (m)")
            plt.colorbar(im, ax=ax, label="Covering points")
    fig.savefig(OUT_DIR / "problem4_coverage_map.pdf", bbox_inches="tight")
    plt.close(fig)
    return results


def problem13_illustration() -> None:
    true_g = np.array([300.0, 200.0])
    s1 = np.array([-800.0, 0.0])
    s2 = np.array([400.0, 800.0])
    theta1 = simulate_bearing(true_g, s1)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, s_other, label in [
        (axes[0], s2, "Small angle (~15°)"),
        (axes[1], np.array([100.0, -100.0]), "Large angle (~90°)"),
    ]:
        th_other = simulate_bearing(true_g, s_other)
        P = compute_region([(s1, theta1), (s_other, th_other)])
        theta_grid = np.linspace(0, 2 * np.pi, 200)
        ax.plot(
            OMEGA_RADIUS * np.cos(theta_grid),
            OMEGA_RADIUS * np.sin(theta_grid),
            "k-",
            linewidth=1.5,
        )
        ax.plot(s1[0], s1[1], "o", color="C0", markersize=8, label="S1")
        ax.plot(s_other[0], s_other[1], "o", color="C1", markersize=8, label="S2")
        ax.annotate("S1", (s1[0] + 30, s1[1] + 30), fontsize=10)
        ax.annotate("S2", (s_other[0] + 30, s_other[1] + 30), fontsize=10)
        for s, th, c in [(s1, theta1, "C0"), (s_other, th_other, "C1")]:
            for ang in [th - DELTA_RAD, th, th + DELTA_RAD]:
                u = direction_vector(ang)
                ax.plot(
                    [s[0], s[0] + 2500 * u[0]],
                    [s[1], s[1] + 2500 * u[1]],
                    "--",
                    color=c,
                    linewidth=1,
                    alpha=0.4,
                )
        if len(P) > 0:
            hull = convex_hull(P)
            ax.fill(hull[:, 0], hull[:, 1], alpha=0.3, color="C3")
            d = polygon_diameter(hull)
            _, r = smallest_enclosing_circle(hull)
            ax.set_title(f"{label}\nD(P)={d:.0f}m, R(P)={r:.0f}m")
        ax.plot(true_g[0], true_g[1], "r*", markersize=12, label="True")
        ax.set_xlim(-2000, 2000)
        ax.set_ylim(-2000, 2000)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)
    fig.savefig(
        OUT_DIR / "problem1_intersection_angle_comparison.pdf", bbox_inches="tight"
    )
    plt.close(fig)


def omni_vs_directional_comparison() -> dict[str, Any]:
    n_trials = 20
    n_sources = 16
    omni_results = []
    dir_results = []
    for t in range(n_trials):
        omni_sources = []
        dir_sources = []
        for _ in range(n_sources):
            while True:
                pos = rng.uniform(-1800, 1800, 2).astype(float)
                if np.linalg.norm(pos) <= 1800:
                    break
            r = rng.uniform(1000, 1500)
            omni_sources.append(SourceSimulator(pos, "omni", r))
            phi = rng.uniform(0, 2 * np.pi)
            dir_sources.append(SourceSimulator(pos.copy(), "directional", r, phi))
        omni_r = run_omni_simulation(
            omni_sources, n_freq=n_sources, seed=t, epsilon=2.0
        )
        dir_r = run_directional_simulation(
            dir_sources, n_freq=n_sources, seed=t, epsilon=2.0
        )
        omni_results.append(omni_r)
        dir_results.append(dir_r)

    fig, ax = plt.subplots(figsize=(8, 5))
    categories = ["Clear ratio", "Avg time (s)", "Measures"]
    omni_vals = [
        np.mean([r["ratio"] for r in omni_results]),
        np.mean([r["time"] for r in omni_results]),
        np.mean([r["measures"] for r in omni_results]),
    ]
    dir_vals = [
        np.mean([r["ratio"] for r in dir_results]),
        np.mean([r["time"] for r in dir_results]),
        np.mean([r["measures"] for r in dir_results]),
    ]
    x = np.arange(len(categories))
    width = 0.35
    ax.bar(x - width / 2, omni_vals, width, label="Omni strategy", alpha=0.8)
    ax.bar(x + width / 2, dir_vals, width, label="Directional strategy", alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.set_ylabel("Value")
    ax.set_title("Omni vs Directional: Comparison")
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    fig.savefig(OUT_DIR / "omni_vs_directional_comparison.pdf", bbox_inches="tight")
    plt.close(fig)
    return {"omni": omni_results, "directional": dir_results}


def main() -> None:
    np.random.seed(2026)
    print("=" * 60)  # noqa: T201
    print("CUMCM 2026 Problem B: 无线电干扰源定位与清除")  # noqa: T201
    print("=" * 60)  # noqa: T201

    print("\n[Problem 1] 有界误差交会定位...")  # noqa: T201
    met1 = problem1_demo()
    print(f"  D(P)={met1['diameter']:.1f}m, R(P)={met1['min_enclosing_radius']:.1f}m")  # noqa: T201
    table1 = problem1_intersection_table()
    print(f"  Intersection table:\n{table1}")  # noqa: T201

    print("\n[Problem 1] 交会角对比图...")  # noqa: T201
    problem13_illustration()
    print("  -> problem1_intersection_angle_comparison.pdf")  # noqa: T201

    print("\n[Problem 2] 第二检测点选择...")  # noqa: T201
    met2 = problem2_demo()
    print(f"  P1 diameter: {met2['P1_diameter']:.1f}m")  # noqa: T201
    print(f"  Best S2 position: {met2['best_s']}")  # noqa: T201
    print(f"  Best worst-case diameter: {met2['best_diameter']:.1f}m")  # noqa: T201
    print("  -> problem2_candidate_heatmap.pdf")  # noqa: T201

    print("\n[Problem 3] 全向源覆盖定位...")  # noqa: T201
    met3 = problem3_demo()
    print(f"  Coverage tour length: {met3['tour_length']:.0f}m")  # noqa: T201
    print(f"  Cleared: {met3['cleared']}/{met3['total']} (ratio: {met3['ratio']:.2f})")  # noqa: T201
    print(f"  Total time: {met3['time']:.1f}s")  # noqa: T201
    print("  -> problem3_coverage_verification.pdf, problem3_search_trajectory.pdf")  # noqa: T201

    print("\n[Problem 4] 定向源模型...")  # noqa: T201
    met4 = problem4_demo()
    print(f"  Cleared: {met4['cleared']}/{met4['total']} (ratio: {met4['ratio']:.2f})")  # noqa: T201
    print("  -> problem4_coverage_map.pdf")  # noqa: T201

    print("\n[Comparison] 全向vs定向策略对比...")  # noqa: T201
    comp = omni_vs_directional_comparison()
    omni_ratio = np.mean([r["ratio"] for r in comp["omni"]])
    dir_ratio = np.mean([r["ratio"] for r in comp["directional"]])
    print(f"  Omni avg clear ratio: {omni_ratio:.3f}")  # noqa: T201
    print(f"  Directional avg clear ratio: {dir_ratio:.3f}")  # noqa: T201
    print("  -> omni_vs_directional_comparison.pdf")  # noqa: T201

    print("\n" + "=" * 60)  # noqa: T201
    print("All artifacts saved to out/")  # noqa: T201


if __name__ == "__main__":
    main()
