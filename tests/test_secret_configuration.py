import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from Backend.cloud import Cloud


class SecretConfigurationTests(unittest.TestCase):
    def load_crypto(self, keyword=None, *, missing=False):
        secret = ModuleType("secret")
        secret.ENCRYPTION_KEYWORD = keyword
        source = Path(__file__).resolve().parents[1] / "Backend" / "crypto.py"
        spec = importlib.util.spec_from_file_location("configured_crypto", source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"secret": None if missing else secret}):
            spec.loader.exec_module(module)
        return module

    def test_missing_secret_explains_how_to_configure_application(self):
        with self.assertRaisesRegex(RuntimeError, "secret.example.py"):
            self.load_crypto(missing=True)

    def test_empty_or_invalid_keyword_is_rejected(self):
        for keyword in ("", "   ", None, 123):
            with self.subTest(keyword=keyword):
                with self.assertRaisesRegex(ValueError, "ENCRYPTION_KEYWORD"):
                    self.load_crypto(keyword)

    def test_same_keyword_decrypts_data_and_different_keyword_cannot(self):
        first = self.load_crypto("test-only shared encryption phrase")
        second = self.load_crypto("test-only shared encryption phrase")
        other = self.load_crypto("test-only different encryption phrase")
        plain = "Дела и заметки".encode("utf-8")
        encrypted = first.encrypt_bytes(plain)
        self.assertEqual(second.decrypt_bytes(encrypted), plain)
        with self.assertRaises(other.EncryptedFileError):
            other.decrypt_bytes(encrypted)

    def test_disk_client_uses_configured_token(self):
        cloud = Cloud.__new__(Cloud)
        with patch("Backend.cloud.YANDEX_DISK_TOKEN", "test-only-token"), \
                patch("Backend.cloud.yadisk.YaDisk") as client:
            self.assertIs(cloud.initizialise_disk(), client.return_value)
        client.assert_called_once_with(token="test-only-token", session="httpx")


if __name__ == "__main__":
    unittest.main()
