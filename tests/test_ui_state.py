import asyncio
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.webstorage import WebSessionStore
from Frontend.init_page import Front


def make_front(theme="chatgpt", dark=False, phone=False, page=None):
    """Build real controls with isolated in-memory data and no cloud workers."""
    if page is None:
        page = Mock(
            web=True, width=360 if phone else 1100, height=800,
            platform_brightness=ft.Brightness.DARK if dark else ft.Brightness.LIGHT,
            client_user_agent="android" if phone else "desktop",
            views=[], overlay=[], _nd_timezone="Europe/Moscow",
        )
    store = WebSessionStore(page)
    store._settings = {"theme_style": theme}
    with ExitStack() as stack:
        for target in (
            "Frontend.init_page.Cloud", "Backend.core.Cloud", "Backend.extended.Cloud",
            "Frontend.init_page.NotificationService", "Frontend.init_page.AutoUpdateService",
        ):
            stack.enter_context(patch(target, return_value=Mock(connect=True)))
        stack.enter_context(patch.object(Front, "update_tasks"))
        front = Front(page, store)
    front.current_group_id = "default"
    front.render_daily_repeat_tasks()
    return front


class TaskPresentationTests(unittest.TestCase):
    def setUp(self):
        self.front = make_front()
        self.front._update_control = Mock()

    def add_tasks(self):
        self.front.back.saveB("Подготовить документы", "default")
        self.front.back.saveB("Купить продукты", "default")
        self.front.render_daily_repeat_tasks()

    def cards(self):
        return [c for c in self.front.tasks_cont.content.controls
                if isinstance(c.data, str)]

    def test_search_opens_and_focuses_after_update_on_both_layouts(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front._update_control = Mock()

                async def invoke_focus(method):
                    self.assertEqual(method, "focus")
                    front._update_control.assert_called_once_with(front.main_cont)
                    self.assertTrue(front.search_field.visible)
                    self.assertTrue(front.search_close_btn.visible)
                    self.assertFalse(front.search_btn.visible)

                with patch.object(ft.TextField, "_invoke_method",
                                  new_callable=AsyncMock, side_effect=invoke_focus) as focus:
                    for _ in range(2):
                        front._update_control.reset_mock()
                        asyncio.run(front.search_btn.on_click(None))
                        front.close_search(None)
                        self.assertFalse(front.search_field.visible)
                        self.assertFalse(front.search_close_btn.visible)
                        self.assertTrue(front.search_btn.visible)
                    self.assertEqual(focus.await_count, 2)

    def test_desktop_search_does_not_add_expanded_to_wrapping_toolbar(self):
        toolbar = self.front.btns_cont.content
        self.assertTrue(toolbar.wrap)
        self.assertIn(self.front.search_field, toolbar.controls)
        self.assertGreater(self.front.search_field.width, 0)
        # Even expand=False becomes Expanded(flex=0), invalid inside Flutter Wrap.
        for control in toolbar.controls:
            self.assertIsNone(control.expand)

    def test_empty_search_and_clear_restore_cards_and_summary(self):
        self.assertTrue(self.front.empty_state.visible)
        self.assertFalse(self.front.task_progress.visible)
        self.add_tasks()
        self.assertFalse(self.front.empty_state.visible)
        self.front.apply_search_filter("  ДОКУМЕНТЫ  ")
        self.assertEqual([c.visible for c in self.cards()], [True, False])
        self.assertEqual(self.front.task_summary.value, "Найдено: 1 из 2")
        self.front.apply_search_filter("несуществующее")
        self.assertTrue(self.front.empty_state.visible)
        self.assertEqual(self.front.empty_title.value, " Ничего не найдено")
        self.front.close_search(None)
        self.assertTrue(all(c.visible for c in self.cards()))
        self.assertFalse(self.front.empty_state.visible)
        self.assertEqual(self.front.task_summary.value, "Выполнено 0 из 2  ·  Осталось 2")

    def test_completion_updates_storage_progress_and_status_sort(self):
        self.add_tasks()
        self.front.current_status_sort = "incomplete_first"
        self.front._rebuild_sorted_tasks()
        card = self.cards()[0]
        checkbox = next(c for c in card.content.controls if isinstance(c, ft.Checkbox))
        checkbox.value = True
        with patch.object(ft.Container, "update"):
            checkbox.on_change(Mock(control=checkbox))
        self.assertTrue(self.front.back.read_tasks()[0]["status"])
        self.assertEqual(self.front.task_progress.value, 0.5)
        self.assertEqual(self.cards()[-1].data, "Подготовить документы")
        self.assertEqual(self.front.task_summary.value, "Выполнено 1 из 2  ·  Осталось 1")

    def test_delete_last_task_restores_empty_state(self):
        self.front.back.saveB("Единственное дело", "default")
        self.front.render_daily_repeat_tasks()
        card = self.cards()[0]
        delete = card.content.controls[0].content.controls[1]
        delete.on_click(None)
        callback, *args = self.front.page.run_task.call_args.args
        asyncio.run(callback(*args))
        self.assertEqual(self.front.back.read_tasks(), [])
        self.assertTrue(self.front.empty_state.visible)
        self.assertFalse(self.front.task_progress.visible)

    def test_rebuild_preserves_search_and_group_title(self):
        self.add_tasks()
        self.front.back.rename_group("default", "Личные дела")
        self.front.apply_search_filter("продукты")
        self.front._rebuild_sorted_tasks()
        self.assertEqual(self.front.task_heading.value, "Личные дела")
        self.assertEqual(self.front.task_summary.value, "Найдено: 1 из 2")
        self.assertEqual([c.visible for c in self.cards()], [False, True])

    def test_search_matches_across_automatic_display_line_breaks(self):
        title = "Подготовить документы и материалы для следующей рабочей встречи"
        self.front.back.saveB(title, "default")
        self.front.render_daily_repeat_tasks()
        self.front.apply_search_filter(title)
        self.assertTrue(self.cards()[0].visible)
        self.assertFalse(self.front.empty_state.visible)

    def test_actions_are_on_left_only_on_desktop(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.back.saveB("Дело", "default")
                front.render_daily_repeat_tasks()
                card = next(c for c in front.tasks_cont.content.controls if isinstance(c.data, str))
                controls = card.content.controls
                self.assertIsInstance(controls[0 if phone else 1], ft.Checkbox)
                actions = controls[2 if phone else 0].content.controls
                self.assertEqual([c.tooltip for c in actions], ["Редактировать дело", "Удалить дело"])

    def test_group_counter_switch_hides_progress_but_keeps_search_results(self):
        self.add_tasks()
        other_id = self.front.back.create_group("Работа")
        settings = self.front.utils2.build_widgets_for_general_sets(
            group_id="default", command_for_rebuild_tasks=self.front.render_daily_repeat_tasks,
        )
        switch = settings.content.controls[-1].controls[-1]
        self.assertIsInstance(switch, ft.Switch)
        self.assertTrue(switch.value)
        switch.value = False
        switch.on_change(None)
        self.assertFalse(self.front.task_summary.visible)
        self.assertFalse(self.front.task_progress.visible)
        self.assertTrue(self.front.back.get_group_settings(other_id)["show_completion_counter"])
        self.front.apply_search_filter("документы")
        self.assertTrue(self.front.task_summary.visible)
        self.assertEqual(self.front.task_summary.value, "Найдено: 1 из 2")
        self.front.close_search(None)
        self.assertFalse(self.front.task_summary.visible)
        self.front.show_groups()
        subtitle = self.front._groups_column.controls[0].controls[0].content.controls[1].controls[1]
        self.assertFalse(subtitle.visible)
        self.front.current_group_id = "default"
        switch.value = True
        switch.on_change(None)
        self.assertTrue(self.front.task_summary.visible)
        self.assertTrue(self.front.task_progress.visible)
        reopened = self.front.utils2.build_widgets_for_general_sets(group_id="default")
        self.assertTrue(reopened.content.controls[-1].controls[-1].value)

    def test_return_to_groups_refreshes_counter_preference(self):
        self.add_tasks()
        self.front.show_groups()
        self.front.current_group_id = "default"
        self.front._set_screen(self.front.main_cont, push=True)
        self.front.back.update_group_settings("default", show_completion_counter=False)
        self.front.close_page()
        self.assertIsNone(self.front.current_group_id)
        subtitle = self.front._groups_column.controls[0].controls[0].content.controls[1].controls[1]
        self.assertFalse(subtitle.visible)

    def test_group_title_switch_is_independent_and_follows_its_label(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.back.saveB("Дело", "default")
                front.render_daily_repeat_tasks()
                other_id = front.back.create_group("Работа")
                settings = front.utils2.build_widgets_for_general_sets(
                    group_id="default", command_for_rebuild_tasks=front.render_daily_repeat_tasks,
                )
                title_row, counter_row = settings.content.controls[-2:]
                for row in (title_row, counter_row):
                    self.assertIsInstance(row.controls[0], ft.Text)
                    self.assertFalse(row.controls[0].expand)
                    self.assertIsInstance(row.controls[1], ft.Switch)
                switch = title_row.controls[1]
                self.assertTrue(switch.value)
                switch.value = False
                switch.on_change(None)
                self.assertFalse(front.task_heading.visible)
                self.assertTrue(front.task_summary.visible)
                self.assertTrue(front.task_overview.visible)
                self.assertTrue(front.back.get_group_settings(other_id)["show_group_title"])
                front.current_group_id = other_id
                front.render_daily_repeat_tasks()
                self.assertTrue(front.task_heading.visible)
                self.assertEqual(front.task_heading.value, "Работа")
                front.current_group_id = "default"
                front.render_daily_repeat_tasks()
                self.assertFalse(front.task_heading.visible)
                counter_row.controls[1].value = False
                counter_row.controls[1].on_change(None)
                self.assertFalse(front.task_overview.visible)
                front.apply_search_filter("Дело")
                self.assertTrue(front.task_overview.visible)
                self.assertFalse(front.task_heading.visible)
                front.apply_search_filter("")
                reopened = front.utils2.build_widgets_for_general_sets(group_id="default")
                self.assertFalse(reopened.content.controls[-2].controls[1].value)
                switch.value = True
                switch.on_change(None)
                self.assertTrue(front.task_heading.visible)
                self.assertTrue(front.task_overview.visible)

    def test_all_palettes_and_layouts_build_with_metadata(self):
        for theme in ("chatgpt", "improved", "improved_green", "classic", "nord", "oled"):
            for dark in (False, True):
                for phone in (False, True):
                    with self.subTest(theme=theme, dark=dark, phone=phone):
                        front = make_front(theme, dark, phone)
                        front.back.saveB("Важное дело", "default", priority="Важно", info_type="priority")
                        front.back.saveB("Обычное дело", "default", info_type="priority")
                        front.back.saveB("Дело со сроком", "default", deadline="09-09-2026", info_type="deadline")
                        front.render_daily_repeat_tasks()
                        front.show_groups()
                        self.assertEqual(front.task_summary.value, "Выполнено 0 из 3  ·  Осталось 3")
                        self.assertEqual(front._group_task_counts()["default"], (3, 0))


if __name__ == "__main__":
    unittest.main()
