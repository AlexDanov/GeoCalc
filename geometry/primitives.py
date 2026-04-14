from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


EPSILON = 1e-9


class GeometryError(Exception):
    pass


def _is_close(value: float, other: float, eps: float = EPSILON) -> bool:
    return abs(value - other) <= eps


class Primitive:
    def selector(self, other, type_handlers):
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

    def bind_name(self, name: str, value: object) -> None:
        if isinstance(value, Point):
            self.scene.point_names[id(value)] = name
            if value.draggable:
                self.scene.draggable_points[name] = value
        elif isinstance(value, Line):
            self.scene.line_names[id(value)] = name
        elif isinstance(value, Circle):
            self.scene.circle_names[id(value)] = name


class Point(Primitive):
    def __init__(
        self,
        x: float,
        y: float,
        *,
        draggable: bool = False,
        name: Optional[str] = None,
    ):
        self.x = float(x)
        self.y = float(y)
        self.draggable = draggable
        self.name = name
        context = BuildContext.current
        if context is not None:
            context.register(self)

    @classmethod
    def base(cls, name: str, x: float, y: float) -> "Point":
        context = BuildContext.current
        if context is not None and name in context.overrides:
            x, y = context.overrides[name]
        return cls(x, y, draggable=True, name=name)

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
                Vector: lambda a, b: Line(a, a + b),
            },
        )

    def move_to(self, x: float, y: float) -> None:
        self.x = float(x)
        self.y = float(y)

    def __repr__(self) -> str:
        return f"Point({self.x:.3f}, {self.y:.3f})"


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


class Line(Primitive):
    def __init__(self, p1: Point, p2: Point):
        if _is_close(p1.x, p2.x) and _is_close(p1.y, p2.y):
            raise GeometryError("A line requires two distinct points")
        self.p1 = p1
        self.p2 = p2
        self.a, self.b, self.c = self._calculate_coefficients()
        context = BuildContext.current
        if context is not None:
            context.register(self)

    def _calculate_coefficients(self):
        a = self.p2.y - self.p1.y
        b = self.p1.x - self.p2.x
        normal = Vector(a, b).normalize()
        a, b = normal.dx, normal.dy
        c = -(a * self.p1.x + b * self.p1.y)
        return a, b, c

    def direction(self) -> Vector:
        return Vector(self.p2.x - self.p1.x, self.p2.y - self.p1.y)

    def cross_line(self, line: "Line") -> Point:
        det = self.a * line.b - line.a * self.b
        if _is_close(det, 0.0):
            raise GeometryError("Parallel lines do not intersect")
        x = (line.c * self.b - self.c * line.b) / det
        y = (self.c * line.a - line.c * self.a) / det
        return Point(x, y)

    def project_point(self, point: Point) -> Point:
        perpendicular = point | ~self
        return self & perpendicular

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
            },
        )

    def __repr__(self) -> str:
        return f"Line({self.p1!r}, {self.p2!r})"


class Circle(Primitive):
    def __init__(self, a, b, c=None):
        if isinstance(a, Point) and isinstance(b, (int, float)) and c is None:
            self.center = a
            self.radius = float(b)
        elif isinstance(a, Point) and isinstance(b, Point) and isinstance(c, Point):
            self.center, self.radius = self._circle_from_three_points(a, b, c)
        else:
            raise TypeError("Circle expects either (center, radius) or three points")

        if self.radius <= EPSILON:
            raise GeometryError("Circle radius must be positive")

        context = BuildContext.current
        if context is not None:
            context.register(self)

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

    def __repr__(self) -> str:
        return f"Circle({self.center!r}, {self.radius:.3f})"
