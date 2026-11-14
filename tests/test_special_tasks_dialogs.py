import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import flet as ft

from Backend.extended import Backend2
from Backend.webstorage import WebSessionStore
from test_glass import walk_controls
from test_ui_performance import serialize
from test_ui_state import make_front


SETTING = "special_tasks_separate_dialogs"
LABEL = "Открытие списка повторяющихся и отложенных как отдельные диалоги"


class SpecialTaskDialogTests(unittest.TestCase):
    def test_setting_defaults_and_persists_in_desktop_and_browser_storage(self):
        for web in (False, True):
            with self.subTest(web=web), tempfile.TemporaryDirectory() as directory:
                back = Backend2.__new__(Backend2)
                back.web = web
                back.store = WebSessionStore(SimpleNamespace())
                back.settings = Path(directory) / "settings.txt"
                # Upgrade an existing configuration without losing its values.
                back._settings_write({"border": "True"})
                back.set_default_settings()
                self.assertFalse(back.read_settings()[SETTING])
                self.assertTrue(back.read_settings()["border"])
                for enabled in (True, False):
                    back.redact_setting(SETTING, enabled)
                    restored = Backend2.__new__(Backend2)
                    restored.web = web
                    restored.settings = back.settings
                    restored.store = WebSessionStore(SimpleNamespace())
                    restored.store._settings = back.store.read_settings_text()
                    restored.set_default_settings()
                    self.assertEqual(restored.read_settings()[SETTING], enabled)
                    self.assertTrue(restored.read_settings()["border"])

    @staticmethod
    def form_content(front):
        centered = front.screen_stack[-1].content.controls[0]
        return centered.content.content.controls[1]

    def test_toggle_changes_next_opening_and_back_returns_to_settings(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.open_settings()
                settings_screen = front.screen_stack[-1]
                settings = front.settings_cont.content.controls
                special_button = settings[0]
                general = settings[3].controls[0]
                preference = next(
                    row for row in general.content.controls
                    if row.controls[0].value == LABEL
                ).controls[1]
                for enabled in (False, True, False):
                    preference.value = enabled
                    preference.on_change(None)
                    special_button.on_click(None)
                    content = self.form_content(front).content.controls
                    for block in content[:2]:
                        if enabled:
                            self.assertIsInstance(block, ft.Button)
                        else:
                            self.assertIsInstance(block.controls[1], ft.ExpansionTile)
                    content[-1].on_click(None)
                    self.assertIs(front.screen_stack[-1], settings_screen)
                    self.assertEqual(front.back2.read_settings()[SETTING], enabled)

    def test_separate_lists_support_create_edit_delete_info_and_back(self):
        for phone in (False, True):
            for repeating in (True, False):
                with self.subTest(phone=phone, repeating=repeating):
                    front = make_front(phone=phone)
                    front.back2.redact_setting(SETTING, True)
                    front.open_settings()
                    settings_screen = front.screen_stack[-1]
                    front.settings_cont.content.controls[0].on_click(None)
                    special_screen = front.screen_stack[-1]
                    hub_content = self.form_content(front)
                    button = hub_content.content.controls[0 if repeating else 1]
                    button.on_click(None)
                    list_screen = front.screen_stack[-1]
                    list_content = self.form_content(front)
                    toolbar, tasks, back = list_content.content.controls
                    self.assertEqual(len(tasks.content.controls), 0)
                    toolbar.controls[-1].on_click(None)
                    self.assertIsNot(front.screen_stack[-1], list_screen)
                    front.close_page()
                    self.assertIs(front.screen_stack[-1], list_screen)

                    toolbar.controls[-2].on_click(None)
                    entry = front.libs.entry_task
                    entry.value = "Новое дело"
                    if not repeating:
                        form = self.form_content(front)
                        next(c for c in walk_controls(form)
                             if isinstance(c, ft.TextField) and c.label == "Дата добавления").value = "01-01-2030"
                    entry.on_submit(None)
                    self.assertIs(front.screen_stack[-1], list_screen)
                    self.assertEqual(len(tasks.content.controls), 1)

                    row = tasks.content.controls[0]
                    edit = row.controls[-1].items[0] if repeating else row.controls[-2]
                    edit.on_click(None)
                    front.libs.entry_task.value = "Изменённое дело"
                    front.libs.entry_task.on_submit(None)
                    self.assertIs(front.screen_stack[-1], list_screen)
                    row = tasks.content.controls[0]
                    self.assertEqual(row.controls[0].controls[0].value, "Изменённое дело")
                    delete = row.controls[-1].items[1] if repeating else row.controls[-1]
                    delete.on_click(None)
                    read = front.back2.read_repeat_tasks if repeating else front.back2.read_postponed_tasks
                    self.assertEqual(read(), [])
                    self.assertEqual(tasks.content.controls, [])
                    back.on_click(None)
                    self.assertIs(front.screen_stack[-1], special_screen)
                    # Reopening creates fresh controls and reads current storage.
                    button.on_click(None)
                    self.assertEqual(self.form_content(front).content.controls[1].content.controls, [])
                    front.close_page()
                    hub_content.content.controls[-1].on_click(None)
                    self.assertIs(front.screen_stack[-1], settings_screen)

    def test_schedule_sections_keep_values_when_collapsed_and_saved(self):
        for phone in (False, True):
            for effect in ("none", "liquid_glass", "liquid_glass_half"):
                for repeating in (True, False):
                    with self.subTest(phone=phone, effect=effect, repeating=repeating):
                        front = make_front(phone=phone, effect=effect)
                        front._update_control = Mock()
                        target_group = front.back.create_group("Работа")
                        front.open_special_task_list(repeating)
                        opener = front.open_repeat_dialog if repeating else front.open_postponed_dialog
                        opener()
                        for editing in (False, True):
                            form = self.form_content(front)
                            tiles = [c for c in walk_controls(form) if isinstance(c, ft.ExpansionTile)]
                            title = "Настройки повторения" if repeating else "Настройки появления"
                            self.assertEqual([tile.title.controls[1].value.strip() for tile in tiles],
                                             [title, "Дополнительная информация", "Прикрепление файлов"])
                            tile = tiles[0]
                            self.assertTrue(tile.maintain_state)
                            self.assertFalse(tile.expanded)
                            tile.expanded = True
                            group_dropdown = next(c for c in walk_controls(tile)
                                                  if isinstance(c, ft.Dropdown) and c.label == "Группа дел")
                            self.assertEqual(group_dropdown.value, target_group if editing else "default")
                            group_dropdown.value = "default" if editing else target_group
                            front.libs.entry_task.value = "Изменено" if editing else "Новое дело"
                            if repeating:
                                front.libs.repeat_type_dd.value = "week"
                                front.libs.repeat_type_dd.on_select(None)
                                if editing:
                                    self.assertEqual([c.data for c in front.libs.weekday_checks if c.value], [2, 4])
                                for checkbox in front.libs.weekday_checks:
                                    checkbox.value = checkbox.data in [2, 4]
                            else:
                                field = next(c for c in walk_controls(tile)
                                             if isinstance(c, ft.TextField) and c.label == "Дата добавления")
                                if editing:
                                    self.assertEqual(field.value, "01-01-2030")
                                field.value = "02-01-2030" if editing else "01-01-2030"
                            tile.expanded = False
                            front.libs.prepare(front.screen_stack[-1])
                            page = ft.Page(sess=Mock())
                            page.views[0].controls = [front.screen_stack[-1]]
                            self.assertTrue(serialize(page, initial=True))
                            front.libs.entry_task.on_submit(None)
                            read = front.back2.read_repeat_tasks if repeating else front.back2.read_postponed_tasks
                            records = read()
                            self.assertEqual(len(records), 1)
                            self.assertEqual(records[0][0], "Изменено" if editing else "Новое дело")
                            self.assertEqual(records[0][3 if repeating else 2],
                                             "default" if editing else target_group)
                            self.assertEqual(records[0][2] if repeating else records[0][1],
                                             [2, 4] if repeating else ("02-01-2030" if editing else "01-01-2030"))
                            if not editing:
                                edit = front.open_edit_repeat_dialog if repeating else front.open_edit_postponed_dialog
                                edit(*records[0])

    def test_invalid_schedule_opens_collapsed_settings_on_create_and_edit(self):
        for phone in (False, True):
            for repeating in (True, False):
                for editing in (False, True):
                    with self.subTest(phone=phone, repeating=repeating, editing=editing):
                        front = make_front(phone=phone)
                        front._update_control = Mock()
                        front.open_special_task_list(repeating)
                        if editing:
                            if repeating:
                                front.back2.create_repeat_task("Дело", "week", [1])
                                front.open_edit_repeat_dialog(*front.back2.read_repeat_tasks()[0])
                            else:
                                front.back2.create_postponed_task("Дело", "01-01-2030")
                                front.open_edit_postponed_dialog(*front.back2.read_postponed_tasks()[0])
                        else:
                            (front.open_repeat_dialog if repeating else front.open_postponed_dialog)()
                        front.libs.entry_task.value = "Дело"
                        screen = front.screen_stack[-1]
                        tile = next(c for c in walk_controls(self.form_content(front))
                                    if isinstance(c, ft.ExpansionTile))
                        if repeating:
                            front.libs.repeat_type_dd.value = "week"
                            front.libs.repeat_type_dd.on_select(None)
                            for checkbox in front.libs.weekday_checks:
                                checkbox.value = False
                        else:
                            field = next(c for c in walk_controls(tile)
                                         if isinstance(c, ft.TextField) and c.label == "Дата добавления")
                            field.value = ""
                        before = front.back2._load()
                        self.assertFalse(tile.expanded)
                        front.libs.entry_task.on_submit(None)
                        self.assertTrue(tile.expanded)
                        self.assertIs(front.screen_stack[-1], screen)
                        self.assertEqual(front.back2._load(), before)
                        self.assertTrue(front.libs.weekday_error.visible if repeating else field.border_color)


if __name__ == "__main__":
    unittest.main()
