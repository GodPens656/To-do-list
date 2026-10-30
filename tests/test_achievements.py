import asyncio
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from Backend.achievements import achievement_summary
from Backend.core import Backend, local_today
from Backend.crypto import is_encrypted, read_text
from Backend.storage import empty_data, ensure_split_storage, load_all_sections, save_all_sections
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front


class AchievementStorageTests(unittest.TestCase):
    def setUp(self):
        self.page = SimpleNamespace(_nd_timezone="Europe/Moscow")
        self.store = WebSessionStore(self.page)
        self.back = Backend(page=self.page, web_store=self.store, cloud=Mock())
        self.today = date(2026, 10, 30)
        clock = patch("Backend.core.local_today", return_value=self.today)
        self.clock = clock.start()
        self.addCleanup(clock.stop)

    def complete(self, title="Дело", day=None, **kwargs):
        self.clock.return_value = day or self.today
        task_id = self.back.saveB(title, **kwargs)
        self.back.redact_statusB(task_id, True)
        return task_id

    def test_points_noop_uncheck_and_recheck(self):
        task_id = self.complete()
        self.assertEqual(self.back.get_achievements()["points"], 10)
        original = self.back._load()
        self.back.redact_statusB(task_id, True)
        self.back.redact_statusB("missing", True)
        self.assertEqual(self.back._load(), original)
        self.back.redact_statusB(task_id, False)
        self.assertEqual(self.back.get_achievements()["points"], 0)
        self.assertEqual(self.back.get_achievements()["current_streak"], 0)
        self.complete("Другое дело")
        self.back.redact_statusB(task_id, True)
        self.assertEqual(self.back.get_achievements()["points"], 20)
        self.assertEqual(self.back.get_achievements()["current_streak"], 1)

    def test_daily_streak_grace_period_gap_restart_and_earned_awards(self):
        for offset in range(7):
            self.complete(day=self.today - timedelta(days=6 - offset))
        progress = self.back.get_achievements()
        self.assertEqual((progress["current_streak"], progress["best_streak"]), (7, 7))
        self.assertEqual(progress["points"], 70)
        self.assertTrue(next(a for a in progress["awards"] if a["id"] == "streak_7")["unlocked"])
        self.clock.return_value = self.today + timedelta(days=1)
        self.assertEqual(self.back.get_achievements()["current_streak"], 7)
        self.assertFalse(self.back.get_achievements()["completed_today"])
        self.clock.return_value += timedelta(days=1)
        self.assertEqual(self.back.get_achievements()["current_streak"], 0)
        self.complete(day=self.clock.return_value)
        progress = self.back.get_achievements()
        self.assertEqual((progress["current_streak"], progress["best_streak"]), (1, 7))
        self.assertEqual(progress["unlocked_count"], 3)

    def test_unchecking_only_completion_revokes_day_but_other_completions_preserve_it(self):
        first = self.complete()
        second = self.complete()
        self.back.redact_statusB(first, False)
        self.assertTrue(self.back.get_achievements()["completed_today"])
        self.back.redact_statusB(second, False)
        self.assertFalse(self.back.get_achievements()["completed_today"])

    def test_deletion_preserves_progress_and_undo_restores_exact_snapshots(self):
        task_id = self.complete()
        completed = self.back._load()
        self.back.kill_taskB(task_id)
        self.assertEqual(self.back.get_achievements()["points"], 10)
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), completed)
        self.back.redact_statusB(task_id, False)
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), completed)
        self.back.redact_statusB(task_id, False)
        incomplete = self.back._load()
        self.back.redact_statusB(task_id, True)
        # Opening achievements must not replace the undo slot.
        self.back.get_achievements()
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), incomplete)

    def test_legacy_completions_receive_points_without_fabricating_streak(self):
        data = empty_data()
        data["tasks"] = [{"id": "old", "status": True, "created_date": "30-10-2026"}]
        self.store.replace_from_cloud(data)
        progress = self.back.get_achievements()
        self.assertEqual(progress["points"], 10)
        self.assertEqual(progress["current_streak"], 0)
        self.back.kill_taskB("old")
        self.assertEqual(self.back.get_achievements()["points"], 10)

    def test_repeating_instances_and_other_groups_contribute_to_same_progress(self):
        group = self.back.create_group("Работа")
        self.complete("Ежедневное", is_repeat=True)
        self.complete("Ежедневное", is_repeat=True, group_id=group)
        self.assertEqual(self.back.get_achievements()["points"], 20)
        self.assertEqual(self.back.get_achievements()["today_count"], 2)

    def test_native_restart_keeps_encrypted_progress_and_upgrade_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            legacy = data_dir / "itog.json"
            # Stale legacy data must not overwrite the four existing sections.
            legacy.write_text(json.dumps(empty_data()), encoding="utf-8")
            current = empty_data()
            current.pop("achievements")
            current["tasks"] = [{"id": "keep", "status": False}]
            save_all_sections(data_dir, current)
            ensure_split_storage(data_dir, legacy)
            self.assertEqual(load_all_sections(data_dir)["tasks"], current["tasks"])
            back = Backend.__new__(Backend)
            back.web = False
            back.page = self.page
            back.data_dir = data_dir
            back.redact_statusB("keep", True)
            raw = (data_dir / "achievements.json").read_bytes()
            self.assertTrue(is_encrypted(raw))
            self.assertEqual(json.loads(read_text(data_dir / "achievements.json")),
                             [{"task_id": "keep", "date": "2026-10-30"}])
            restored = Backend.__new__(Backend)
            restored.web = False
            restored.data_dir = data_dir
            self.assertEqual(restored.get_achievements()["points"], 10)
            self.assertEqual(restored.get_achievements()["current_streak"], 1)
            self.assertFalse(ensure_split_storage(data_dir, legacy))

    def test_browser_preferences_round_trip_keeps_history(self):
        self.complete()
        preferences = {}
        self.page.shared_preferences = SimpleNamespace(
            set=lambda key, value: preferences.__setitem__(key, value),
            get=preferences.get,
        )
        asyncio.run(self.store._persist_async())
        restored = WebSessionStore(self.page)
        asyncio.run(restored.load())
        self.assertEqual(restored.load_all_sections(), self.back._load())

    def test_malformed_duplicate_and_future_dates_do_not_inflate_streak(self):
        data = empty_data()
        data["achievements"] = [None, {}, {"task_id": "a", "date": "bad"},
                                {"task_id": "a", "date": "2026-10-30"},
                                {"task_id": "b", "date": "2026-11-01"}]
        progress = achievement_summary(data, self.today)
        self.assertEqual(progress["points"], 20)
        self.assertEqual(progress["current_streak"], 0)

    def test_client_date_independent_of_server_timezone(self):
        from datetime import datetime, timezone
        instant = datetime(2026, 10, 30, 21, 1, tzinfo=timezone.utc)
        self.clock.side_effect = local_today
        with patch("Backend.core.datetime", wraps=datetime) as client_clock:
            client_clock.now.side_effect = lambda tz=None: instant.astimezone(tz)
            for zone, expected in (("Europe/Moscow", "2026-10-31"),
                                   ("America/Los_Angeles", "2026-10-30")):
                with self.subTest(zone=zone):
                    self.page._nd_timezone = zone
                    task_id = self.back.saveB("Перед сном")
                    self.back.redact_statusB(task_id, True)
                    entry = next(item for item in self.back._load()["achievements"]
                                 if item["task_id"] == task_id)
                    self.assertEqual(entry["date"], expected)
                    self.assertTrue(self.back.get_achievements()["completed_today"])


class AchievementUITests(unittest.TestCase):
    def test_settings_navigation_fresh_progress_and_back_on_desktop_and_phone(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.open_settings()
                settings_screen = front.screen_stack[-1]
                button = next(c for c in front.settings_cont.content.controls
                              if isinstance(c, ft.Button) and isinstance(c.content, ft.Row)
                              and any(isinstance(t, ft.Text) and t.value.strip() == "Достижения"
                                      for t in c.content.controls))
                button.on_click(None)
                self.assertEqual(front.achievements_view.progress["points"], 0)
                front.achievements_view.back.on_click(None)
                self.assertIs(front.screen_stack[-1], settings_screen)
                front.close_page()
                task_id = front.back.saveB("Сделать")
                front.back.redact_statusB(task_id, True)
                front.open_settings()  # Reuses the cached web settings screen.
                button.on_click(None)
                self.assertEqual(front.achievements_view.progress["points"], 10)
                self.assertTrue(front.achievements_view.progress["completed_today"])
                self.assertEqual(len(front.achievements_view.progress["week"]), 7)


if __name__ == "__main__":
    unittest.main()
