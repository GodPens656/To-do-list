import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from Backend.cloud import Cloud
from Backend.crypto import decrypt_bytes, encrypt_bytes
from Backend.storage import SECTION_FILENAMES, empty_data, load_all_sections, save_all_sections
from Backend.webstorage import WebSessionStore


class RefreshProtectionTests:
    web = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = WebSessionStore(Mock()) if self.web else None
        self.remote = empty_data()
        self.remote['tasks'] = [{'id': 'old', 'name': 'Existing task'}]
        self.cloud = self.make_cloud()
        self.cloud.disk = Mock()
        self.cloud.disk.exists.side_effect = lambda path: path.rsplit('/', 1)[-1] in SECTION_FILENAMES.values()
        self.cloud.disk.download.side_effect = self.download
        self.cloud.disk.upload.side_effect = self.upload
        self.assertTrue(self.cloud.download('account'))

    def make_cloud(self):
        cloud = Cloud.__new__(Cloud)
        cloud.web = self.web
        cloud.web_store = self.store
        cloud.data_dir = self.directory
        cloud.user_data_dir = self.directory / 'user_data'
        cloud._last_synced_versions = {}
        cloud._last_synced_versions_lock = threading.Lock()
        cloud._sync_lock = threading.RLock()
        cloud._upload_state_callback = None
        cloud.request_upload = Mock()
        cloud._load_sync_state()
        return cloud

    def download(self, path, target):
        key = path.rsplit('/', 1)[-1].removesuffix('.json')
        target.write(encrypt_bytes(json.dumps(self.remote[key]).encode()))

    def upload(self, source, path, **kwargs):
        payload = source.read() if isinstance(source, io.BytesIO) else Path(source).read_bytes()
        key = path.rsplit('/', 1)[-1].removesuffix('.json')
        self.remote[key] = json.loads(decrypt_bytes(payload))

    def read(self):
        return self.store.load_all_sections() if self.web else load_all_sections(self.directory)

    def save(self, data):
        if self.web:
            self.store.save_all_sections(data)
        else:
            save_all_sections(self.directory, data)

    def edit(self):
        data = self.read()
        data['tasks'].append({'id': 'new', 'name': 'Unsent task'})
        self.save(data)
        return data['tasks']

    def test_clean_refresh_receives_remote_changes(self):
        self.remote['tasks'].append({'id': 'remote', 'name': 'Other device'})
        self.assertTrue(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], self.remote['tasks'])
        self.assertFalse(self.cloud._section_needs_upload('account', 'tasks'))

    def test_unsent_changes_block_refresh_and_queue_upload(self):
        expected = self.edit()
        self.cloud.disk.download.reset_mock()
        self.assertFalse(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], expected)
        self.cloud.disk.download.assert_not_called()
        self.cloud.request_upload.assert_called_once_with('account')

    def test_failed_upload_then_refresh_keeps_local_tasks(self):
        expected = self.edit()
        self.cloud.disk.upload.side_effect = TimeoutError('upload failed')
        self.cloud.upload('account', max_retries=1)
        self.assertFalse(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], expected)
        self.assertTrue(self.cloud._section_needs_upload('account', 'tasks'))

    def test_successful_upload_allows_refresh_again(self):
        expected = self.edit()
        self.cloud.upload('account')
        self.assertEqual(self.remote['tasks'], expected)
        self.assertTrue(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], expected)

    def test_edit_during_download_rejects_entire_snapshot(self):
        original = self.download
        edited = []

        def download_and_edit(path, target):
            original(path, target)
            if path.endswith('/tasks.json'):
                edited.extend(self.edit())

        self.cloud.disk.download.side_effect = download_and_edit
        self.remote['groups'].append({'id': 'remote', 'name': 'Remote group'})
        self.assertFalse(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], edited)
        self.assertEqual(len(self.read()['groups']), 1)
        self.assertTrue(self.cloud._section_needs_upload('account', 'tasks'))

    def test_edit_during_upload_remains_unsent(self):
        self.edit()
        expected = []

        def upload_and_edit(source, path, **kwargs):
            self.upload(source, path, **kwargs)
            if path.endswith('/tasks.json'):
                expected.extend(self.edit())

        self.cloud.disk.upload.side_effect = upload_and_edit
        self.cloud.upload('account')
        self.assertFalse(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], expected)
        self.assertTrue(self.cloud._section_needs_upload('account', 'tasks'))

    def test_restart_preserves_unsent_changes(self):
        expected = self.edit()
        if self.web:
            # A browser restart resets in-memory revision counters.
            old_store = self.store
            self.store = WebSessionStore(Mock())
            self.store._data = old_store.load_all_sections()
            self.store._meta = copy.deepcopy(old_store._meta)
        restarted = self.make_cloud()
        restarted.disk = self.cloud.disk
        self.assertFalse(restarted.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], expected)
        restarted.request_upload.assert_called_once_with('account')

    def test_first_login_replaces_guest_data(self):
        self.edit()
        self.cloud._last_synced_versions = {}
        self.assertTrue(self.cloud.download('new-account'))
        self.assertEqual(self.read()['tasks'], self.remote['tasks'])

    def test_first_refresh_without_sync_metadata_can_load_account(self):
        self.cloud._last_synced_versions = {}
        self.assertTrue(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], self.remote['tasks'])

    def test_clean_restart_can_receive_remote_changes(self):
        restarted = self.make_cloud()
        restarted.disk = self.cloud.disk
        self.remote['tasks'].append({'id': 'remote', 'name': 'Other device'})
        self.assertTrue(restarted.download('account', preserve_local=True))
        self.assertEqual(self.read()['tasks'], self.remote['tasks'])

    def test_legacy_formats_remain_pending_until_uploaded(self):
        for filename, payload in (
            ('itog.json', json.dumps({'normal': [{'id': 'legacy', 'name': 'Old task'}]})),
            ('itog.txt', 'Old task|False|legacy\n---\n---\n---\n'),
        ):
            with self.subTest(filename=filename):
                self.cloud.disk.exists.side_effect = lambda path: path.endswith('/' + filename)
                self.cloud.disk.download.side_effect = lambda path, target: target.write(encrypt_bytes(payload.encode()))
                self.assertTrue(self.cloud.download('legacy-account'))
                self.assertEqual(self.read()['tasks'][0]['id'], 'legacy')
                self.assertTrue(self.cloud._section_needs_upload('legacy-account', 'tasks'))
                self.cloud.upload('legacy-account')
                self.assertFalse(self.cloud._section_needs_upload('legacy-account', 'tasks'))

    def test_refresh_waits_for_in_flight_upload(self):
        expected = self.edit()
        uploading = threading.Event()
        release = threading.Event()
        refreshing = threading.Event()
        downloaded = threading.Event()
        errors = []

        def slow_upload(source, path, **kwargs):
            if path.endswith('/tasks.json'):
                uploading.set()
                if not release.wait(5):
                    raise TimeoutError('test did not release upload')
            self.upload(source, path, **kwargs)

        def observed_download(path, target):
            downloaded.set()
            self.download(path, target)

        def refresh():
            try:
                refreshing.set()
                self.cloud.download('account', preserve_local=True)
            except Exception as exc:
                errors.append(exc)

        self.cloud.disk.upload.side_effect = slow_upload
        self.cloud.disk.download.side_effect = observed_download
        sender = threading.Thread(target=self.cloud.upload, args=('account',), daemon=True)
        receiver = threading.Thread(target=refresh, daemon=True)
        sender.start()
        try:
            self.assertTrue(uploading.wait(2))
            receiver.start()
            self.assertTrue(refreshing.wait(2))
            self.assertFalse(downloaded.wait(0.1))
        finally:
            release.set()
            sender.join(3)
            if receiver.ident is not None:
                receiver.join(3)
        self.assertFalse(sender.is_alive())
        self.assertFalse(receiver.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.read()['tasks'], expected)

    def test_partial_download_failure_does_not_modify_local_files(self):
        expected = self.read()

        def broken_download(path, target):
            if path.endswith('/tasks.json'):
                target.write(b'broken')
                raise TimeoutError('download interrupted')
            self.download(path, target)

        self.cloud.disk.download.side_effect = broken_download
        self.assertFalse(self.cloud.download('account', preserve_local=True))
        self.assertEqual(self.read(), expected)

    def test_startup_uses_protected_refresh(self):
        expected = self.edit()
        self.cloud.connect = True
        self.cloud.check_user_data = Mock(return_value=True)
        self.cloud.read_user_data_text = Mock(return_value='account~~login~~password')
        self.cloud.alg_for_start_app()
        self.assertEqual(self.read()['tasks'], expected)
        self.cloud.request_upload.assert_called_once_with('account')


class NativeRefreshTests(RefreshProtectionTests, unittest.TestCase):
    pass


class WebRefreshTests(RefreshProtectionTests, unittest.TestCase):
    web = True


if __name__ == '__main__':
    unittest.main()
