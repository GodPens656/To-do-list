import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.core import Backend
from Backend.attachments import AttachmentQuotaError, attachment_bytes, attachment_usage, make_attachment
from Backend.storage import load_data, save_data, save_all_sections
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front


class NoteStorageTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock(_nd_timezone='Europe/Moscow')
        self.store = WebSessionStore(self.page)
        self.back = Backend(page=self.page, web_store=self.store, cloud=Mock())

    def test_legacy_groups_remain_tasks_and_notes_are_separate(self):
        self.assertEqual(self.back.get_group_type('default'), 'tasks')
        self.back.saveB('Старое дело')
        tasks = self.back.read_tasks()
        group_id = self.back.create_group('Идеи', group_type='notes')
        text = 'Первая строка\n\nВторая строка | --- {N}'
        note_id = self.back.save_note(group_id, text)
        self.assertIsNotNone(note_id)
        self.assertIsNone(self.back.save_note('default', text))
        self.assertIsNone(self.back.save_note(group_id, ' \n '))
        self.assertEqual(self.back.read_notes(group_id)[0]['text'], text)
        self.back.rename_group(group_id, 'Личные заметки')
        self.back.update_group_settings(group_id, show_created_date=False)
        self.back.save_note(group_id, 'Новый текст\nЕщё строка', note_id)
        self.assertEqual(len(self.back.read_notes(group_id)), 1)
        self.assertEqual(self.back.read_tasks(), tasks)
        self.assertTrue(self.back.delete_note(group_id, note_id))
        self.assertEqual(self.back.read_notes(group_id), [])
        self.back.save_note(group_id, text)
        self.back.delete_group(group_id)
        self.assertEqual(self.back.read_notes(group_id), [])
        self.assertEqual(self.back.read_tasks(), tasks)

    def test_notes_survive_native_browser_and_cloud_payload_round_trips(self):
        group_id = self.back.create_group('Записи', group_type='notes')
        self.back.save_note(group_id, 'Сохранённая заметка\nс переносом',
                            attachments=[make_attachment('данные.bin', bytes(range(256)))])
        expected = self.back.read_notes(group_id)
        with tempfile.TemporaryDirectory() as directory:
            save_all_sections(directory, self.store.load_all_sections())
            native = Backend.__new__(Backend)
            native.web = False
            native.data_dir = Path(directory)
            self.assertEqual(native.read_notes(group_id), expected)
            self.assertEqual(native.get_group_type(group_id), 'notes')
            path = Path(directory) / 'payload.json'
            save_data(path, native._load())
            cloud_store = WebSessionStore(Mock())
            cloud_store.replace_from_cloud(load_data(path))
            self.assertEqual(cloud_store.load_all_sections()['groups'], native._load()['groups'])
        values = {}
        async def set_value(key, value):
            values[key] = value
        self.page.shared_preferences = Mock(
            get=AsyncMock(side_effect=lambda key: values.get(key)),
            set=AsyncMock(side_effect=set_value),
        )
        asyncio.run(self.store._persist_async())
        reopened_store = WebSessionStore(self.page)
        asyncio.run(reopened_store.load())
        reopened = Backend(page=self.page, web_store=reopened_store, cloud=Mock())
        self.assertEqual(reopened.read_notes(group_id), expected)

    def test_note_files_are_copied_preserved_on_text_edit_and_restored_by_undo(self):
        group_id = self.back.create_group('Файлы', group_type='notes')
        files = [make_attachment('file.txt', b'contents')]
        note_id = self.back.save_note(group_id, 'Текст', attachments=files)
        files[0]['name'] = 'changed.txt'
        notes = self.back.read_notes(group_id)
        self.assertEqual(notes[0]['attachments'][0]['name'], 'file.txt')
        notes[0]['attachments'].clear()
        self.back.save_note(group_id, 'Изменённый текст', note_id)
        self.assertEqual(attachment_bytes(self.back.read_notes(group_id)[0]['attachments'][0]), b'contents')
        self.back.save_note(group_id, 'Без файла', note_id, attachments=[])
        self.assertEqual(self.back.read_notes(group_id)[0]['attachments'], [])
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(len(self.back.read_notes(group_id)[0]['attachments']), 1)
        self.back.delete_note(group_id, note_id)
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(attachment_bytes(self.back.read_notes(group_id)[0]['attachments'][0]), b'contents')

    def test_notes_and_tasks_share_quota_and_replacements_credit_existing_files(self):
        group_id = self.back.create_group('Файлы', group_type='notes')
        self.back.cloud.check_user_data.return_value = True
        with patch('Backend.attachments.MAX_ACCOUNT_BYTES', 10):
            self.back.saveB('Дело', attachments=[make_attachment('task.txt', b'1234')])
            note_id = self.back.save_note(group_id, 'Заметка', attachments=[make_attachment('note.txt', b'123456')])
            self.assertEqual(attachment_usage(self.back._load()), 10)
            self.back.validate_attachment_selection(
                [make_attachment('replacement.txt', b'abcdef')], note_id, 'notes', group_id=group_id)
            with self.assertRaises(AttachmentQuotaError):
                self.back.validate_attachment_selection(
                    [make_attachment('extra.txt', b'x')], section='notes', group_id=group_id)
            with self.assertRaises(AttachmentQuotaError):
                self.back.save_note(group_id, 'Ещё заметка', attachments=[make_attachment('extra.txt', b'x')])
            self.assertEqual(len(self.back.read_notes(group_id)), 1)
            self.back.save_note(group_id, 'Текст изменён', note_id)
            self.back.save_note(group_id, 'Без файла', note_id, attachments=[])
            self.assertEqual(attachment_usage(self.back._load()), 4)


