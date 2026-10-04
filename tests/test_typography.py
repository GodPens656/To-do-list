import asyncio
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import fields
from pathlib import Path
from unittest.mock import AsyncMock, patch

import flet as ft
from PIL import ImageFont

from Backend.extended import Backend2
from Frontend.typography import FONT_ASSETS, apply_typography
from Frontend.theme import THEME_STYLE_OPTIONS
from test_ui_state import make_front


class TypographyTests(unittest.TestCase):
    def assert_theme_font_family(self, theme, family):
        expected = None if family == "default" else family
        self.assertEqual(theme.font_family, expected)
        for text_theme in (theme.text_theme, theme.primary_text_theme):
            for slot in fields(ft.TextTheme):
                self.assertEqual(getattr(text_theme, slot.name).font_family, expected)
        self.assertEqual(theme.dropdown_theme.text_style.font_family, expected)

    def test_implicit_text_and_dropdowns_use_palette_after_font_changes(self):
        for style, _ in THEME_STYLE_OPTIONS:
            for dark in (False, True):
                with self.subTest(style=style, dark=dark):
                    front = make_front(theme=style, dark=dark)
                    for family in ("default", *FONT_ASSETS, "default"):
                        front.back2.redact_setting("font_family", family)
                        front._apply_page_theme()
                        theme = front.page.theme
                        self.assert_theme_font_family(theme, family)
                        for slot in ("body_large", "body_medium", "title_medium", "label_large"):
                            self.assertEqual(
                                getattr(theme.text_theme, slot).color, front.TxtColor
                            )
                        self.assertEqual(theme.dropdown_theme.text_style.color, front.TxtColor)
                        self.assertEqual(
                            theme.primary_text_theme.body_medium.color,
                            theme.color_scheme.on_primary,
                        )

    def test_local_settings_survive_reopening_and_invalid_values_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend2.__new__(Backend2)
            back.web = False
            back.settings = Path(directory) / "settings.txt"
            back.set_default_settings()
            self.assertEqual(back.read_settings()["font_size"], "medium")
            self.assertEqual(back.read_settings()["font_family"], "default")
            back.redact_setting("font_family", "Ubuntu")
            back.redact_setting("font_size", "large")
            reopened = Backend2.__new__(Backend2)
            reopened.web = False
            reopened.settings = back.settings
            self.assertEqual(reopened.read_settings()["font_family"], "Ubuntu")
            self.assertEqual(reopened.read_settings()["font_size"], "large")
            reopened.redact_setting("font_family", "unknown")
            reopened.redact_setting("font_size", "huge")
            self.assertEqual(reopened.read_settings()["font_family"], "default")
            self.assertEqual(reopened.read_settings()["font_size"], "medium")

    def test_selectors_apply_immediately_preserve_group_and_do_not_accumulate_scale(self):
        async def exercise(phone, native):
            front = make_front(phone=phone)
            front.web = not native
            front.page.web = not native
            front.page.push_route = AsyncMock()
            front.back.saveB("Проверить шрифты", "default")
            front.render_daily_repeat_tasks()
            normal_heading_size = front.task_heading.size
            with ExitStack() as stack:
                stack.enter_context(patch("Backend.core.Backend.get_device", return_value=phone))
                for target in ("Frontend.init_page.Cloud", "Backend.core.Cloud", "Backend.extended.Cloud"):
                    stack.enter_context(patch(target, return_value=front.cloud))
                for setting, label, values in (
                    ("font_family", "Шрифт", (*FONT_ASSETS, "default")),
                    ("font_size", "Размер текста", ("large", "small", "medium", "large")),
                ):
                    for value in values:
                        panel = front.utils2.build_widgets_for_customization()
                        selector = next(c for c in panel.content.controls
                                        if isinstance(c, ft.Dropdown) and c.label == label)
                        selector.value = value
                        selector.on_select(None)
                        self.assertEqual(front.back2.read_settings()[setting], value)
                        if setting == "font_family":
                            self.assert_theme_font_family(front.page.theme, value)
                        self.assertEqual(front.current_group_id, "default")
                        self.assertEqual(len(front.back.read_tasks()), 1)
                self.assertEqual(front.task_heading.size, round(normal_heading_size * 1.2, 2))
                self.assertEqual(front.page.theme.text_theme.body_medium.size, 16.8)
                self.assertIsNone(front.page.theme.font_family)
                panel = front.utils2.build_widgets_for_customization()
                self.assertEqual(panel.content.controls[-1].content.controls[1].size, 19.2)
        for phone in (False, True):
            for native in (False, True):
                with self.subTest(phone=phone, native=native):
                    asyncio.run(exercise(phone, native))

    def test_font_assets_are_readable_and_web_paths_are_route_independent(self):
        front = make_front()
        for family, relative_path in FONT_ASSETS.items():
            font = ImageFont.truetype(str(Path("assets") / relative_path), 18)
            self.assertGreater(font.getlength("Съешь ещё этих мягких булок — 123"), 0)
            theme = ft.Theme()
            apply_typography(front.page, theme, family, "medium")
            self.assertEqual(theme.font_family, family)
            self.assertEqual(front.page.fonts[family], "/" + relative_path)

    def test_font_sizes_are_isolated_between_sessions(self):
        large = make_front()
        normal = make_front()
        large.back2.redact_setting("font_size", "large")
        large._apply_page_theme()
        self.assertEqual(large.libs.text_size(16), 19.2)
        self.assertEqual(normal.libs.text_size(16), 16)
