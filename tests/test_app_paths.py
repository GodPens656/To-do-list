import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Backend.app_paths import get_assets_dir


class AssetsPathTests(unittest.TestCase):
    def test_source_assets_do_not_depend_on_working_directory(self):
        with patch.dict(os.environ, {}, clear=True):
            expected = Path(__file__).resolve().parents[1] / "assets"
            self.assertEqual(get_assets_dir(), expected)

    def test_frozen_assets_use_pyinstaller_bundle(self):
        # Одинаковая схема для _internal в one-folder и _MEI… в one-file.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for bundle_name in ("_internal", "_MEI12345"):
                with self.subTest(bundle=bundle_name), patch.dict(os.environ, {}, clear=True):
                    with patch.object(sys, "frozen", True, create=True), \
                         patch.object(sys, "executable", str(root / "Dnevnik.exe")), \
                         patch.object(sys, "_MEIPASS", str(root / bundle_name), create=True):
                        self.assertEqual(get_assets_dir(), root / bundle_name / "assets")

    def test_external_assets_take_precedence_over_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "assets").mkdir()
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "executable", str(root / "Dnevnik.exe")), \
                 patch.object(sys, "_MEIPASS", str(root / "_internal"), create=True):
                self.assertEqual(get_assets_dir(), root / "assets")

    def test_environment_override_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict(os.environ, {
                "ND_ASSETS_DIR": str(root),
                "FLET_ASSETS_DIR": str(root / "flet-assets"),
            }, clear=True):
                self.assertEqual(get_assets_dir(), root)

    def test_flet_assets_can_be_outside_python_app_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory).resolve() / "flutter_assets" / "assets"
            with patch.dict(os.environ, {"FLET_ASSETS_DIR": str(assets)}, clear=True):
                self.assertEqual(get_assets_dir(), assets)

    def test_empty_flet_assets_uses_source_directory(self):
        with patch.dict(os.environ, {"FLET_ASSETS_DIR": ""}, clear=True):
            self.assertEqual(
                get_assets_dir(), Path(__file__).resolve().parents[1] / "assets"
            )


if __name__ == "__main__":
    unittest.main()
