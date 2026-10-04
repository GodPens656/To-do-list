import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from build_windows import verify_desktop_bundle


class WindowsBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.executable = self.root / "Dnevnik.exe"
        self.executable.touch()
        self.runtime_files = [
            "flet/flet.exe", "flet/flutter_windows.dll", "flet/data/icudtl.dat",
        ]

    def test_rejects_bundle_without_desktop_client(self):
        with self.assertRaisesRegex(RuntimeError, "flet/flet.exe"):
            verify_desktop_bundle(self.executable, self.runtime_files)

    def test_checks_client_dlls_and_flutter_data(self):
        runtime = self.root / "_internal/flet_desktop/app"
        for name in self.runtime_files:
            path = runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        verify_desktop_bundle(self.executable, self.runtime_files)
        (runtime / "flet/data/icudtl.dat").unlink()
        with self.assertRaisesRegex(RuntimeError, "icudtl.dat"):
            verify_desktop_bundle(self.executable, self.runtime_files)

    def test_onefile_checks_archive_paths_instead_of_external_directory(self):
        archive = Mock(toc={
            "flet_desktop\\app\\" + name.replace("/", "\\"): None
            for name in self.runtime_files
        })
        with patch("PyInstaller.archive.readers.CArchiveReader", return_value=archive):
            verify_desktop_bundle(self.executable, self.runtime_files, onefile=True)
            archive.toc.pop("flet_desktop\\app\\flet\\flet.exe")
            with self.assertRaisesRegex(RuntimeError, "flet/flet.exe"):
                verify_desktop_bundle(self.executable, self.runtime_files, onefile=True)


if __name__ == "__main__":
    unittest.main()
