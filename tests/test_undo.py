import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import flet as ft

from Backend.core import Backend
from Backend.extended import Backend2
from Backend.webstorage import WebSessionStore
from Frontend.libs import Fr_Libs
from test_ui_state import make_front


class UndoStorageTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock(_nd_timezone='Europe/Moscow')
        self.store = WebSessionStore(self.page)
        self.back = Backend(page=self.page, web_store=self.store, cloud=Mock())
        self.back2 = Backend2(page=self.page, web_store=self.store,
                              back=self.back, cloud=Mock())

    def test_create_edit_complete_delete_restore_exact_task(self):
        self.assertFalse(self.back.can_undo())
        self.back.saveB('Первая строка\nВторая', deadline='30-09-2026', priority='Важно')
        original = self.back.read_tasks()[0]
        for action in (
            lambda: self.back.redact_taskB(original['id'], 'Изменено', {'deadline': ''}),
            lambda: self.back.redact_statusB(original['id'], True),
            lambda: self.back.kill_taskB(original['id']),
        ):
            with self.subTest(action=action):
                action()
                self.assertTrue(self.back.undo_last_action())
                self.assertEqual(self.back.read_tasks(), [original])
                self.assertFalse(self.back.undo_last_action())
        self.back.saveB('Новое дело')
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back.read_tasks(), [original])

    def test_noop_does_not_replace_last_action(self):
        before = self.back._load()
        self.back.saveB('Дело')
        self.back.kill_taskB('missing')
        self.back.redact_statusB(self.back.read_tasks()[0]['id'], False)
        self.back.delete_empty_lines()
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), before)

    def test_group_deletion_restores_tasks_and_notes_together(self):
        group = self.back.create_group('Записи', group_type='notes')
        self.back.save_note(group, 'Текст\nзаметки')
        self.back.saveB('Дело', group)
        before = self.back._load()
        self.back.delete_group(group)
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), before)

    def test_note_edit_and_delete_can_be_undone(self):
        group = self.back.create_group('Записи', group_type='notes')
        note = self.back.save_note(group, 'Исходный текст')
        before = self.back._load()
        self.back.save_note(group, 'Новый текст', note)
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), before)
        self.back.delete_note(group, note)
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), before)

    def test_repeat_and_postponed_share_one_undo_slot(self):
        self.back.saveB('Обычное дело')
        before = self.back._load()
        self.back2.create_repeat_task('Повтор', group_id='default')
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), before)
        self.back2.create_postponed_task('Позже', '01-01-2099')
        saved = self.back._load()
        self.back2.delete_postponed_task('Позже', '01-01-2099')
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), saved)
        self.assertFalse(self.back.undo_last_action())

    def test_external_changes_are_never_overwritten(self):
        self.back.saveB('Моё дело')
        remote = self.back._load()
        remote['tasks'][0]['name'] = 'Из облака'
        self.store.replace_from_cloud(remote)
        self.assertFalse(self.back.can_undo())
        self.assertFalse(self.back.undo_last_action())
        self.assertEqual(self.back._load(), remote)

    def test_automatic_generation_is_not_undoable(self):
        self.back.saveB('Дело')
        self.back.saveB('Автоматическое', is_repeat=True)
        self.assertFalse(self.back.can_undo())

    def test_failed_save_preserves_previous_undo(self):
        self.back.saveB('Дело')
        with patch.object(self.store, 'save_all_sections', side_effect=OSError):
            with self.assertRaises(OSError):
                self.back.saveB('Не сохранено')
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back.read_tasks(), [])

    def test_native_undo_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend.__new__(Backend)
            back.web = False
            back.page = self.page
            back.data_dir = Path(directory)
            back.saveB('Сохранённое дело')
            original = back.read_tasks()
            back.kill_taskB(original[0]['id'])
            self.assertTrue(back.undo_last_action())
            reopened = Backend.__new__(Backend)
            reopened.web = False
            reopened.data_dir = Path(directory)
            self.assertEqual(reopened.read_tasks(), original)
            self.assertFalse(reopened.can_undo())


class UndoUITests(unittest.TestCase):
    def test_button_position_and_completion_undo_on_desktop_and_phone(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front._update_control = Mock()
                row = front.btns_cont.content
                if phone:
                    row = row.controls[0]
                index = row.controls.index(front.auth_btn)
                self.assertIs(row.controls[index + 1], front.undo_btn)
                self.assertIs(row.controls[index + 2], front.upd_btn)
                self.assertTrue(front.undo_btn.disabled)
                front.back.saveB('Проверить отмену')
                front.render_daily_repeat_tasks()
                card = next(c for c in front.tasks_cont.content.controls if isinstance(c.data, str))
                checkbox = next(c for c in card.content.controls if isinstance(c, ft.Checkbox))
                checkbox.value = True
                with patch.object(ft.Container, 'update'):
                    checkbox.on_change(Mock(control=checkbox))
                self.assertFalse(front.undo_btn.disabled)
                front.undo_btn.on_click(None)
                self.assertFalse(front.back.read_tasks()[0]['status'])
                self.assertEqual(front.task_progress.value, 0)
                self.assertTrue(front.undo_btn.disabled)
                front.cloud.alg_for_redact.assert_called()

    def test_group_toolbar_undo_restores_deleted_group(self):
        front = make_front()
        front.show_groups()
        row = front._build_group_actions()
        self.assertEqual(row.controls[-3].tooltip.message, 'Аккаунт')
        self.assertIs(row.controls[-2], front.groups_undo_btn)
        self.assertEqual(row.controls[-1].tooltip.message, 'Обновить дела')
        group = front.back.create_group('Восстановить')
        front.back.delete_group(group)
        self.assertFalse(front.groups_undo_btn.disabled)
        front.groups_undo_btn.on_click(None)
        self.assertTrue(any(g['id'] == group for g in front.back.get_groups()))
        self.assertTrue(front.groups_undo_btn.disabled)

    def test_undo_icon_available_for_all_packs(self):
        for pack in ('flet', 'minimalistic', 'minimalistic-blue', 'old', 'custom'):
            libs = Fr_Libs('chatgpt', False, icon_pack=pack)
            button = libs.build_button_with_image('undo', 'Отмена')
            self.assertIsInstance(button.content, ft.Icon)
            self.assertEqual(button.content.icon, ft.Icons.UNDO_ROUNDED)


if __name__ == '__main__':
    unittest.main()
