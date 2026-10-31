"""Animated wallpapers for both the browser and native Flet clients.

Adapted from MixiYT/dayplanner, app/ui/bg.js (Apache-2.0):
https://github.com/MixiYT/dayplanner/blob/main/app/ui/bg.js
Changes: ported the canvas effects to Python/Flet, bounded particle counts,
and added Flet view, resize and application lifecycle handling.
See assets/licenses/dayplanner-LICENSE.txt.
"""

import asyncio
import colorsys
import math
import random
import time
from dataclasses import dataclass, field

import flet as ft
import flet.canvas as cv


WALLPAPER_OPTIONS = (
    ("none", "Без обоев"),
    ("aurora", "Северное сияние"),
    ("bubbles", "Пузыри"),
    ("stars", "Звёзды"),
    ("waves", "Волны"),
    ("gradient", "Переливы"),
)
WALLPAPER_MODES = {key for key, _ in WALLPAPER_OPTIONS}


def normalize_wallpaper(value):
    return value if isinstance(value, str) and value in WALLPAPER_MODES else "none"


def normalize_wallpaper_intensity(value):
    try:
        return max(10, min(100, round(float(value))))
    except (TypeError, ValueError, OverflowError):
        return 60


def _accent_hsl(accent):
    # Palette accents may be Material color names, hex, or Flet opacity colors.
    value = getattr(accent, "value", str(accent)).split(",", 1)[0]
    material = {
        "red": "F44336", "pink": "E91E63", "purple": "9C27B0",
        "deeppurple": "673AB7", "indigo": "3F51B5", "blue": "2196F3",
        "lightblue": "03A9F4", "cyan": "00BCD4", "teal": "009688",
        "green": "4CAF50", "lightgreen": "8BC34A", "lime": "CDDC39",
        "yellow": "FFEB3B", "amber": "FFC107", "orange": "FF9800",
        "deeporange": "FF5722", "brown": "795548", "bluegrey": "607D8B",
        "grey": "9E9E9E", "black": "000000", "white": "FFFFFF",
    }
    value = material.get(value.lower(), value).lstrip("#")[-6:]
    try:
        rgb = tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        rgb = (0x67 / 255, 0x50 / 255, 0xA4 / 255)
    hue, _, saturation = colorsys.rgb_to_hls(*rgb)
    return hue * 360, saturation


def _hsl(hue, saturation, lightness):
    rgb = colorsys.hls_to_rgb((hue % 360) / 360, lightness, saturation)
    return "#" + "".join(f"{round(c * 255):02X}" for c in rgb)


@dataclass
class _WallpaperScene:
    """Animation state outlives individual navigation views and their canvases."""

    elapsed: float = 3.0
    width: float = 1
    height: float = 1
    particles: list = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)


