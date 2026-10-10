"""Совместимость со старыми импортами; приложение использует Backend.app_paths."""

from Backend.app_paths import get_assets_dir

__all__ = ["get_assets_dir"]
