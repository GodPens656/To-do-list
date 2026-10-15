import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Backend.cloud import BACKUP_CHECK_SECONDS, BACKUP_RETRY_SECONDS, Cloud
from Backend.crypto import encrypt_bytes
from Backend.storage import SECTION_FILENAMES
from Backend.webstorage import WebSessionStore


class MemoryDisk:
    """Модель облака: реальные пути/байты, без сети и настоящих аккаунтов."""

    def __init__(self):
        self.dirs = {'/For_to-do', '/For_to-do/user_password'}
        self.files = {
            '/For_to-do/user_password/' + name: encrypt_bytes(b'[{"id":"saved"}]')
            for name in SECTION_FILENAMES.values()
        }
        self.copy = Mock(side_effect=self._copy)
        self.move = Mock(side_effect=self._move)

    def exists(self, path):
        return path in self.dirs or path in self.files

    def mkdir(self, path):
        if self.exists(path):
            raise FileExistsError()
        if path.rsplit('/', 1)[0] not in self.dirs:
            raise FileNotFoundError()
        self.dirs.add(path)

    def listdir(self, path):
        if path not in self.dirs:
            raise FileNotFoundError()
        return [
            SimpleNamespace(name=item.rsplit('/', 1)[1], type=kind)
            for paths, kind in ((self.dirs, 'dir'), (self.files, 'file'))
            for item in paths if item.rsplit('/', 1)[0] == path
        ]

    def _copy(self, source, target, **kwargs):
        if source not in self.files:
            raise FileNotFoundError()
        if self.exists(target) and not kwargs.get('overwrite'):
            raise FileExistsError()
        self.files[target] = self.files[source]

    def _move(self, source, target, **kwargs):
        if self.exists(target) and not kwargs.get('overwrite'):
            raise FileExistsError()
        for path in list(self.files):
            if path.startswith(source + '/'):
                self.files[target + path[len(source):]] = self.files.pop(path)
        self.dirs.remove(source)
        self.dirs.add(target)

    def remove(self, path, **kwargs):
        self.dirs.remove(path)
        self.files = {key: value for key, value in self.files.items()
                      if not key.startswith(path + '/')}


