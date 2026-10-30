import asyncio
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import flet as ft

from Backend.extended import Backend2
from Frontend.layout import ACTION_PANEL_OPTIONS, GROUP_PANEL_OPTIONS
from test_glass import walk_controls
from test_ui_state import make_front


class PanelLayoutTests(unittest.TestCase):
    def test_defaults_and_local_settings_survive_reopening(self):
        for phone in (False, True):
            with self.subTest(phone=phone), tempfile.TemporaryDirectory() as directory:
                back = Backend2.__new__(Backend2)
                back.web, back.phone = False, phone
                back.settings = Path(directory) / "settings.txt"
                back.set_default_settings()
                self.assertEqual(back.read_settings()["action_panel_position"], "bottom" if phone else "top")
                self.assertEqual(back.read_settings()["group_panel_position"], "top")
                for position, _ in ACTION_PANEL_OPTIONS:
                    back.redact_setting("action_panel_position", position)
                    back.redact_setting("group_panel_position", "bottom")
                    back.set_default_settings()
                    reopened = Backend2.__new__(Backend2)
                    reopened.web, reopened.phone, reopened.settings = False, phone, back.settings
                    self.assertEqual(reopened.read_settings()["action_panel_position"], position)
                    self.assertEqual(reopened.read_settings()["group_panel_position"], "bottom")
                back.redact_setting("action_panel_position", "invalid")
                back.redact_setting("group_panel_position", "left")
                self.assertEqual(back.read_settings()["action_panel_position"], "bottom" if phone else "top")
                self.assertEqual(back.read_settings()["group_panel_position"], "top")

    def test_positions_keep_actions_reachable_and_lists_lazy_in_all_effects(self):
        for phone in (False, True):
            for effect in (("none", "liquid_glass_half") if phone else ("none", "liquid_glass", "liquid_glass_half")):
                for position, _ in ACTION_PANEL_OPTIONS:
                    for groups_position, _ in GROUP_PANEL_OPTIONS:
                        with self.subTest(phone=phone, effect=effect, position=position, groups=groups_position):
                            front = make_front(phone=phone, effect=effect, settings={
                                "action_panel_position": position, "group_panel_position": groups_position,
                            })
                            front.libs.prepare(front.main_cont)
                            controls = walk_controls(front.main_cont)
                            for action in (front.button_add_task, front.settings, front.auth_btn,
                                           front.undo_btn, front.upd_btn, front.group_tabs):
                                self.assertIn(id(action), [id(c) for c in controls])
                            self.assertIs(front.main_cont.content.controls[0 if groups_position == "top" else -2],
                                          front.group_tabs)
                            if effect == "liquid_glass_half":
                                self.assertEqual(sum(isinstance(c, ft.Container) and c.blur is not None
                                                     for c in controls), 1)
                            self.assertTrue(front.tasks_cont.content.build_controls_on_demand)
                            front.open_group_management()
                            front.libs.prepare(front._groups_screen)
                            self.assertTrue(front._groups_column.expand)
                            self.assertTrue(front._groups_column.build_controls_on_demand)
                            group_controls = walk_controls(front._groups_screen)
                            self.assertIn(front.groups_undo_btn, group_controls)
                            for control in group_controls:
                                if isinstance(control, (ft.Column, ft.Row)):
                                    self.assertTrue(all(isinstance(child, ft.Control)
                                                        for child in control.controls))

    def test_selectors_apply_immediately_and_preserve_group_data_and_theme(self):
        async def exercise(phone, native):
            front = make_front("nord", phone=phone, effect="liquid_glass_half")
            front.web = front.page.web = not native
            front.page.push_route = AsyncMock()
            front.back.saveB("Сохранить дело", "default")
            with ExitStack() as stack:
                stack.enter_context(patch("Backend.core.Backend.get_device", return_value=phone))
                for target in ("Frontend.init_page.Cloud", "Backend.core.Cloud", "Backend.extended.Cloud"):
                    stack.enter_context(patch(target, return_value=front.cloud))
                for setting, label, options in (
                    ("action_panel_position", "Положение панели кнопок", ACTION_PANEL_OPTIONS),
                    ("group_panel_position", "Положение панели групп", GROUP_PANEL_OPTIONS),
                ):
                    for value, _ in options:
                        panel = front.utils2.build_widgets_for_customization()
                        selector = next(c for c in panel.content.controls
                                        if isinstance(c, ft.Dropdown) and c.label == label)
                        self.assertEqual([(o.key, o.text) for o in selector.options], list(options))
                        selector.value = value
                        selector.on_select(None)
                        self.assertEqual(front.back2.read_settings()[setting], value)
                        self.assertEqual(getattr(front, setting), value)
                        self.assertEqual(front.theme_effect, "liquid_glass_half")
                        self.assertEqual(front.theme_style, "nord")
                        self.assertEqual(front.current_group_id, "default")
                        self.assertEqual(len(front.back.read_tasks()), 1)
            await asyncio.sleep(0)

        for phone in (False, True):
            for native in (False, True):
                with self.subTest(phone=phone, native=native):
                    asyncio.run(exercise(phone, native))
