import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import flet as ft

from Backend.extended import Backend2
from Backend.crypto import read_text
from test_ui_state import make_front


class RepeatTaskDisabledTests(unittest.TestCase):
    def test_disabled_rules_persist_and_skip_every_schedule_until_enabled(self):
        today = date(2026, 10, 20)
        rules = (("day", 1), ("day", 3), ("week", 2), ("month", 20), ("year", "20-10"))
        for web in (False, True):
            with self.subTest(web=web), tempfile.TemporaryDirectory() as directory:
                front = make_front()
                back, back2 = front.back, front.back2
                if not web:
                    for client in (back, back2):
                        client.web = False
                        client.data_dir = Path(directory)
                with patch("Backend.extended.local_today", return_value=today):
                    ids = [back2.create_repeat_task("Повтор", kind, value) for kind, value in rules]
                    before = back2._load()
                    for item in before["repeat_tasks"]:
                        # Old rules without the new field must remain active.
                        item.pop("disabled")
                        item["last_date"] = "01-01-2000"
                    back2._save(before)
                    for ident in ids:
                        self.assertTrue(back2.set_repeat_task_disabled(ident))
                    self.assertTrue(all(item[-1]["disabled"] for item in back2.read_repeat_tasks()))
                    if not web:
                        self.assertIn('"disabled": true', read_text(Path(directory) / "repeat_tasks.json"))
                    # Load through a new backend instance to check persistence.
                    restored = Backend2.__new__(Backend2)
                    restored.__dict__.update(back2.__dict__)
                    self.assertEqual(restored.check_repeat_tasks()[0], [])
                    self.assertTrue(all(item["last_date"] == "01-01-2000"
                                        for item in restored._load()["repeat_tasks"]))
                    for ident, (kind, value) in zip(ids, rules):
                        restored.update_repeat_task(ident, "Изменено", kind, value, "default", {"priority": "Важно"})
                    self.assertEqual(restored.check_repeat_tasks()[0], [])
                    for ident in ids:
                        self.assertTrue(restored.set_repeat_task_disabled(ident, False))
                    self.assertEqual(len(restored.check_repeat_tasks()[0]), len(rules))
                    self.assertEqual(restored.check_repeat_tasks()[0], [])

    def test_legacy_rules_are_active_and_missing_id_does_not_change_data(self):
        front = make_front()
        ident = front.back2.create_repeat_task("Повтор")
        data = front.back2._load()
        data["repeat_tasks"][0].pop("disabled")
        data["repeat_tasks"][0]["last_date"] = "01-01-2000"
        front.back2._save(data)
        self.assertFalse(front.back2.read_repeat_tasks()[0][-1]["disabled"])
        self.assertFalse(front.back2.set_repeat_task_disabled("missing"))
        self.assertEqual(front.back2._load(), data)
        self.assertEqual(len(front.back2.check_repeat_tasks()[0]), 1)
        self.assertEqual(front.back2.read_repeat_tasks()[0][4], ident)

    def test_menu_toggles_status_and_restores_additional_info_after_reopening(self):
        for phone in (False, True):
            for separate in (False, True):
                with self.subTest(phone=phone, separate=separate):
                    front = make_front(phone=phone)
                    ident = front.back2.create_repeat_task("Повтор", metadata={"info_type": "priority", "priority": "Важно"})
                    front.back2.redact_setting("special_tasks_separate_dialogs", separate)
                    front.open_settings()
                    front.settings_cont.content.controls[0].on_click(None)
                    if separate:
                        front.open_special_task_list(True)
                    container = front.utils2.cont_with_repeat_task.content
                    row = container.controls[0]
                    self.assertEqual(len(row.controls), 2)
                    menu = row.controls[-1]
                    self.assertIsInstance(menu, ft.PopupMenuButton)
                    self.assertEqual([item.content for item in menu.items], ["Удалить", "Редактировать", "Отключить"])
                    self.assertTrue(all(item.icon for item in menu.items))
                    toggle = menu.items[2]
                    toggle.on_click(None)
                    self.assertTrue(front.back2.read_repeat_tasks()[0][-1]["disabled"])
                    extra = row.controls[0].controls[2]
                    self.assertEqual(extra.value, "Дело отключено")
                    self.assertEqual(extra.color, ft.Colors.YELLOW_700)
                    self.assertEqual(toggle.content, "Включить")
                    # Refresh from saved state, as happens when reopening the dialog.
                    container.controls.clear()
                    front.utils2.read_repeat_tasks_and_add_to_cont()
                    row = container.controls[0]
                    self.assertEqual(row.controls[0].controls[2].value, "Дело отключено")
                    front.utils2.on_edit_repeat = Mock()
                    row.controls[-1].items[1].on_click(None)
                    self.assertEqual(front.utils2.on_edit_repeat.call_args.args[4], ident)
                    row.controls[-1].items[2].on_click(None)
                    self.assertEqual(row.controls[0].controls[2].value, "Важность: Важно")
                    self.assertEqual(row.controls[-1].items[2].content, "Отключить")
                    self.assertFalse(front.back2.read_repeat_tasks()[0][-1]["disabled"])


if __name__ == "__main__":
    unittest.main()
