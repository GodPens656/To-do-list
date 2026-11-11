import unittest
from unittest.mock import Mock

import flet as ft

from Backend.core import Backend
from Backend.extended import Backend2
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front, task_menu


class TextLengthStorageTests(unittest.TestCase):
    def setUp(self):
        page = Mock(_nd_timezone='Europe/Moscow')
        store = WebSessionStore(page)
        self.back = Backend(page=page, web_store=store, cloud=Mock())
        self.back2 = Backend2(page=page, web_store=store, back=self.back, cloud=Mock())

    def test_create_and_edit_boundaries_for_all_types(self):
        notes_group = self.back.create_group('Заметки', group_type='notes')

        def create_task(text):
            self.back.saveB(text)
            return self.back.read_id(text)

        operations = [
            (create_task, self.back.redact_taskB, 1000),
            (lambda text: self.back.save_note(notes_group, text),
             lambda ident, text: self.back.save_note(notes_group, text, ident), 1000),
            (lambda text: self.back2.create_repeat_task(text),
             lambda ident, text: self.back2.update_repeat_task(ident, text, 'day', 1, 'default'), 1000),
            (lambda text: self.back2.create_postponed_task(text, '01-01-2030'),
             lambda ident, text: self.back2.update_postponed_task(ident, text, '01-01-2030', 'default'), 1000),
        ]
        for group_type in ('tasks', 'notes'):
            operations.append((
                lambda text, kind=group_type: self.back.create_group(text, group_type=kind),
                self.back.rename_group,
                100,
            ))

        # Cyrillic, emoji, spaces and manual newlines count before {N} encoding.
        for index, (create, edit, limit) in enumerate(operations):
            with self.subTest(kind=index):
                for length in (limit - 1, limit):
                    text = 'Я🙂 \n' + 'а' * (length - 4)
                    ident = create(text)
                    self.assertTrue(ident)
                    before = self.back._load()
                    edit(ident, 'б' * length)
                    self.assertNotEqual(self.back._load(), before)
                before = self.back._load()
                undo = self.back._undo_state
                self.back2.cloud.reset_mock()
                self.assertFalse(create('в' * (limit + 1)))
                self.assertFalse(edit(ident, 'г' * (limit + 1)))
                self.assertEqual(self.back._load(), before)
                self.assertEqual(self.back._undo_state, undo)
                self.back2.cloud.alg_for_redact.assert_not_called()

    def test_group_limit_includes_surrounding_spaces(self):
        for kind in ('tasks', 'notes'):
            self.assertIsNone(self.back.create_group(' ' + 'а' * 100, group_type=kind))
        self.assertFalse(self.back.rename_group('default', 'а' * 100 + ' '))


class TextLengthUITests(unittest.TestCase):
    def setUp(self):
        self.front = make_front()
        self.front._update_control = Mock()
        self.front.open_page = Mock()
        self.front.open_modified_dialog = Mock()
        self.front.close_page = Mock()
        self.front.show_groups = Mock()

    def assert_rejected(self, entry, save, limit=1000):
        before = self.front.back._load()
        entry.value = 'я' * (limit + 1)
        self.front.cloud.reset_mock()
        self.front.close_page.reset_mock()
        save(None)
        self.assertEqual(entry.error, f'Максимум {limit} символов. Сейчас: {limit + 1}.')
        self.assertEqual(entry.value, 'я' * (limit + 1))
        self.assertEqual(self.front.back._load(), before)
        self.front.close_page.assert_not_called()
        self.front.cloud.alg_for_redact.assert_not_called()

    def test_task_create_edit_and_legacy_display(self):
        front = self.front
        self.assertEqual(front.entry_task.helper, '0/1000 символов')
        self.assert_rejected(front.entry_task, front.create_task.on_click)
        front.entry_task.value = 'я' * 1000
        front.create_task.on_click(None)
        self.assertIsNone(front.entry_task.error)
        self.assertEqual(front.back.read_tasks()[0]['name'], 'я' * 1000)
        front.render_daily_repeat_tasks()
        card = next(c for c in front.tasks_cont.content.controls if isinstance(c.data, str))
        task_menu(card).items[0].on_click(None)
        self.assert_rejected(front.libs.entry_task, front.libs.entry_task.on_submit)
        data = front.back._load()
        data['tasks'][0]['name'] = 'я' * 1001
        front.back._save(data)
        front.render_daily_repeat_tasks()
        self.assertTrue(any(c.data == 'я' * 1001 for c in front.tasks_cont.content.controls))

    def test_note_create_and_edit(self):
        front = self.front
        group = front.back.create_group('Заметки', group_type='notes')
        front.current_group_id = group
        note_id = front.back.save_note(group, 'Текст')
        for note in (None, front.back.read_notes(group)[0]):
            front.open_note_editor(note)
            self.assertEqual(front.libs.entry_task.helper,
                             f"{len(note['text']) if note else 0}/1000 символов")
            form = front.open_page.call_args.args[1]
            save = form.content.controls[-1].controls[0].on_click
            self.assert_rejected(front.libs.entry_task, save)
            front.libs.entry_task.value = 'я' * 1000
            save(None)
            self.assertIsNone(front.libs.entry_task.error)
        self.assertEqual(next(n['text'] for n in front.back.read_notes(group) if n['id'] == note_id), 'я' * 1000)

    def test_group_create_and_edit_for_both_types(self):
        front = self.front
        for kind in ('tasks', 'notes'):
            front._open_create_group()
            form = front.open_modified_dialog.call_args.args[1]
            selector = next(c for c in form.content.controls if isinstance(c, ft.Dropdown))
            selector.value = kind
            self.assertEqual(front.libs.entry_task.helper, '0/100 символов')
            self.assert_rejected(front.libs.entry_task, front.libs.entry_task.on_submit, 100)
            group_id = front.back.create_group('Группа', group_type=kind)
            group = next(g for g in front.back.get_groups() if g['id'] == group_id)
            column = ft.Column()
            front._append_group_row(column, group, Mock())
            column.controls[0].controls[1].items[0].on_click(None)
            self.assertEqual(front.libs.entry_task.helper, '6/100 символов')
            self.assert_rejected(front.libs.entry_task, front.libs.entry_task.on_submit, 100)

    def test_special_task_create_and_edit(self):
        front = self.front
        repeat = front.back2.create_repeat_task('Повтор')
        postponed = front.back2.create_postponed_task('Позже', '01-01-2030')
        for open_form in (
            front.open_repeat_dialog,
            front.open_postponed_dialog,
            lambda: front.open_edit_repeat_dialog('Повтор', 'day', 1, 'default', repeat),
            lambda: front.open_edit_postponed_dialog('Позже', '01-01-2030', 'default', postponed),
        ):
            open_form()
            self.assert_rejected(front.libs.entry_task, front.libs.entry_task.on_submit)


if __name__ == '__main__':
    unittest.main()
