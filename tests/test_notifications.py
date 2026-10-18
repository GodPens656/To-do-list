import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from Backend.core import Backend
from Backend.extended import Backend2
from Backend.notifications import NotificationService
from Backend.webstorage import WebSessionStore
from Frontend.settings import Utils2


NOW = datetime.datetime(2026, 10, 17, 12)


class FrozenDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = {
            "notifications_enabled": True,
            "notification_interval": 15,
            "notification_important_enabled": True,
            "notification_deadline_enabled": True,
        }
        self.data = {
            "groups": [
                {"id": "default", "name": "Без группы"},
                {"id": "work", "name": "Работа"},
                {"id": "home", "name": "Дом"},
                {"id": "notes", "name": "Заметки", "type": "notes"},
            ],
            "tasks": [],
        }
        self.provider = Mock(side_effect=lambda: self.data)
        self.service = NotificationService(
            Mock(), False, lambda: self.settings, data_provider=self.provider,
        )
        self.service.show_desktop_notification = Mock()
        self.clock = patch("Backend.notifications.datetime.datetime", FrozenDatetime)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def add_task(self, group="work", **fields):
        self.data["tasks"].append({"group": group, "status": False, **fields})

    def bodies(self):
        return self.service._notification_bodies(self.settings, NOW)

    def test_one_notification_per_group_and_condition(self):
        for _ in range(3):
            self.add_task(priority="Очень важно", deadline="18-10-2026")
        self.add_task("home", priority="Очень важно")
        self.add_task("default", deadline="18-10-2026")
        expected = [
            'Скоро подойдёт дедлайн в делах группы "Без группы"',
            'Есть очень важные дела в группе "Работа"',
            'Скоро подойдёт дедлайн в делах группы "Работа"',
            'Есть очень важные дела в группе "Дом"',
        ]
        self.assertEqual(self.bodies(), expected)
        self.service._notify_desktop()
        self.assertEqual(self.service.show_desktop_notification.call_args_list,
                         [call("To-do", body) for body in expected])

    def test_conditions_are_independent(self):
        self.add_task(priority="Очень важно", deadline="18-10-2026")
        self.settings["notification_important_enabled"] = False
        self.assertEqual(self.bodies(), ['Скоро подойдёт дедлайн в делах группы "Работа"'])
        self.settings["notification_important_enabled"] = True
        self.settings["notification_deadline_enabled"] = False
        self.assertEqual(self.bodies(), ['Есть очень важные дела в группе "Работа"'])
        self.settings["notification_important_enabled"] = False
        self.provider.reset_mock()
        self.assertEqual(self.bodies(), [NotificationService.BODY])
        self.provider.assert_not_called()

    def test_ignores_completed_lower_priorities_notes_and_missing_groups(self):
        self.add_task(status=True, priority="Очень важно", deadline="18-10-2026")
        self.add_task(priority="Важно")
        self.add_task("notes", priority="Очень важно", deadline="18-10-2026")
        self.add_task("deleted", priority="Очень важно", deadline="18-10-2026")
        self.data["repeat_tasks"] = [{"group": "work", "priority": "Очень важно"}]
        self.data["postponed"] = [{"group": "work", "deadline": "18-10-2026"}]
        self.assertEqual(self.bodies(), [NotificationService.BODY])

    def test_deadline_is_tomorrow_only_and_invalid_dates_are_ignored(self):
        for deadline in (None, "", "invalid", "31-02-2026", "16-10-2026",
                         "17-10-2026", "19-10-2026"):
            self.add_task(deadline=deadline)
        self.assertEqual(self.bodies(), [NotificationService.BODY])
        self.add_task(deadline="18-10-2026")
        self.assertEqual(self.bodies(), ['Скоро подойдёт дедлайн в делах группы "Работа"'])
        check_dt = datetime.datetime(2026, 12, 31, 23, 59)
        self.data["tasks"] = [{"group": "home", "deadline": "01-01-2027"}]
        self.assertEqual(self.service._notification_bodies(self.settings, check_dt),
                         ['Скоро подойдёт дедлайн в делах группы "Дом"'])

    def test_desktop_reads_current_data_each_time(self):
        self.add_task(priority="Очень важно")
        self.service._notify_desktop()
        self.data["tasks"][0]["status"] = True
        self.service._notify_desktop()
        self.assertEqual(self.service.show_desktop_notification.call_args_list, [
            call("To-do", 'Есть очень важные дела в группе "Работа"'),
            call("To-do", NotificationService.BODY),
        ])

    def test_desktop_obeys_master_switch_and_quiet_hours(self):
        self.settings["notifications_enabled"] = False
        self.service._notify_desktop()
        self.settings.update(notifications_enabled=True, notification_quiet_enabled=True,
                             notification_quiet_start="11:00", notification_quiet_end="13:00")
        self.service._notify_desktop()
        self.service.show_desktop_notification.assert_not_called()

    def prepare_android(self, count=2):
        self.service.phone = True
        self.service.notifications = SimpleNamespace(cancel_all_notifications=AsyncMock())
        self.service._schedule_android_notification = AsyncMock()
        self.service.ANDROID_PRELOAD_COUNT = count

    async def test_android_schedules_all_groups_with_unique_ids_at_each_interval(self):
        self.prepare_android()
        self.add_task(priority="Очень важно")
        self.add_task("home", deadline="18-10-2026")
        await self.service.refresh_android_schedule()
        scheduled = self.service._schedule_android_notification.call_args_list
        self.assertEqual([args.args[0] for args in scheduled], [100000, 100001, 100002, 100003])
        self.assertEqual([args.args[1] for args in scheduled], [900, 900, 1800, 1800])
        self.assertEqual([args.args[3] for args in scheduled], self.bodies() * 2)
        self.service.notifications.cancel_all_notifications.assert_awaited_once()

    async def test_android_evaluates_deadline_at_delivery_date_after_quiet_hours(self):
        self.prepare_android()
        self.settings.update(notification_quiet_enabled=True, notification_quiet_start="12:00",
                             notification_quiet_end="08:00")
        self.add_task(deadline="18-10-2026")
        self.add_task("home", deadline="19-10-2026")
        await self.service.refresh_android_schedule()
        scheduled = self.service._schedule_android_notification.call_args_list
        self.assertEqual([args.args[3] for args in scheduled],
                         ['Скоро подойдёт дедлайн в делах группы "Дом"'] * 2)
        self.assertEqual(scheduled[0].args[1], 20 * 3600)

    async def test_android_clears_obsolete_reminders_after_completion_or_disabling(self):
        self.prepare_android(count=1)
        self.add_task(priority="Очень важно")
        await self.service.refresh_android_schedule()
        self.data["tasks"][0]["status"] = True
        await self.service.refresh_android_schedule()
        self.assertEqual(self.service._schedule_android_notification.call_args.args[3],
                         NotificationService.BODY)
        self.service._schedule_android_notification.reset_mock()
        self.settings["notifications_enabled"] = False
        await self.service.refresh_android_schedule()
        self.assertEqual(self.service.notifications.cancel_all_notifications.await_count, 3)
        self.service._schedule_android_notification.assert_not_awaited()
        self.assertIsNone(self.service.last_scheduled_at)

    def test_data_changes_refresh_android_and_web_stays_disabled(self):
        self.prepare_android()
        self.service.data_changed()
        self.service.page.run_task.assert_called_once_with(self.service.refresh_android_schedule)
        self.service.page.run_task.reset_mock()
        self.service.web = True
        self.service.data_changed()
        self.service.notify()
        self.service.reload_settings()
        self.service.page.run_task.assert_not_called()

    def test_backend_changes_and_undo_refresh_notifications(self):
        self.prepare_android()
        store = WebSessionStore(Mock())
        back = Backend(web_store=store, cloud=Mock())
        back.on_data_change = self.service.data_changed
        task_id = back.saveB("Задача", priority="Очень важно")
        back.redact_statusB(task_id, True)
        back.undo_last_action()
        self.assertEqual(self.service.page.run_task.call_count, 3)


class NotificationSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.back = Backend2.__new__(Backend2)
        self.back.web = False
        self.back.settings = Path(self.directory.name) / "settings.txt"
        self.back.set_default_settings()

    def test_new_options_default_to_false_and_survive_reload(self):
        for key in ("notification_important_enabled", "notification_deadline_enabled"):
            self.assertFalse(self.back.read_settings()[key])
            self.back.redact_setting(key, True)
        self.back.set_default_settings()
        reopened = Backend2.__new__(Backend2)
        reopened.web = False
        reopened.settings = self.back.settings
        for key in ("notification_important_enabled", "notification_deadline_enabled"):
            self.assertTrue(reopened.read_settings()[key])
            reopened.redact_setting(key, "False")
            self.assertFalse(reopened.read_settings()[key])

    def test_existing_settings_get_new_options_without_resetting_interval(self):
        self.back._settings_write({"notification_interval": "27", "notifications_enabled": "False"})
        self.back.set_default_settings()
        settings = self.back.read_settings()
        self.assertEqual(settings["notification_interval"], 27)
        self.assertFalse(settings["notifications_enabled"])
        self.assertFalse(settings["notification_important_enabled"])
        self.assertFalse(settings["notification_deadline_enabled"])

    def test_ui_switches_save_independently_and_request_schedule_refresh(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                utils = Utils2(Mock(), Mock(web=False, page=SimpleNamespace(width=360, height=800),
                                           get_device=Mock(return_value=phone)),
                               "light", self.back)
                reload_settings = Mock()
                panel = utils.build_widgets_for_notifications(Mock(), reload_settings)
                important, deadline = [row.controls[1] for row in panel.content.controls[2:4]]
                important.value = True
                important.on_change(None)
                deadline.value = True
                deadline.on_change(None)
                important.value = False
                important.on_change(None)
                self.assertFalse(self.back.read_settings()["notification_important_enabled"])
                self.assertTrue(self.back.read_settings()["notification_deadline_enabled"])
                self.assertEqual(reload_settings.call_count, 3)

    def test_browser_switches_remain_disabled(self):
        self.back.web = True
        self.back.store = WebSessionStore(Mock())
        self.back.set_default_settings()
        for key in ("notification_important_enabled", "notification_deadline_enabled"):
            self.back.redact_setting(key, True)
            self.assertFalse(self.back.read_settings()[key])
        utils = Utils2(Mock(), Mock(web=True, get_device=Mock(return_value=False)),
                       "light", self.back)
        panel = utils.build_widgets_for_notifications(Mock())
        for row in panel.content.controls[2:4]:
            self.assertTrue(row.controls[1].disabled)
            self.assertFalse(row.controls[1].value)


if __name__ == "__main__":
    unittest.main()
