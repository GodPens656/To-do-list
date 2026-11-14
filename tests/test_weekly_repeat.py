import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import flet as ft

from Backend.extended import Backend2
from test_ui_performance import serialize
from test_ui_state import make_front


class WeeklyRepeatTests(unittest.TestCase):
    @staticmethod
    def select_days(front, days):
        for checkbox in front.libs.weekday_checks:
            checkbox.value = checkbox.data in days
            checkbox.on_change(None)

    def test_multiple_weekdays_persist_and_generate_once_on_each_selected_day(self):
        for web in (False, True):
            with self.subTest(web=web), tempfile.TemporaryDirectory() as directory:
                front = make_front()
                back = front.back2
                if not web:
                    for client in (front.back, back):
                        client.web = False
                        client.data_dir = Path(directory)
                with patch("Backend.extended.local_today", return_value=date(2026, 11, 8)):
                    ident = back.create_repeat_task("Тренировка", "week", [5, 1, 3, 3], metadata={
                        "info_type": "deadline", "deadline_days": 2,
                    })
                reopened = Backend2.__new__(Backend2)
                reopened.__dict__.update(back.__dict__)
                self.assertEqual(reopened.read_repeat_tasks()[0][2], [1, 3, 5])
                self.assertEqual(len(reopened._load()["repeat_tasks"]), 1)
                for day, due in ((9, True), (10, False), (11, True), (13, True),
                                 (15, False), (16, True)):
                    today = date(2026, 11, day)
                    with self.subTest(day=day), patch("Backend.extended.local_today", return_value=today):
                        tasks, _ = reopened.check_repeat_tasks()
                        self.assertEqual(len(tasks), int(due))
                        if due:
                            self.assertEqual(tasks[0][:2], ("Тренировка", "default"))
                            self.assertEqual(tasks[0][2]["deadline"], f"{day + 2:02d}-11-2026")
                        self.assertEqual(reopened.check_repeat_tasks()[0], [])
                self.assertEqual(reopened.read_repeat_tasks()[0][4], ident)

    def test_legacy_single_weekday_still_generates_and_opens_for_editing(self):
        for value in (4, "4"):
            with self.subTest(value=value):
                front = make_front()
                ident = front.back2.create_repeat_task("Старое дело", "week", 4)
                data = front.back2._load()
                data["repeat_tasks"][0].update(repeat_value=value, last_date="01-11-2026")
                front.back2._save(data)
                record = front.back2.read_repeat_tasks()[0]
                self.assertEqual(record[2], [4])
                front.open_edit_repeat_dialog(*record)
                self.assertEqual([c.data for c in front.libs.weekday_checks if c.value], [4])
                front.libs.entry_task.on_submit(None)
                self.assertEqual(front.back2.read_repeat_tasks()[0][4], ident)
                with patch("Backend.extended.local_today", return_value=date(2026, 11, 11)):
                    self.assertEqual(front.back2.check_repeat_tasks()[0], [])
                with patch("Backend.extended.local_today", return_value=date(2026, 11, 12)):
                    self.assertEqual(len(front.back2.check_repeat_tasks()[0]), 1)
                self.assertEqual(front.utils2._describe_repeat_rule("week", value),
                                 "каждую неделю по четвергам")

    def test_calendar_projects_all_selected_weekdays_and_relative_deadlines(self):
        front = make_front()
        with patch("Backend.extended.local_today", return_value=date(2026, 11, 8)):
            front.back2.create_repeat_task("Отчёт", "week", [1, 3, 5], metadata={
                "info_type": "deadline", "deadline_days": 2,
            })
            before = front.back2._load()
            events = front.back2.read_schedule(date(2026, 11, 9), date(2026, 11, 15))
        repeats = [day for day, entries in events.items() if any(e.kind == "repeat" for e in entries)]
        deadlines = [day for day, entries in events.items() if any(e.kind == "deadline" for e in entries)]
        self.assertEqual(sorted(repeats), [date(2026, 11, day) for day in (9, 11, 13)])
        self.assertEqual(sorted(deadlines), [date(2026, 11, day) for day in (11, 13, 15)])
        self.assertEqual(front.back2._load(), before)

    def test_creation_requires_a_day_and_saves_multiple_days_on_desktop_and_phone(self):
        for phone in (False, True):
            for effect in ("none", "liquid_glass_half"):
                with self.subTest(phone=phone, effect=effect):
                    front = make_front(phone=phone, effect=effect)
                    front._update_control = Mock()
                    front.open_repeat_dialog(name="Тренировка")
                    form = front.screen_stack[-1]
                    self.assertFalse(front.libs.weekday_picker.visible)
                    front.libs.repeat_type_dd.value = "week"
                    front.libs.repeat_type_dd.on_select(None)
                    self.assertTrue(front.libs.weekday_picker.visible)
                    self.select_days(front, [])
                    front.libs.entry_task.on_submit(None)
                    self.assertTrue(front.libs.weekday_error.visible)
                    self.assertEqual(front.back2.read_repeat_tasks(), [])
                    self.assertIs(front.screen_stack[-1], form)
                    self.select_days(front, [1, 3, 5])
                    self.assertFalse(front.libs.weekday_error.visible)
                    front.libs.btn_create_task.on_click(None)
                    self.assertEqual(front.back2.read_repeat_tasks()[0][:4],
                                     ("Тренировка", "week", [1, 3, 5], "default"))
                    self.assertEqual(front.utils2._describe_repeat_rule("week", [1, 3, 5]),
                                     "каждую неделю по понедельникам, средам и пятницам")

    def test_editing_keeps_selection_and_metadata_and_rejects_empty_selection(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front._update_control = Mock()
                ident = front.back2.create_repeat_task("Повтор", "week", [1, 3, 5], metadata={
                    "info_type": "priority", "priority": "Важно",
                })
                front.back2.set_repeat_task_disabled(ident)
                front.open_edit_repeat_dialog(*front.back2.read_repeat_tasks()[0])
                self.assertEqual([c.data for c in front.libs.weekday_checks if c.value], [1, 3, 5])
                for kind in ("day", "week"):
                    front.libs.repeat_type_dd.value = kind
                    front.libs.repeat_type_dd.on_select(None)
                    self.assertEqual(front.libs.weekday_picker.visible, kind == "week")
                    self.assertEqual([c.data for c in front.libs.weekday_checks if c.value], [1, 3, 5])
                before = front.back2._load()
                self.select_days(front, [])
                front.libs.entry_task.on_submit(None)
                self.assertTrue(front.libs.weekday_error.visible)
                self.assertEqual(front.back2._load(), before)
                self.select_days(front, [2, 4])
                front.libs.entry_task.on_submit(None)
                record = front.back2.read_repeat_tasks()[0]
                self.assertEqual(record[2], [2, 4])
                self.assertEqual(record[4], ident)
                self.assertTrue(record[-1]["disabled"])
                self.assertEqual(record[-1]["priority"], "Важно")
                front.open_edit_repeat_dialog(*record)
                self.assertEqual([c.data for c in front.libs.weekday_checks if c.value], [2, 4])

    def test_weekday_controls_serialize_with_each_theme_effect(self):
        for phone in (False, True):
            for effect in ("none", "liquid_glass", "liquid_glass_half"):
                with self.subTest(phone=phone, effect=effect):
                    front = make_front(phone=phone, effect=effect)
                    front._update_control = Mock()
                    front.open_repeat_dialog(name="Повтор")
                    front.libs.repeat_type_dd.value = "week"
                    front.libs.repeat_type_dd.on_select(None)
                    self.select_days(front, [1, 3, 5])
                    front.libs.prepare(front.screen_stack[-1])
                    page = ft.Page(sess=Mock())
                    page.views[0].controls = [front.screen_stack[-1]]
                    self.assertTrue(serialize(page, initial=True))
                    self.assertEqual([c.data for c in front.libs.weekday_checks if c.value], [1, 3, 5])


if __name__ == "__main__":
    unittest.main()
