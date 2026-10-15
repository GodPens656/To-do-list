import hashlib
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from dropbox import exceptions, files

from Backend.cloud import Cloud
from Backend.dropbox_disk import (
    DropboxDisk, DropboxDiskError, _ContentHash, load_dropbox_credentials,
)


def content_hash(payload):
    blocks = (payload[i:i + 4 * 1024 * 1024]
              for i in range(0, len(payload), 4 * 1024 * 1024))
    return hashlib.sha256(b"".join(hashlib.sha256(b).digest() for b in blocks)).hexdigest()


class DropboxDiskTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.disk = DropboxDisk()
        self.disk._client = self.client

    def test_refresh_auth_is_lazy_and_takes_priority_over_access_token(self):
        credentials = dict(DROPBOX_APP_KEY="app", DROPBOX_REFRESH_TOKEN="refresh",
                           DROPBOX_ACCESS_TOKEN="expired", DROPBOX_APP_SECRET="")
        with patch("Backend.dropbox_disk.load_dropbox_credentials", return_value=credentials), \
                patch("Backend.dropbox_disk.dropbox.Dropbox") as factory:
            disk = DropboxDisk()
            factory.assert_not_called()
            disk.check_connection()
            disk.check_connection()
            factory.assert_called_once()
            self.assertEqual(factory.call_args.kwargs["oauth2_refresh_token"], "refresh")
            self.assertIsNone(factory.call_args.kwargs["oauth2_access_token"])
            self.assertIsNone(factory.call_args.kwargs["app_secret"])
            disk.close()
            factory.return_value.close.assert_called_once()

    def test_generated_access_token_can_be_used_without_app_key(self):
        credentials = dict(DROPBOX_APP_KEY="", DROPBOX_REFRESH_TOKEN="",
                           DROPBOX_ACCESS_TOKEN="access", DROPBOX_APP_SECRET="")
        with patch("Backend.dropbox_disk.load_dropbox_credentials", return_value=credentials), \
                patch("Backend.dropbox_disk.dropbox.Dropbox") as factory:
            with DropboxDisk() as disk:
                disk.check_connection()
            self.assertEqual(factory.call_args.kwargs["oauth2_access_token"], "access")
            self.assertIsNone(factory.call_args.kwargs["oauth2_refresh_token"])

    def test_listdir_follows_pagination_and_preserves_names(self):
        self.client.files_list_folder.return_value = SimpleNamespace(
            entries=[files.FolderMetadata(name="Дела", id="folder")],
            has_more=True, cursor="next")
        self.client.files_list_folder_continue.return_value = SimpleNamespace(
            entries=[files.FileMetadata(name="tasks.json", id="file",
                                       client_modified=datetime(2026, 1, 1),
                                       server_modified=datetime(2026, 1, 1), rev="abcdef123", size=3)],
            has_more=False)
        entries = self.disk.listdir("/For_to-do")
        self.assertEqual([(e.name, e.type, e.size) for e in entries],
                         [("Дела", "dir", None), ("tasks.json", "file", 3)])
        self.client.files_list_folder_continue.assert_called_once_with("next")

    def test_missing_path_is_distinct_from_auth_and_network_errors(self):
        self.client.files_get_metadata.side_effect = exceptions.ApiError(
            "request", files.GetMetadataError.path(files.LookupError.not_found), None, None)
        self.assertFalse(self.disk.exists("/missing"))
        for failure, retryable in (
            (exceptions.AuthError("request", "private token"), False),
            (requests.Timeout("private URL"), True),
        ):
            with self.subTest(failure=type(failure).__name__):
                self.client.files_get_metadata.side_effect = failure
                with self.assertRaises(DropboxDiskError) as raised:
                    self.disk.exists("/account_password")
                self.assertEqual(raised.exception.retryable, retryable)
                self.assertNotIn("private", str(raised.exception))
                self.assertNotIn("account_password", str(raised.exception))

    def test_folder_conflict_maps_to_file_exists(self):
        self.client.files_create_folder_v2.side_effect = exceptions.ApiError(
            "request", files.CreateFolderError.path(
                files.WriteError.conflict(files.WriteConflictError.folder)), None, None)
        with self.assertRaises(FileExistsError):
            self.disk.mkdir("/existing")

    def test_small_upload_overwrites_without_renaming_and_keeps_stream_open(self):
        stream = io.BytesIO(b"encrypted data")
        self.disk.upload(stream, "/For_to-do/tasks.json", overwrite=True)
        args, kwargs = self.client.files_upload.call_args
        self.assertEqual(args, (b"encrypted data", "/For_to-do/tasks.json"))
        self.assertEqual(kwargs["mode"], files.WriteMode.overwrite)
        self.assertFalse(kwargs["autorename"])
        self.assertTrue(kwargs["strict_conflict"])
        self.assertEqual(kwargs["content_hash"], content_hash(b"encrypted data"))
        self.assertFalse(stream.closed)

    def test_session_upload_preserves_bytes_offsets_and_conflict_policy(self):
        self.disk.chunk_size = 4
        self.client.files_upload_session_start.return_value.session_id = "session"
        offsets = []
        self.client.files_upload_session_append_v2.side_effect = (
            lambda chunk, cursor, **kwargs: offsets.append(cursor.offset))
        self.disk.upload(io.BytesIO(b"abcdefghijklmn"), "/large")
        self.assertEqual(self.client.files_upload_session_start.call_args.args, (b"abcd",))
        self.assertEqual(offsets, [4, 8])
        tail, cursor, commit = self.client.files_upload_session_finish.call_args.args
        self.assertEqual((tail, cursor.offset, commit.path), (b"mn", 12, "/large"))
        self.assertEqual(commit.mode, files.WriteMode.add)
        self.assertFalse(commit.autorename)
        self.assertTrue(commit.strict_conflict)

    def response(self, payload, *, checksum=None):
        response = Mock()
        response.iter_content.return_value = [payload[:2], payload[2:]]
        meta = SimpleNamespace(size=len(payload), content_hash=checksum or content_hash(payload))
        self.client.files_download.return_value = meta, response
        return response

    def test_download_verifies_hash_before_writing_to_stream(self):
        response = self.response(b"encrypted")
        output = io.BytesIO()
        self.disk.download("/data", output)
        self.assertEqual(output.getvalue(), b"encrypted")
        response.close.assert_called_once()
        self.response(b"corrupt", checksum="wrong")
        output = io.BytesIO(b"existing")
        with self.assertRaises(DropboxDiskError):
            self.disk.download("/data", output)
        self.assertEqual(output.getvalue(), b"existing")

    def test_failed_download_preserves_existing_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tasks.json"
            target.write_bytes(b"previous")
            response = self.response(b"partial")
            response.iter_content.side_effect = requests.ConnectionError("private URL")
            with self.assertRaises(DropboxDiskError) as raised:
                self.disk.download("/data", target)
            self.assertTrue(raised.exception.retryable)
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertEqual(list(Path(directory).iterdir()), [target])
            response.close.assert_called_once()
            self.response(b"complete")
            self.disk.download("/data", target)
            self.assertEqual(target.read_bytes(), b"complete")

    def test_mutations_cannot_target_root_or_parent_traversal(self):
        for path in ("", "/", "/../data", "/data/./tasks.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.disk.remove(path)
        self.client.files_delete_v2.assert_not_called()

    def test_backup_copy_move_and_delete_use_native_dropbox_operations(self):
        self.disk.copy("/source", "/backup")
        self.disk.move("/backup", "/renamed")
        self.disk.remove("/renamed", permanently=True)
        self.client.files_copy_v2.assert_called_once_with("/source", "/backup", autorename=False)
        self.client.files_move_v2.assert_called_once_with("/backup", "/renamed", autorename=False)
        self.client.files_delete_v2.assert_called_once_with("/renamed")

    def test_hash_handles_empty_and_multiple_blocks_across_stream_chunks(self):
        for payload in (b"", b"x" * (4 * 1024 * 1024), b"x" * (4 * 1024 * 1024 + 7)):
            digest = _ContentHash()
            for offset in range(0, len(payload), 700_000):
                digest.update(payload[offset:offset + 700_000])
            self.assertEqual(digest.hexdigest(), content_hash(payload))

    def test_provider_switch_does_not_reuse_mega_sync_markers(self):
        cloud = Cloud.__new__(Cloud)
        self.assertNotEqual(cloud._account_key("account"),
                            hashlib.sha256(b"mega:account").hexdigest())


class DropboxCredentialsTests(unittest.TestCase):
    def test_environment_overrides_file_including_explicit_empty_values(self):
        secret = SimpleNamespace(DROPBOX_ACCESS_TOKEN="old access", DROPBOX_APP_KEY=" app ")
        with patch.dict(sys.modules, {"secret": secret}), patch.dict(os.environ, {
            "DROPBOX_ACCESS_TOKEN": "", "DROPBOX_REFRESH_TOKEN": " refresh ",
            "DROPBOX_APP_SECRET": "",
        }, clear=True):
            values = load_dropbox_credentials()
            self.assertEqual(values["DROPBOX_ACCESS_TOKEN"], "")
            self.assertEqual(values["DROPBOX_APP_KEY"], "app")
            self.assertEqual(values["DROPBOX_REFRESH_TOKEN"], "refresh")

    def test_missing_credentials_or_refresh_without_app_key_are_rejected(self):
        for environment in ({}, {"DROPBOX_REFRESH_TOKEN": "refresh"}):
            with self.subTest(environment=environment), \
                    patch.dict(sys.modules, {"secret": None}), \
                    patch.dict(os.environ, environment, clear=True), self.assertRaises(ValueError):
                load_dropbox_credentials()


if __name__ == "__main__":
    unittest.main()
