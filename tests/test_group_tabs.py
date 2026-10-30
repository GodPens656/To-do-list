import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

import flet as ft

from Frontend.main import ALL_TASKS_GROUP_ID
from test_ui_state import make_front


class GroupTabsTests(unittest.TestCase):
    def select(self, front, group_id):
        front._update_control = Mock()
        front.group_tabs.selected_index = next(
            index for index, tab in enumerate(front.group_tab_bar.tabs) if tab.data == group_id
        )
        front.group_tabs.on_change(Mock(control=front.group_tabs))

    def test_tabs_are_above_tasks_with_management_and_add_buttons(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.show_groups()
                self.assertIs(front.main_cont.content.controls[0], front.group_tabs)
                self.assertEqual(front.group_tabs.content.controls, [
                    front.group_settings_btn, front.group_tab_bar,
                ])
                self.assertIs(front.group_tab_bar.tabs[-1].label, front.group_add_btn)
                self.assertTrue(front.group_tab_bar.scrollable)
                self.assertEqual(front.screen_stack, [front.main_cont])
                front.show_groups()
                self.assertEqual(front.screen_stack, [front.main_cont])

    def test_switching_tabs_changes_content_and_filter_without_navigation(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front._update_control = Mock()
                work = front.back.create_group("Работа")
                notes = front.back.create_group("Идеи", group_type="notes")
                front.back.saveB("Рабочее дело", work)
                front.back.save_note(notes, "Заметка для проверки")
                front.back.set_group_default_filter(work, "priority_desc", "complete_first")
                front.show_groups()
                front.apply_search_filter("старый поиск")
                self.select(front, work)
                self.assertEqual(front.current_group_id, work)
                self.assertEqual((front.current_sort, front.current_status_sort),
                                 ("priority_desc", "complete_first"))
                self.assertEqual(front.current_search, "")
                self.assertEqual(front.task_heading.value, "Работа")
                self.assertFalse(front.empty_state.visible)
                self.select(front, notes)
                self.assertTrue(front._notes_group)
                self.assertFalse(front.filter_btn.visible)
                self.assertFalse(front.empty_state.visible)
                self.assertEqual(front.screen_stack, [front.main_cont])

    def test_add_button_creates_and_selects_group_and_cancel_keeps_selection(self):
        front = make_front()
        front.show_groups()
        front.group_add_btn.on_click(None)
        front.libs.entry_task.value = "Новая вкладка"
        front.libs.entry_task.on_submit(None)
        created_id = front.current_group_id
        self.assertNotEqual(created_id, "default")
        self.assertEqual(front.task_heading.value, "Новая вкладка")
        self.assertEqual(front.group_tab_bar.tabs[front.group_tabs.selected_index].data, created_id)
        self.assertEqual(front.screen_stack, [front.main_cont])
        front.group_add_btn.on_click(None)
        front.close_page()
        self.assertEqual(front.current_group_id, created_id)
        self.assertEqual(len(front.group_tab_bar.tabs), 4)
        front.group_tabs.selected_index = len(front.group_tab_bar.tabs) - 1
        front._update_control = Mock()
        front.group_tabs.on_change(Mock(control=front.group_tabs))
        self.assertEqual(front.group_tab_bar.tabs[front.group_tabs.selected_index].data, created_id)
        front.close_page()
        self.assertEqual(front.current_group_id, created_id)

    def test_management_edits_and_deletes_selected_group_and_undo_restores_tab(self):
        front = make_front()
        group_id = front.back.create_group("Работа")
        front.back.saveB("Дело в группе", group_id)
        front.show_groups()
        self.select(front, group_id)
        front.group_settings_btn.on_click(None)
        self.assertEqual(front.screen_stack, [front.main_cont, front._groups_screen])
        row = front._groups_column.controls[1]
        row.controls[1].items[0].on_click(None)
        front.libs.entry_task.value = "Проекты"
        front.libs.entry_task.on_submit(None)
        self.assertIs(front.screen_stack[-1], front._groups_screen)
        self.assertEqual(front.current_group_id, group_id)
        self.assertEqual(front.task_heading.value, "Проекты")
        front._groups_column.controls[1].controls[1].items[1].on_click(None)
        self.assertEqual(front.current_group_id, ALL_TASKS_GROUP_ID)
        self.assertNotIn(group_id, [tab.data for tab in front.group_tab_bar.tabs])
        front.groups_undo_btn.on_click(None)
        self.assertIn(group_id, [tab.data for tab in front.group_tab_bar.tabs])
        self.assertEqual(len(front._groups_column.controls), 2)
        front.close_page()
        self.assertEqual(front.screen_stack, [front.main_cont])
        self.assertEqual(front.task_heading.value, "Все дела")

    def test_creating_from_management_returns_to_management(self):
        front = make_front()
        front.show_groups()
        front.open_group_management()
        front._open_create_group()
        front.libs.entry_task.value = "Из настроек"
        front.libs.entry_task.on_submit(None)
        self.assertIs(front.screen_stack[-1], front._groups_screen)
        self.assertEqual(len(front._groups_column.controls), 2)
        front.close_page()
        self.assertEqual(front.task_heading.value, "Из настроек")

    def test_native_switching_keeps_one_root_view_and_back_returns_from_management(self):
        async def exercise():
            front = make_front(phone=True)
            front.web = front.page.web = False
            front.page.push_route = AsyncMock()
            front._update_control = Mock()
            group_id = front.back.create_group("Работа")
            front.show_groups()
            self.select(front, group_id)
            self.select(front, "default")
            self.assertEqual(front.page.views, [front.root_view])
            self.assertEqual(front.root_view.controls, [front.main_cont])
            front.open_group_management()
            self.assertEqual(len(front.page.views), 2)
            front.close_page()
            self.assertEqual(front.page.views, [front.root_view])
            self.assertEqual(front.root_view.controls, [front.main_cont])
            await asyncio.sleep(0)
        asyncio.run(exercise())

    def test_cloud_refresh_removes_missing_active_tab_on_native_and_web(self):
        async def exercise(native):
            front = make_front()
            front.web = front.page.web = not native
            front.page.push_route = AsyncMock()
            front._update_control = Mock()
            group_id = front.back.create_group("Общая группа")
            front.show_groups()
            self.select(front, group_id)
            front.cloud.alg_for_start_app.side_effect = lambda: front.back.delete_group(group_id)
            await front.refresh_tasks_silent()
            self.assertEqual(front.current_group_id, ALL_TASKS_GROUP_ID)
            self.assertEqual([tab.data for tab in front.group_tab_bar.tabs if tab.data],
                             [ALL_TASKS_GROUP_ID, "default"])
            self.assertEqual(front.task_heading.value, "Все дела")
            await asyncio.sleep(0)
        for native in (False, True):
            with self.subTest(native=native):
                asyncio.run(exercise(native))


if __name__ == "__main__":
    unittest.main()
