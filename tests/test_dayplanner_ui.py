"""The shared skin must cover late controls without disturbing UI state."""
import unittest
from unittest.mock import Mock

import flet as ft

from Frontend.dayplanner import contrast_color
from Frontend.libs import Fr_Libs
from Frontend.theme import build_flet_theme
from test_ui_performance import serialize
from test_ui_state import make_front


class DayPlannerUiTests(unittest.TestCase):
    def test_later_fields_keep_values_events_errors_and_serialize_only_once(self):
        for theme in ("chatgpt_light", "chatgpt_dark", "liquid_glass_half_chatgpt_light",
                      "liquid_glass_chatgpt_dark"):
            with self.subTest(theme=theme):
                libs = Fr_Libs(theme, False)
                inner = libs.host(content=ft.Column([]))
                page = ft.Page(sess=Mock())
                page.views[0].controls = [libs.host(content=inner)]
                serialize(page, initial=True)
                handler = Mock()
                entry = ft.TextField(value="Несохранённый текст", error="Проверьте поле",
                                     on_change=handler, password=True)
                dropdown = ft.Dropdown(value="b", options=[ft.dropdown.Option("a"),
                                                          ft.dropdown.Option("b")])
                inner.content.controls.extend([entry, dropdown])
                self.assertTrue(serialize(page))
                self.assertTrue(entry.filled)
                self.assertTrue(dropdown.filled)
                self.assertEqual(entry.value, "Несохранённый текст")
                self.assertEqual(entry.error, "Проверьте поле")
                self.assertIs(entry.on_change, handler)
                self.assertTrue(entry.password)
                self.assertEqual(dropdown.value, "b")
                self.assertEqual(serialize(page), [])

    def test_group_tab_capsule_uses_supported_indicator_and_keeps_selection(self):
        front = make_front()
        front.back.create_group("Работа")
        front.render_daily_repeat_tasks()
        selected = front.group_tabs.selected_index
        handler = front.group_tabs.on_change
        front.libs.prepare(front.main_cont)
        self.assertIsInstance(front.group_tab_bar.indicator, ft.UnderlineTabIndicator)
        self.assertEqual(front.group_tabs.selected_index, selected)
        self.assertIs(front.group_tabs.on_change, handler)

    def test_mobile_navigation_has_only_controls_for_text_and_icon_actions(self):
        for effect in ("none", "liquid_glass_half"):
            front = make_front(phone=True, effect=effect, settings={"action_panel_position": "top"})
            front.open_group_management()
            button = front.groups_add_btn
            self.assertIsInstance(button.content, ft.Column)
            self.assertTrue(all(isinstance(child, ft.Control) for child in button.content.controls))
            self.assertIsNotNone(button.on_click)

    def test_primary_actions_choose_readable_text_for_custom_accents(self):
        for accent, foreground in (("#FFFF00", "#161616"), ("#25134A", "#FFFFFF"),
                                   (ft.Colors.YELLOW, "#161616"), (ft.Colors.BLACK, "#FFFFFF")):
            with self.subTest(accent=accent):
                libs = Fr_Libs("chatgpt_light", False, button_color=accent)
                button = libs.create_style_button("Сохранить", primary=True)
                libs.prepare(button)
                self.assertEqual(button.bgcolor, libs.colors["PrimaryColor"])
                self.assertNotEqual(button.bgcolor, accent)
                self.assertEqual(button.style.color, contrast_color(button.bgcolor))
                self.assertEqual(contrast_color(accent), foreground)
                entry = ft.TextField(value="Сохранить читаемость")
                libs.prepare(entry)
                self.assertEqual(entry.fill_color, Fr_Libs("chatgpt_light", False).BtnColor)

    def test_dark_checkbox_outline_uses_supported_theme_and_control_types(self):
        libs = Fr_Libs("chatgpt_dark", False)
        checkbox = ft.Checkbox(value=False)
        libs.prepare(checkbox)
        self.assertIsInstance(build_flet_theme(libs.theme).checkbox_theme.border_side, ft.BorderSide)
        self.assertEqual(checkbox.border_side[ft.ControlState.DEFAULT].color, libs.colors["MutedColor"])
        self.assertEqual(checkbox.border_side[ft.ControlState.SELECTED].color, libs.colors["SuccessColor"])


if __name__ == "__main__":
    unittest.main()
