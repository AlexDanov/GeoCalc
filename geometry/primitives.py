from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


EPSILON = 1e-9


class GeometryError(Exception):
    pass


def _is_close(value: float, other: float, eps: float = EPSILON) -> bool:
    return abs(value - other) <= eps


class Primitive:
    def selector(self, other, type_handlers: Dict[type, Callable]):
        for expected_type, handler in type_handlers.items():
            if isinstance(other, expected_type):
                return handler(self, other)
        raise TypeError(
            f"Operation is not defined for {type(self).__name__} and {type(other).__name__}"
        )


@dataclass
class SceneSnapshot:
    points: List["Point"] = field(default_factory=list)
    lines: List["Line"] = field(default_factory=list)
    circles: List["Circle"] = field(default_factory=list)
    point_names: Dict[int, str] = field(default_factory=dict)
    line_names: Dict[int, str] = field(default_factory=dict)
    circle_names: Dict[int, str] = field(default_factory=dict)
    draggable_points: Dict[str, "Point"] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    visible_point_ids: set[int] = field(default_factory=set)
    visible_line_ids: set[int] = field(default_factory=set)
    visible_circle_ids: set[int] = field(default_factory=set)
    hidden_point_ids: set[int] = field(default_factory=set)
    hidden_line_ids: set[int] = field(default_factory=set)
    hidden_circle_ids: set[int] = field(default_factory=set)


class BuildContext:
    current: Optional["BuildContext"] = None

    def __init__(self, overrides: Optional[Dict[str, tuple[float, float]]] = None):
        self.overrides = overrides or {}
        self.scene = SceneSnapshot()

    def register(self, primitive: Primitive) -> None:
        if isinstance(primitive, Point):
            self.scene.points.append(primitive)
        elif isinstance(primitive, Line):
            self.scene.lines.append(primitive)
        elif isinstance(primitive, Circle):
            self.scene.circles.append(primitive)

    @staticmethod
    def _bind_primitive_name(
        name: str,
        primitive: Primitive,
        names_map: Dict[int, str],
        visible_ids: set[int],
        hidden_ids: set[int],
    ) -> bool:
        if name.startswith("_"):
            hidden_ids.add(id(primitive))
            return True
        names_map[id(primitive)] = name
        visible_ids.add(id(primitive))
        return False

    def bind_name(self, name: str, value: object) -> None:
        if isinstance(value, Point):
            hidden = self._bind_primitive_name(
                name,
                value,
                self.scene.point_names,
                self.scene.visible_point_ids,
                self.scene.hidden_point_ids,
            )
            if value.draggable and not hidden:
                self.scene.draggable_points[name] = value
        elif isinstance(value, Line):
            self._bind_primitive_name(
                name,
                value,
                self.scene.line_names,
                self.scene.visible_line_ids,
                self.scene.hidden_line_ids,
            )
        elif isinstance(value, Circle):
            self._bind_primitive_name(
                name,
                value,
                self.scene.circle_names,
                self.scene.visible_circle_ids,
                self.scene.hidden_circle_ids,
            )


class Vector(Primitive):
    def __init__(self, dx: float, dy: float):
        self.dx = float(dx)
        self.dy = float(dy)

    def __iter__(self):
        yield from (self.dx, self.dy)

    def __add__(self, other):
        return self.selector(
            other,
            {Vector: lambda a, b: Vector(a.dx + b.dx, a.dy + b.dy)},
        )

    def __sub__(self, other):
        return self.selector(
            other,
            {Vector: lambda a, b: Vector(a.dx - b.dx, a.dy - b.dy)},
        )

    def __mul__(self, other):
        return self.selector(
            other,
            {
                int: lambda a, b: Vector(a.dx * b, a.dy * b),
                float: lambda a, b: Vector(a.dx * b, a.dy * b),
            },
        )

    def __rmul__(self, other):
        return self.__mul__(other)

    def __truediv__(self, other):
        if _is_close(float(other), 0.0):
            raise GeometryError("Cannot divide vector by zero")
        return self.selector(
            other,
            {
                int: lambda a, b: Vector(a.dx / b, a.dy / b),
                float: lambda a, b: Vector(a.dx / b, a.dy / b),
            },
        )

    def __neg__(self):
        return Vector(-self.dx, -self.dy)

    def dot(self, other: "Vector") -> float:
        return self.dx * other.dx + self.dy * other.dy

    def cross(self, other: "Vector") -> float:
        return self.dx * other.dy - self.dy * other.dx

    def length(self) -> float:
        return math.hypot(self.dx, self.dy)

    def atan2(self) -> float:
        return math.degrees(math.atan2(self.dy, self.dx))

    def normalize(self) -> "Vector":
        length = self.length()
        if _is_close(length, 0.0):
            raise GeometryError("Cannot normalize zero-length vector")
        return self / length

    def __abs__(self) -> float:
        return self.length()

    def __xor__(self, other):
        return self.selector(
            other,
            {Vector: lambda a, b: a.atan2() - b.atan2()},
        )

    def __invert__(self):
        return Vector(-self.dy, self.dx)

    def __repr__(self) -> str:
        return f"Vector({self.dx:.3f}, {self.dy:.3f})"


