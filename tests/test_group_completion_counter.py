import tempfile
import unittest
from itertools import product
from pathlib import Path
from types import SimpleNamespace

from Backend.core import Backend
from Backend.json_migration import load_data_from_dict
from Backend.webstorage import WebSessionStore


class GroupDisplayPreferenceTests(unittest.TestCase):
    def test_preference_survives_reload_without_changing_other_group_data(self):
        for web, setting in product((False, True), ("show_completion_counter", "show_group_title")):
            with self.subTest(web=web, setting=setting), tempfile.TemporaryDirectory() as directory:
                back = Backend.__new__(Backend)
                back.web = web
                back.data_dir = Path(directory)
                back.store = WebSessionStore(SimpleNamespace())
                back._save({
                    "groups": [
                        {"id": "default", "name": "Без группы"},
                        {"id": "work", "name": "Работа", "split_by_dates": False,
                         "default_task_filter": {"sort": "priority_desc", "status_sort": "disabled"}},
                    ],
                    "tasks": [{"id": "task", "name": "Дело", "group": "work"}],
                })
                self.assertTrue(back.get_group_settings("work")[setting])
                before = back._load()
                self.assertTrue(back.update_group_settings("work", **{setting: False}))
                restored = Backend.__new__(Backend)
                restored.web = web
                restored.data_dir = Path(directory)
                restored.store = WebSessionStore(SimpleNamespace())
                restored.store.replace_from_cloud(back._load())
                self.assertFalse(restored.get_group_settings("work")[setting])
                self.assertTrue(restored.get_group_settings("default")[setting])
                self.assertEqual(restored._load()["tasks"], before["tasks"])
                self.assertFalse(restored.get_group_settings("work")["split_by_dates"])
                self.assertEqual(restored.get_group_default_filter("work"), back.get_group_default_filter("work"))
                new_id = restored.create_group("Новая группа")
                self.assertTrue(restored.get_group_settings(new_id)[setting])
                restored.update_group_settings("work", show_created_date=False)
                self.assertFalse(restored.get_group_settings("work")[setting])
                restored.update_group_settings("work", **{setting: True})
                self.assertTrue(restored.get_group_settings("work")[setting])

    def test_migration_enables_legacy_groups_and_preserves_explicit_false(self):
        data = load_data_from_dict({"groups": [
            {"id": "legacy", "name": "Старая группа"},
            {"id": "hidden", "name": "Без счётчика", "show_completion_counter": False,
             "show_group_title": False},
        ]})
        groups = {group["id"]: group for group in data["groups"]}
        self.assertTrue(groups["default"]["show_completion_counter"])
        self.assertTrue(groups["legacy"]["show_completion_counter"])
        self.assertFalse(groups["hidden"]["show_completion_counter"])
        self.assertTrue(groups["default"]["show_group_title"])
        self.assertTrue(groups["legacy"]["show_group_title"])
        self.assertFalse(groups["hidden"]["show_group_title"])


if __name__ == "__main__":
    unittest.main()
