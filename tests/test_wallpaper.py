import asyncio
import tempfile
import unittest
from copy import deepcopy
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.extended import Backend2
from Frontend.theme import BUTTON_BACKGROUND_OPTIONS
from Frontend.wallpaper import (
    WALLPAPER_OPTIONS, WallpaperCanvas, WallpaperManager,
    _accent_hsl, normalize_wallpaper_intensity,
)
from test_ui_state import make_front


class WallpaperTests(unittest.TestCase):
    def test_settings_default_persist_and_reject_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend2.__new__(Backend2)
            back.web = False
            back.settings = Path(directory) / "settings.txt"
            back.set_default_settings()
            self.assertEqual(back.read_settings()["animated_wallpaper"], "none")
            self.assertEqual(back.read_settings()["wallpaper_intensity"], 60)
            for mode, _ in WALLPAPER_OPTIONS:
                back.redact_setting("animated_wallpaper", mode)
                back.redact_setting("wallpaper_intensity", 73)
                reopened = Backend2.__new__(Backend2)
                reopened.web, reopened.settings = False, back.settings
                reopened.set_default_settings()
                self.assertEqual(reopened.read_settings()["animated_wallpaper"], mode)
                self.assertEqual(reopened.read_settings()["wallpaper_intensity"], 73)
            back.redact_setting("animated_wallpaper", "unknown")
            back.redact_setting("wallpaper_intensity", "invalid")
            self.assertEqual(back.read_settings()["animated_wallpaper"], "none")
            self.assertEqual(back.read_settings()["wallpaper_intensity"], 60)
        for value, expected in ((None, 60), (float("nan"), 60), (float("inf"), 60),
                                (-10, 10), (120, 100), ("50", 50)):
            self.assertEqual(normalize_wallpaper_intensity(value), expected)

    def test_selector_and_intensity_preserve_screen_and_group(self):
        for phone in (False, True):
            front = make_front(phone=phone)
            front.back.saveB("Сохранить дело", "default")
            front.show_groups()
            front.open_settings()
            panel = front.utils2.build_widgets_for_customization()
            selector = next(c for c in panel.content.controls
                            if isinstance(c, ft.Dropdown) and c.label == "Анимированные обои")
            index = panel.content.controls.index(selector)
            intensity = panel.content.controls[index + 1]
            slider = intensity.controls[1]
            host, stack = front.screen_host, list(front.screen_stack)
            for mode, _ in WALLPAPER_OPTIONS[1:] + WALLPAPER_OPTIONS[:1]:
                selector.value = mode
                selector.on_select(None)
                self.assertEqual(front.wallpaper.mode, mode)
                self.assertEqual(front.web_store._settings["animated_wallpaper"], mode)
                self.assertEqual(intensity.disabled, mode == "none")
                self.assertIs(front.screen_host, host)
                self.assertEqual(front.screen_stack, stack)
                self.assertEqual(front.current_group_id, "default")
                self.assertEqual(len(front.back.read_tasks()), 1)
            slider.value = 83
            slider.on_change(None)
            self.assertEqual(front.wallpaper.intensity, .83)
            self.assertEqual(front.back2.read_settings()["wallpaper_intensity"], 60)
            slider.on_change_end(None)
            self.assertEqual(front.back2.read_settings()["wallpaper_intensity"], 83)
            self.assertEqual(intensity.controls[0].value, "Интенсивность обоев: 83%")

    def test_drag_uses_event_value_and_only_updates_counter_until_release(self):
        front = make_front(settings={"animated_wallpaper": "stars"})
        panel = front.utils2.build_widgets_for_customization()
        controls = panel.content.controls
        index = next(i for i, c in enumerate(controls)
                     if isinstance(c, ft.Dropdown) and c.label == "Анимированные обои")
        label, slider = controls[index + 1].controls
        front.page.update.reset_mock()
        with patch.object(label, "update") as update, \
                patch.object(front.back2, "_settings_read", wraps=front.back2._settings_read) as read:
            for value in (11, 85, 32, 99):
                slider.value = 60  # stale control snapshot from another event
                slider.on_change(SimpleNamespace(data=str(value), control=slider))
                self.assertEqual(label.value, f"Интенсивность обоев: {value}%")
                self.assertEqual(front.wallpaper.intensity, value / 100)
            self.assertEqual(update.call_count, 4)
            read.assert_not_called()
            slider.on_change_end(SimpleNamespace(data="74", control=slider))
        self.assertEqual(front.back2.read_settings()["wallpaper_intensity"], 74)
        self.assertEqual(label.value, "Интенсивность обоев: 74%")
        front.page.update.assert_not_called()

    def test_frames_reuse_paints_and_wave_vertices_and_intensity_keeps_positions(self):
        manager = WallpaperManager(Mock(views=[]))
        for mode, _ in WALLPAPER_OPTIONS[1:]:
            manager.configure(mode, 60, "#6750A4", True)
            canvas = WallpaperCanvas(manager, ft.View())
            canvas.resize_to(1366, 900)
            paints = [shape.paint for shape in canvas.shapes]
            vertices = list(canvas.shapes[0].elements) if mode == "waves" else []
            with patch("Frontend.wallpaper.ft.Paint", side_effect=AssertionError("new paint per frame")), \
                    patch("Frontend.wallpaper.cv.Path.LineTo", side_effect=AssertionError("new vertex per frame")):
                for _ in range(10):
                    canvas.draw(1 / 30)
            self.assertTrue(all(shape.paint is paint for shape, paint in zip(canvas.shapes, paints)))
            if vertices:
                self.assertTrue(all(a is b for a, b in zip(canvas.shapes[0].elements, vertices)))
            before = [(p["x"], p["y"], p["ph"]) for p in canvas._particles]
            manager.set_intensity(90)
            canvas.draw(0)
            self.assertEqual([(p["x"], p["y"], p["ph"]) for p in canvas._particles[:len(before)]], before)

    def test_all_effects_draw_resize_and_animate_with_bounded_particle_counts(self):
        manager = WallpaperManager(Mock(views=[]))
        canvas = WallpaperCanvas(manager, ft.View())
        for dark in (False, True):
            for mode, _ in WALLPAPER_OPTIONS[1:]:
                manager.configure(mode, 60, "#6750A4", dark)
                # Flet mounts before reporting the available canvas dimensions.
                WallpaperCanvas(manager, ft.View()).draw(.1)
                for width, height in ((360, 800), (1366, 900), (4000, 2200)):
                    canvas.resize_to(width, height)
                    self.assertGreater(len(canvas.shapes), 0)
                    self.assertLessEqual(len(canvas.shapes), 240)
                    if mode in ("stars", "bubbles"):
                        before = canvas.shapes[0].y
                        canvas.draw(.1)
                        self.assertNotEqual(canvas.shapes[0].y, before)
                    elif mode == "waves":
                        before = canvas.shapes[0].elements[1].y
                        canvas.draw(.1)
                        self.assertNotEqual(canvas.shapes[0].elements[1].y, before)
                    else:
                        before = deepcopy(canvas.shapes[0].paint.gradient)
                        canvas.draw(.1)
                        self.assertNotEqual(canvas.shapes[0].paint.gradient, before)
                    self.assertTrue(all(c.paint is not None for c in canvas.shapes))

    def test_named_accents_match_their_hex_swatches(self):
        for _, _, accent in BUTTON_BACKGROUND_OPTIONS:
            self.assertTrue(all(math_value >= 0 for math_value in _accent_hsl(accent)))
        self.assertEqual(_accent_hsl(ft.Colors.DEEP_PURPLE), _accent_hsl("#673AB7"))
        self.assertEqual(_accent_hsl(ft.Colors.RED), _accent_hsl("#F44336"))
        self.assertEqual(_accent_hsl("red,0.3"), _accent_hsl("#F44336"))

    def test_new_views_and_return_keep_the_same_animation_frame(self):
        def frame(canvas):
            return [(
                getattr(shape, "x", None), getattr(shape, "y", None),
                getattr(shape, "radius", None),
                [(getattr(point, "x", None), getattr(point, "y", None))
                 for point in getattr(shape, "elements", [])],
                deepcopy(shape.paint),
            ) for shape in canvas.shapes]

        for mode, _ in WALLPAPER_OPTIONS[1:]:
            with self.subTest(mode=mode):
                page = Mock(views=[])
                manager = WallpaperManager(page)
                manager.configure(mode, 60, "#6750A4", True)
                root = manager.wrap_view(ft.View(controls=[ft.Container()]))
                page.views.append(root)
                original = root._nd_wallpaper_layer.canvas
                original.resize_to(360, 800)
                original.draw(.7)
                expected = frame(original)
                elapsed = original._elapsed

                with patch.object(manager._scene.rng, "random",
                                  side_effect=AssertionError("Navigation regenerated particles")):
                    dialog = manager.wrap_view(ft.View(controls=[ft.Text("Dialog")]))
                    page.views.append(dialog)
                    current = dialog._nd_wallpaper_layer.canvas
                    current.resize_to(360, 800)
                    self.assertEqual(frame(current), expected)
                    self.assertEqual(current._elapsed, elapsed)
                    self.assertIsNot(current.shapes[0], original.shapes[0])
                current.draw(.4)
                expected = frame(current)
                self.assertNotEqual(expected, frame(original))

                with patch.object(manager._scene.rng, "random",
                                  side_effect=AssertionError("Navigation regenerated particles")):
                    page.views.pop()
                    manager.clear_view(dialog)
                    original.draw(0)
                    self.assertEqual(frame(original), expected)
                    # Returning to the native task screen can rebuild its wrapper.
                    manager.clear_view(root)
                    manager.wrap_view(root)
                    self.assertEqual(frame(root._nd_wallpaper_layer.canvas), expected)

    def test_particle_positions_survive_viewport_and_density_changes(self):
        for mode in ("stars", "bubbles"):
            with self.subTest(mode=mode):
                manager = WallpaperManager(Mock(views=[]))
                manager.configure(mode, 60, "#6750A4", True)
                canvas = WallpaperCanvas(manager, ft.View())
                canvas.resize_to(1366, 900)
                canvas.draw(.7)
                particles = list(canvas._particles)
                positions = [(p["x"], p["y"], p["ph"]) for p in particles]
                with patch.object(manager._scene.rng, "random",
                                  side_effect=AssertionError("Existing particles were regenerated")):
                    canvas.resize_to(360, 800)
                    manager.set_intensity(10)
                    canvas.draw(0)
                    canvas.resize_to(1366, 900)
                    manager.set_intensity(60)
                    canvas.draw(0)
                self.assertEqual([(p["x"], p["y"], p["ph"]) for p in canvas._particles], positions)
                self.assertTrue(all(a is b for a, b in zip(canvas._particles, particles)))

    def test_views_restore_padding_and_controls_after_disabling(self):
        front = make_front(settings={"animated_wallpaper": "waves"})
        front.show_groups()
        front.web = False
        body = ft.Container(expand=True)
        view = front.libs.view(route="/test", controls=[body], padding=20)
        front.page.views.append(view)
        layer = view._nd_wallpaper_layer
        self.assertEqual(view.padding, 0)
        self.assertIs(layer.body.controls[0], body)
        self.assertEqual(front.wallpaper.view_controls(view), [body])
        self.assertIsInstance(layer.stack.controls[0], ft.TransparentPointer)
        self.assertEqual(layer.padding, 20)
        front.back2.redact_setting("animated_wallpaper", "none")
        front.apply_wallpaper_settings()
        self.assertEqual(view.padding, 20)
        self.assertEqual(view.controls, [body])
        self.assertEqual(view.route, "/test")
        self.assertIsNone(view._nd_wallpaper_layer)

    def test_single_worker_pauses_resumes_and_only_updates_top_view(self):
        page = Mock(views=[], run_task=Mock(side_effect=lambda *args: Future()))
        manager = WallpaperManager(page)
        manager.configure("stars", 60, "#6750A4", True)
        for _ in range(2):
            view = ft.View(controls=[ft.Container()], padding=10)
            manager.wrap_view(view)
            page.views.append(view)
            canvas = view._nd_wallpaper_layer.canvas
            canvas.resize_to(360, 800)
            canvas.update = Mock()
            manager.attach(canvas)
        self.assertEqual(page.run_task.call_count, 1)
        generation = manager._generation

        async def stop_after_frame(_):
            manager._generation += 1

        with patch("Frontend.wallpaper.asyncio.sleep", new=AsyncMock(side_effect=stop_after_frame)):
            asyncio.run(manager._animate(generation))
        page.views[0]._nd_wallpaper_layer.canvas.update.assert_not_called()
        page.views[1]._nd_wallpaper_layer.canvas.update.assert_called_once()
        worker = manager._task
        manager.on_lifecycle(SimpleNamespace(state=ft.AppLifecycleState.HIDE))
        self.assertTrue(worker.cancelled())
        manager.on_lifecycle(SimpleNamespace(state=ft.AppLifecycleState.RESUME))
        self.assertEqual(page.run_task.call_count, 2)
        manager.on_disconnect()
        self.assertIsNone(manager._task)
        manager.on_connect()
        self.assertEqual(page.run_task.call_count, 3)
        for view in page.views:
            manager.clear_view(view)
        self.assertIsNone(manager._task)

    def test_native_navigation_and_silent_refresh_recognize_wallpaper_wrapped_screens(self):
        async def exercise():
            front = make_front(phone=True, settings={"animated_wallpaper": "waves"})
            front.web = front.page.web = False
            front.page.push_route = AsyncMock()
            front._update_control = Mock()
            front.show_groups()
            with patch.object(front, "render_daily_repeat_tasks") as render:
                await front.refresh_tasks_silent()
                render.assert_called_once()
            front.open_group_management()
            front.open_page(ft.Text("Редактирование"), ft.Column(), route="edit")
            with patch.object(front, "_refresh_group_management") as refresh:
                front.close_page()
                refresh.assert_called_once()
            self.assertEqual(front.wallpaper.view_controls(front.page.views[-1]), [front._groups_screen])
            front.close_page()
            self.assertEqual(front.page.views, [front.root_view])
            self.assertEqual(front.wallpaper.view_controls(front.root_view), [front.main_cont])
            await asyncio.sleep(0)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