class BackupTests:
    web = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.disk = MemoryDisk()
        self.cloud = self.make_cloud()
        self.cloud.write_user_data_text('user_password~~user~~password')
        self.today = date(2026, 9, 19)
        self.backups = '/For_to-do/user_password/backups'

    def make_cloud(self):
        cloud = Cloud.__new__(Cloud)
        cloud.web = self.web
        cloud.web_store = WebSessionStore(Mock()) if self.web else None
        cloud.user_data = Path(self.temp.name) / 'user_data.txt'
        cloud._sync_lock = threading.RLock()
        cloud._upload_cv = threading.Condition()
        cloud._pending_login_password = None
        cloud._backup_checks = {}
        cloud.disk = self.disk
        return cloud

    def test_guest_does_not_access_cloud(self):
        self.cloud.write_user_data_text('')
        self.cloud.disk = Mock()
        self.assertFalse(self.cloud.create_weekly_backup(self.today))
        self.cloud._check_weekly_backup()
        self.assertEqual(self.cloud.disk.mock_calls, [])

    def test_copies_exactly_four_files_preserving_encrypted_bytes(self):
        original = dict(self.disk.files)
        self.assertTrue(self.cloud.create_weekly_backup(self.today))
        target = self.backups + '/backup_19.09.2026'
        self.assertEqual({entry.name for entry in self.disk.listdir(target)},
                         set(SECTION_FILENAMES.values()))
        for name in SECTION_FILENAMES.values():
            self.assertEqual(self.disk.files[target + '/' + name],
                             original['/For_to-do/user_password/' + name])
        self.assertEqual(self.disk.copy.call_count, 4)
        for call in self.disk.copy.call_args_list:
            self.assertTrue(call.kwargs['wait'])
            self.assertFalse(call.kwargs['overwrite'])
        self.assertTrue(self.disk.move.call_args.kwargs['wait'])
        self.assertFalse(self.disk.move.call_args.kwargs['overwrite'])
        self.assertFalse(any('.pending_' in path for path in self.disk.dirs))

    def test_repeat_only_after_seven_days_and_keeps_old_backup(self):
        self.assertTrue(self.cloud.create_weekly_backup(self.today))
        old = dict(self.disk.files)
        self.assertFalse(self.cloud.create_weekly_backup(self.today))
        self.assertFalse(self.cloud.create_weekly_backup(date(2026, 9, 25)))
        self.assertTrue(self.cloud.create_weekly_backup(date(2026, 9, 26)))
        for path, payload in old.items():
            self.assertEqual(self.disk.files[path], payload)
        self.assertEqual(self.disk.copy.call_count, 8)

    def test_restart_or_second_device_uses_cloud_history(self):
        self.cloud.create_weekly_backup(self.today)
        restarted = self.make_cloud()
        restarted.write_user_data_text('user_password~~user~~password')
        self.assertFalse(restarted.create_weekly_backup(date(2026, 9, 20)))
        self.assertEqual(self.disk.copy.call_count, 4)

    def test_overdue_backup_uses_actual_date_across_year_boundary(self):
        self.cloud.create_weekly_backup(date(2025, 12, 30))
        self.assertFalse(self.cloud.create_weekly_backup(date(2026, 1, 5)))
        self.assertTrue(self.cloud.create_weekly_backup(date(2026, 2, 10)))
        self.assertIn(self.backups + '/backup_10.02.2026', self.disk.dirs)

    def test_failed_copy_is_not_published_and_can_be_retried(self):
        copy_file = self.disk._copy

        def fail_third(source, target, **kwargs):
            if self.disk.copy.call_count == 3:
                raise TimeoutError('offline')
            copy_file(source, target, **kwargs)

        self.disk.copy.side_effect = fail_third
        with self.assertRaises(TimeoutError):
            self.cloud.create_weekly_backup(self.today)
        self.assertEqual(self.disk.listdir(self.backups), [])
        self.disk.copy.side_effect = copy_file
        self.assertTrue(self.cloud.create_weekly_backup(self.today))

    def test_missing_source_does_not_create_partial_backup(self):
        self.disk.files.pop('/For_to-do/user_password/repeat_tasks.json')
        with self.assertRaises(FileNotFoundError):
            self.cloud.create_weekly_backup(self.today)
        self.assertEqual(self.disk.listdir(self.backups), [])

    def test_concurrent_device_cannot_overwrite_published_backup(self):
        target = self.backups + '/backup_19.09.2026'

        def other_device_finishes_first(source, destination, **kwargs):
            self.disk.mkdir(destination)
            for name in SECTION_FILENAMES.values():
                self.disk.files[destination + '/' + name] = b'other device snapshot'
            self.disk._move(source, destination, **kwargs)

        self.disk.move.side_effect = other_device_finishes_first
        with self.assertRaises(FileExistsError):
            self.cloud.create_weekly_backup(self.today)
        self.assertFalse(self.cloud.create_weekly_backup(self.today))
        for name in SECTION_FILENAMES.values():
            self.assertEqual(self.disk.files[target + '/' + name], b'other device snapshot')
        self.assertFalse(any('.pending_' in path for path in self.disk.dirs))

    def test_other_account_has_independent_history(self):
        self.cloud.create_weekly_backup(self.today)
        self.disk.mkdir('/For_to-do/second_password')
        for name in SECTION_FILENAMES.values():
            self.disk.files['/For_to-do/second_password/' + name] = b'second account'
        self.cloud.write_user_data_text('second_password~~second~~password')
        self.assertTrue(self.cloud.create_weekly_backup(self.today))
        for name in SECTION_FILENAMES.values():
            self.assertEqual(self.disk.files[
                '/For_to-do/second_password/backups/backup_19.09.2026/' + name
            ], b'second account')

    def test_logout_during_copy_cancels_publication(self):
        def logout(source, target, **kwargs):
            self.disk._copy(source, target, **kwargs)
            self.cloud.write_user_data_text('')

        self.disk.copy.side_effect = logout
        self.assertFalse(self.cloud.create_weekly_backup(self.today))
        self.assertEqual(self.disk.copy.call_count, 1)
        self.assertEqual(self.disk.listdir(self.backups), [])

    def test_unfinished_and_invalid_folders_do_not_delay_backup(self):
        self.disk.mkdir(self.backups)
        for name in ('.pending_abandoned', 'backup_18.09.2026', 'backup_invalid'):
            self.disk.mkdir(self.backups + '/' + name)
        self.assertTrue(self.cloud.create_weekly_backup(self.today))

    def test_checks_are_throttled_and_failures_retry_sooner(self):
        self.cloud.create_weekly_backup = Mock(side_effect=[TimeoutError(), True, False])
        with patch('Backend.cloud.time.monotonic', return_value=1000) as clock:
            self.cloud._check_weekly_backup()
            self.cloud._check_weekly_backup()
            self.assertEqual(self.cloud.create_weekly_backup.call_count, 1)
            clock.return_value += BACKUP_RETRY_SECONDS
            self.cloud._check_weekly_backup()
            self.assertEqual(self.cloud.create_weekly_backup.call_count, 2)
            clock.return_value += BACKUP_CHECK_SECONDS - 1
            self.cloud._check_weekly_backup()
            self.assertEqual(self.cloud.create_weekly_backup.call_count, 2)
            clock.return_value += 1
            self.cloud._check_weekly_backup()
            self.assertEqual(self.cloud.create_weekly_backup.call_count, 3)

    def test_idle_worker_checks_backups_without_task_edits(self):
        self.cloud._check_weekly_backup = Mock()
        with patch.object(self.cloud._upload_cv, 'wait', side_effect=[None, SystemExit]) as wait:
            with self.assertRaises(SystemExit):
                self.cloud._upload_worker()
        self.assertEqual(self.cloud._check_weekly_backup.call_count, 2)
        wait.assert_called_with(timeout=BACKUP_RETRY_SECONDS)

    def test_login_wakes_worker(self):
        with patch.object(self.cloud._upload_cv, 'notify') as notify:
            self.cloud.write_user_data_text('user_password~~user~~password')
        notify.assert_called_once_with()

    def test_manual_backup_once_per_day_and_survives_restart(self):
        self.assertTrue(self.cloud.create_manual_backup(self.today))
        self.assertFalse(self.cloud.create_manual_backup(self.today))
        restarted = self.make_cloud()
        restarted.write_user_data_text('user_password~~user~~password')
        self.assertFalse(restarted.create_manual_backup(self.today))
        self.assertEqual(self.disk.copy.call_count, 4)
        self.assertTrue(restarted.create_manual_backup(date(2026, 9, 20)))
        self.assertIn(self.backups + '/backup_19.09.2026', self.disk.dirs)
        self.assertIn(self.backups + '/backup_20.09.2026', self.disk.dirs)

    def test_manual_and_automatic_backups_share_daily_limit_and_schedule(self):
        self.assertTrue(self.cloud.create_weekly_backup(self.today))
        self.assertFalse(self.cloud.create_manual_backup(self.today))
        self.assertTrue(self.cloud.create_manual_backup(date(2026, 9, 20)))
        self.assertFalse(self.cloud.create_weekly_backup(date(2026, 9, 26)))
        self.assertTrue(self.cloud.create_weekly_backup(date(2026, 9, 27)))

    def test_manual_failure_does_not_consume_daily_limit(self):
        self.disk.copy.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.cloud.create_manual_backup(self.today)
        self.assertEqual(self.disk.listdir(self.backups), [])
        self.disk.copy.side_effect = self.disk._copy
        self.assertTrue(self.cloud.create_manual_backup(self.today))

    def test_manual_guest_does_not_access_cloud(self):
        self.cloud.write_user_data_text('')
        self.cloud.disk = Mock()
        self.assertFalse(self.cloud.create_manual_backup(self.today))
        self.assertEqual(self.cloud.disk.mock_calls, [])

    def test_concurrent_manual_requests_create_only_one_backup(self):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                self.cloud.create_manual_backup, [self.today, self.today]
            ))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.disk.copy.call_count, 4)


class NativeBackupTests(BackupTests, unittest.TestCase):
    pass


class WebBackupTests(BackupTests, unittest.TestCase):
    web = True


if __name__ == '__main__':
    unittest.main()
