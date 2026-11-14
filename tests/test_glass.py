"""Glass material must preserve live control state, layout and semantic colors."""
import asyncio
import unittest
from dataclasses import fields
from unittest.mock import Mock, patch

import flet as ft

from Frontend.glass import GlassHost, apply_glass, glass_gradient
from Frontend.libs import Fr_Libs
from Frontend.theme import build_flet_theme, get_theme_colors, resolve_theme
from test_ui_state import make_front, task_menu


def walk_controls(control):
    seen = set()

    def visit(item):
        if not isinstance(item, ft.BaseControl) or id(item) in seen:
            return
        seen.add(id(item))
        yield item
        for field in fields(item):
            if field.name.startswith("_") or field.name == "data":
                continue
            child = getattr(item, field.name)
            for entry in child if isinstance(child, (list, tuple)) else (child,):
                yield from visit(entry)

    return list(visit(control))


class GlassTests(unittest.TestCase):
    def setUp(self):
        self.theme = "liquid_glass_light"
        self.colors = get_theme_colors(self.theme)

    def prepare(self, control):
        return apply_glass(control, self.theme, self.colors)

    def test_material_keeps_button_identity_events_and_layout_state(self):
        callback = Mock()
        button = ft.Button("Добавить", on_click=callback, width=160,
                           visible=False, disabled=True, data="action")
        row = ft.Row([button])
        self.prepare(row)
        self.assertIs(row.controls[0], button)
        self.assertFalse(button.visible)
        self.assertTrue(button.disabled)
        self.assertEqual(button.width, 160)
        self.assertEqual(button.data, "action")
        button.on_click(None)
        callback.assert_called_once_with(None)
        self.assertIsNone(button.content.blur)
        self.assertIsNone(button.content.shadow)
        self.assertIsNotNone(button.content.gradient)

    def test_repeated_updates_and_replaced_labels_do_not_nest_material(self):
        button = ft.Button("Отключить", icon=ft.Icons.PAUSE_ROUNDED)
        self.prepare(button)
        skin = button.content
        self.prepare(button)
        self.assertIs(button.content, skin)
        button.content = "Включить"
        button.icon = ft.Icons.PLAY_ARROW_ROUNDED
        button.disabled = True
        self.prepare(button)
        self.assertEqual(button.content.content.controls[-1].value, "Включить")
        self.assertLess(button.content.opacity, 1)
        button.disabled = False
        self.prepare(button)
        self.assertEqual(button.content.opacity, 1)

    def test_intrinsic_toolbar_buttons_do_not_expand_across_wrap(self):
        button = ft.Button(ft.Icon(ft.Icons.ADD_ROUNDED), style=ft.ButtonStyle(padding=2))
        self.prepare(button)
        self.assertIsNone(button.content.width)
        self.assertIsNone(button.content.alignment)
        self.assertEqual(button.content.padding, 2)

    def test_compact_material_uses_the_same_transparency_as_panels(self):
        for theme in ("liquid_glass_light", "liquid_glass_dark"):
            with self.subTest(theme=theme):
                libs = Fr_Libs(theme, False)
                button = libs.build_button_with_image("nazad", "Назад")
                panel = libs.create_style_cont([button], framed=True)
                libs.prepare(panel)
                self.assertEqual(button.content.gradient, panel.gradient)
                self.assertIsNone(button.content.bgcolor)

    def test_text_buttons_in_editor_and_dialogs_support_material(self):
        button = ft.TextButton("Прикрепить файлы", icon=ft.Icons.ATTACH_FILE_ROUNDED)
        self.prepare(button)
        self.assertIsNone(button.content.blur)
        self.assertIsNotNone(button.content.gradient)
        self.assertEqual(button.content.content.controls[-1].value, "Прикрепить файлы")

    def test_host_styles_widgets_added_after_initial_render(self):
        column = ft.Column([])
        host = GlassHost(self.theme, self.colors, content=column)
        host.before_update()
        button = ft.IconButton(ft.Icons.EDIT_ROUNDED)
        field = ft.TextField(value="Текст", visible=False)
        column.controls.extend([button, field])
        host.before_update()
        self.assertIs(column.controls[0], button)
        self.assertIsNone(button.icon.blur)
        self.assertIsNotNone(button.icon.gradient)
        self.assertFalse(field.visible)
        self.assertEqual(field.value, "Текст")
        self.assertEqual(field.fill_color, self.colors["GlassInputColor"])

    def test_color_swatches_and_badges_keep_their_meaning(self):
        swatch = ft.Button(ft.Icon(ft.Icons.CHECK_ROUNDED), bgcolor="#C62828",
                           width=42, height=42,
                           style=ft.ButtonStyle(shape=ft.CircleBorder(), padding=0,
                                                side=ft.BorderSide(2, "#203553")))
        badge = ft.Container(ft.Text("Важно"), bgcolor="#30E0A020", border_radius=6)
        self.prepare(ft.Column([swatch, badge]))
        self.assertEqual(swatch.content.bgcolor, "#C62828")
        self.assertIsNone(swatch.content.gradient)
        self.assertIsNone(swatch.content.foreground_decoration)
        self.assertEqual(swatch.content.padding, 0)
        self.assertEqual(swatch.content.border.top.width, 2)
        self.assertEqual(badge.bgcolor, "#30E0A020")

    def test_settings_expansion_has_blurred_surface_in_both_modes(self):
        for theme in ("liquid_glass_light", "liquid_glass_dark"):
            libs = Fr_Libs(theme, False)
            panel = libs.create_style_expansion_category(
                ft.Icons.TUNE_ROUNDED, "Настройки", [], framed=True,
            )
            libs.prepare(panel)
            self.assertIsNone(panel.bgcolor)
            self.assertIsNotNone(panel.border)
            self.assertIsNotNone(panel.gradient)
            self.assertIsNotNone(panel.blur)
            self.assertIsInstance(panel.content, ft.ExpansionTile)
            self.assertEqual(panel.content.bgcolor, ft.Colors.TRANSPARENT)
            self.assertIsNone(panel.content.shape.side)
            self.assertIsNone(panel.content.collapsed_shape.side)
            built = build_flet_theme(theme)
            self.assertIsNotNone(built.checkbox_theme)
            self.assertIsNotNone(built.date_picker_theme)

    def test_other_themes_are_unchanged(self):
        button = ft.Button("Добавить", bgcolor="#FFFFFF")
        apply_glass(button, "chatgpt_light", get_theme_colors("chatgpt_light"))
        self.assertEqual(button.content, "Добавить")
        self.assertEqual(button.bgcolor, "#FFFFFF")

    def test_dropdown_popup_has_readable_background_separate_from_input_fill(self):
        dropdown = ft.Dropdown(options=[ft.dropdown.Option("none", "Нет")])
        self.prepare(dropdown)
        self.assertEqual(dropdown.bgcolor, self.colors["GlassPopupColor"])
        self.assertEqual(dropdown.fill_color, self.colors["GlassInputColor"])
        self.assertNotEqual(dropdown.bgcolor, ft.Colors.TRANSPARENT)