class Point(Primitive):
    def __init__(
        self,
        x: float,
        y: float,
        *,
        draggable: bool = False,
        name: Optional[str] = None,
        _register: bool = True,
    ):
        self.x = float(x)
        self.y = float(y)
        self.draggable = draggable
        self.name = name
        self.hidden = False
        context = BuildContext.current
        if context is not None and _register:
            context.register(self)

    @classmethod
    def base(cls, name: str, x: float, y: float) -> "Point":
        context = BuildContext.current
        if context is not None and name in context.overrides:
            x, y = context.overrides[name]
        return cls(x, y, draggable=True, name=name)

    @classmethod
    def hidden(cls, x: float, y: float) -> "Point":
        point = cls(x, y, _register=False)
        point.hidden = True
        return point

    def __iter__(self):
        yield from (self.x, self.y)

    def __sub__(self, other):
        return self.selector(
            other,
            {
                Point: lambda a, b: Vector(a.x - b.x, a.y - b.y),
                Vector: lambda a, b: Point(a.x - b.dx, a.y - b.dy),
            },
        )

    def __add__(self, other):
        return self.selector(
            other,
            {Vector: lambda a, b: Point(a.x + b.dx, a.y + b.dy)},
        )

    def __or__(self, other):
        return self.selector(
            other,
            {
                Point: lambda a, b: Line(a, b),
                Vector: lambda a, b: Line.from_point_direction(a, b),
                int: lambda a, b: Circle.from_center_radius(a, float(b)),
                float: lambda a, b: Circle.from_center_radius(a, float(b)),
            },
        )

    def __floordiv__(self, other):
        return self.selector(
            other,
            {Line: lambda a, b: Line.from_point_direction(a, b.direction().normalize())},
        )

    def __matmul__(self, other):
        def reflect(point: Point, line: Line):
            d = line.a * point.x + line.b * point.y + line.c
            return Point(point.x - 2 * d * line.a, point.y - 2 * d * line.b)

        return self.selector(
            other,
            {Line: reflect},
        )

    def __mod__(self, other):
        return self.selector(
            other,
            {Circle: lambda a, b: b.tangents_from_point(a)},
        )

    def move_to(self, x: float, y: float) -> None:
        self.x = float(x)
        self.y = float(y)

    def __repr__(self) -> str:
        return f"Point({self.x:.3f}, {self.y:.3f})"


