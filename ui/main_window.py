from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from geometry.dsl import DSLExecutionError, DSLRunner
from geometry.primitives import Circle, Line, Point, SceneSnapshot, Vector


DEFAULT_CODE = """# Drag base points on the canvas.
A = Point(-150, -150)
B = Point(250, -150)
C = Point(180, 150)

AB = A | B
BC = B | C
AC = A | C

L = B + (C - B) / 2
M = A + (B - A) / 2
N = A + (C - A) / 2

CM = C | M
BN = B | N
D = CM & BN

OM_axis = M | ~AB
ON_axis = N | ~AC
O = OM_axis & ON_axis
OM = M | O
ON = N | O

E = AB & (C | ~AB)
F = AC & (B | ~AC)
CE = C | E
BF = B | F
H = CE & BF

c9 = Circle(E, M, N)
P, R = c9

OH = O | H

print(D in OH, P in OH)
print(L in c9)
print(f"AB = {abs(AB):.1f}")
print(f"AC = {abs(AC):.1f}")
print(f"BC = {abs(BC):.1f}")
"""


class GeoCalcApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("GeoCalc DSL")
        self.root.geometry("1440x900")
        self.root.minsize(1000, 700)

        self.runner = DSLRunner()
        self.current_scene: SceneSnapshot | None = None
        self.last_good_scene: SceneSnapshot | None = None
        self.last_error = ""
        self.drag_point_name: str | None = None
        self.drag_marker_id: int | None = None
        self.dragging = False
        self.pan_start: tuple[float, float] | None = None
        self.code_after_id: str | None = None
        self.label_after_id: str | None = None
        self.overrides: dict[str, tuple[float, float]] = {}
        self.viewport = {"scale": 1.0, "offset_x": 0.0, "offset_y": 0.0}
        self.view_fitted_once = False
        self.visible_line_segments: list[tuple[float, float, float, float]] = []
        self.visible_circles: list[tuple[float, float, float]] = []
        self.visible_points_for_labels: list[tuple[str, float, float]] = []
        self.sidebar_width = 360
        self.user_resized_sidebar = False
        self.label_layout_cache: dict[str, tuple[float, float, str]] = {}
        self.label_animation_targets: dict[str, tuple[float, float, str]] = {}
        self.label_animation_after_id: str | None = None
        self.label_boxes: dict[str, tuple[float, float, float, float]] = {}

        self._build_ui()
        self._bind_events()
        self.editor.insert("1.0", DEFAULT_CODE)
        self.rebuild_scene(fit=True)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=0)

        self.main_pane = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            sashrelief=tk.FLAT,
            sashwidth=6,
            bg="#d8d8d8",
            showhandle=False,
        )
        self.main_pane.grid(row=0, column=0, sticky="nsew")

        self.canvas_frame = ttk.Frame(self.main_pane)
        self.sidebar = ttk.Frame(self.main_pane, padding=8, width=self.sidebar_width)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(1, weight=1)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#fcfcfb", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.main_pane.add(self.canvas_frame, stretch="always", minsize=500)
        self.main_pane.add(self.sidebar, minsize=280)

        toolbar = ttk.Frame(self.sidebar)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(1, weight=1)

        run_button = ttk.Button(toolbar, text="Run  F5 / Ctrl+Enter", command=self.rebuild_scene)
        run_button.grid(row=0, column=0, sticky="w")

        self.autorun_var = tk.BooleanVar(value=True)
        autorun = ttk.Checkbutton(toolbar, text="Auto-run", variable=self.autorun_var)
        autorun.grid(row=0, column=1, sticky="e")

        self.editor = tk.Text(
            self.sidebar,
            wrap="none",
            undo=True,
            font=("Consolas", 11),
            padx=10,
            pady=10,
            background="#f7f7f4",
            foreground="#1f2933",
            insertbackground="#1f2933",
        )
        self.editor.grid(row=1, column=0, sticky="nsew")

        status_frame = ttk.Frame(self.root, padding=(10, 6))
        status_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        status_frame.columnconfigure(1, weight=0)

        self.status_var = tk.StringVar(value="Ready")
        self.status = ttk.Label(status_frame, textvariable=self.status_var)
        self.status.grid(row=0, column=0, sticky="w")

        self.coords_var = tk.StringVar(value="")
        self.coords = ttk.Label(status_frame, textvariable=self.coords_var)
        self.coords.grid(row=0, column=1, sticky="e")

    def _bind_events(self) -> None:
        self.root.bind("<F5>", self._on_run_shortcut)
        self.root.bind("<Control-Return>", self._on_run_shortcut)
        self.root.bind("<Configure>", self._on_root_configure)
        self.editor.bind("<<Modified>>", self._on_editor_modified)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag_point)
        self.canvas.bind("<ButtonRelease-1>", self._stop_drag)
        self.canvas.bind("<Control-MouseWheel>", self._zoom_canvas)
        self.main_pane.bind("<B1-Motion>", self._on_pane_drag)
        self.main_pane.bind("<ButtonRelease-1>", self._on_pane_release)

    def _on_run_shortcut(self, event=None):
        self.rebuild_scene()
        return "break"

    def _on_editor_modified(self, event=None):
        self.editor.edit_modified(False)
        if not self.autorun_var.get():
            return
        if self.code_after_id is not None:
            self.root.after_cancel(self.code_after_id)
        self.code_after_id = self.root.after(350, self.rebuild_scene)

    def _on_root_configure(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        self._apply_sidebar_width()

    def _on_canvas_configure(self, event=None):
        if self.current_scene is not None and not self.view_fitted_once:
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()
            if width > 100 and height > 100:
                self._fit_viewport(self.current_scene)
                self.view_fitted_once = True
        self.render_scene()

    def rebuild_scene(self, event=None, fit: bool = False):
        if self.code_after_id is not None:
            self.root.after_cancel(self.code_after_id)
            self.code_after_id = None

        source = self.editor.get("1.0", "end-1c")
        try:
            result = self.runner.execute(source, overrides=self.overrides)
        except DSLExecutionError as exc:
            self.last_error = str(exc)
            if self.last_good_scene is not None:
                self.status_var.set(f"Last valid drawing kept. {self.last_error}")
                self.current_scene = self.last_good_scene
                self.render_scene()
            else:
                self.status_var.set(self.last_error)
                self.canvas.delete("all")
            return

        self.current_scene = result.scene
        self.last_good_scene = result.scene
        self.last_error = ""

        for name, point in result.scene.draggable_points.items():
            self.overrides[name] = (point.x, point.y)

        if fit or self.viewport["scale"] == 1.0 and self.viewport["offset_x"] == 0.0 and self.viewport["offset_y"] == 0.0:
            self._fit_viewport(result.scene)
            if self.canvas.winfo_width() > 100 and self.canvas.winfo_height() > 100:
                self.view_fitted_once = True

        log_suffix = ""
        if result.scene.logs:
            log_suffix = " | " + "".join(result.scene.logs).strip().replace("\n", " | ")
        self.status_var.set(
            f"Scene updated: {len(result.scene.points)} points, "
            f"{len(result.scene.lines)} lines, {len(result.scene.circles)} circles{log_suffix}"
        )
        self.render_scene()
        if not self.dragging:
            self._schedule_label_refresh()

    def _apply_sidebar_width(self) -> None:
        total_width = self.root.winfo_width()
        if total_width <= 0:
            return
        default_width = max(320, int(total_width * 0.25))
        desired_sidebar_width = self.sidebar_width if self.user_resized_sidebar else default_width
        max_sidebar_width = max(280, total_width - 500)
        desired_sidebar_width = min(max(desired_sidebar_width, 280), max_sidebar_width)
        self.sidebar_width = desired_sidebar_width
        canvas_width = max(300, total_width - desired_sidebar_width)
        self.root.after_idle(lambda: self.main_pane.sash_place(0, canvas_width, 0))

    def _capture_sidebar_width(self) -> None:
        total_width = self.root.winfo_width()
        if total_width <= 0:
            return
        try:
            sash_x, _ = self.main_pane.sash_coord(0)
        except tk.TclError:
            return
        width = total_width - sash_x
        max_sidebar_width = max(280, total_width - 500)
        self.sidebar_width = min(max(width, 280), max_sidebar_width)
        self.user_resized_sidebar = True

    def _on_pane_drag(self, event=None):
        self._capture_sidebar_width()

    def _on_pane_release(self, event=None):
        self._capture_sidebar_width()

    def _fit_viewport(self, scene: SceneSnapshot):
        points = [(point.x, point.y) for point in scene.points]
        for circle in scene.circles:
            points.extend(
                [
                    (circle.center.x - circle.radius, circle.center.y - circle.radius),
                    (circle.center.x + circle.radius, circle.center.y + circle.radius),
                ]
            )
        if not points:
            self.viewport = {"scale": 1.0, "offset_x": 0.0, "offset_y": 0.0}
            return

        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        min_x = min(x for x, _ in points)
        max_x = max(x for x, _ in points)
        min_y = min(y for _, y in points)
        max_y = max(y for _, y in points)

        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        padding = 50
        scale = min((width - 2 * padding) / span_x, (height - 2 * padding) / span_y)
        scale = max(scale, 0.2)

        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        self.viewport = {
            "scale": scale,
            "offset_x": width / 2 - center_x * scale,
            "offset_y": height / 2 + center_y * scale,
        }

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        scale = self.viewport["scale"]
        sx = x * scale + self.viewport["offset_x"]
        sy = self.viewport["offset_y"] - y * scale
        return sx, sy

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        scale = self.viewport["scale"]
        x = (sx - self.viewport["offset_x"]) / scale
        y = (self.viewport["offset_y"] - sy) / scale
        return x, y

    def render_scene(self) -> None:
        scene = self.current_scene
        self.canvas.delete("all")
        self.visible_line_segments = []
        self.visible_circles = []
        self.visible_points_for_labels = []
        self.label_boxes = {}
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            return

        self._draw_grid(width, height)
        if scene is None:
            return

        for circle in scene.circles:
            self._draw_circle(circle)
        for line in scene.lines:
            self._draw_line(line)
        points = sorted(scene.points, key=lambda point: point.draggable)
        for point in points:
            name = scene.point_names.get(id(point))
            px, py = self.world_to_screen(point.x, point.y)
            self.visible_points_for_labels.append((name or "", px, py))
        for point in points:
            self._draw_point(point, scene.point_names.get(id(point)))

    def _draw_grid(self, width: int, height: int) -> None:
        step = max(25, int(self.viewport["scale"] * 50))
        if step <= 0:
            return
        for x in range(0, width, step):
            self.canvas.create_line(x, 0, x, height, fill="#ece9e1")
        for y in range(0, height, step):
            self.canvas.create_line(0, y, width, y, fill="#ece9e1")
        ax1, ay1 = self.world_to_screen(-10000, 0)
        ax2, ay2 = self.world_to_screen(10000, 0)
        self.canvas.create_line(ax1, ay1, ax2, ay2, fill="#c8c4b7", width=1)
        bx1, by1 = self.world_to_screen(0, -10000)
        bx2, by2 = self.world_to_screen(0, 10000)
        self.canvas.create_line(bx1, by1, bx2, by2, fill="#c8c4b7", width=1)

    def _draw_line(self, line: Line, label: str | None = None) -> None:
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        p1 = self._clip_line_to_viewport(line, width, height)
        if p1 is None:
            return
        x1, y1, x2, y2 = p1
        self.canvas.create_line(x1, y1, x2, y2, fill="#506680", width=2)
        self.visible_line_segments.append((x1, y1, x2, y2))

    def _clip_line_to_viewport(self, line: Line, width: int, height: int):
        x_min, y_max = self.screen_to_world(0, 0)
        x_max, y_min = self.screen_to_world(width, height)
        candidates: list[tuple[float, float]] = []

        if abs(line.b) > 1e-9:
            for x in (x_min, x_max):
                y = (-line.a * x - line.c) / line.b
                if y_min - 1e-6 <= y <= y_max + 1e-6:
                    candidates.append((x, y))
        if abs(line.a) > 1e-9:
            for y in (y_min, y_max):
                x = (-line.b * y - line.c) / line.a
                if x_min - 1e-6 <= x <= x_max + 1e-6:
                    candidates.append((x, y))

        unique: list[tuple[float, float]] = []
        for point in candidates:
            if all(abs(point[0] - other[0]) > 1e-6 or abs(point[1] - other[1]) > 1e-6 for other in unique):
                unique.append(point)

        if len(unique) < 2:
            return None
        (x1, y1), (x2, y2) = unique[0], unique[1]
        sx1, sy1 = self.world_to_screen(x1, y1)
        sx2, sy2 = self.world_to_screen(x2, y2)
        return sx1, sy1, sx2, sy2

    def _draw_circle(self, circle: Circle) -> None:
        cx, cy = self.world_to_screen(circle.center.x, circle.center.y)
        radius = circle.radius * self.viewport["scale"]
        self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline="#b85c38", width=2)
        self.visible_circles.append((cx, cy, radius))

    def _draw_point(self, point: Point, label: str | None = None) -> None:
        x, y = self.world_to_screen(point.x, point.y)
        radius = 6 if point.draggable else 5
        fill = "#1f2933"
        outline = "#146356" if point.draggable else "#f7f7f4"
        outline_width = 2 if point.draggable else 2
        if point.draggable and label:
            hit_radius = 14
            hit_id = self.canvas.create_oval(
                x - hit_radius,
                y - hit_radius,
                x + hit_radius,
                y + hit_radius,
                outline="",
                fill="",
            )
            self.canvas.addtag_withtag(f"draggable:{label}", hit_id)
        marker_id = self.canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            fill=fill,
            outline=outline,
            width=outline_width,
        )
        if point.draggable:
            self.canvas.addtag_withtag(f"draggable:{label}", marker_id)
        if label:
            label_x, label_y, anchor = self._get_point_label_position(label, x, y)
            text_fill = "#146356" if point.draggable else "#111827"
            self.label_boxes[label] = self._label_box(label_x, label_y, label)
            for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                self.canvas.create_text(
                    label_x + offset_x,
                    label_y + offset_y,
                    text=label,
                    anchor=anchor,
                    fill="#fcfcfb",
                    font=("Segoe UI", 9, "bold"),
                )
            text_id = self.canvas.create_text(
                label_x,
                label_y,
                text=label,
                anchor=anchor,
                fill=text_fill,
                font=("Segoe UI", 9, "bold"),
            )
            if point.draggable:
                self.canvas.addtag_withtag(f"draggable:{label}", text_id)

    def _start_drag(self, event):
        draggable_name = self._find_draggable_at(event.x, event.y)
        if draggable_name:
            self.drag_point_name = draggable_name
            self.dragging = True
            self.pan_start = None
            return
        self.drag_point_name = None
        self.dragging = False
        self.pan_start = (event.x, event.y)

    def _drag_point(self, event):
        if self.dragging and self.drag_point_name:
            x, y = self.screen_to_world(event.x, event.y)
            self.overrides[self.drag_point_name] = (x, y)
            self.coords_var.set(f"{self.drag_point_name} = ({x:.1f}, {y:.1f})")
            self._schedule_label_refresh()
            self.rebuild_scene()
            return

        if self.pan_start is not None:
            last_x, last_y = self.pan_start
            dx = event.x - last_x
            dy = event.y - last_y
            self.viewport["offset_x"] += dx
            self.viewport["offset_y"] += dy
            self.pan_start = (event.x, event.y)
            self.coords_var.set("pan")
            self.render_scene()

    def _stop_drag(self, event):
        self.dragging = False
        self.drag_point_name = None
        self.drag_marker_id = None
        self.pan_start = None
        self.coords_var.set("")
        self._refresh_label_layout()

    def _find_draggable_at(self, x: float, y: float) -> str | None:
        hit_items = self.canvas.find_overlapping(x - 12, y - 12, x + 12, y + 12)
        for item_id in reversed(hit_items):
            for tag in self.canvas.gettags(item_id):
                if tag.startswith("draggable:"):
                    return tag.split(":", 1)[1]
        closest = self.canvas.find_closest(x, y)
        if closest:
            for tag in self.canvas.gettags(closest[0]):
                if tag.startswith("draggable:"):
                    return tag.split(":", 1)[1]
        return None

    def _zoom_canvas(self, event):
        if event.delta == 0:
            return "break"
        zoom = 1.1 if event.delta > 0 else 1 / 1.1
        old_scale = self.viewport["scale"]
        new_scale = min(max(old_scale * zoom, 0.05), 20.0)
        if abs(new_scale - old_scale) < 1e-9:
            return "break"

        world_x, world_y = self.screen_to_world(event.x, event.y)
        self.viewport["scale"] = new_scale
        self.viewport["offset_x"] = event.x - world_x * new_scale
        self.viewport["offset_y"] = event.y + world_y * new_scale
        self.render_scene()
        return "break"

    def _get_point_label_position(self, label: str | None, x: float, y: float) -> tuple[float, float, str]:
        if not label:
            return x + 14, y - 12, "center"

        cached = self.label_layout_cache.get(label)
        if cached is None:
            cached = self._choose_point_label_layout(x, y, label, self.label_boxes)
            self.label_layout_cache[label] = cached

        dx, dy, anchor = cached
        return x + dx, y + dy, anchor

    def _schedule_label_refresh(self) -> None:
        if self.label_after_id is not None:
            self.root.after_cancel(self.label_after_id)
        self.label_after_id = self.root.after(220, self._refresh_label_layout)

    def _refresh_label_layout(self) -> None:
        if self.label_after_id is not None:
            self.root.after_cancel(self.label_after_id)
            self.label_after_id = None
        if self.current_scene is None:
            return
        new_targets: dict[str, tuple[float, float, str]] = {}
        placed_boxes: dict[str, tuple[float, float, float, float]] = {}
        for label, x, y in self.visible_points_for_labels:
            if not label:
                continue
            layout = self._choose_point_label_layout(x, y, label, placed_boxes)
            new_targets[label] = layout
            dx, dy, _ = layout
            placed_boxes[label] = self._label_box(x + dx, y + dy, label)

        if not new_targets:
            return

        if self.label_animation_after_id is not None:
            self.root.after_cancel(self.label_animation_after_id)
            self.label_animation_after_id = None

        changed = False
        for label, target in new_targets.items():
            current = self.label_layout_cache.get(label)
            if current is None:
                self.label_layout_cache[label] = target
                continue
            if current != target:
                self.label_animation_targets[label] = target
                changed = True

        for label, target in new_targets.items():
            if label not in self.label_layout_cache:
                self.label_layout_cache[label] = target

        if changed:
            self._animate_label_layout_step()
        else:
            self.label_animation_targets.clear()
            self.render_scene()

    def _animate_label_layout_step(self) -> None:
        still_running = False
        for label, target in list(self.label_animation_targets.items()):
            current = self.label_layout_cache.get(label, target)
            next_layout = self._interpolate_label_layout(current, target)
            self.label_layout_cache[label] = next_layout
            if next_layout == target:
                del self.label_animation_targets[label]
            else:
                still_running = True

        self.render_scene()
        if still_running:
            self.label_animation_after_id = self.root.after(32, self._animate_label_layout_step)
        else:
            self.label_animation_after_id = None

    @staticmethod
    def _interpolate_label_layout(
        current: tuple[float, float, str],
        target: tuple[float, float, str],
    ) -> tuple[float, float, str]:
        cx, cy, ca = current
        tx, ty, ta = target

        def step(value: float, goal: float) -> float:
            delta = goal - value
            distance = abs(delta)
            if distance < 0.2:
                return goal
            if distance > 10:
                factor = 0.42
            elif distance > 4:
                factor = 0.28
            else:
                factor = 0.16
            next_value = value + delta * factor
            if (delta > 0 and next_value > goal) or (delta < 0 and next_value < goal):
                return goal
            return next_value

        nx = step(cx, tx)
        ny = step(cy, ty)
        return (nx, ny, "center")

    def _choose_point_label_layout(
        self,
        x: float,
        y: float,
        label: str | None = None,
        placed_boxes: dict[str, tuple[float, float, float, float]] | None = None,
    ) -> tuple[float, float, str]:
        candidates = [
            (14, -12, "center"),
            (14, 12, "center"),
            (-14, -12, "center"),
            (-14, 12, "center"),
            (0, -16, "center"),
            (0, 16, "center"),
            (18, 0, "center"),
            (-18, 0, "center"),
            (22, -14, "center"),
            (-22, -14, "center"),
            (22, 14, "center"),
            (-22, 14, "center"),
        ]

        best: tuple[float, float, str] | None = None
        best_score = float("-inf")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        placed_boxes = placed_boxes or {}

        for dx, dy, anchor in candidates:
            label_x = x + dx
            label_y = y + dy
            min_line_distance = min(
                (self._distance_point_to_segment(label_x, label_y, *segment) for segment in self.visible_line_segments),
                default=999.0,
            )
            min_circle_distance = min(
                (self._distance_point_to_circle(label_x, label_y, *circle) for circle in self.visible_circles),
                default=999.0,
            )
            min_other_point_distance = min(
                (
                    ((label_x - px) ** 2 + (label_y - py) ** 2) ** 0.5
                    for point_label, px, py in self.visible_points_for_labels
                    if point_label != label
                ),
                default=999.0,
            )
            label_box = self._label_box(label_x, label_y, label or "")
            min_label_gap = 999.0
            label_overlap_penalty = 0.0
            for other_label, other_box in placed_boxes.items():
                if other_label == label:
                    continue
                gap = self._rect_gap(label_box, other_box)
                min_label_gap = min(min_label_gap, gap)
                if gap < 0:
                    label_overlap_penalty += 150.0 + abs(gap) * 25.0
                elif gap < 10:
                    label_overlap_penalty += (10 - gap) * 20.0

            edge_penalty = 0.0
            if label_box[0] < 8 or label_box[2] > width - 8:
                edge_penalty += 50.0
            if label_box[1] < 8 or label_box[3] > height - 8:
                edge_penalty += 50.0

            distance_from_point = ((dx * dx + dy * dy) ** 0.5)
            distance_penalty = max(0.0, distance_from_point - 20.0) * 3.0
            if distance_from_point < 11.0:
                distance_penalty += 30.0

            line_penalty = max(0.0, 22.0 - min_line_distance) * 8.5
            circle_penalty = max(0.0, 20.0 - min_circle_distance) * 7.5
            point_collision_penalty = max(0.0, 22.0 - min_other_point_distance) * 9.5

            score = (
                2.8 * min_line_distance
                + 2.2 * min_circle_distance
                + 1.5 * min_other_point_distance
                + 2.8 * min_label_gap
                - edge_penalty
                - distance_penalty
                - line_penalty
                - circle_penalty
                - point_collision_penalty
                - label_overlap_penalty
            )
            if score > best_score:
                best_score = score
                best = (dx, dy, anchor)

        return best if best is not None else (14, -12, "center")

    @staticmethod
    def _distance_point_to_segment(
        px: float,
        py: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> float:
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5

        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5

    @staticmethod
    def _distance_point_to_circle(
        px: float,
        py: float,
        cx: float,
        cy: float,
        radius: float,
    ) -> float:
        return abs((((px - cx) ** 2 + (py - cy) ** 2) ** 0.5) - radius)

    @staticmethod
    def _label_box(x: float, y: float, label: str) -> tuple[float, float, float, float]:
        width = max(14, len(label) * 10)
        height = 18
        half_w = width / 2
        half_h = height / 2
        return (x - half_w, y - half_h, x + half_w, y + half_h)

    @staticmethod
    def _rect_gap(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> float:
        ax1, ay1, ax2, ay2 = first
        bx1, by1, bx2, by2 = second
        dx = max(bx1 - ax2, ax1 - bx2, 0.0)
        dy = max(by1 - ay2, ay1 - by2, 0.0)
        if dx == 0.0 and dy == 0.0:
            overlap_x = min(ax2, bx2) - max(ax1, bx1)
            overlap_y = min(ay2, by2) - max(ay1, by1)
            return -min(overlap_x, overlap_y)
        return (dx * dx + dy * dy) ** 0.5