class DesktopGlassTests(unittest.TestCase):
    def assert_outer_material(self, screen, panels):
        surfaces = [c for c in walk_controls(screen) if isinstance(c, ft.Container)]
        for attribute in ("blur", "shadow", "foreground_decoration"):
            self.assertEqual([c for c in surfaces if getattr(c, attribute) is not None], panels)

    def test_task_list_keeps_matching_toolbar_material_regardless_of_length_or_host_updates(self):
        for dark in (False, True):
            front = make_front(dark=dark, effect="liquid_glass")
            for count in (1, 100):
                with self.subTest(dark=dark, count=count):
                    data = front.back._load()
                    data["tasks"] = [dict(id=str(i), name=f"Task {i}", group="default", status=False,
                                          info_type="priority", priority="Важно") for i in range(count)]
                    front.back.store.save_all_sections(data)
                    front.render_daily_repeat_tasks()
                    front.libs.prepare(front.main_cont)
                    for control in walk_controls(front.main_cont):
                        if isinstance(control, GlassHost):
                            control.before_update()
                    self.assert_outer_material(front.main_cont, [])
                    self.assertIsNone(front.btns_cont.bgcolor)
                    self.assertEqual(front.btns_cont.gradient, glass_gradient(front.theme))
                    self.assertIsNone(front.tasks_cont.bgcolor)
                    self.assertIsNone(front.tasks_cont.border)
                    self.assertIsNone(front.tasks_cont.gradient)
                    for card in front.tasks_cont.content.controls:
                        if isinstance(card.data, str):
                            self.assertIsNone(card.bgcolor)
                            self.assertIsNotNone(card.border)
                            self.assertEqual(card.gradient, glass_gradient(front.theme))
                    self.assertTrue(front.tasks_cont.content.build_controls_on_demand)

    def test_groups_keep_matching_toolbar_material_as_the_list_grows(self):
        front = make_front(effect="liquid_glass")
        for count in (1, 100):
            data = front.back._load()
            data["groups"] = [dict(id=f"g{i}", name=f"Group {i}") for i in range(count)]
            front.back.store.save_all_sections(data)
            front.show_groups()
            front.open_group_management()
            front.libs.prepare(front._groups_screen)
            panels = [c for c in walk_controls(front._groups_screen)
                      if isinstance(c, ft.Container) and c.blur is not None]
            body = front._groups_screen.content.content.controls[1]
            self.assertEqual(panels, [body])
            self.assertIsNotNone(body.border)
            self.assertIsNone(front.groups_btns_cont.bgcolor)
            self.assertEqual(front.groups_btns_cont.gradient, glass_gradient(front.theme))
            self.assert_outer_material(front._groups_screen, panels)
            self.assertTrue(front._groups_column.build_controls_on_demand)

    def test_nested_host_and_later_children_share_the_outer_filter(self):
        libs = Fr_Libs("liquid_glass_light", False)
        inner = libs.create_style_cont([], framed=True)
        libs.prepare(inner)  # The inner panel may be prepared before mounting.
        self.assertIsNotNone(inner.blur)
        outer = libs.create_style_cont([inner], framed=True)
        libs.prepare(outer)
        self.assert_outer_material(outer, [outer])
        inner.before_update()
        panel = ft.Container(ft.Button("Добавить"), bgcolor=libs.ContBgColor, border_radius=16)
        inner.content.controls.append(panel)
        inner.before_update()
        self.assertIsNotNone(panel.gradient)
        self.assertIsNotNone(panel.content.content.gradient)
        self.assert_outer_material(outer, [outer])


