import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Frontend.main import ALL_TASKS_GROUP_ID
from test_ui_state import make_front, task_menu


class TaskActionsTests(unittest.TestCase):
    @staticmethod
    def card(front, task_id):
        return next(c for c in front.tasks_cont.content.controls if c.key == task_id)

    def front_with_task(self, phone=False):
        front = make_front(phone=phone)
        front.page.services = []
        front._update_control = Mock()
        front._set_screen(front.main_cont, reset=True)
        group = front.back.create_group("Работа")
        name = "Подготовить документы и материалы для следующей рабочей встречи\nУточнить время"
        task_id = front.back.saveB(name, group)
        front.back.saveB(name, "default")
        front.current_group_id = ALL_TASKS_GROUP_ID
        front.render_daily_repeat_tasks()
        return front, task_id, name, group

    def test_copy_preserves_full_name_and_newlines_and_reuses_clipboard(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front, task_id, name, _ = self.front_with_task(phone)
                before = front.back._load()
                copy = task_menu(self.card(front, task_id)).items[1]
                with patch.object(ft.Clipboard, "set", new_callable=AsyncMock) as set_text:
                    asyncio.run(copy.on_click(None))
                    asyncio.run(copy.on_click(None))
                self.assertEqual(set_text.await_count, 2)
                set_text.assert_awaited_with(name)
                self.assertEqual(len(front.page.services), 1)
                self.assertEqual(front.back._load(), before)

    def test_repeat_prefills_source_group_saves_without_opening_settings_and_resets(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front, task_id, name, group = self.front_with_task(phone)
                source = front.back.get_task(task_id)
                repeat = task_menu(self.card(front, task_id)).items[2]
                repeat.on_click(None)
                self.assertEqual(front.libs.entry_task.value, name)
                self.assertEqual(front.back2.read_repeat_tasks(), [])
                front.close_page()
                self.assertEqual(front.back2.read_repeat_tasks(), [])
                repeat.on_click(None)
                front.libs.entry_task.on_submit(None)
                created = front.back2.read_repeat_tasks()
                self.assertEqual(len(created), 1)
                self.assertEqual(created[0][:4], (name, "day", 1, group))
                self.assertEqual(front.back.get_task(task_id), source)
                self.assertEqual(front.current_group_id, ALL_TASKS_GROUP_ID)
                front.open_repeat_dialog()
                self.assertEqual(front.libs.entry_task.value, "")
                front.close_page()
                front.open_special_tasks()
                self.assertEqual(len(front.utils2.cont_with_repeat_task.content.controls), 1)

    def test_all_actions_after_edit_use_current_name_and_original_id(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front, task_id, _, group = self.front_with_task(phone)
                task_menu(self.card(front, task_id)).items[0].on_click(None)
                name = "Обновлённое дело\nВторая строка"
                front.libs.entry_task.value = name
                front.libs.entry_task.on_submit(None)
                menu = task_menu(self.card(front, task_id))
                with patch.object(ft.Clipboard, "set", new_callable=AsyncMock) as set_text:
                    asyncio.run(menu.items[1].on_click(None))
                set_text.assert_awaited_once_with(name)
                menu.items[2].on_click(None)
                self.assertEqual(front.libs.entry_task.value, name)
                front.libs.entry_task.on_submit(None)
                self.assertEqual(front.back2.read_repeat_tasks()[0][:4], (name, "day", 1, group))
                menu = task_menu(self.card(front, task_id))
                menu.items[-1].on_click(None)
                callback, *args = front.page.run_task.call_args.args
                asyncio.run(callback(*args))
                self.assertIsNone(front.back.get_task(task_id))
                self.assertEqual(len(front.back.read_tasks()), 1)

    def test_clipboard_error_is_reported_without_modifying_task(self):
        front, task_id, _, _ = self.front_with_task()
        source = front.back.get_task(task_id)
        with patch.object(ft.Clipboard, "set", new_callable=AsyncMock,
                          side_effect=RuntimeError("Clipboard unavailable")):
            asyncio.run(task_menu(self.card(front, task_id)).items[1].on_click(None))
        self.assertEqual(front.page.show_dialog.call_args.args[0].title.value, "Копирование дела")
        self.assertEqual(front.back.get_task(task_id), source)


if __name__ == "__main__":
    unittest.main()
