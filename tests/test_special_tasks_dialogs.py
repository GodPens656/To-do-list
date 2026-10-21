import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import flet as ft

from Backend.extended import Backend2
from Backend.webstorage import WebSessionStore
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
                        next(c for c in form.content.controls
                             if isinstance(c, ft.TextField) and c.label == "Дата добавления").value = "01-01-2030"
                    entry.on_submit(None)
                    self.assertIs(front.screen_stack[-1], list_screen)
                    self.assertEqual(len(tasks.content.controls), 1)

                    row = tasks.content.controls[0]
                    edit = row.controls[-1].items[1] if repeating else row.controls[-2]
                    edit.on_click(None)
                    front.libs.entry_task.value = "Изменённое дело"
                    front.libs.entry_task.on_submit(None)
                    self.assertIs(front.screen_stack[-1], list_screen)
                    row = tasks.content.controls[0]
                    self.assertEqual(row.controls[0].controls[0].value, "Изменённое дело")
                    delete = row.controls[-1].items[0] if repeating else row.controls[-1]
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


if __name__ == "__main__":
    unittest.main()
