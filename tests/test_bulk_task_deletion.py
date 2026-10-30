import tempfile
import unittest
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import flet as ft

from Backend.core import Backend
from Backend.extended import Backend2
from Backend.storage import empty_data
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front


class BulkTaskDeletionStorageTests(unittest.TestCase):
    def test_scope_status_and_undo_in_native_and_web_storage(self):
        cases = (
            (None, None, set()),
            (True, None, {'legacy', 'work-pending', 'home-pending'}),
            (False, None, {'default-done', 'work-done', 'home-done'}),
            (None, 'work', {'legacy', 'default-done', 'home-pending', 'home-done'}),
            (True, 'work', {'legacy', 'default-done', 'work-pending', 'home-pending', 'home-done'}),
            (False, 'work', {'legacy', 'default-done', 'work-done', 'home-pending', 'home-done'}),
            (None, 'default', {'work-pending', 'work-done', 'home-pending', 'home-done'}),
            (True, 'default', {'legacy', 'work-pending', 'work-done', 'home-pending', 'home-done'}),
            (False, 'default', {'default-done', 'work-pending', 'work-done', 'home-pending', 'home-done'}),
        )
        for web, (status, group_id, remaining) in product((False, True), cases):
            with self.subTest(web=web, status=status, group_id=group_id), tempfile.TemporaryDirectory() as directory:
                back = Backend.__new__(Backend)
                back.web = web
                back.data_dir = Path(directory)
                back.store = WebSessionStore(SimpleNamespace())
                back2 = Backend2.__new__(Backend2)
                back2.web = web
                back2.data_dir = back.data_dir
                back2.store = back.store
                back2.back = back
                back2.cloud = Mock()
                data = empty_data()
                data['tasks'] = [
                    {'id': 'legacy', 'name': 'Старое дело', 'status': False},
                    {'id': 'default-done', 'group': 'default', 'status': True},
                    {'id': 'work-pending', 'group': 'work', 'status': False},
                    {'id': 'work-done', 'group': 'work', 'status': 'True'},
                    {'id': 'home-pending', 'group': 'home', 'status': 'False'},
                    {'id': 'home-done', 'group': 'home', 'status': True},
                ]
                data['repeat_tasks'] = [{'id': 'repeat', 'group': 'work'}]
                data['postponed'] = [{'id': 'later', 'group': 'work'}]
                data['groups'].append({
                    'id': 'notes', 'name': 'Записи', 'type': 'notes',
                    'notes': [{'id': 'note', 'text': 'Сохранить'}],
                })
                back._save(data)
                before = back._load()

                back2.delete_special_tasks(status, group_id=group_id)

                after = back._load()
                self.assertEqual({task['id'] for task in after['tasks']}, remaining)
                for section in ('groups', 'repeat_tasks', 'postponed'):
                    self.assertEqual(after[section], before[section])
                back2.cloud.alg_for_redact.assert_called_once_with()
                self.assertTrue(back.undo_last_action())
                self.assertEqual(back._load(), before)


class BulkTaskDeletionUITests(unittest.TestCase):
    @staticmethod
    def management_controls(front):
        management = front.settings_cont.content.controls[2].controls[0]
        return management.content.controls

    def test_all_three_buttons_respect_checkbox_on_desktop_and_phone(self):
        for phone, scoped, button_index in product((False, True), (False, True), range(3)):
            with self.subTest(phone=phone, scoped=scoped, button=button_index):
                front = make_front(phone=phone)
                group = front.back.create_group('Работа')
                for group_id, prefix in (('default', 'other'), (group, 'current')):
                    front.back.saveB(prefix + '-pending', group_id)
                    task_id = front.back.saveB(prefix + '-done', group_id)
                    front.back.redact_statusB(task_id, True)
                front.current_group_id = group
                front.render_daily_repeat_tasks()
                before = front.back._load()
                front.open_settings()
                controls = self.management_controls(front)
                checkbox = controls[3]
                self.assertIsInstance(checkbox, ft.Checkbox)
                self.assertEqual(checkbox.label, 'Только для этой группы')
                self.assertFalse(checkbox.value)
                self.assertFalse(checkbox.disabled)
                checkbox.value = scoped

                controls[button_index].on_click(None)

                expected = (set(), {'current-done'}, {'current-pending'})[button_index].copy()
                if scoped:
                    expected.update(('other-pending', 'other-done'))
                elif button_index == 1:
                    expected.add('other-done')
                elif button_index == 2:
                    expected.add('other-pending')
                self.assertEqual({task['name'] for task in front.back.read_tasks()}, expected)
                self.assertTrue(front.back.undo_last_action())
                self.assertEqual(front.back._load(), before)

    def test_selection_is_temporary_and_resets_when_reopening_cached_settings(self):
        front = make_front()
        original_settings = front.back2.read_settings()
        original_data = front.back._load()
        front.open_settings()
        screen = front.screen_stack[-1]
        checkbox = self.management_controls(front)[3]
        checkbox.value = True
        # Returning from another settings section keeps the current selection.
        front.settings_cont.content.controls[0].on_click(None)
        front.close_page()
        self.assertIs(front.screen_stack[-1], screen)
        self.assertTrue(checkbox.value)
        front.close_page()
        front.open_settings()
        self.assertIs(front.screen_stack[-1], screen)
        self.assertFalse(self.management_controls(front)[3].value)
        self.assertFalse(self.management_controls(front)[3].disabled)
        self.assertEqual(front.back2.read_settings(), original_settings)
        self.assertEqual(front.back._load(), original_data)

    def test_root_tasks_keep_group_scope_after_returning_from_settings(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.open_settings()
                self.management_controls(front)[3].value = True
                front.close_page()
                front.show_groups()
                front.open_settings()
                checkbox = self.management_controls(front)[3]
                self.assertFalse(checkbox.value)
                self.assertFalse(checkbox.disabled)
                front.close_page()
                front.current_group_id = 'default'
                front.open_settings()
                checkbox = self.management_controls(front)[3]
                self.assertFalse(checkbox.value)
                self.assertFalse(checkbox.disabled)


if __name__ == '__main__':
    unittest.main()