class MobileGlassTests(unittest.TestCase):
    walk = staticmethod(walk_controls)

    def assert_light_material_and_toolbar_gloss(self, screen, toolbar, theme):
        controls = self.walk(screen)
        surfaces = [c for c in controls if isinstance(c, ft.Container)]
        self.assertFalse(any(c.blur is not None for c in surfaces))
        glass_surfaces = [c for c in surfaces if c.gradient is not None]
        self.assertIn(toolbar, glass_surfaces)
        self.assertEqual(toolbar.gradient, glass_gradient(theme, mobile=True, toolbar=True))
        for surface in glass_surfaces:
            if surface is not toolbar:
                self.assertEqual(surface.gradient, glass_gradient(theme, mobile=True))
            self.assertIsNone(surface.bgcolor)
        self.assertEqual([c for c in surfaces if c.shadow is not None], [toolbar])
        highlights = [c for c in surfaces if c.foreground_decoration is not None]
        self.assertIn(toolbar, highlights)
        self.assertTrue(all(len(c.foreground_decoration.gradient.colors) == 2
                            for c in highlights if c is not toolbar))
        self.assertFalse(any(getattr(c, "_nd_glass_skin", None) for c in controls))

    def assert_overlay(self, screen, list_container, scrollable, toolbar, *, framed=False):
        stack = next(c for c in self.walk(screen) if isinstance(c, ft.Stack))
        self.assertIs(stack.controls[0], list_container)
        self.assertEqual(list_container.bottom, 0)
        self.assertIsNone(list_container.bgcolor)
        if framed:
            self.assertIsNotNone(list_container.gradient)
            self.assertIsNotNone(list_container.border)
        else:
            self.assertIsNone(list_container.gradient)
            self.assertIsNone(list_container.border)
        menu = stack.controls[-1]
        self.assertIs(menu.content, toolbar)
        self.assertGreater(menu.bottom, 0)
        self.assertIsInstance(scrollable, ft.ListView)
        self.assertTrue(scrollable.build_controls_on_demand)
        # The inset scrolls with the items and clears even the larger add button.
        add = stack.controls[1]
        self.assertGreater(scrollable.padding.bottom, add.bottom + add.content.height)

    def test_toolbar_keeps_gloss_and_cards_keep_light_material_as_the_list_grows(self):
        for dark in (False, True):
            with self.subTest(dark=dark):
                front = make_front(phone=True, dark=dark, effect="liquid_glass_half",
                                   settings={"action_panel_position": "bottom"})
                self.assertIsNone(front.root_view.decoration)
                for count in (1, 30):
                    for index in range(count):
                        front.back.saveB(f"Дело {count}-{index}", "default",
                                         info_type="priority", priority="Важно")
                    front.render_daily_repeat_tasks()
                    front.libs.prepare(front.main_cont)
                    # Nested hosts also run their hooks during serialization.
                    for control in self.walk(front.main_cont):
                        if isinstance(control, GlassHost):
                            control.before_update()
                    self.assert_light_material_and_toolbar_gloss(front.main_cont, front.btns_cont, front.theme)
                    self.assert_overlay(front.main_cont, front.tasks_cont,
                                        front.tasks_cont.content, front.btns_cont)
                front.show_groups()
                front.open_group_management()
                screen = front._groups_screen
                front.libs.prepare(screen)
                self.assert_light_material_and_toolbar_gloss(screen, front.groups_btns_cont, front.theme)
                stack = next(c for c in self.walk(screen) if isinstance(c, ft.Stack))
                self.assert_overlay(screen, stack.controls[0], front._groups_column,
                                    front.groups_btns_cont, framed=True)

    def test_half_glass_styles_later_controls_without_wrappers_or_filters(self):
        theme = resolve_theme("chatgpt", ft.Brightness.LIGHT, "liquid_glass_half")
        colors = get_theme_colors(theme)
        column = ft.Column([])
        host = GlassHost(theme, colors, mobile=True, content=column)
        host.before_update()
        button = ft.Button("Удалить", bgcolor="#C62828", disabled=True)
        badge = ft.Container(ft.Text("Важно"), bgcolor="#30E0A020", border_radius=6)
        field = ft.TextField(value="Текст", visible=False)
        dropdown = ft.Dropdown(value="none", options=[ft.dropdown.Option("none", "Нет")])
        column.controls.extend([button, badge, field, dropdown])
        original_controls = self.walk(host)
        host.before_update()
        self.assertEqual(button.content, "Удалить")
        self.assertEqual(button.bgcolor, "#C62828")
        self.assertEqual(badge.bgcolor, "#30E0A020")
        self.assertTrue(button.disabled)
        self.assertIsNotNone(button.style.side)
        self.assertIsNotNone(badge.foreground_decoration)
        self.assertEqual(field.value, "Текст")
        self.assertFalse(field.visible)
        self.assertTrue(field.filled)
        self.assertTrue(dropdown.filled)
        self.assertEqual(dropdown.value, "none")
        self.assertEqual(dropdown.menu_style.elevation, 0)
        decoration, style = badge.foreground_decoration, button.style
        button.disabled = False
        badge.bgcolor = "#30C62828"
        host.before_update()
        self.assertEqual(button.content, "Удалить")
        self.assertFalse(button.disabled)
        self.assertEqual(badge.bgcolor, "#30C62828")
        self.assertIs(badge.foreground_decoration, decoration)
        self.assertIs(button.style, style)
        self.assertEqual([id(c) for c in self.walk(host)], [id(c) for c in original_controls])
        self.assertTrue(all(c.blur is None and c.shadow is None
                            for c in self.walk(host) if isinstance(c, ft.Container)))

    def test_mobile_list_keeps_search_completion_and_last_task_deletion(self):
        front = make_front(phone=True, effect="liquid_glass_half",
                           settings={"action_panel_position": "bottom"})
        front._update_control = Mock()
        front.back.saveB("Единственное дело", "default")
        front.render_daily_repeat_tasks()
        front.libs.prepare(front.main_cont)
        scrollable = front.tasks_cont.content
        card = next(c for c in scrollable.controls if isinstance(c.data, str))
        checkbox = next(c for c in card.content.controls if isinstance(c, ft.Checkbox))
        checkbox.value = True
        with patch.object(ft.Container, "update"):
            checkbox.on_change(Mock(control=checkbox))
        self.assertTrue(front.back.read_tasks()[0]["status"])
        self.assertEqual(front.task_progress.value, 1)
        front.apply_search_filter("Нет совпадений")
        self.assertFalse(card.visible)
        self.assertTrue(front.empty_state.visible)
        front.close_search(None)
        self.assertTrue(card.visible)
        delete = task_menu(card).items[-1]
        delete.on_click(None)
        callback, *args = front.page.run_task.call_args.args
        asyncio.run(callback(*args))
        front.libs.prepare(front.main_cont)
        self.assertEqual(front.back.read_tasks(), [])
        self.assertTrue(front.empty_state.visible)
        self.assertIs(front.tasks_cont.content, scrollable)
        self.assert_overlay(front.main_cont, front.tasks_cont, scrollable, front.btns_cont)


if __name__ == "__main__":
    unittest.main()
