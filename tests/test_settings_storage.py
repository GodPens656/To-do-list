import tempfile
import unittest
from pathlib import Path

from Backend.crypto import (
    EncryptedFileError,
    encrypt_bytes,
    is_encrypted,
    read_text,
    write_text,
)
from Backend.extended import Backend2


class SettingsStorageTests(unittest.TestCase):
    def make_backend(self, settings_path):
        back = Backend2.__new__(Backend2)
        back.web = False
        back.settings = settings_path
        return back

    def test_plaintext_settings_remain_editable_after_save_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            for layout in ("settings", "android"):
                with self.subTest(layout=layout):
                    path = Path(directory) / layout / "settings.txt"
                    path.parent.mkdir()
                    path.write_text("custom_setting: Настройки вручную\n", encoding="utf-8")
                    back = self.make_backend(path)
                    back.set_default_settings()
                    back.redact_setting("theme_style", "nord")
                    self.assertIn("theme_style: nord\n", path.read_text(encoding="utf-8"))
                    self.assertIn("custom_setting: Настройки вручную\n", path.read_text(encoding="utf-8"))

                    reopened = self.make_backend(path)
                    reopened.set_default_settings()
                    self.assertEqual(reopened.read_settings()["theme_style"], "nord")
                    self.assertFalse(is_encrypted(path.read_bytes()))

    def test_encrypted_settings_are_migrated_without_changing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.txt"
            plain = "theme_style: nord\ncustom_setting: Сохранённое значение\n".encode("utf-8")
            path.write_bytes(encrypt_bytes(plain))
            back = self.make_backend(path)
            self.assertEqual(back._settings_read(), {
                "theme_style": "nord", "custom_setting": "Сохранённое значение",
            })
            self.assertEqual(path.read_bytes(), plain)
            self.assertEqual(read_text(path), plain.decode("utf-8"))
            self.assertEqual(path.read_bytes(), plain)

    def test_corrupt_encrypted_settings_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.txt"
            encrypted = encrypt_bytes(b"theme_style: nord\n")
            corrupted = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
            path.write_bytes(corrupted)
            with self.assertRaises(EncryptedFileError):
                self.make_backend(path)._settings_read()
            self.assertEqual(path.read_bytes(), corrupted)

    def test_other_private_files_remain_encrypted(self):
        with tempfile.TemporaryDirectory() as directory:
            for filename in ("accounts.txt", "tasks.json", "custom_icon_pack.zip"):
                with self.subTest(filename=filename):
                    path = Path(directory) / filename
                    write_text(path, "private content")
                    self.assertTrue(is_encrypted(path.read_bytes()))
                    self.assertEqual(read_text(path), "private content")
                    self.assertTrue(is_encrypted(path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