class WallpaperCanvas(cv.Canvas):
    def __init__(self, manager, view):
        super().__init__(expand=True, on_resize=self._resize, resize_interval=100)
        self.manager = manager
        self.view = view
        self._w, self._h = manager._scene.width, manager._scene.height
        self._mode = None
        self._style_revision = -1
        self._wave_points = []
        # did_mount can start the animation before the first resize event.
        self.reset()

    def did_mount(self):
        self.draw(0)
        self.manager.attach(self)

    def will_unmount(self):
        self.manager.detach(self)

    def _resize(self, event):
        ft.context.disable_auto_update()
        self.resize_to(event.width, event.height)
        self.update()

    def resize_to(self, width, height):
        size = max(1, width), max(1, height)
        if size != (self._w, self._h):
            self._w, self._h = size
            self.manager._scene.width, self.manager._scene.height = size
            self.reset()

    @property
    def _elapsed(self):
        return self.manager._scene.elapsed

    def reset(self):
        mode = self._mode = self.manager.mode
        self._style_revision = -1
        self._particles = self.manager._scene.particles
        self._random = self.manager._scene.rng
        self._wave_points = []
        self.shapes = []
        if mode == "aurora":
            self.shapes = [cv.Rect(0, 0, self._w, self._h, paint=ft.Paint(
                gradient=ft.PaintRadialGradient(center=(0, 0), radius=1, colors=[]))) for _ in range(4)]
        elif mode == "waves":
            # Reuse a bounded set of vertices; only their y coordinates move.
            segments = min(64, max(16, math.ceil(self._w / 16)))
            for i in range(4):
                points = [cv.Path.LineTo(self._w * j / segments, 0) for j in range(segments + 1)]
                self.shapes.append(cv.Path(elements=[cv.Path.MoveTo(0, self._h), *points,
                                                    cv.Path.LineTo(self._w, self._h), cv.Path.Close()],
                                           paint=ft.Paint()))
                k = .004 - i * .0004
                self._wave_points.append([(p, p.x * k, p.x * k * 2.1) for p in points])
        elif mode == "gradient":
            self.shapes = [cv.Rect(0, 0, self._w, self._h, paint=ft.Paint(
                gradient=ft.PaintLinearGradient(begin=(0, 0), end=(0, self._h),
                                                colors=[], color_stops=[0, .5, 1])))]
        self.draw(0)

    def _apply_style(self):
        manager = self.manager
        mode, intensity, cols = manager.mode, manager.intensity, manager.palette
        alpha = ft.Colors.with_opacity
        if mode in ("bubbles", "stars"):
            bubbles = mode == "bubbles"
            count = min(48 if bubbles else 160, max(1, round(
                self._w * self._h / (26000 if bubbles else 5200)
                * ((0.5 if bubbles else 0.4) + intensity))))
            per_particle = 2 if bubbles else 1
            # Retain a bounded particle pool when views, size or density change.
            del self.shapes[count * per_particle:]
            rng = self._random
            while len(self._particles) < count:
                self._particles.append(dict(
                    x=rng.random(), y=rng.random(),
                    r=8 + rng.random() * 46 if bubbles else .5 + rng.random() * 1.6,
                    v=6 + rng.random() * 18, ph=rng.random() * math.tau,
                    sp=.6 + rng.random() * 1.8, d=2 + rng.random() * 10))
            while len(self.shapes) < count * per_particle:
                paint = ft.Paint(gradient=ft.PaintRadialGradient(
                    center=(0, 0), radius=1, colors=[])) if bubbles else ft.Paint()
                self.shapes.append(cv.Circle(0, 0, paint=paint))
                if bubbles:
                    self.shapes.append(cv.Circle(0, 0, paint=ft.Paint(
                        style=ft.PaintingStyle.STROKE, stroke_width=1)))
            if bubbles:
                a = .1 + .3 * intensity
                for i, p in zip(range(count), self._particles):
                    fill, edge = self.shapes[2 * i], self.shapes[2 * i + 1]
                    fill.radius = edge.radius = p["r"]
                    fill.paint.gradient.radius = p["r"]
                    fill.paint.gradient.focal_radius = p["r"] * .1
                    fill.paint.gradient.colors = [alpha(a * .6, cols[i % 3]), alpha(a * 1.4, cols[i % 3])]
                    edge.paint.color = alpha(.16 * intensity + .04, "#FFFFFF")
            else:
                colors = (cols[1], "#FFFFFF" if manager.dark else cols[0])
                levels = [[alpha((.35 + .65 * j / 31) * (.25 + .75 * intensity), c)
                           for j in range(32)] for c in colors]
                for shape, p in zip(self.shapes, self._particles):
                    shape.x, shape.radius = p["x"] * self._w, p["r"]
                    p["colors"] = levels[0 if p["r"] > 1.5 else 1]
        elif mode == "aurora":
            for i, shape in enumerate(self.shapes):
                shape.paint.blend_mode = ft.BlendMode.PLUS if manager.dark else ft.BlendMode.SRC_OVER
                color = cols[i % 3]
                shape.paint.gradient.colors = [alpha(.16 + .36 * intensity, color), alpha(0, color)]
        elif mode == "waves":
            for i, shape in enumerate(self.shapes):
                shape.paint.color = alpha((.08 + .2 * intensity) * (1 - i * .16), cols[i % 3])
        self._style_revision = manager.style_revision

    def draw(self, dt):
        if self._mode != self.manager.mode:
            self.reset()
        if self._style_revision != self.manager.style_revision:
            self._apply_style()
        self.manager._scene.elapsed += dt
        t, w, h = self._elapsed, self._w, self._h
        manager = self.manager
        if manager.mode == "aurora":
            blobs = ((.2, .18, .62, .07), (.85, .35, .55, .09),
                     (.45, .88, .7, .06), (.9, .95, .45, .1))
            for i, (shape, (cx, cy, radius, speed)) in enumerate(zip(self.shapes, blobs)):
                x = (cx + math.sin(t * speed + i * 1.7) * .16) * w
                y = (cy + math.cos(t * speed * 1.2 + i) * .13) * h
                radius *= max(w, h) * (.85 + .15 * math.sin(t * .2 + i))
                shape.paint.gradient.center = (x, y)
                shape.paint.gradient.radius = radius
        elif manager.mode == "bubbles":
            for i, p in enumerate(self._particles):
                p["y"] -= p["v"] * dt / h
                p["x"] += math.sin(t * .5 + p["ph"]) * 4 * dt / w
                if p["y"] + p["r"] / h < 0:
                    p["y"], p["x"] = 1 + p["r"] / h, self._random.random()
                if i >= len(self.shapes) // 2:
                    continue
                fill, edge = self.shapes[2 * i], self.shapes[2 * i + 1]
                x, y = p["x"] * w, p["y"] * h
                for shape in (fill, edge):
                    shape.x, shape.y = x, y
                fill.paint.gradient.center = (x, y)
                fill.paint.gradient.focal = (x - p["r"] * .3, y - p["r"] * .3)
        elif manager.mode == "stars":
            for shape, p in zip(self.shapes, self._particles):
                level = round(31 * (.5 + .5 * math.sin(t * p["sp"] + p["ph"])))
                shape.y = (p["y"] * h + t * p["d"]) % h
                shape.paint.color = p["colors"][level]
        elif manager.mode == "waves":
            for i, points in enumerate(self._wave_points):
                base, amp = h * (.62 + i * .1), 14 + i * 9
                phase, counter_phase = t * (.5 + i * .18) + i, t * .4
                for point, first, second in points:
                    point.y = base + math.sin(first + phase) * amp + math.sin(second - counter_phase) * amp * .4
        elif manager.mode == "gradient":
            alpha = ft.Colors.with_opacity
            hue, saturation = manager.hue, max(.5, min(.9, manager.saturation))
            shift, a = math.sin(t * .08) * 40, .1 + .38 * manager.intensity
            shape = self.shapes[0]
            gradient = shape.paint.gradient
            gradient.begin = (w * (.5 + .5 * math.sin(t * .05)), 0)
            gradient.end = (w * (.5 - .5 * math.cos(t * .06)), h)
            gradient.colors = [alpha(a, _hsl(hue + shift, saturation, .4 if manager.dark else .7)),
                               alpha(a * .8, _hsl(hue + 50 + shift, saturation, .35 if manager.dark else .75)),
                               alpha(a, _hsl(hue - 50 + shift, saturation, .3 if manager.dark else .68))]