class Line(Primitive):
    def __init__(self, p1: Point, p2: Point, *, _register: bool = True):
        if _is_close(p1.x, p2.x) and _is_close(p1.y, p2.y):
            raise GeometryError("A line requires two distinct points")
        self.p1 = p1
        self.p2 = p2
        self.a, self.b, self.c = self._calculate_coefficients()
        context = BuildContext.current
        if context is not None and _register:
            context.register(self)

    @classmethod
    def from_point_direction(cls, point: Point, direction: Vector, *, _register: bool = True) -> "Line":
        if _is_close(abs(direction), 0.0):
            raise GeometryError("Direction vector for a line cannot be zero")
        hidden = Point.hidden(point.x + direction.dx, point.y + direction.dy)
        return cls(point, hidden, _register=_register)

    def _calculate_coefficients(self):
        a = self.p2.y - self.p1.y
        b = self.p1.x - self.p2.x
        normal = Vector(a, b).normalize()
        a, b = normal.dx, normal.dy
        c = -(a * self.p1.x + b * self.p1.y)
        return a, b, c

    def direction(self) -> Vector:
        return Vector(-self.b, self.a)

    def cross_line(self, line: "Line") -> Optional[Point]:
        det = self.a * line.b - line.a * self.b
        if _is_close(det, 0.0):
            return None
        x = (line.c * self.b - self.c * line.b) / det
        y = (self.c * line.a - line.c * self.a) / det
        return Point(x, y)

    def project_point(self, point: Point) -> Point:
        d = self.a * point.x + self.b * point.y + self.c
        return Point(point.x - d * self.a, point.y - d * self.b)

    def __invert__(self):
        return Vector(self.a, self.b)

    def __abs__(self):
        return abs(self.p1 - self.p2)

    def __contains__(self, other):
        if isinstance(other, Point):
            return _is_close(self.a * other.x + self.b * other.y + self.c, 0.0, 1e-6)
        return False

    def __and__(self, other):
        return self.selector(
            other,
            {
                Line: lambda a, b: a.cross_line(b),
                Point: lambda a, b: a.project_point(b),
                Circle: lambda a, b: b.intersect_line(a),
            },
        )

    def __or__(self, other):
        return self.selector(
            other,
            {Point: lambda a, b: Circle(a.p1, a.p2, b)},
        )

    def __repr__(self) -> str:
        return f"Line({self.p1!r}, {self.p2!r})"


class Circle(Primitive):
    def __init__(self, a, b, c=None):
        if isinstance(a, Point) and isinstance(b, (int, float)) and c is None:
            self.center = a
            self.radius = float(b)
        elif isinstance(a, Point) and isinstance(b, Point) and c is None:
            self.center = a
            self.radius = abs(a - b)
        elif isinstance(a, Point) and isinstance(b, Point) and isinstance(c, Point):
            self.center, self.radius = self._circle_from_three_points(a, b, c)
        else:
            raise TypeError("Circle expects (center, radius), (center, point), or three points")

        if self.radius <= EPSILON:
            raise GeometryError("Circle radius must be positive")

        context = BuildContext.current
        if context is not None:
            context.register(self)

    @classmethod
    def from_center_radius(cls, center: Point, radius: float) -> "Circle":
        return cls(center, radius)

    @staticmethod
    def _circle_from_three_points(a: Point, b: Point, c: Point) -> tuple[Point, float]:
        determinant = 2 * (
            a.x * (b.y - c.y)
            + b.x * (c.y - a.y)
            + c.x * (a.y - b.y)
        )
        if _is_close(determinant, 0.0):
            raise GeometryError("Cannot build a circle through collinear points")

        a_sq = a.x**2 + a.y**2
        b_sq = b.x**2 + b.y**2
        c_sq = c.x**2 + c.y**2

        ux = (
            a_sq * (b.y - c.y)
            + b_sq * (c.y - a.y)
            + c_sq * (a.y - b.y)
        ) / determinant
        uy = (
            a_sq * (c.x - b.x)
            + b_sq * (a.x - c.x)
            + c_sq * (b.x - a.x)
        ) / determinant

        center = Point(ux, uy)
        radius = abs(a - center)
        return center, radius

    def __iter__(self):
        yield from (self.center, self.radius)

    def __contains__(self, other):
        if isinstance(other, Point):
            return _is_close(abs(self.center - other), self.radius, 1e-5)
        return False

    def __and__(self, other):
        return self.selector(
            other,
            {
                Circle: lambda a, b: a.intersect_circle(b),
                Line: lambda a, b: a.intersect_line(b),
            },
        )

    def __rmod__(self, other):
        return self.selector(
            other,
            {Point: lambda a, b: b.tangents_from_point(a)},
        )

    def intersect_line(self, line: Line):
        cx, cy = self.center.x, self.center.y
        d = line.a * cx + line.b * cy + line.c
        fx = cx - d * line.a
        fy = cy - d * line.b
        disc = self.radius**2 - d**2

        if disc < -EPSILON:
            return None
        if disc <= EPSILON:
            p = Point(fx, fy)
            return (p, p)

        h = math.sqrt(disc)
        dx, dy = -line.b, line.a
        p1 = Point(fx + h * dx, fy + h * dy)
        p2 = Point(fx - h * dx, fy - h * dy)
        return (p1, p2)

    def intersect_circle(self, other: "Circle"):
        x1, y1, r1 = self.center.x, self.center.y, self.radius
        x2, y2, r2 = other.center.x, other.center.y, other.radius
        d = math.hypot(x2 - x1, y2 - y1)

        if d < EPSILON or d > r1 + r2 + EPSILON or d < abs(r1 - r2) - EPSILON:
            return None

        a = (r1**2 - r2**2 + d**2) / (2 * d)
        h2 = r1**2 - a**2
        h = math.sqrt(max(h2, 0.0))

        mx = x1 + a * (x2 - x1) / d
        my = y1 + a * (y2 - y1) / d
        px = h * (y2 - y1) / d
        py = h * (x2 - x1) / d

        p1 = Point(mx + px, my - py)
        p2 = Point(mx - px, my + py)
        return (p1, p2)

    def tangents_from_point(self, point: Point):
        d = abs(point - self.center)
        if d < self.radius - EPSILON:
            return None

        if _is_close(d, self.radius):
            n = (point - self.center).normalize()
            tang = Vector(-n.dy, n.dx)
            line = Line.from_point_direction(point, tang)
            return (line, line)

        h = math.sqrt(d**2 - self.radius**2)
        angle_base = math.atan2(self.center.y - point.y, self.center.x - point.x)
        alpha = math.asin(self.radius / d)

        lines = []
        for sign in (1.0, -1.0):
            a = angle_base + sign * alpha
            q = Point(point.x + h * math.cos(a), point.y + h * math.sin(a))
            lines.append(Line(point, q))
        return tuple(lines)

    def __repr__(self) -> str:
        return f"Circle({self.center!r}, {self.radius:.3f})"


