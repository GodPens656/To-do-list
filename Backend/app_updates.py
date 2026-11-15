"""Проверка публичных GitHub Releases без зависимости от интерфейса."""

from dataclasses import dataclass
import logging
import platform
import re
from urllib.parse import urlsplit

import requests


REPOSITORY = "GodPens656/To-do-list"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
SUPPORTED_PLATFORMS = {"windows", "android"}
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppUpdate:
    version: str
    asset_name: str
    download_url: str


def _version_key(value):
    """Сравниваем числовые версии, включая теги v3.15.0 и 3.15."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    match = re.fullmatch(r"[vV]?(\d+(?:\.\d+){0,3})(?:\+[\w.-]+)?", value.strip())
    if not match:
        return None
    parts = tuple(int(part) for part in match[1].split("."))
    return parts + (0,) * (4 - len(parts))


def _architecture(value):
    for architecture, pattern in (
        ("x64", r"x86[_-]64|amd64|x64"),
        ("arm64", r"arm64(?:-v8a)?|aarch64"),
        ("x86", r"x86|i[3-6]86|win32"),
        ("arm", r"armeabi-v7a|armv7[al]?|arm32"),
    ):
        if re.search(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])", value.lower()):
            return architecture
    return None


def _select_asset(assets, target, machine):
    extensions = {"android": (".apk",), "windows": (".exe", ".msi", ".zip")}[target]
    architecture = _architecture(machine)
    candidates = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name, url = asset.get("name"), asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if asset.get("state", "uploaded") != "uploaded":
            continue
        lower = name.lower()
        extension = next((ext for ext in extensions if lower.endswith(ext)), None)
        if extension is None:
            continue
        # ZIP без указания платформы поддерживает существующие Windows-релизы.
        if target == "windows" and re.search(
            r"(?:android|linux|macos|darwin|osx|ios|source|symbols|debug)", lower,
        ):
            continue
        asset_architecture = _architecture(lower)
        if asset_architecture and asset_architecture != architecture:
            continue
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.netloc != "github.com"
                    or not parsed.path.startswith(f"/{REPOSITORY}/releases/download/")):
                continue
        except ValueError:
            continue
        # Универсальный APK подходит всем устройствам; затем предпочитаем
        # установщик/файл, соответствующий архитектуре текущего устройства.
        universal = target == "android" and "universal" in lower
        score = (not universal, extensions.index(extension), asset_architecture is None, lower)
        candidates.append((score, name, url))
    return min(candidates)[1:] if candidates else None


def check_for_update(current_version, target, *, machine=None):
    """Возвращает обновление для платформы или None при отсутствии/сбое сети."""
    target = getattr(target, "value", target)
    current = _version_key(current_version)
    if target not in SUPPORTED_PLATFORMS or current is None:
        return None
    try:
        with requests.get(
            LATEST_RELEASE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"To-do-list/{current_version}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=(3.05, 8),
        ) as response:
            response.raise_for_status()
            release = response.json()
    except (requests.RequestException, ValueError):
        _logger.debug("Не удалось проверить обновления приложения", exc_info=True)
        return None

    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    version = release.get("tag_name")
    latest = _version_key(version)
    assets = release.get("assets")
    if latest is None or latest <= current or not isinstance(assets, list):
        return None
    asset = _select_asset(assets, target, machine if machine is not None else platform.machine())
    if asset is None:
        return None
    return AppUpdate(version.strip().lstrip("vV"), *asset)