@dataclass
class _ViewLayer:
    canvas: WallpaperCanvas
    stack: ft.Stack
    body: ft.Column
    padding: object


class WallpaperManager:
    """Own one animation task per page; only paint the currently visible view."""

    def __init__(self, page):
        self.page = page
        self.mode = "none"
        self._scene = _WallpaperScene()
        self.intensity = .6
        self.dark = False
        self.hue, self.saturation = 0, .55
        self.palette = []
        self.style_revision = 0
        self._appearance = None
        self._mounted = set()
        self._task = None
        self._generation = 0
        self._paused = False

    @property
    def enabled(self):
        return self.mode != "none"

    def configure(self, mode, intensity, accent, dark):
        mode = normalize_wallpaper(mode)
        if self.mode != mode:
            self.mode = mode
            self._scene = _WallpaperScene(width=self._scene.width, height=self._scene.height)
            self.style_revision += 1
        self.set_intensity(intensity)
        self.dark = dark
        if self._appearance != (accent, dark):
            self._appearance = accent, dark
            self.hue, self.saturation = _accent_hsl(accent)
            saturation = max(.55, min(.95, self.saturation))
            lightness = .55 if dark else .62
            self.palette = [_hsl(self.hue + shift, saturation, lightness + extra)
                            for shift, extra in ((0, 0), (40, 0), (320, .04))]
            self.style_revision += 1
        for view in self.page.views:
            layer = getattr(view, "_nd_wallpaper_layer", None)
            if not self.enabled:
                self.clear_view(view)
            elif layer is not None:
                layer.canvas.draw(0)
            elif view.controls:
                self.wrap_view(view)
        if self.enabled:
            self._start()
        else:
            self.stop()

    def set_intensity(self, value):
        intensity = normalize_wallpaper_intensity(value) / 100
        if self.intensity != intensity:
            self.intensity = intensity
            self.style_revision += 1

    def wrap_view(self, view):
        if not self.enabled or not view.controls or getattr(view, "_nd_wallpaper_layer", None) is not None:
            return view
        canvas = WallpaperCanvas(self, view)
        body = ft.Column(list(view.controls), expand=True, spacing=view.spacing,
                         alignment=view.vertical_alignment, horizontal_alignment=view.horizontal_alignment)
        stack = ft.Stack([
            ft.TransparentPointer(canvas, left=0, top=0, right=0, bottom=0),
            ft.Container(body, padding=view.padding, left=0, top=0, right=0, bottom=0),
        ], expand=True)
        layer = _ViewLayer(canvas, stack, body, view.padding)
        object.__setattr__(view, "_nd_wallpaper_layer", layer)
        view.padding = 0
        view.controls = [stack]
        return view

    def clear_view(self, view):
        layer = getattr(view, "_nd_wallpaper_layer", None)
        if layer is not None:
            self.detach(layer.canvas)
            view.controls = layer.body.controls
            view.padding = layer.padding
            object.__setattr__(view, "_nd_wallpaper_layer", None)

    @staticmethod
    def view_controls(view):
        layer = getattr(view, "_nd_wallpaper_layer", None)
        return layer.body.controls if layer is not None else view.controls

    def attach(self, canvas):
        self._mounted.add(canvas)
        self._start()

    def detach(self, canvas):
        self._mounted.discard(canvas)
        if not self._mounted:
            self.stop()

    def _start(self):
        if self.enabled and not self._paused and self._mounted and (self._task is None or self._task.done()):
            self._generation += 1
            self._task = self.page.run_task(self._animate, self._generation)

    def stop(self):
        self._generation += 1
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def on_lifecycle(self, event):
        # These handlers only manage the worker. Flet's automatic page patch can
        # race the closing websocket when a browser tab is hidden or closed.
        ft.context.disable_auto_update()
        if event.state in (ft.AppLifecycleState.HIDE, ft.AppLifecycleState.PAUSE, ft.AppLifecycleState.DETACH):
            self.on_disconnect()
        elif event.state in (ft.AppLifecycleState.SHOW, ft.AppLifecycleState.RESUME, ft.AppLifecycleState.RESTART):
            self.on_connect()

    def on_disconnect(self, event=None):
        if event is not None:
            ft.context.disable_auto_update()
        self._paused = True
        self.stop()

    def on_connect(self, event=None):
        if event is not None:
            ft.context.disable_auto_update()
        self._paused = False
        self._start()

    async def _animate(self, generation):
        last = time.monotonic()
        while generation == self._generation and self.enabled and not self._paused:
            now = time.monotonic()
            dt, last = min(.1, now - last), now
            view = self.page.views[-1] if self.page.views else None
            layer = getattr(view, "_nd_wallpaper_layer", None)
            if layer is not None and layer.canvas in self._mounted:
                try:
                    layer.canvas.draw(dt)
                    layer.canvas.update()
                except RuntimeError:
                    # A navigation update can unmount the canvas between frames.
                    self.detach(layer.canvas)
                    return
            # Include rendering/serialization time in the frame budget so an
            # expensive update doesn't add another whole frame of delay.
            interval = 1 / (20 if self.mode in ("aurora", "gradient") else 30)
            await asyncio.sleep(max(0, interval - (time.monotonic() - now)))
