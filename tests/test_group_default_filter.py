import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import flet as ft

from Backend.core import Backend
from Backend.extended import Backend2
from Backend.storage import save_all_sections
from Backend.webstorage import WebSessionStore
from Frontend.init_page import Front
from Frontend.libs import Fr_Libs


class GroupDefaultFilterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.back = Backend.__new__(Backend)
        self.back.web = False
        self.back.data_dir = Path(self.directory.name)
        save_all_sections(self.back.data_dir, {
            "groups": [
                {"id": "default", "name": "Без группы"},
                {"id": "work", "name": "Работа", "split_by_dates": False},
                {"id": "home", "name": "Дом"},
            ],
            "tasks": [{"id": "task", "group": "work", "name": "Дело"}],
        })
        self.back2 = Backend2.__new__(Backend2)
        self.back2.web = True
        self.back2.store = WebSessionStore(SimpleNamespace())
        self.back2.redact_setting("default_task_sort", "priority_desc")
        self.back2.redact_setting("default_task_status_sort", "incomplete_first")
        self.front = Front.__new__(Front)
        self.front.back = self.back
        self.front.back2 = self.back2
        self.front.current_group_id = "work"
        self.front.libs = Fr_Libs("light", False)
        self.front.TxtColor = self.front.libs.TxtColor
        self.front.BorderColor = self.front.libs.BorderColor
        self.front.cloud = Mock()
        self.front.close_page = Mock()
        self.front.open_page = Mock()
        self.front._rebuild_sorted_tasks = Mock()
        self.front._load_default_task_filter()

    def assert_filter(self, main, status):
        self.assertEqual(
            (self.front.current_sort, self.front.current_status_sort), (main, status)
        )

    def open_filter(self, main="deadline_asc", status="complete_first"):
        self.front.open_task_filter_dialog()
        content = self.front.open_page.call_args.args[1]
        controls = content.content.controls
        dropdowns = [control for control in controls if isinstance(control, ft.Dropdown)]
        dropdowns[0].value = main
        dropdowns[1].value = status
        return {
            button.content: button
            for row in controls if isinstance(row, ft.Row)
            for button in row.controls
        }

    def test_opening_groups_selects_their_defaults(self):
        self.back.set_group_default_filter("work", "deadline_asc", "complete_first")
        self.front.web = True
        self.front.phone = False
        self.front.main_cont = ft.Container()
        self.front._set_screen = Mock()
        self.front.render_daily_repeat_tasks = Mock()
        for group_id, expected in [
            ("work", ("deadline_asc", "complete_first")),
            ("home", ("priority_desc", "incomplete_first")),
            ("default", ("priority_desc", "incomplete_first")),
            ("work", ("deadline_asc", "complete_first")),
        ]:
            with self.subTest(group=group_id):
                column = ft.Column()
                group = next(g for g in self.back.get_groups() if g["id"] == group_id)
                self.front._append_group_row(column, group, Mock())
                column.controls[0].controls[0].on_click(None)
                self.assert_filter(*expected)

    def test_group_button_persists_disabled_override_and_preserves_other_data(self):
        before = self.back._load()
        self.open_filter("disabled", "disabled")["Сохранить для этой группы"].on_click(None)
        self.assert_filter(None, None)
        reopened = Backend.__new__(Backend)
        reopened.web = False
        reopened.data_dir = self.back.data_dir
        self.assertEqual(reopened.get_group_default_filter("work"), {
            "sort": "disabled", "status_sort": "disabled",
        })
        self.assertIsNone(reopened.get_group_default_filter("home"))
        self.assertFalse(reopened.get_group_settings("work")["split_by_dates"])
        self.assertEqual(before["tasks"], reopened.read_tasks())
        self.assertEqual(self.back2.read_settings()["default_task_sort"], "priority_desc")
        self.front.cloud.alg_for_redact.assert_called_once()

    def test_global_save_and_reset_keep_group_override(self):
        self.back.set_group_default_filter("work", "deadline_desc", "disabled")
        self.open_filter()["Сохранить общий фильтр"].on_click(None)
        self.assert_filter("deadline_desc", None)
        self.assertEqual(self.back2.read_settings()["default_task_sort"], "deadline_asc")
        self.open_filter()["Сбросить общий фильтр"].on_click(None)
        self.assert_filter("deadline_desc", None)
        self.front.current_group_id = "home"
        self.front._load_default_task_filter()
        self.assert_filter(None, None)

    def test_reset_group_uses_latest_global_default(self):
        self.back.set_group_default_filter("work", "disabled", "disabled")
        self.back2.redact_setting("default_task_sort", "deadline_desc")
        self.open_filter()["Использовать общий фильтр"].on_click(None)
        self.assertIsNone(self.back.get_group_default_filter("work"))
        self.assert_filter("deadline_desc", "incomplete_first")
        self.assertTrue(self.open_filter()["Использовать общий фильтр"].disabled)
        self.front._rebuild_sorted_tasks.assert_called_once()

    def test_apply_is_temporary_and_sorts_tasks(self):
        self.open_filter()["Применить"].on_click(None)
        self.assert_filter("deadline_asc", "complete_first")
        self.assertIsNone(self.back.get_group_default_filter("work"))
        tasks = [
            {"id": "late", "deadline": "09-09-2026", "status": True},
            {"id": "pending", "deadline": "01-09-2026", "status": False},
            {"id": "early", "deadline": "02-09-2026", "status": True},
        ]
        self.assertEqual(
            [task["id"] for task in self.front._sort_tasks(tasks)],
            ["early", "late", "pending"],
        )
        self.front._load_default_task_filter()
        self.assert_filter("priority_desc", "incomplete_first")

    def test_web_storage_round_trip(self):
        store = WebSessionStore(SimpleNamespace())
        store.save_all_sections(self.back._load())
        self.back.web = True
        self.back.store = store
        self.assertTrue(self.back.set_group_default_filter("default", "priority_asc", "disabled"))
        restored = WebSessionStore(SimpleNamespace())
        restored.replace_from_cloud(store.load_all_sections())
        self.back.store = restored
        self.front.current_group_id = "default"
        self.front._load_default_task_filter()
        self.assert_filter("priority_asc", None)
        self.back.reset_group_default_filter("default")
        self.front._load_default_task_filter()
        self.assert_filter("priority_desc", "incomplete_first")


if __name__ == "__main__":
    unittest.main()