class NoteGroupUITests(unittest.TestCase):
    def test_attachment_create_cancel_edit_remove_and_quota_error_on_both_layouts(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.page.services = []
                front.open_page = Mock()
                front.close_page = Mock()
                group_id = front.back.create_group('Файлы', group_type='notes')
                front.current_group_id = group_id

                def editor(note=None):
                    front.open_note_editor(note)
                    form = front.open_page.call_args.args[1]
                    files = form.content.controls[-2].controls[0].on_click.__self__
                    save = form.content.controls[-1].controls[0]
                    return files, save

                files, save = editor()
                selected = SimpleNamespace(name='файл.txt', bytes=b'original', size=8, path=None)
                with patch.object(ft.FilePicker, 'pick_files', new=AsyncMock(return_value=[selected])) as pick:
                    asyncio.run(files.pick(None))
                self.assertIn('заметке', pick.call_args.kwargs['dialog_title'])
                front.libs.entry_task.value = 'С файлом'
                save.on_click(None)
                note = front.back.read_notes(group_id)[0]
                self.assertEqual(attachment_bytes(note['attachments'][0]), b'original')
                card = next(c for c in front.tasks_cont.content.controls if c.data == note['text'])

                def descendants(control):
                    yield control
                    for child in getattr(control, 'controls', None) or []:
                        yield from descendants(child)
                    content = getattr(control, 'content', None)
                    if isinstance(content, ft.Control):
                        yield from descendants(content)

                self.assertTrue(any(isinstance(c, ft.IconButton) and c.tooltip == 'Скачать файл'
                                    for c in descendants(card)))
                files, save = editor(note)
                files.remove(files.attachments[0])
                front.close_page()  # Cancelled draft must not change stored files.
                self.assertEqual(front.back.read_notes(group_id)[0]['attachments'], note['attachments'])
                files, save = editor(note)
                files.remove(files.attachments[0])
                save.on_click(None)
                self.assertEqual(front.back.read_notes(group_id)[0]['attachments'], [])
                self.assertTrue(front.back.undo_last_action())
                self.assertEqual(front.back.read_notes(group_id)[0]['attachments'], note['attachments'])
                files, save = editor()
                self.assertEqual(files.values(), [])
                front.back.cloud.check_user_data.return_value = True
                with patch('Backend.attachments.MAX_ACCOUNT_BYTES', 10):
                    with patch.object(ft.FilePicker, 'pick_files', new=AsyncMock(return_value=[selected])):
                        asyncio.run(files.pick(None))
                    self.assertTrue(files.error.visible)
                    self.assertEqual(files.values(), [])
                    smaller = SimpleNamespace(name='draft.txt', bytes=b'12', size=2, path=None)
                    with patch.object(ft.FilePicker, 'pick_files', new=AsyncMock(return_value=[smaller])):
                        asyncio.run(files.pick(None))
                    self.assertFalse(files.error.visible)
                    front.back.saveB('Между выбором и сохранением', attachments=[make_attachment('one', b'1')])
                    front.close_page.reset_mock()
                    front.libs.entry_task.value = 'Черновик'
                    save.on_click(None)
                    front.close_page.assert_not_called()
                    self.assertEqual(len(front.back.read_notes(group_id)), 1)
                    self.assertEqual(len(files.values()), 1)
                    self.assertEqual(front.page.show_dialog.call_args.args[0].title.value, ' Лимит вложений')

    def test_create_group_form_selects_type(self):
        front = make_front()
        front.open_modified_dialog = Mock()
        front._open_create_group()
        _, form, _ = front.open_modified_dialog.call_args.args
        selector = next(c for c in form.content.controls if isinstance(c, ft.Dropdown) and c.label == 'Тип группы')
        self.assertEqual(selector.value, 'tasks')
        selector.value = 'notes'
        front.libs.entry_task.value = 'Мои заметки'
        front.libs.entry_task.on_submit(None)
        group = next(g for g in front.back.get_groups() if g['name'] == 'Мои заметки')
        self.assertEqual(group['type'], 'notes')

    def test_notes_render_search_edit_delete_and_return_to_tasks(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front._update_control = Mock()
                front.back.saveB('Обычное дело')
                group_id = front.back.create_group('Идеи', group_type='notes')
                front.back.save_note(group_id, 'Идея\nдля проекта')
                front.current_group_id = group_id
                front.render_daily_repeat_tasks()
                cards = lambda: [c for c in front.tasks_cont.content.controls if isinstance(c.data, str)]
                def actions(card):
                    return card.content.controls[1 if phone else 0].content.controls
                self.assertFalse(front.filter_btn.visible)
                self.assertFalse(front.task_progress.visible)
                self.assertEqual(front.task_summary.value, 'Заметок: 1')
                self.assertFalse(any(isinstance(c, ft.Checkbox) for c in cards()[0].content.controls))
                self.assertNotIn(group_id, [o.key for o in front.create_group_dropdown().options])
                front.apply_search_filter('ПРОЕКТА')
                self.assertTrue(cards()[0].visible)
                front.apply_search_filter('нет совпадений')
                self.assertTrue(front.empty_state.visible)
                front.apply_search_filter('')
                front.open_page = Mock()
                front.close_page = Mock()
                front.button_add_task.on_click(None)
                _, new_form, _, _ = front.open_page.call_args.args
                front.libs.entry_task.value = 'Новая заметка'
                new_form.content.controls[-1].controls[0].on_click(None)
                self.assertEqual(len(front.back.read_notes(group_id)), 2)
                actions(cards()[1])[1].on_click(None)
                actions(cards()[0])[0].on_click(None)
                _, form, _, _ = front.open_page.call_args.args
                entry = front.libs.entry_task
                self.assertEqual(entry.value, 'Идея\nдля проекта')
                self.assertIsNone(entry.on_submit)
                # The form's last row holds Save and Cancel.
                save = form.content.controls[-1].controls[0]
                entry.value = ' '
                save.on_click(None)
                self.assertEqual(entry.error, 'Введите текст заметки')
                entry.value = 'Изменено\n\nс переносом'
                save.on_click(None)
                self.assertEqual(cards()[0].data, entry.value)
                actions(cards()[0])[1].on_click(None)
                self.assertEqual(front.back.read_notes(group_id), [])
                self.assertEqual(front.empty_title.value, ' Здесь пока нет заметок')
                front.current_group_id = 'default'
                front.render_daily_repeat_tasks()
                self.assertTrue(front.filter_btn.visible)
                self.assertTrue(front.task_progress.visible)
                self.assertEqual(cards()[0].data, 'Обычное дело')


if __name__ == '__main__':
    unittest.main()
