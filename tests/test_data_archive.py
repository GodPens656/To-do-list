import asyncio
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zipfile import ZipFile

import flet as ft

from Backend.attachments import make_attachment
from Backend.core import Backend
from Backend.crypto import encrypt_bytes, is_encrypted
from Backend.data_archive import create_data_archive, read_data_archive
from Backend.storage import SECTION_FILENAMES, empty_data, save_all_sections
from Backend.webstorage import WebSessionStore
from Frontend.libs import Fr_Libs
from Frontend.settings import Utils2


def sample_data():
    data = empty_data()
    data['tasks'] = [{'id': 'new', 'name': 'Новое дело', 'group': 'default', 'status': True,
                      'attachments': [make_attachment('документ.txt', b'important content')]}]
    data['groups'].append({'id': 'notes', 'name': 'Заметки', 'type': 'notes',
                           'notes': [{'id': 'note', 'text': 'Запись'}]})
    data['repeat_tasks'] = [{'id': 'repeat', 'name': 'Повтор', 'repeat_type': 'day', 'repeat_value': 1}]
    data['postponed'] = [{'id': 'later', 'name': 'Позже', 'date': '05-11-2026'}]
    data['achievements'] = [{'task_id': 'new', 'date': '2026-11-04'}]
    return data


def archive_with_files(files):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


class DataArchiveTests(unittest.TestCase):
    def make_backend(self, directory, web=False):
        back = Backend.__new__(Backend)
        back.web = web
        back.data_dir = Path(directory)
        back.store = WebSessionStore(SimpleNamespace())
        back.cloud = Mock()
        back.cloud.check_user_data.return_value = False
        back.on_data_change = Mock()
        return back

    def test_round_trip_replaces_all_sections_native_and_web(self):
        for web in (False, True):
            with self.subTest(web=web), tempfile.TemporaryDirectory() as directory:
                back = self.make_backend(directory, web)
                back.import_data_archive(create_data_archive(sample_data()))
                expected = back._load()
                exported = back.export_data_archive()
                with ZipFile(BytesIO(exported)) as archive:
                    self.assertEqual(set(archive.namelist()), set(SECTION_FILENAMES.values()))
                    self.assertEqual(json.loads(archive.read('tasks.json')), expected['tasks'])
                back._save(empty_data())
                back._undo_state = ('old', 'state')
                back.import_data_archive(exported)
                self.assertEqual(back._load(), expected)
                self.assertIsNone(back._undo_state)
                back.on_data_change.assert_called()
                if not web:
                    self.assertTrue(is_encrypted((Path(directory) / 'tasks.json').read_bytes()))

    def test_invalid_archives_leave_existing_data_untouched(self):
        files = {name: json.dumps(sample_data()[key]) for key, name in SECTION_FILENAMES.items()}
        invalid = [b'not zip', archive_with_files({'tasks.json': '[]'})]
        for name, value in [('tasks.json', '{'), ('groups.json', '{}'),
                            ('postponed.json', '[42]'), ('groups.json', '[{}]'),
                            ('tasks.json', '[{"attachments":[{"content":"broken!"}]}]'),
                            ('../tasks.json', '[]')]:
            invalid.append(archive_with_files({**files, name: value}))
        with tempfile.TemporaryDirectory() as directory:
            back = self.make_backend(directory)
            back.import_data_archive(create_data_archive(sample_data()))
            before = back._load()
            for content in invalid:
                with self.subTest(content=content[:15]), self.assertRaises(ValueError):
                    back.import_data_archive(content)
                self.assertEqual(back._load(), before)

    def test_older_archive_without_achievements_and_encrypted_sections(self):
        expected = sample_data()
        files = {('group.json' if key == 'groups' else name): encrypt_bytes(json.dumps(value).encode())
                 for key, name in SECTION_FILENAMES.items()
                 if key != 'achievements' for value in [expected[key]]}
        data = read_data_archive(archive_with_files(files))
        self.assertEqual(data['tasks'], expected['tasks'])
        self.assertEqual(data['achievements'], [])

    def test_failed_write_restores_original_bytes_and_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            back = self.make_backend(directory)
            save_all_sections(directory, empty_data(), force=True)
            originals = {path: path.read_bytes() for path in Path(directory).glob('*.json')}
            back._undo_state = 'previous'

            def fail_halfway(data_dir, data, force=False):
                save_all_sections(data_dir, {'groups': data['groups']}, force=True)
                raise OSError('disk failure')

            with patch('Backend.storage.save_all_sections', side_effect=fail_halfway):
                with self.assertRaises(OSError):
                    back.import_data_archive(create_data_archive(sample_data()))
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)
            self.assertEqual(back._undo_state, 'previous')
            back.on_data_change.assert_not_called()

    def test_archive_size_limit_and_account_quota_are_checked_before_replacement(self):
        content = create_data_archive(sample_data())
        with patch('Backend.data_archive.MAX_ARCHIVE_BYTES', len(content) - 1):
            with self.assertRaises(ValueError):
                read_data_archive(content)
        with tempfile.TemporaryDirectory() as directory:
            back = self.make_backend(directory, web=True)
            back.cloud.check_user_data.return_value = True
            with patch('Backend.attachments.MAX_ACCOUNT_BYTES', 1):
                with self.assertRaises(ValueError):
                    back.import_data_archive(content)
            self.assertEqual(back._load(), empty_data())


class DataArchiveUiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Utils2.__new__(Utils2)
        self.settings.libs = Fr_Libs('light', False)
        self.settings.TxtColor = self.settings.libs.TxtColor
        self.settings.back = Mock()
        self.settings.back.page.web = True
        self.settings.cloud = Mock()
        self.rebuild = Mock()
        self.import_button, self.export_button, self.status = self.settings.build_widgets_for_data_archive(self.rebuild)
        self.content = create_data_archive(sample_data())
        self.picker = Mock(pick_files=AsyncMock(return_value=[SimpleNamespace(
            size=len(self.content), bytes=self.content, path=None)]),
            save_file=AsyncMock(return_value='download.zip'))
        self.picker_patch = patch('Frontend.settings.file_picker', return_value=self.picker)
        self.picker_patch.start()
        self.addCleanup(self.picker_patch.stop)

    async def test_import_requires_confirmation_then_rebuilds_and_syncs(self):
        def confirm(dialog):
            self.settings.back.import_data_archive.assert_not_called()
            asyncio.create_task(dialog.actions[1].on_click(None))
        self.settings.back.page.show_dialog.side_effect = confirm
        await self.import_button.on_click(None)
        self.settings.back.import_data_archive.assert_called_once_with(self.content)
        self.rebuild.assert_called_once_with()
        self.settings.cloud.alg_for_redact.assert_called_once_with()
        self.assertFalse(self.import_button.disabled)

    async def test_cancellation_and_invalid_archive_never_replace_data(self):
        self.settings.back.page.show_dialog.side_effect = lambda dialog: asyncio.create_task(dialog.actions[0].on_click(None))
        await self.import_button.on_click(None)
        self.settings.back.import_data_archive.assert_not_called()
        self.picker.pick_files.return_value[0].bytes = b'invalid'
        self.settings.back.page.show_dialog.reset_mock()
        await self.import_button.on_click(None)
        self.settings.back.import_data_archive.assert_not_called()
        self.settings.back.page.show_dialog.assert_not_called()
        self.assertIn('Не удалось', self.status.value)
        self.assertFalse(self.import_button.disabled)

    async def test_export_downloads_bytes_in_browser_and_writes_desktop_destination(self):
        self.settings.back.export_data_archive.return_value = self.content
        await self.export_button.on_click(None)
        self.assertEqual(self.picker.save_file.call_args.kwargs['src_bytes'], self.content)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'export.zip'
            self.settings.back.page.web = False
            self.settings.back.page.platform = ft.PagePlatform.WINDOWS
            self.picker.save_file.return_value = str(destination)
            await self.export_button.on_click(None)
            self.assertEqual(destination.read_bytes(), self.content)
        self.assertFalse(self.export_button.disabled)

    async def test_import_updates_real_list_when_previous_group_disappears(self):
        from test_ui_state import make_front

        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                old_group = front.back.create_group('Прежняя группа')
                front.current_group_id = old_group
                front.back.saveB('Прежнее дело', old_group)
                front.render_daily_repeat_tasks()
                front.open_settings()
                controls = front.utils2.build_widgets_for_data_archive(front.render_daily_repeat_tasks)
                front.page.show_dialog.side_effect = lambda dialog: asyncio.create_task(dialog.actions[1].on_click(None))
                await controls[0].on_click(None)
                self.assertEqual([task['name'] for task in front.back.read_tasks()], ['Новое дело'])
                self.assertNotEqual(front.current_group_id, old_group)
                self.assertIn('Без группы', [group['name'] for group in front.back.get_groups()])
                self.assertIn('Данные импортированы', controls[2].value)


if __name__ == '__main__':
    unittest.main()
