import numpy as np

type Vec2 = np.ndarray


def direction_vector(alpha: float) -> Vec2:
    return np.array([np.cos(alpha), np.sin(alpha)])


def cross_2d(a: Vec2, b: Vec2) -> float:
    return a[0] * b[1] - a[1] * b[0]


def normalize_angle(theta: float) -> float:
    return theta % (2 * np.pi)


def convex_hull(points: np.ndarray) -> np.ndarray:
    pts = points[np.lexsort((points[:, 0], points[:, 1]))]
    lower: list[Vec2] = []
    for p in pts:
        while len(lower) >= 2 and cross_2d(lower[-1] - lower[-2], p - lower[-1]) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Vec2] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross_2d(upper[-1] - upper[-2], p - upper[-1]) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def clip_convex_polygon_by_halfplane(
    polygon: np.ndarray,
    point: Vec2,
    normal: Vec2,
) -> np.ndarray:
    eps = -1e-12
    output: list[Vec2] = []
    m = len(polygon)
    for i in range(m):
        cur = polygon[i]
        prev = polygon[(i - 1) % m]
        cur_in = np.dot(normal, cur - point) >= eps
        prev_in = np.dot(normal, prev - point) >= eps
        if cur_in:
            if not prev_in:
                t = np.dot(normal, prev - point) / np.dot(normal, prev - cur)
                output.append(prev + t * (cur - prev))
            output.append(cur)
        elif prev_in:
            t = np.dot(normal, prev - point) / np.dot(normal, prev - cur)
            output.append(prev + t * (cur - prev))
    return np.array(output) if output else np.empty((0, 2))


def polygon_diameter(vertices: np.ndarray) -> float:
    if len(vertices) < 2:
        return 0.0
    max_d = 0.0
    n = len(vertices)
    for i in range(n):
        vi = vertices[i]
        for j in range(i + 1, n):
            d = float(np.linalg.norm(vi - vertices[j]))
            max_d = max(max_d, d)
    return max_d


def smallest_enclosing_circle(vertices: np.ndarray) -> tuple[Vec2, float]:
    n = len(vertices)
    if n == 0:
        return np.array([0.0, 0.0]), 0.0
    if n == 1:
        return vertices[0].copy(), 0.0
    if n == 2:
        center = (vertices[0] + vertices[1]) / 2
        radius = float(np.linalg.norm(vertices[0] - vertices[1]) / 2)
        return center, radius
    points = vertices.copy()
    rng = np.random.default_rng(42)
    rng.shuffle(points)

    def _circle_from_boundary(b: list[Vec2]) -> tuple[Vec2, float]:
        if len(b) == 0:
            return np.array([0.0, 0.0]), 0.0
        if len(b) == 1:
            return b[0].copy(), 0.0
        if len(b) == 2:
            c = (b[0] + b[1]) / 2
            r = float(np.linalg.norm(b[0] - b[1]) / 2)
            return c, r
        a0, b0, c0 = b[0], b[1], b[2]
        d2_ab = float(np.linalg.norm(a0 - b0) ** 2)
        d2_bc = float(np.linalg.norm(b0 - c0) ** 2)
        d2_ca = float(np.linalg.norm(c0 - a0) ** 2)
        if d2_ab + d2_bc <= d2_ca:
            return (a0 + c0) / 2, np.sqrt(d2_ca) / 2
        if d2_ab + d2_ca <= d2_bc:
            return (b0 + c0) / 2, np.sqrt(d2_bc) / 2
        if d2_bc + d2_ca <= d2_ab:
            return (a0 + b0) / 2, np.sqrt(d2_ab) / 2
        d = 2 * (
            a0[0] * (b0[1] - c0[1]) + b0[0] * (c0[1] - a0[1]) + c0[0] * (a0[1] - b0[1])
        )
        if abs(d) < 1e-15:
            c = (a0 + b0 + c0) / 3
            return c, float(np.linalg.norm(a0 - c))
        ux = (
            (a0[0] ** 2 + a0[1] ** 2) * (b0[1] - c0[1])
            + (b0[0] ** 2 + b0[1] ** 2) * (c0[1] - a0[1])
            + (c0[0] ** 2 + c0[1] ** 2) * (a0[1] - b0[1])
        ) / d
        uy = (
            (a0[0] ** 2 + a0[1] ** 2) * (c0[0] - b0[0])
            + (b0[0] ** 2 + b0[1] ** 2) * (a0[0] - c0[0])
            + (c0[0] ** 2 + c0[1] ** 2) * (b0[0] - a0[0])
        ) / d
        center = np.array([ux, uy])
        return center, float(np.linalg.norm(a0 - center))

    def _welzl(p: list[Vec2], r: list[Vec2]) -> tuple[Vec2, float]:
        if len(p) == 0 or len(r) == 3:
            return _circle_from_boundary(r)
        pick = p[0]
        c, rad = _welzl(p[1:], r)
        if np.linalg.norm(pick - c) <= rad + 1e-12:
            return c, rad
        return _welzl(p[1:], [*r, pick])

    return _welzl(list(points), [])


def polygon_area(vertices: np.ndarray) -> float:
    if len(vertices) < 3:
        return 0.0
    x, y = vertices[:, 0], vertices[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))


def regular_polygon_vertices(
    n: int, radius: float, center: Vec2 | None = None
) -> np.ndarray:
    if center is None:
        center = np.array([0.0, 0.0])
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack(
        [center[0] + radius * np.cos(angles), center[1] + radius * np.sin(angles)]
    )
