from __future__ import annotations

import ast
import math
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Optional

from .primitives import (
    BuildContext,
    Circle,
    GeometryError,
    Line,
    Point,
    SceneSnapshot,
    Vector,
    angle,
    bisect,
    dist,
    div,
    mid,
)


class DSLExecutionError(Exception):
    pass


SAFE_BUILTINS = {
    "abs": abs,
    "isinstance": isinstance,
    "len": len,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "sum": sum,
}


class BasePointTransformer(ast.NodeTransformer):
    @staticmethod
    def _numeric_literal(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return isinstance(node.value, (int, float))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return BasePointTransformer._numeric_literal(node.operand)
        return False

    @staticmethod
    def _tuple_to_point_call(node: ast.AST) -> ast.AST | None:
        if not isinstance(node, ast.Tuple):
            return None
        if len(node.elts) != 2:
            return None
        if not all(BasePointTransformer._numeric_literal(elt) for elt in node.elts):
            return None
        return ast.Call(func=ast.Name(id="Point", ctx=ast.Load()), args=list(node.elts), keywords=[])

    def visit_Assign(self, node: ast.Assign):
        self.generic_visit(node)
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "Point"
        ):
            node.value.func.id = "__base_point__"
            node.value.args.insert(0, ast.Constant(node.targets[0].id))
        return node

    def visit_BinOp(self, node: ast.BinOp):
        self.generic_visit(node)
        if isinstance(node.op, ast.BitOr):
            left_point = self._tuple_to_point_call(node.left)
            right_point = self._tuple_to_point_call(node.right)
            if left_point is not None:
                node.left = left_point
            if right_point is not None:
                node.right = right_point
        return node


@dataclass
class ExecutionResult:
    scene: SceneSnapshot
    namespace: Dict[str, object]


class _Console:
    def __init__(self, context: BuildContext):
        self._context = context

    def print(self, *args, **kwargs):
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        self._context.scene.logs.append(sep.join(str(item) for item in args) + end)


class DSLNamespace(dict):
    """Runtime namespace with implicit support for two-point line aliases.

    If `AB` is requested and not defined, but `A` and `B` exist as points,
    it resolves to `A | B`. `BA` resolves to the same line instance.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._implicit_line_cache: dict[str, Line] = {}

    @staticmethod
    def _is_pair_name(name: str) -> bool:
        return len(name) == 2 and name.isalpha()

    def _resolve_from_existing_reverse(self, name: str) -> Line | None:
        reverse = name[::-1]
        reverse_value = dict.get(self, reverse)
        if isinstance(reverse_value, Line):
            self[name] = reverse_value
            return reverse_value
        return None

    def _resolve_from_points(self, name: str) -> Line | None:
        if not self._is_pair_name(name):
            return None

        a_name, b_name = name[0], name[1]
        if a_name == b_name:
            return None

        a = dict.get(self, a_name)
        b = dict.get(self, b_name)
        if not isinstance(a, Point) or not isinstance(b, Point):
            return None

        canonical = "".join(sorted((a_name, b_name)))
        line = self._implicit_line_cache.get(canonical)
        if line is None:
            line = a | b
            self._implicit_line_cache[canonical] = line
        self[name] = line
        self[name[::-1]] = line
        return line

    def __missing__(self, key):
        if isinstance(key, str) and self._is_pair_name(key):
            reverse_line = self._resolve_from_existing_reverse(key)
            if reverse_line is not None:
                return reverse_line
            line = self._resolve_from_points(key)
            if line is not None:
                return line
        raise KeyError(key)


@contextmanager
def build_context(overrides: Optional[Dict[str, tuple[float, float]]] = None):
    previous = BuildContext.current
    context = BuildContext(overrides)
    BuildContext.current = context
    try:
        yield context
    finally:
        BuildContext.current = previous


class DSLRunner:
    @staticmethod
    def _compile(source: str):
        tree = ast.parse(source, mode="exec")
        tree = BasePointTransformer().visit(tree)
        ast.fix_missing_locations(tree)
        return compile(tree, "<geocalc-dsl>", "exec")

    @staticmethod
    def _create_namespace(console: _Console) -> Dict[str, object]:
        return DSLNamespace({
            "__builtins__": {**SAFE_BUILTINS, "print": console.print},
            "__base_point__": Point.base,
            "Circle": Circle,
            "GeometryError": GeometryError,
            "Line": Line,
            "Point": Point,
            "Vector": Vector,
            "angle": angle,
            "bisect": bisect,
            "dist": dist,
            "div": div,
            "math": math,
            "mid": mid,
        })

    @staticmethod
    def _bind_scene_names(namespace: Dict[str, object], context: BuildContext) -> None:
        for name, value in namespace.items():
            if name.startswith("__"):
                continue
            context.bind_name(name, value)
            if isinstance(value, Point) and value.name is None:
                value.name = name

    def execute(self, source: str, overrides: Optional[Dict[str, tuple[float, float]]] = None) -> ExecutionResult:
        try:
            code = self._compile(source)
        except SyntaxError as exc:
            raise DSLExecutionError(str(exc)) from exc

        with build_context(overrides) as context:
            console = _Console(context)
            namespace = self._create_namespace(console)
            try:
                exec(code, namespace, namespace)
            except Exception as exc:
                raise DSLExecutionError(f"{type(exc).__name__}: {exc}") from exc

            self._bind_scene_names(namespace, context)
            return ExecutionResult(scene=context.scene, namespace=namespace)
