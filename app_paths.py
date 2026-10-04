"""Пути к ресурсам при запуске из исходников и после сборки PyInstaller."""

import os
import sys
from pathlib import Path


def get_assets_dir():
    override = os.getenv("ND_ASSETS_DIR")
    if override is not None:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        # Сохраняем поддержку внешней папки assets рядом с .exe.
        external = Path(sys.executable).resolve().parent / "assets"
        if external.is_dir():
            return external
        # One-file распаковывает данные в _MEIPASS, one-folder — в _internal.
        bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return bundled / "assets"

    return Path(__file__).resolve().parent / "assets"
