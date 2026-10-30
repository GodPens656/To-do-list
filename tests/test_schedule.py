import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

import flet as ft

from test_ui_state import make_front


TODAY = date(2026, 10, 29)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.front = make_front()
        self.back = self.front.back
        self.back2 = self.front.back2
        self.clock = patch("Backend.extended.local_today", return_value=TODAY)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def read(self, start=date(2026, 10, 1), end=date(2026, 11, 30), group_id=None):
        return self.back2.read_schedule(start, end, group_id)

    def dates(self, name, **kwargs):
        return [day for day, entries in sorted(self.read(**kwargs).items())
                if any(entry.name == name for entry in entries)]

    def test_deadlines_use_due_date_including_completed_and_other_groups(self):
        other = self.back.create_group("Работа")
        ident = self.back.saveB("Сдать отчёт", other, created_date="01-10-2026",
                                deadline="30-10-2026", info_type="deadline")
        self.back.redact_statusB(ident, True)
        self.back.saveB("Без срока")
        self.assertEqual(self.dates("Сдать отчёт"), [date(2026, 10, 30)])
        self.assertEqual(self.read(group_id="default"), {})
        entry = self.read()[date(2026, 10, 30)][0]
        self.assertTrue(entry.completed)
        self.assertEqual(entry.group, other)
        self.assertEqual(entry.kind, "deadline")

    def test_postponed_and_its_relative_deadline_can_cross_month_boundary(self):
        self.back2.create_postponed_task("Подготовить документы", "31-10-2026", metadata={
            "info_type": "deadline", "deadline_days": 3,
        })
        events = self.read()
        self.assertEqual(events[date(2026, 10, 31)][0].kind, "postponed")
        self.assertEqual(events[date(2026, 11, 3)][0].kind, "deadline")
        self.assertEqual(len(events), 2)

    def test_all_repeat_rules_and_disabled_rules(self):
        for name, kind, value in (("Интервал", "day", 3), ("Понедельник", "week", 1),
                                  ("Конец месяца", "month", 31), ("Годовщина", "year", "05-11")):
            self.back2.create_repeat_task(name, kind, value)
        disabled = self.back2.create_repeat_task("Отключено")
        self.back2.set_repeat_task_disabled(disabled)
        start, end = date(2026, 10, 30), date(2026, 11, 8)
        period = dict(start=start, end=end)
        self.assertEqual(self.dates("Интервал", **period), [date(2026, 11, 1), date(2026, 11, 4), date(2026, 11, 7)])
        self.assertEqual(self.dates("Понедельник", **period), [date(2026, 11, 2)])
        self.assertEqual(self.dates("Конец месяца", **period), [date(2026, 10, 31)])
        self.assertEqual(self.dates("Годовщина", **period), [date(2026, 11, 5)])
        self.assertEqual(self.dates("Отключено", **period), [])

    def test_overdue_daily_rule_restarts_today_and_view_does_not_mutate_storage(self):
        self.back2.create_repeat_task("Раз в три дня", "day", 3)
        data = self.back2._load()
        data["repeat_tasks"][0].update(last_date="20-10-2026", created_date="01-10-2026")
        self.back2._save(data)
        undo = self.back._undo_state
        with patch.object(self.back2, "_save") as save:
            days = self.dates("Раз в три дня", start=TODAY, end=date(2026, 11, 4))
        self.assertEqual(days, [TODAY, date(2026, 11, 1), date(2026, 11, 4)])
        save.assert_not_called()
        self.assertEqual(self.back2._load(), data)
        self.assertIs(self.back._undo_state, undo)

    def test_invalid_month_dates_and_leap_days_do_not_roll_forward(self):
        self.back2.create_repeat_task("31 число", "month", 31)
        self.back2.create_repeat_task("29 февраля", "year", "29-02")
        february = dict(start=date(2027, 2, 1), end=date(2027, 3, 2))
        self.assertEqual(self.dates("31 число", **february), [])
        self.assertEqual(self.dates("29 февраля", **february), [])
        self.assertEqual(self.dates("29 февраля", start=date(2028, 2, 1), end=date(2028, 3, 1)),
                         [date(2028, 2, 29)])

    def test_repeat_deadlines_include_occurrences_before_visible_month(self):
        self.back2.create_repeat_task("Недельный отчёт", "week", 5, metadata={
            "info_type": "deadline", "deadline_days": 3,
        })
        events = self.read(start=date(2026, 11, 1), end=date(2026, 11, 2))
        self.assertEqual(events[date(2026, 11, 2)][0].kind, "deadline")
        self.assertEqual(events[date(2026, 11, 2)][0].detail, "Повтор · 30.10.2026")

    def test_existing_generated_task_takes_precedence_over_projected_deadline(self):
        self.back2.create_repeat_task("Отчёт", "week", 5, metadata={
            "info_type": "deadline", "deadline_days": 3,
        })
        self.back.saveB("Отчёт", deadline="02-11-2026", info_type="deadline", is_repeat=True)
        events = self.read()[date(2026, 11, 2)]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].detail, "")

    def test_malformed_dates_and_empty_templates_are_ignored(self):
        data = self.back2._load()
        data["tasks"].append({"name": "Ошибка", "deadline": "31-02-2026"})
        data["postponed"].extend([None, {"name": "Ошибка", "date": "не дата"}])
        data["repeat_tasks"].extend([None, {"name": "", "repeat_type": "bad", "repeat_value": "bad"}])
        self.back2._save(data)
        self.assertEqual(self.read(), {})

    def test_settings_navigation_month_rollover_group_filter_and_fresh_reopening(self):
        for phone in (False, True):
            with self.subTest(phone=phone), patch("Frontend.schedule.local_today", return_value=TODAY):
                front = make_front(phone=phone)
                front.open_settings()
                settings_screen = front.screen_stack[-1]
                button = next(button for button in front.settings_cont.content.controls
                              if getattr(button, "content", None) is not None
                              and hasattr(button.content, "controls")
                              and any(getattr(child, "value", "").strip() == "Расписание"
                                      for child in button.content.controls))
                button.on_click(None)
                schedule = front.task_schedule
                self.assertTrue(schedule.empty.visible)
                self.assertEqual(len(schedule.grid.controls[0].controls), 7)
                self.assertTrue(all(len(row.controls) == 7 for row in schedule.grid.controls))
                self.assertLessEqual(schedule.width, front.page.width)
                schedule.month = date(2026, 12, 1)
                schedule.next.on_click(None)
                self.assertEqual(schedule.month, date(2027, 1, 1))
                schedule.previous.on_click(None)
                self.assertEqual(schedule.month, date(2026, 12, 1))
                schedule.today_button.on_click(None)
                front.back.saveB("Новый срок", deadline="30-10-2026", info_type="deadline")
                schedule.refresh()
                self.assertFalse(schedule.empty.visible)
                schedule.group_filter.value = "other"
                schedule.group_filter.on_select(None)
                self.assertEqual(schedule.entries, {})
                schedule.back.on_click(None)
                self.assertIs(front.screen_stack[-1], settings_screen)
                button.on_click(None)
                self.assertEqual(front.task_schedule.entries[date(2026, 10, 30)][0].name, "Новый срок")
                front.task_schedule.show_entry(front.task_schedule.entries[date(2026, 10, 30)][0])
                front.page.show_dialog.assert_called_once()

    def test_native_calendar_uses_a_view_and_returns_to_settings(self):
        async def navigate(phone):
            front = make_front(phone=phone)
            front.web = False
            front.page.push_route = AsyncMock()
            front.page.views = [ft.View(route="/groups")]
            front.open_settings()
            settings = front.page.views[-1]
            front.open_schedule()
            self.assertTrue(front.page.views[-1].route.startswith("/schedule-"))
            front.task_schedule.back.on_click(None)
            self.assertIs(front.page.views[-1], settings)
            await asyncio.sleep(0)

        for phone in (False, True):
            with self.subTest(phone=phone):
                asyncio.run(navigate(phone))


if __name__ == "__main__":
    unittest.main()
