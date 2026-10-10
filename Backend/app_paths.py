"""Пути к ресурсам исходников, сборок Flet и PyInstaller."""

import os
import sys
from pathlib import Path


def get_assets_dir():
    override = os.getenv("ND_ASSETS_DIR")
    if override is not None:
        return Path(override).expanduser().resolve()

    # В APK ресурсы могут находиться отдельно от Python-кода приложения.
    flet_assets = os.getenv("FLET_ASSETS_DIR")
    if flet_assets:
        return Path(flet_assets).expanduser().resolve()

    app_root = Path(__file__).resolve().parent.parent
    if getattr(sys, "frozen", False):
        # Сохраняем поддержку внешней папки assets рядом с .exe.
        external = Path(sys.executable).resolve().parent / "assets"
        if external.is_dir():
            return external
        # One-file распаковывает данные в _MEIPASS, one-folder — в _internal.
        bundled = Path(getattr(sys, "_MEIPASS", app_root))
        return bundled / "assets"

    return app_root / "assets"
