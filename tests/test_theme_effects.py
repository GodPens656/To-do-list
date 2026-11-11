"""Effects combine with every palette and survive customization and restarts."""
import asyncio
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import flet as ft

from Backend.extended import Backend2
from Frontend.glass import glass_background, glass_gradient
from Frontend.dayplanner import color_rgb, contrast_color
from Frontend.libs import Fr_Libs
from Frontend.theme import (
    BUTTON_BACKGROUND_OPTIONS, THEME_STYLE_OPTIONS, build_flet_theme,
    get_theme_colors, resolve_theme,
)
from test_ui_state import make_front


class ThemeEffectTests(unittest.TestCase):
    def test_every_palette_and_layout_preserves_colors_with_glass(self):
        for style, _ in THEME_STYLE_OPTIONS:
            for dark in (False, True):
                for phone, effect in ((False, "liquid_glass"), (False, "liquid_glass_half"),
                                      (True, "liquid_glass_half")):
                    with self.subTest(style=style, dark=dark, phone=phone, effect=effect):
                        front = make_front(style, dark, phone, effect=effect)
                        base = get_theme_colors(resolve_theme(style, front.page.platform_brightness))
                        self.assertEqual(front.libs.glass, effect == "liquid_glass")
                        for key in ("BgColor", "TxtColor", "ProgressColor", "BtnColor"):
                            self.assertEqual(front.colors[key], base[key])
                        self.assertEqual(glass_background(front.theme).colors[0], base["BgColor"])
                        front.back.saveB("Проверить эффект", "default", info_type="priority", priority="Важно")
                        front.render_daily_repeat_tasks()
                        front.libs.prepare(front.main_cont)
                        self.assertIsNone(front.tasks_cont.bgcolor)
                        self.assertIsNone(front.tasks_cont.gradient)
                        self.assertIsNone(front.tasks_cont.border)
                        card = next(c for c in front.tasks_cont.content.controls
                                    if isinstance(c.data, str))
                        self.assertIsNone(card.bgcolor)
                        self.assertEqual(card.gradient, glass_gradient(front.theme, mobile=phone))
                        self.assertIsNotNone(card.border)
                        if phone:
                            self.assertNotEqual(front.btns_cont.gradient, card.gradient)
                            self.assertNotEqual(front.btns_cont.border, card.border)
                            self.assertIsNone(front.btns_cont.bgcolor)
                            self.assertIsNone(front.btns_cont.blur)
                            self.assertIsNotNone(front.btns_cont.shadow)
                            self.assertIsNotNone(front.btns_cont.foreground_decoration)
                        else:
                            for attribute in ("bgcolor", "gradient", "border", "blur", "shadow", "foreground_decoration"):
                                self.assertEqual(getattr(front.btns_cont, attribute), getattr(card, attribute))
                        front.show_groups()
                        self.assertEqual(len(front.back.read_tasks()), 1)
                        if effect == "liquid_glass":
                            self.assertIsNotNone(front.page.theme.dialog_theme)
                            self.assertIsNotNone(front.page.theme.dropdown_theme.menu_style)
                        else:
                            self.assertEqual(front.page.theme.dialog_theme.elevation, 0)
                            self.assertEqual(front.page.theme.dropdown_theme.menu_style.elevation, 0)
                            self.assertIsNone(front.root_view.decoration)
                            self.assertIsNone(front.btns_cont.blur)

    def test_selector_applies_and_removes_effect_preserving_group_and_theme(self):
        async def exercise(phone, native):
            front = make_front("improved_green", phone=phone)
            front.web = front.page.web = not native
            front.page.push_route = AsyncMock()
            front.back.saveB("Сохранить дело", "default")
            front.render_daily_repeat_tasks()
            with ExitStack() as stack:
                stack.enter_context(patch("Backend.core.Backend.get_device", return_value=phone))
                for target in ("Frontend.init_page.Cloud", "Backend.core.Cloud", "Backend.extended.Cloud"):
                    stack.enter_context(patch(target, return_value=front.cloud))
                final_effect = "liquid_glass_half" if phone else "liquid_glass"
                effects = ("liquid_glass_half", "none", final_effect)
                options = [("none", "Нет"), ("liquid_glass_half", "Liquid glass 0,5x")]
                if not phone:
                    options.insert(1, ("liquid_glass", "Liquid glass"))
                for effect in effects:
                    controls = front.utils2.build_widgets_for_customization().content.controls
                    label_index = next(i for i, c in enumerate(controls) if isinstance(c, ft.Text) and c.value == "Эффект:")
                    selector = controls[label_index + 1]
                    self.assertIsInstance(selector, ft.Dropdown)
                    self.assertEqual([(o.key, o.text) for o in selector.options], options)
                    selector.value = effect
                    selector.on_select(None)
                    self.assertEqual(front.back2.read_settings()["theme_effect"], effect)
                    self.assertEqual(front.theme_style, "improved_green")
                    self.assertEqual(front.libs.glass, effect == "liquid_glass")
                    self.assertEqual(front.libs.glass_mobile, phone and effect != "none")
                    self.assertEqual(front.current_group_id, "default")
                    self.assertEqual(len(front.back.read_tasks()), 1)
                front.back2.redact_setting("theme_style", "oled_green")
                front.apply_theme_style("oled_green", ft.Brightness.DARK)
                self.assertEqual(front.theme, f"{final_effect}_oled_green_dark")
                front._on_platform_brightness_change(type("Event", (), {"brightness": ft.Brightness.LIGHT})())
                self.assertEqual(front.theme, f"{final_effect}_oled_green_light")
                front.back2.redact_setting("button_bg_mode", "custom")
                front.back2.redact_setting("button_custom_color", "#C62828")
                front.apply_button_color()
                self.assertEqual(front.colors["ProgressColor"], "#C62828")
                self.assertIsNotNone(front.colors["GlassButtonTint"])
        for phone in (False, True):
            for native in (False, True):
                with self.subTest(phone=phone, native=native):
                    asyncio.run(exercise(phone, native))

    def test_local_settings_migrate_legacy_glass_and_persist_separate_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend2.__new__(Backend2)
            back.web = False
            back.settings = Path(directory) / "settings.txt"
            back._settings_write({"theme_style": "liquid_glass"})
            back.set_default_settings()
            self.assertEqual(back.read_settings()["theme_style"], "chatgpt")
            self.assertEqual(back.read_settings()["theme_effect"], "liquid_glass")
            back.redact_setting("theme_style", "nord")
            reopened = Backend2.__new__(Backend2)
            reopened.web, reopened.settings = False, back.settings
            reopened.set_default_settings()
            self.assertEqual(reopened.read_settings()["theme_style"], "nord")
            self.assertEqual(reopened.read_settings()["theme_effect"], "liquid_glass")
            reopened.redact_setting("theme_effect", "liquid_glass_half")
            reopened.set_default_settings()
            self.assertEqual(reopened.read_settings()["theme_effect"], "liquid_glass_half")
            reopened.redact_setting("theme_effect", "none")
            self.assertEqual(reopened.read_settings()["theme_effect"], "none")
            reopened.redact_setting("theme_effect", "invalid")
            self.assertEqual(reopened.read_settings()["theme_effect"], "none")

    def test_browser_settings_migrate_legacy_glass(self):
        front = make_front("liquid_glass")
        self.assertEqual(front.theme_style, "chatgpt")
        self.assertEqual(front.theme_effect, "liquid_glass")
        self.assertNotIn("liquid_glass", dict(THEME_STYLE_OPTIONS))

    def test_desktop_preserves_saved_half_glass(self):
        front = make_front("nord", effect="liquid_glass_half")
        self.assertEqual(front.theme_style, "nord")
        self.assertEqual(front.theme_effect, "liquid_glass_half")
        self.assertEqual(front.web_store._settings["theme_effect"], "liquid_glass_half")
        front.back2.redact_setting("theme_effect", "liquid_glass_half")
        self.assertEqual(front.back2.read_settings()["theme_effect"], "liquid_glass_half")
        self.assertEqual(front.web_store._settings["theme_effect"], "liquid_glass_half")

    def test_local_desktop_keeps_saved_half_glass_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend2.__new__(Backend2)
            back.web, back.phone = False, False
            back.settings = Path(directory) / "settings.txt"
            back._settings_write({"theme_style": "nord", "theme_effect": "liquid_glass_half"})
            for _ in range(2):
                back.set_default_settings()
                self.assertEqual(back._settings_read()["theme_effect"], "liquid_glass_half")
                self.assertEqual(back.read_settings()["theme_style"], "nord")
                self.assertEqual(back.read_settings()["theme_effect"], "liquid_glass_half")

    def test_phone_replaces_saved_full_glass_and_cannot_reenable_it(self):
        for style, effect in (("liquid_glass", None), ("nord", "liquid_glass")):
            with self.subTest(style=style):
                front = make_front(style, phone=True, effect=effect)
                self.assertEqual(front.theme_effect, "liquid_glass_half")
                self.assertEqual(front.web_store._settings["theme_effect"], "liquid_glass_half")
                self.assertEqual(front.theme_style, "chatgpt" if effect is None else style)
                front.back2.redact_setting("theme_effect", "liquid_glass")
                self.assertEqual(front.back2.read_settings()["theme_effect"], "liquid_glass_half")
                self.assertEqual(front.web_store._settings["theme_effect"], "liquid_glass_half")

    def test_local_phone_settings_replace_full_glass_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend2.__new__(Backend2)
            back.web, back.phone = False, True
            back.settings = Path(directory) / "settings.txt"
            back._settings_write({"theme_style": "nord", "theme_effect": "liquid_glass"})
            back.set_default_settings()
            self.assertEqual(back._settings_read()["theme_effect"], "liquid_glass_half")
            self.assertEqual(back.read_settings()["theme_effect"], "liquid_glass_half")
            back.redact_setting("theme_effect", "liquid_glass")
            self.assertEqual(back._settings_read()["theme_effect"], "liquid_glass_half")

    def test_half_glass_keeps_custom_colors_and_uses_lightweight_widget_themes(self):
        for style, _ in THEME_STYLE_OPTIONS:
            for brightness in (ft.Brightness.LIGHT, ft.Brightness.DARK):
                with self.subTest(style=style, brightness=brightness):
                    theme = resolve_theme(style, brightness, "liquid_glass_half")
                    base = resolve_theme(style, brightness)
                    for accent in (None, "#C62828"):
                        colors = get_theme_colors(theme, accent)
                        for key, value in get_theme_colors(base, accent).items():
                            if accent is None and key in ("CategoryIconColor", "CategoryIconBgColor"):
                                continue
                            self.assertEqual(colors[key], value)
                        half, regular = build_flet_theme(theme, accent), build_flet_theme(base, accent)
                        self.assertEqual(half.color_scheme, regular.color_scheme)
                        self.assertEqual(half.button_theme.style.elevation, 0)
                        self.assertEqual(half.dialog_theme.elevation, 0)
                        self.assertEqual(half.popup_menu_theme.elevation, 0)
                        self.assertEqual(half.dropdown_theme.menu_style.elevation, 0)
                        self.assertIsNotNone(half.checkbox_theme)
                        self.assertIsNotNone(half.switch_theme)
                        self.assertIsNone(half.tooltip_theme.decoration.gradient)

    def test_glass_supports_every_named_accent_as_well_as_custom_hex(self):
        for style, _ in THEME_STYLE_OPTIONS:
            for brightness in (ft.Brightness.LIGHT, ft.Brightness.DARK):
                theme = resolve_theme(style, brightness, "liquid_glass")
                for key, _, accent in BUTTON_BACKGROUND_OPTIONS:
                    with self.subTest(style=style, brightness=brightness, accent=key):
                        colors = get_theme_colors(theme, accent)
                        self.assertEqual(colors["ProgressColor"], accent)
                        self.assertIsNotNone(colors["GlassButtonTint"])
                        self.assertIsNotNone(build_flet_theme(theme, accent).button_theme)

    def test_custom_accents_keep_primary_actions_and_settings_icons_distinct(self):
        accents = [color for _, _, color in BUTTON_BACKGROUND_OPTIONS]
        accents.extend(("#25134A", "#C62828", "#FAFAF8"))
        for style, _ in THEME_STYLE_OPTIONS:
            for brightness in (ft.Brightness.LIGHT, ft.Brightness.DARK):
                for effect in ("none", "liquid_glass", "liquid_glass_half"):
                    for accent in accents:
                        with self.subTest(style=style, brightness=brightness, effect=effect, accent=accent):
                            libs = Fr_Libs(resolve_theme(style, brightness, effect), False, button_color=accent)
                            primary = libs.create_style_button("Добавить дело", primary=True)
                            category = libs.create_style_category_button(ft.Icons.PALETTE_ROUNDED, "Кастомизация")
                            expansion = libs.create_style_expansion_category(
                                ft.Icons.TUNE_ROUNDED, "Общие настройки", [], framed=True,
                            )
                            section = libs.create_style_expansion_category(
                                ft.Icons.PALETTE_ROUNDED, "Акцентный цвет", [],
                            )
                            libs.prepare(ft.Column([primary, category, expansion, section]))
                            full_glass = effect == "liquid_glass"
                            primary_fill = primary.content.bgcolor if full_glass else primary.bgcolor
                            row = category.content.content if full_glass else category.content
                            tile = expansion.content if full_glass else expansion
                            plain_tile = section.content if full_glass else section
                            badge = row.controls[0]
                            self.assertNotEqual(color_rgb(primary_fill), color_rgb(accent))
                            self.assertEqual(primary.style.color, contrast_color(primary_fill))
                            self.assertEqual(badge.content.color, primary_fill)
                            self.assertEqual(tile.title.controls[0].content.color, primary_fill)
                            self.assertEqual(libs.colors["ProgressColor"], accent)
                            self.assertEqual(tile.collapsed_text_color, libs.colors["ButtonTextColor"])
                            self.assertEqual(plain_tile.collapsed_bgcolor, ft.Colors.TRANSPARENT)
                            if full_glass:
                                self.assertEqual(category.content.bgcolor, expansion.bgcolor)
                                self.assertEqual(expansion.bgcolor, libs.colors["BtnColor"])
                                self.assertIsNone(expansion.gradient)
                                self.assertIsNone(tile.shape.side)
                                self.assertEqual(tile.collapsed_bgcolor, ft.Colors.TRANSPARENT)
                                self.assertEqual(tile.bgcolor, ft.Colors.TRANSPARENT)
                            else:
                                self.assertEqual(category.bgcolor, accent)
                                self.assertEqual(tile.collapsed_bgcolor, accent)
                                self.assertEqual(tile.bgcolor, libs.colors["BgColor"])
                            # Repeated preparation must preserve both the tint
                            # and icon colors after navigating or expanding.
                            tile.expanded = True
                            libs.prepare(expansion)
                            self.assertTrue(tile.expanded)
                            self.assertEqual(tile.title.controls[0].content.color, primary_fill)
                            self.assertEqual(expansion.bgcolor if full_glass else tile.collapsed_bgcolor,
                                             libs.colors["BtnColor"])

    def test_default_settings_icons_remain_readable_over_glass(self):
        def luminance(color):
            channels = [channel / 255 for channel in color_rgb(color)]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                      for v in channels]
            return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for style, _ in THEME_STYLE_OPTIONS:
            for brightness in (ft.Brightness.LIGHT, ft.Brightness.DARK):
                for effect in ("liquid_glass", "liquid_glass_half"):
                    with self.subTest(style=style, brightness=brightness, effect=effect):
                        libs = Fr_Libs(resolve_theme(style, brightness, effect), False)
                        category = libs.create_style_category_button(ft.Icons.PALETTE_ROUNDED, "Кастомизация")
                        libs.prepare(category)
                        row = category.content.content if effect == "liquid_glass" else category.content
                        badge = row.controls[0]
                        foreground, background = sorted((luminance(badge.content.color), luminance(badge.bgcolor)))
                        self.assertGreaterEqual((background + 0.05) / (foreground + 0.05), 4.5)
                        self.assertIsNone(badge.gradient)
                        self.assertIsNone(badge.blur)
                        self.assertIsNotNone(badge.border)


if __name__ == "__main__":
    unittest.main()
