"""Bounded calendar rendering and constant storage reads for large lists."""
import unittest
from datetime import date
from unittest.mock import patch

import flet as ft

from Backend.schedule import build_schedule
from Frontend.schedule import TaskSchedule
from test_ui_state import make_front


TODAY = date(2026, 10, 29)


class LargeListTests(unittest.TestCase):
    @staticmethod
    def seed(front, count):
        data = front.back._load()
        data["tasks"] = [
            dict(id=str(i), name=f"Task {i}", group="default", status=False)
            for i in range(500)
        ]
        data["repeat_tasks"] = [
            dict(id=f"r{i}", name=f"Repeat {i:03}", group="default",
                 repeat_type="day", repeat_value=1,
                 created_date="01-09-2026", last_date="28-10-2026")
            for i in range(count)
        ]
        data["postponed"] = [
            dict(id=f"p{i}", name=f"Postponed {i:03}", group="missing" if i == 0 else "default",
                 date="30-10-2026") for i in range(count)
        ]
        front.back.store.save_all_sections(data)

    def test_special_lists_read_storage_twice_regardless_of_size_and_see_group_renames(self):
        for count in (1, 300):
            for phone in (False, True):
                for repeating in (False, True):
                    with self.subTest(count=count, phone=phone, repeating=repeating):
                        front = make_front(phone=phone)
                        self.seed(front, count)
                        for group_name in ("Первая группа", "Новое название"):
                            front.back.rename_group("default", group_name)
                            with patch.object(front.back.store, "load_all_sections",
                                              wraps=front.back.store.load_all_sections) as reads, \
                                 patch.object(front.back, "_save") as save:
                                _, _, _, tasks = front.utils2._build_special_task_list(
                                    repeating, lambda: None, lambda: None, front.page,
                                )
                            self.assertEqual(reads.call_count, 2)
                            save.assert_not_called()
                            self.assertIsInstance(tasks.content, ft.ListView)
                            self.assertTrue(tasks.content.build_controls_on_demand)
                            self.assertEqual(len(tasks.content.controls), count)
                            for index, row in enumerate(tasks.content.controls):
                                expected = "Без группы" if not repeating and index == 0 else group_name
                                self.assertTrue(row.controls[0].controls[1].value.endswith(expected))

    def test_tasks_and_groups_render_on_demand_in_every_layout(self):
        for phone in (False, True):
            for theme in ("chatgpt", "improved_purple"):
                for effect in ("none", "liquid_glass_half"):
                    with self.subTest(phone=phone, theme=theme, effect=effect):
                        front = make_front(phone=phone, theme=theme, effect=effect)
                        self.assertIsInstance(front.tasks_cont.content, ft.ListView)
                        self.assertTrue(front.tasks_cont.content.build_controls_on_demand)
                        front.show_groups()
                        front.open_group_management()
                        self.assertIsInstance(front._groups_column, ft.ListView)
                        self.assertTrue(front._groups_column.build_controls_on_demand)
                        self.assertTrue(front._groups_column.expand)

    def test_busy_calendar_bounds_cards_but_preserves_every_event_and_summary(self):
        front = make_front(phone=True)
        self.seed(front, 250)
        with patch("Frontend.schedule.local_today", return_value=TODAY), \
             patch("Backend.extended.local_today", return_value=TODAY):
            schedule = TaskSchedule(front)
        cards = [control for row in schedule.grid.controls[1:] for cell in row.controls
                 for control in cell.content.controls if hasattr(control.data, "kind")]
        self.assertGreater(sum(map(len, schedule.entries.values())), 7500)
        self.assertLessEqual(len(cards), 42 * schedule.DAY_PREVIEW_LIMIT)
        self.assertEqual(len(schedule.entries[TODAY]), 250)
        self.assertIn("8000", schedule.summary.value)  # 31 * 250 repeats + 250 postponed
        cell = next(cell for row in schedule.grid.controls[1:] for cell in row.controls
                    if cell.data == TODAY)
        more = next(control for control in cell.content.controls if isinstance(control, ft.TextButton))
        self.assertEqual(more.content, "Ещё 247")
        more.on_click(None)
        dialog = front.page.show_dialog.call_args.args[0]
        self.assertIn("29.10.2026", dialog.title.value)

    def test_day_pages_reach_all_events_without_building_the_whole_day(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                self.seed(front, 83)
                with patch("Frontend.schedule.local_today", return_value=TODAY), \
                     patch("Backend.extended.local_today", return_value=TODAY):
                    schedule = TaskSchedule(front)
                front.page.show_dialog.reset_mock()
                with patch.object(schedule, "entry_card", wraps=schedule.entry_card) as build:
                    schedule.show_day(TODAY)
                    dialog = front.page.show_dialog.call_args.args[0]
                    listing, pager = dialog.content.content.controls
                    previous, counter, next_button = pager.controls
                    self.assertEqual(build.call_count, schedule.DAY_PAGE_SIZE)
                    self.assertTrue(previous.disabled)
                    visited = []
                    while True:
                        self.assertLessEqual(len(listing.controls), schedule.DAY_PAGE_SIZE)
                        visited.extend(card.data for card in listing.controls)
                        if next_button.disabled:
                            break
                        next_button.on_click(None)
                    self.assertEqual(visited, schedule.entries[TODAY])
                    self.assertEqual(counter.value, "81–83 из 83")
                    listing.controls[-1].on_click(None)
                    detail = front.page.show_dialog.call_args.args[0]
                    self.assertIn("Repeat 082", detail.content.value)
                    detail.actions[0].on_click(None)
                    front.page.pop_dialog.assert_called_once()
                    previous.on_click(None)
                    self.assertEqual(counter.value, "41–80 из 83")
                    dialog.actions[0].on_click(None)
                    self.assertEqual(front.page.pop_dialog.call_count, 2)

    def test_calendar_filter_skips_rules_of_other_groups_before_projection(self):
        rules = [dict(name="Other", group="other", repeat_type="day", repeat_value=1),
                 dict(name="Mine", group="default", repeat_type="day", repeat_value=1)]
        # Missing group IDs retain the default-group semantics.
        rules.append(dict(name="Legacy", repeat_type="day", repeat_value=1))
        from Backend.schedule import repeat_dates
        with patch("Backend.schedule.repeat_dates", wraps=repeat_dates) as project:
            days = build_schedule({"repeat_tasks": rules}, TODAY, TODAY, TODAY,
                                  lambda *_: "", group_id="default")
        self.assertEqual(project.call_count, 2)
        self.assertEqual([entry.name for entry in days[TODAY]], ["Legacy", "Mine"])


if __name__ == "__main__":
    unittest.main()
