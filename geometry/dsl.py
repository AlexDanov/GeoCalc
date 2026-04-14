from __future__ import annotations

import ast
import math
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Optional

from .primitives import BuildContext, Circle, GeometryError, Line, Point, SceneSnapshot, Vector


class DSLExecutionError(Exception):
    pass


class BasePointTransformer(ast.NodeTransformer):
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
    def __init__(self):
        self._last_code = ""

    def execute(self, source: str, overrides: Optional[Dict[str, tuple[float, float]]] = None) -> ExecutionResult:
        try:
            tree = ast.parse(source, mode="exec")
            tree = BasePointTransformer().visit(tree)
            ast.fix_missing_locations(tree)
            code = compile(tree, "<geocalc-dsl>", "exec")
        except SyntaxError as exc:
            raise DSLExecutionError(str(exc)) from exc

        with build_context(overrides) as context:
            console = _Console(context)
            namespace: Dict[str, object] = {
                "__builtins__": {
                    "abs": abs,
                    "len": len,
                    "max": max,
                    "min": min,
                    "print": console.print,
                    "range": range,
                    "round": round,
                },
                "__base_point__": Point.base,
                "Circle": Circle,
                "GeometryError": GeometryError,
                "Line": Line,
                "Point": Point,
                "Vector": Vector,
                "math": math,
            }
            try:
                exec(code, namespace, namespace)
            except Exception as exc:
                raise DSLExecutionError(f"{type(exc).__name__}: {exc}") from exc

            for name, value in namespace.items():
                if name.startswith("__"):
                    continue
                context.bind_name(name, value)
                if isinstance(value, Point) and value.name is None:
                    value.name = name

            return ExecutionResult(scene=context.scene, namespace=namespace)
