"""Проверка точки входа APK без старого app_paths.py в корне."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class AndroidStartupTests(unittest.TestCase):
    def test_packaged_entry_point_runs_without_root_app_paths(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "app"
            app.mkdir()
            shutil.copy2(source / "main.py", app / "main.py")
            for package in ("Backend", "Frontend"):
                target = app / package
                target.mkdir()
                for module in (source / package).glob("*.py"):
                    shutil.copy2(module, target / module.name)
            assets = root / "flutter_assets" / "assets"
            assets.mkdir(parents=True)
            environment = os.environ.copy()
            environment.pop("ND_ASSETS_DIR", None)
            environment["FLET_ASSETS_DIR"] = str(assets)
            # Изолированный Python не сможет случайно импортировать корневой
            # app_paths.py из рабочей папки или PYTHONPATH разработчика.
            script = """
import importlib.util
import runpy
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
assert importlib.util.find_spec("app_paths") is None
secret = ModuleType("secret")
secret.YANDEX_DISK_TOKEN = "test-only-token"
secret.ENCRYPTION_KEYWORD = "test-only encryption phrase"
sys.modules["secret"] = secret
with patch("flet.run") as run:
    runpy.run_path(str(Path(sys.argv[1]) / "main.py"), run_name="__main__")
run.assert_called_once()
assert callable(run.call_args.args[0])
assert Path(run.call_args.kwargs["assets_dir"]) == Path(sys.argv[2])
"""
            result = subprocess.run(
                [sys.executable, "-I", "-c", script, str(app), str(assets)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
