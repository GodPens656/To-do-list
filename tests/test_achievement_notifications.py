import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

import flet as ft

from Backend.core import local_today
from test_ui_state import make_front, task_menu


def notification_text(front):
    snackbars = [call.args[0] for call in front.page.show_dialog.call_args_list
                 if isinstance(call.args[0], ft.SnackBar)]
    text = []
    for snackbar in snackbars:
        pending = [snackbar.content]
        while pending:
            control = pending.pop()
            if isinstance(control, ft.Text):
                text.append(control.value)
            pending.extend(getattr(control, "controls", []))
    return snackbars, "\n".join(text)


class AchievementNotificationTests(unittest.TestCase):
    def test_checkbox_completion_uncheck_and_undo_on_desktop_and_phone(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                task_id = front.back.saveB("Сделать")
                front.render_daily_repeat_tasks()
                front._update_control = Mock()
                front.page.show_dialog.assert_not_called()
                card = next(c for c in front.tasks_cont.content.controls if c.key == task_id)
                checkbox = next(c for c in card.content.controls if isinstance(c, ft.Checkbox))
                checkbox.value = True
                checkbox.on_change(None)
                snackbars, text = notification_text(front)
                self.assertEqual(len(snackbars), 1)
                self.assertIn("Первый шаг", text)
                self.assertIn("+10 баллов · Всего: 10", text)
                snackbars[-1].on_dismiss(None)

                front.page.show_dialog.reset_mock()
                checkbox.value = False
                checkbox.on_change(None)
                self.assertIn("-10 баллов · Всего: 0", notification_text(front)[1])
                notification_text(front)[0][-1].on_dismiss(None)

                front.page.show_dialog.reset_mock()
                front.undo_last_action()
                self.assertIn("+10 баллов · Всего: 10", notification_text(front)[1])

    def test_multiple_awards_are_included_in_one_notification(self):
        front = make_front(phone=True)
        today = local_today(True, front.page)
        data = front.back._load()
        data["achievements"] = [
            {"task_id": f"previous-{i}",
             "date": (today - timedelta(days=1 if i == 8 else 2)).isoformat()}
            for i in range(9)
        ]
        front.web_store.save_all_sections(data)
        task_id = front.back.saveB("Продолжить серию")
        front.back.redact_statusB(task_id, True)
        snackbars, text = notification_text(front)
        self.assertEqual(len(snackbars), 1)
        self.assertIn("В хорошем темпе", text)
        self.assertIn("Искра привычки", text)
        self.assertIn("+10 баллов · Всего: 100", text)
        self.assertNotIn("Первый шаг", text)

    def test_rapid_changes_wait_for_the_previous_notification_to_dismiss(self):
        front = make_front()
        first = front.back.saveB("Первое")
        second = front.back.saveB("Второе")
        front.back.redact_statusB(first, True)
        front.back.redact_statusB(second, True)
        front.back.redact_statusB(second, False)
        snackbars, text = notification_text(front)
        self.assertEqual(len(snackbars), 1)
        self.assertIn("Первый шаг", text)
        snackbars[0].on_dismiss(None)
        self.assertIn("+10 баллов · Всего: 20", notification_text(front)[1])
        notification_text(front)[0][-1].on_dismiss(None)
        self.assertIn("-10 баллов · Всего: 10", notification_text(front)[1])
        self.assertEqual(len(notification_text(front)[0]), 3)
        notification_text(front)[0][-1].on_dismiss(None)
        self.assertEqual(len(notification_text(front)[0]), 3)

    def test_no_notifications_for_noops_edits_deletion_or_reopening(self):
        front = make_front()
        task_id = front.back.saveB("Сделать")
        front.back.redact_statusB(task_id, True)
        front.page.show_dialog.reset_mock()
        front.back.redact_statusB(task_id, True)
        front.back.redact_statusB("missing", True)
        front.back.redact_taskB(task_id, "Новое название")
        front.render_daily_repeat_tasks()
        front.open_achievements()
        front.close_page()
        front.back.kill_taskB(task_id)
        front.page.show_dialog.assert_not_called()

    def test_reset_discards_old_notifications_without_dismissing_future_awards(self):
        front = make_front()
        front._update_control = Mock()
        first = front.back.saveB("Первое")
        second = front.back.saveB("Второе")
        front.back.redact_statusB(first, True)
        front.back.redact_statusB(second, True)
        notifications = front._achievement_notifications
        old = notifications.active
        self.assertTrue(notifications.pending)
        front.open_achievements()
        front.achievements_view.reset_button.on_click(None)
        front.page.show_dialog.call_args.args[0].actions[-1].on_click(None)
        self.assertIsNone(notifications.active)
        self.assertFalse(notifications.pending)
        self.assertFalse(old.open)
        self.assertEqual(front.back.get_achievements()["points"], 0)

        third = front.back.saveB("После сброса")
        front.back.redact_statusB(third, True)
        current = notifications.active
        self.assertIsNotNone(current)
        old.on_dismiss(None)
        self.assertIs(notifications.active, current)
        self.assertEqual(front.back.get_achievements()["points"], 10)

    def test_import_and_reset_report_actual_points_change(self):
        front = make_front()
        task_id = front.back.saveB("Сделать")
        front.back.redact_statusB(task_id, True)
        archive = front.back.export_data_archive()
        notification_text(front)[0][-1].on_dismiss(None)
        front.back.redact_statusB(task_id, False)
        notification_text(front)[0][-1].on_dismiss(None)
        front.page.show_dialog.reset_mock()
        front.back.import_data_archive(archive)
        self.assertIn("+10 баллов · Всего: 10", notification_text(front)[1])
        notification_text(front)[0][-1].on_dismiss(None)
        front.page.show_dialog.reset_mock()
        front.back.delete_all()
        self.assertIn("-10 баллов · Всего: 0", notification_text(front)[1])

    def test_failed_save_does_not_announce_points_or_awards(self):
        front = make_front()
        task_id = front.back.saveB("Сделать")
        with patch.object(front.web_store, "save_all_sections", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                front.back.redact_statusB(task_id, True)
        front.page.show_dialog.assert_not_called()
        self.assertEqual(front.back.get_achievements()["points"], 0)


class TaskCharacterTests(unittest.TestCase):
    def test_create_edit_and_reload_titles_with_legacy_delimiters(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front._update_control = Mock()
                front.button_add_task.on_click(None)
                front.entry_task.value = "План | заметки --- на сегодня"
                front.create_task.on_click(None)
                task = front.back.read_tasks()[0]
                self.assertEqual(task["name"], "План | заметки --- на сегодня")
                front.render_daily_repeat_tasks()
                card = next(c for c in front.tasks_cont.content.controls if c.key == task["id"])
                task_menu(card).items[0].on_click(None)
                front.libs.entry_task.value = "Новый план --- итог | завтра"
                front.libs.entry_task.on_submit(None)
                front.render_daily_repeat_tasks()
                self.assertEqual(front.back.read_name(task["id"]), "Новый план --- итог | завтра")
                self.assertTrue(any(c.data == "Новый план --- итог | завтра"
                                    for c in front.tasks_cont.content.controls))
                front.page.show_dialog.assert_not_called()


if __name__ == "__main__":
    unittest.main()
