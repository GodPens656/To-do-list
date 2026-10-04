import asyncio
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from Backend.cloud import Cloud
from Backend.crypto import decrypt_bytes, encrypt_bytes, is_encrypted
from Backend.storage import (
    SECTION_FILENAMES, empty_data, ensure_split_storage,
    load_all_sections, save_all_sections, save_section,
)
from Backend.json_migration import migrate_legacy_storage
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front


class AccountEncryptionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.data = empty_data()
        self.data["tasks"] = [{"id": "cloud", "name": "Дело из облака 🔒"}]
        self.remote = {
            f"/For_to-do/account/{filename}": encrypt_bytes(json.dumps(self.data[key], ensure_ascii=False).encode())
            for key, filename in SECTION_FILENAMES.items()
        }
        self.disk = Mock()
        self.disk.exists.side_effect = self.remote.__contains__
        self.disk.download.side_effect = lambda path, target: target.write(self.remote[path])
        self.disk.upload.side_effect = self.upload

    def upload(self, source, path, **kwargs):
        self.remote[path] = source.read() if isinstance(source, io.BytesIO) else Path(source).read_bytes()

    def make_cloud(self, web):
        cloud = Cloud.__new__(Cloud)
        cloud.web = web
        cloud.web_store = WebSessionStore(Mock()) if web else None
        cloud.data_dir = self.directory
        cloud.user_data_dir = self.directory / "user_data"
        cloud.disk = self.disk
        cloud.connect = True
        cloud._sync_lock = threading.RLock()
        cloud._last_synced_versions_lock = threading.Lock()
        cloud._last_synced_versions = {}
        cloud._upload_state_callback = None
        cloud.read_user_data_text = Mock(return_value="account~~login~~password")
        cloud.request_upload = Mock()
        return cloud

    def test_disable_reenable_and_future_uploads_on_web_and_native(self):
        for web in (False, True):
            with self.subTest(web=web):
                cloud = self.make_cloud(web)
                self.assertTrue(cloud.account_encryption_enabled("account", refresh=True))
                cloud.set_account_encryption("account", False)
                for key, filename in SECTION_FILENAMES.items():
                    raw = self.remote[f"/For_to-do/account/{filename}"]
                    self.assertFalse(is_encrypted(raw))
                    self.assertEqual(json.loads(raw), self.data[key])
                # A new device gets the account setting from the cloud.
                cloud = self.make_cloud(web)
                self.assertTrue(cloud.download("account"))
                local = cloud.web_store.load_all_sections() if web else load_all_sections(self.directory)
                local["tasks"].append({"id": "new", "name": "Новое дело"})
                if web:
                    cloud.web_store.save_all_sections(local)
                else:
                    save_all_sections(self.directory, local)
                cloud.upload("account")
                self.assertFalse(is_encrypted(self.remote["/For_to-do/account/tasks.json"]))
                self.assertEqual(json.loads(self.remote["/For_to-do/account/tasks.json"]), local["tasks"])
                if not web:
                    self.assertEqual(json.loads((self.directory / "tasks.json").read_bytes()), local["tasks"])
                cloud.set_account_encryption("account", True)
                if not web:
                    self.assertTrue(is_encrypted((self.directory / "tasks.json").read_bytes()))
                for key, filename in SECTION_FILENAMES.items():
                    raw = self.remote[f"/For_to-do/account/{filename}"]
                    self.assertTrue(is_encrypted(raw))
                    self.assertEqual(json.loads(decrypt_bytes(raw)), local[key])
                self.data = local

    def test_conversion_preserves_unsent_local_changes_and_other_accounts(self):
        cloud = self.make_cloud(False)
        local = empty_data()
        local["tasks"] = [{"id": "unsent", "name": "Локальная правка"}]
        save_all_sections(self.directory, local)
        self.remote["/For_to-do/other/tasks.json"] = encrypt_bytes(b"[]")
        other = self.remote["/For_to-do/other/tasks.json"]
        cloud.set_account_encryption("account", False)
        self.assertEqual(json.loads((self.directory / "tasks.json").read_bytes()), local["tasks"])
        self.assertEqual(load_all_sections(self.directory)["tasks"], local["tasks"])
        self.assertEqual(json.loads(self.remote["/For_to-do/account/tasks.json"]), self.data["tasks"])
        self.assertEqual(self.remote["/For_to-do/other/tasks.json"], other)

    def test_legacy_cloud_files_are_converted_too(self):
        self.remote["/For_to-do/account/itog.json"] = encrypt_bytes(b'{"tasks": []}')
        cloud = self.make_cloud(True)
        cloud.set_account_encryption("account", False)
        self.assertEqual(self.remote["/For_to-do/account/itog.json"], b'{"tasks": []}')

    def test_failed_conversion_restores_files_and_previous_setting(self):
        originals = dict(self.remote)
        def fail_once(source, path, **kwargs):
            if path.endswith("tasks.json") and not hasattr(fail_once, "failed"):
                fail_once.failed = True
                raise OSError("upload failed")
            self.upload(source, path, **kwargs)
        self.disk.upload.side_effect = fail_once
        cloud = self.make_cloud(True)
        with self.assertRaises(OSError):
            cloud.set_account_encryption("account", False)
        self.assertEqual(self.remote, originals)
        self.assertTrue(cloud.account_encryption_enabled("account"))

    def test_guest_offline_and_invalid_settings_are_rejected(self):
        cloud = self.make_cloud(True)
        cloud.read_user_data_text.return_value = ""
        with self.assertRaises(ValueError):
            cloud.set_account_encryption("account", False)
        cloud.read_user_data_text.return_value = "account~~login~~password"
        cloud.connect = False
        with self.assertRaises(ValueError):
            cloud.set_account_encryption("account", False)
        cloud.connect = True
        self.remote["/For_to-do/account/security.json"] = b'{"encryption_enabled": "False"}'
        with self.assertRaises(ValueError):
            cloud.account_encryption_enabled("account", refresh=True)


    def test_setting_upload_applied_then_failed_is_rolled_back(self):
        originals = dict(self.remote)
        def fail_after_write(source, path, **kwargs):
            self.upload(source, path, **kwargs)
            if path.endswith("security.json") and not hasattr(fail_after_write, "failed"):
                fail_after_write.failed = True
                raise TimeoutError("response lost")
        self.disk.upload.side_effect = fail_after_write
        cloud = self.make_cloud(True)
        with self.assertRaises(TimeoutError):
            cloud.set_account_encryption("account", False)
        for path, raw in originals.items():
            self.assertEqual(self.remote[path], raw)
        self.assertTrue(cloud.account_encryption_enabled("account", refresh=True))

    def test_local_files_remain_plain_after_read_edit_restart_and_sync(self):
        cloud = self.make_cloud(False)
        self.assertTrue(cloud.download("account"))
        cloud.set_account_encryption("account", False)
        for filename in SECTION_FILENAMES.values():
            self.assertIsInstance(json.loads((self.directory / filename).read_bytes()), list)
        self.assertFalse(cloud._section_needs_upload("account", "tasks"))
        data = load_all_sections(self.directory)
        data["tasks"].append({"id": "offline", "name": "Правка после отключения"})
        save_section(self.directory, "tasks", data["tasks"])
        self.assertEqual(json.loads((self.directory / "tasks.json").read_bytes()), data["tasks"])
        # Повторяем подготовку сохранений при запуске без обращения к облаку.
        migrate_legacy_storage(self.directory, self.directory / "itog.json")
        ensure_split_storage(self.directory, self.directory / "itog.json")
        load_all_sections(self.directory)
        restarted = self.make_cloud(False)
        restarted._load_sync_state()
        self.assertTrue(restarted._section_needs_upload("account", "tasks"))
        restarted.upload("account")
        self.assertEqual(json.loads(self.remote["/For_to-do/account/tasks.json"]), data["tasks"])
        self.assertEqual(json.loads((self.directory / "tasks.json").read_bytes()), data["tasks"])
        self.assertTrue(restarted.download("account", preserve_local=True))
        self.assertEqual(json.loads((self.directory / "tasks.json").read_bytes()), data["tasks"])

    def test_opening_disabled_account_repairs_old_encrypted_local_files(self):
        cloud = self.make_cloud(False)
        self.assertTrue(cloud.download("account"))
        self.remote["/For_to-do/account/security.json"] = b'{"encryption_enabled": false}'
        self.assertFalse(cloud.load_account_encryption("account"))
        self.assertEqual(json.loads((self.directory / "tasks.json").read_bytes()), self.data["tasks"])
        self.assertFalse(cloud._section_needs_upload("account", "tasks"))

    def test_failed_change_keeps_local_format_and_data(self):
        cloud = self.make_cloud(False)
        self.assertTrue(cloud.download("account"))
        before = (self.directory / "tasks.json").read_bytes()
        self.disk.upload.side_effect = OSError("offline")
        with self.assertRaises(OSError):
            cloud.set_account_encryption("account", False)
        self.assertEqual((self.directory / "tasks.json").read_bytes(), before)
        self.assertTrue(cloud.account_encryption_enabled("account"))

    def test_ui_switch_converts_actual_local_and_cloud_file_bytes(self):
        cloud = self.make_cloud(False)
        self.assertTrue(cloud.download("account"))
        front = make_front()
        front.utils2.cloud = cloud
        widgets, load = front.utils2.build_widgets_for_account_encryption(front.page)
        asyncio.run(load())
        switch, _, status = widgets.controls
        switch.value = False
        asyncio.run(switch.on_change(None))
        self.assertFalse(switch.value)
        self.assertIn("отключено", status.value)
        self.assertEqual(json.loads((self.directory / "tasks.json").read_bytes()), self.data["tasks"])
        self.assertEqual(json.loads(self.remote["/For_to-do/account/tasks.json"]), self.data["tasks"])
        switch.value = True
        asyncio.run(switch.on_change(None))
        self.assertTrue(is_encrypted((self.directory / "tasks.json").read_bytes()))
        self.assertTrue(is_encrypted(self.remote["/For_to-do/account/tasks.json"]))

    def test_guest_backup_restores_its_own_encryption_mode(self):
        cloud = self.make_cloud(False)
        cloud.local_data_dir = self.directory / "local"
        save_all_sections(self.directory, self.data)
        cloud._move_active_saves_to_local_backup()
        cloud.set_account_encryption("account", False)
        self.assertFalse(is_encrypted((self.directory / "tasks.json").read_bytes()))
        cloud._restore_local_backup_to_active()
        self.assertTrue(is_encrypted((self.directory / "tasks.json").read_bytes()))
        save_section(self.directory, "tasks", [{"id": "guest", "name": "Гостевое дело"}])
        self.assertTrue(is_encrypted((self.directory / "tasks.json").read_bytes()))


if __name__ == "__main__":
    unittest.main()