def mid(a: Point, b: Point) -> Point:
    return Point((a.x + b.x) / 2, (a.y + b.y) / 2)


def div(a: Point, b: Point, k: float, n: float = 1.0) -> Point:
    denom = k + n
    if _is_close(denom, 0.0):
        raise GeometryError("div(A, B, k, n) requires k + n != 0")
    t = k / denom
    return Point(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y))


def dist(point: Point, obj) -> float:
    if isinstance(obj, Line):
        return abs(obj.a * point.x + obj.b * point.y + obj.c)
    if isinstance(obj, Point):
        return abs(point - obj)
    raise TypeError("dist expects Point and (Line|Point)")


def angle(b: Point, a: Point, c: Point) -> float:
    v1 = b - a
    v2 = c - a
    denom = abs(v1) * abs(v2)
    if _is_close(denom, 0.0):
        raise GeometryError("angle(B, A, C) is undefined for zero-length rays")
    cos_value = max(-1.0, min(1.0, v1.dot(v2) / denom))
    return math.degrees(math.acos(cos_value))


def bisect(a: Point, b: Point, c: Point, n: int = 1):
    """Angle bisector(s) for angle ABC with vertex at B."""
    if n < 1:
        raise GeometryError("bisect requires n >= 1")
    if not (isinstance(a, Point) and isinstance(b, Point) and isinstance(c, Point)):
        raise TypeError("bisect expects (Point A, Point B, Point C[, n])")

    d1 = (a - b).normalize()
    d2 = (c - b).normalize()
    vertex = b

    if _is_close(abs(d1), 0.0) or _is_close(abs(d2), 0.0):
        raise GeometryError("Cannot bisect angle with zero-length ray")

    a1 = math.atan2(d1.dy, d1.dx)
    a2 = math.atan2(d2.dy, d2.dx)
    da = a2 - a1
    while da > math.pi:
        da -= 2 * math.pi
    while da < -math.pi:
        da += 2 * math.pi

    mid_angle = a1 + da / 2.0
    bisector_dir = Vector(math.cos(mid_angle), math.sin(mid_angle))
    if _is_close(abs(bisector_dir), 0.0):
        raise GeometryError("Cannot compute bisector direction")

    if n == 1:
        return Line.from_point_direction(vertex, bisector_dir)

    if n == 2:
        primary = Line.from_point_direction(vertex, bisector_dir)
        secondary = Line.from_point_direction(vertex, ~primary)
        return (primary, secondary)

    lines = []
    for i in range(1, n):
        a = a1 + da * i / n
        direction = Vector(math.cos(a), math.sin(a))
        lines.append(Line.from_point_direction(vertex, direction))
    return tuple(lines)
