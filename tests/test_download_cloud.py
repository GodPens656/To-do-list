import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from download_cloud import CLOUD_ROOT, MANIFEST_NAME, download_tree, main
from Backend.dropbox_disk import load_dropbox_credentials


def resource(name, kind="file", payload=b""):
    return SimpleNamespace(name=name, type=kind, size=len(payload),
                           sha256=hashlib.sha256(payload).hexdigest())


class DownloadCloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "copy"
        self.disk = Mock()
        self.disk.get_meta.return_value = resource("For_to-do", "dir")

    def test_all_nested_files_binary_backups_and_empty_folders_are_saved(self):
        payload = b"ND-AES256-GCM\x01\x00\xff"
        tree = {
            CLOUD_ROOT: [resource("account", "dir"), resource("empty", "dir")],
            CLOUD_ROOT + "/account": [resource("tasks.json", payload=payload),
                                     resource("backups", "dir")],
            CLOUD_ROOT + "/account/backups": [resource("backup.bin", payload=payload)],
            CLOUD_ROOT + "/empty": [],
        }
        self.disk.listdir.side_effect = lambda path, **kwargs: iter(tree[path])
        self.disk.download.side_effect = lambda src, dst, **kwargs: Path(dst).write_bytes(payload)
        reports = []
        self.assertEqual(download_tree(self.disk, self.output, reports.append), (2, 3, 2 * len(payload)))
        self.assertEqual((self.output / "account/tasks.json").read_bytes(), payload)
        self.assertEqual((self.output / "account/backups/backup.bin").read_bytes(), payload)
        self.assertTrue((self.output / "empty").is_dir())
        self.assertTrue(all("account" not in message for message in reports))

    def test_existing_destination_is_preserved(self):
        self.output.mkdir()
        existing = self.output / "tasks.json"
        existing.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "пустой"):
            download_tree(self.disk, self.output)
        self.assertEqual(existing.read_bytes(), b"keep")
        self.disk.download.assert_not_called()

    def test_failed_download_removes_partial_file(self):
        self.disk.listdir.return_value = [resource("data.bin", payload=b"complete")]

        def fail(src, dst, **kwargs):
            Path(dst).write_bytes(b"partial")
            raise TimeoutError("private URL and token")

        self.disk.download.side_effect = fail
        with self.assertRaises(TimeoutError):
            download_tree(self.disk, self.output)
        self.assertEqual([path.name for path in self.output.iterdir()], [MANIFEST_NAME])
        self.assertFalse(json.loads((self.output / MANIFEST_NAME).read_text(encoding="utf-8"))["complete"])

    def test_bad_size_or_checksum_is_rejected(self):
        for payload in (b"short", b"corrupt"):
            with self.subTest(payload=payload):
                self.disk.listdir.return_value = [resource("data.bin", payload=b"correct")]
                self.disk.download.side_effect = lambda src, dst, **kwargs: Path(dst).write_bytes(payload)
                with self.assertRaises(ValueError):
                    download_tree(self.disk, self.output)
                self.assertEqual([path.name for path in self.output.iterdir()], [MANIFEST_NAME])

    def test_windows_incompatible_folder_does_not_stop_nested_downloads(self):
        payload = b"encrypted"
        self.disk.listdir.side_effect = lambda path, **kwargs: iter({
            CLOUD_ROOT: [resource("first", "dir"), resource("account:password?", "dir"),
                         resource("last", "dir")],
            CLOUD_ROOT + "/first": [resource("tasks.json", payload=payload)],
            CLOUD_ROOT + "/account:password?": [resource("tasks.json", payload=payload)],
            CLOUD_ROOT + "/last": [resource("tasks.json", payload=payload)],
        }[path])
        self.disk.download.side_effect = lambda src, dst, **kwargs: Path(dst).write_bytes(payload)
        self.assertEqual(download_tree(self.disk, self.output, lambda message: None), (3, 3, 27))
        self.assertEqual((self.output / "account%3Apassword%3F/tasks.json").read_bytes(), payload)
        manifest = json.loads((self.output / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertTrue(manifest["complete"])
        self.assertIn({"cloud_path": CLOUD_ROOT + "/account:password?/tasks.json",
                       "local_path": "account%3Apassword%3F/tasks.json",
                       "type": "file", "downloaded": True}, manifest["entries"])

    def test_reserved_long_traversal_and_case_colliding_names_are_all_saved(self):
        names = ["..", "../outside", "C:\\outside", "a:b", "a%3Ab", "NUL",
                 "trailing.", "TASKS.json", "tasks.json", "x" * 300, MANIFEST_NAME]
        self.disk.listdir.return_value = [resource(name, payload=str(i).encode())
                                         for i, name in enumerate(names)]
        self.disk.download.side_effect = lambda src, dst, **kwargs: Path(dst).write_bytes(
            str(names.index(src[len(CLOUD_ROOT) + 1:])).encode())
        self.assertEqual(download_tree(self.disk, self.output, lambda message: None)[0], len(names))
        manifest = json.loads((self.output / MANIFEST_NAME).read_text(encoding="utf-8"))
        local_paths = [entry["local_path"].casefold() for entry in manifest["entries"]]
        self.assertEqual(len(set(local_paths)), len(names))
        for i, entry in enumerate(manifest["entries"]):
            path = self.output / entry["local_path"]
            self.assertEqual(path.parent, self.output)
            self.assertEqual(path.read_bytes(), str(i).encode())

    def test_cli_failure_does_not_print_private_network_error(self):
        stderr = io.StringIO()
        with patch("Backend.dropbox_disk.load_dropbox_credentials"), \
                patch("Backend.dropbox_disk.DropboxDisk") as client, \
                patch("download_cloud.download_tree", side_effect=TimeoutError("private-token")), \
                patch("sys.stderr", stderr), patch("sys.stdout", io.StringIO()):
            self.assertEqual(main(["--output", str(self.output)]), 1)
        self.assertIn("TimeoutError", stderr.getvalue())
        self.assertNotIn("private-token", stderr.getvalue())
        client.assert_called_once_with()
        client.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
