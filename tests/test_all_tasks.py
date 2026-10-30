import asyncio
import unittest
from unittest.mock import Mock, patch

import flet as ft

from Frontend.main import ALL_TASKS_GROUP_ID
from test_ui_state import make_front


class AllTasksTests(unittest.TestCase):
    def front(self, phone=False):
        front = make_front(phone=phone)
        front._update_control = Mock()
        front.back.rename_group("default", "Без группы")
        front.back.clear_undo()
        front.current_group_id = None
        front.show_groups()
        return front

    @staticmethod
    def cards(front):
        return [control for control in front.tasks_cont.content.controls
                if isinstance(control.data, str)]

    @staticmethod
    def select(front, group_id):
        front.group_tabs.selected_index = next(
            i for i, tab in enumerate(front.group_tab_bar.tabs) if tab.data == group_id
        )
        front.group_tabs.on_change(Mock(control=front.group_tabs))

    def test_new_account_starts_with_all_tasks_instead_of_ungrouped(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = self.front(phone)
                self.assertEqual(front.current_group_id, ALL_TASKS_GROUP_ID)
                self.assertEqual(front.task_heading.value, "Все дела")
                self.assertEqual([tab.data for tab in front.group_tab_bar.tabs],
                                 [ALL_TASKS_GROUP_ID, None])
                self.assertNotIn(ALL_TASKS_GROUP_ID, [g["id"] for g in front.back.get_groups()])
                front.open_group_management()
                self.assertEqual(front._groups_column.controls, [])

    def test_all_tasks_collects_groups_and_ungrouped_but_excludes_notes(self):
        front = self.front()
        work = front.back.create_group("Работа")
        home = front.back.create_group("Дом")
        notes = front.back.create_group("Заметки", group_type="notes")
        front.back.save_note(notes, "Это заметка")
        ids = {front.back.saveB("Одинаковое название", group) for group in ("default", work, home)}
        ids.add(front.back.saveB("Запланированное дело", work, is_repeat=True))
        front.back2.create_postponed_task("Пока не наступило", "01-01-2099", home)
        front.render_daily_repeat_tasks()
        self.assertEqual({card.key for card in self.cards(front)}, ids)
        self.assertEqual(front.task_summary.value, "Выполнено 0 из 4  ·  Осталось 4")
        self.select(front, work)
        self.assertEqual(len(self.cards(front)), 2)
        self.select(front, ALL_TASKS_GROUP_ID)
        self.assertEqual({card.key for card in self.cards(front)}, ids)
        front.apply_search_filter("запланированное")
        self.assertEqual(sum(card.visible for card in self.cards(front)), 1)
        self.assertEqual(front.task_summary.value, "Найдено: 1 из 4")

    def test_new_task_from_all_tasks_is_stored_once_without_virtual_group(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = self.front(phone)
                front.button_add_task.on_click(None)
                front.entry_task.value = "Первое дело"
                front.create_task.on_click(None)
                tasks = front.back.read_tasks()
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]["group"], "default")
                self.assertEqual([card.key for card in self.cards(front)], [tasks[0]["id"]])
                self.assertEqual(front.current_group_id, ALL_TASKS_GROUP_ID)

    def test_sort_status_and_edit_use_original_ids_and_groups(self):
        front = self.front()
        work = front.back.create_group("Работа")
        home = front.back.create_group("Дом")
        first = front.back.saveB("Дело", work, priority="Неважно")
        second = front.back.saveB("Дело", home, priority="Очень важно")
        front.back.set_group_default_filter(work, "priority_asc", "complete_first")
        front.back2.redact_setting("default_task_sort", "priority_desc")
        front.back2.redact_setting("default_task_status_sort", "incomplete_first")
        front._load_default_task_filter()
        front.render_daily_repeat_tasks()
        self.assertEqual([card.key for card in self.cards(front)], [second, first])
        card = self.cards(front)[0]
        checkbox = next(c for c in card.content.controls if isinstance(c, ft.Checkbox))
        checkbox.value = True
        with patch.object(ft.Container, "update"):
            checkbox.on_change(Mock(control=checkbox))
        self.assertTrue(front.back.get_task(second)["status"])
        self.assertFalse(front.back.get_task(first)["status"])
        self.assertEqual([card.key for card in self.cards(front)], [first, second])
        card.content.controls[0].content.controls[0].on_click(None)
        front.libs.entry_task.value = "Изменённое дело"
        front.libs.entry_task.on_submit(None)
        self.assertEqual(front.back.get_task(second)["group"], home)
        self.assertEqual(front.back.get_task(second)["name"], "Изменённое дело")
        self.assertEqual(front.current_group_id, ALL_TASKS_GROUP_ID)

    def test_customized_legacy_group_remains_available(self):
        front = self.front()
        front.back.rename_group("default", "Личные дела")
        task_id = front.back.saveB("Старое дело")
        front.render_daily_repeat_tasks()
        self.assertEqual([tab.data for tab in front.group_tab_bar.tabs],
                         [ALL_TASKS_GROUP_ID, "default", None])
        self.select(front, "default")
        self.assertEqual(front.task_heading.value, "Личные дела")
        self.assertEqual([card.key for card in self.cards(front)], [task_id])

    def test_refresh_and_undo_keep_all_tasks_selected(self):
        async def exercise():
            front = self.front()
            work = front.back.create_group("Работа")
            task_id = front.back.saveB("Из другой группы", work)
            front.render_daily_repeat_tasks()
            front.back.kill_taskB(task_id)
            front.undo_last_action()
            self.assertEqual(front.current_group_id, ALL_TASKS_GROUP_ID)
            self.assertEqual([card.key for card in self.cards(front)], [task_id])
            front.cloud.alg_for_start_app.side_effect = lambda: front.back.saveB("Из облака", work)
            await front.refresh_tasks_silent()
            self.assertEqual(front.current_group_id, ALL_TASKS_GROUP_ID)
            self.assertEqual(len(self.cards(front)), 2)
        asyncio.run(exercise())

    def test_settings_and_filters_use_global_scope_for_all_tasks(self):
        front = self.front()
        front.open_settings()
        checkbox = front.utils2.only_current_group_checkbox
        self.assertTrue(checkbox.disabled)
        front.close_page()
        front.open_page = Mock()
        front.open_task_filter_dialog()
        content = front.open_page.call_args.args[1]
        buttons = {button.content: button for row in content.content.controls
                   if isinstance(row, ft.Row) for button in row.controls}
        self.assertTrue(buttons["Сохранить для этой группы"].disabled)
        self.assertFalse(buttons["Сохранить общий фильтр"].disabled)


if __name__ == "__main__":
    unittest.main()
