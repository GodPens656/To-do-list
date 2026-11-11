"""Хранилище ежедневника: раздельные JSON-файлы дел, групп, расписания
и истории достижений в папке сохранений.

Этот модуль работает только с текущей JSON-схемой и ничего не знает про
старый itog.txt или про промежуточный JSON с ключами normal/repeat — вся
логика переноса из этих устаревших форматов вынесена в Backend/json_migration.py
и используется один раз при первом запуске приложения.
"""
import json
import os
import shutil
import threading
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from .crypto import (
    ACCOUNT_DATA_FILENAMES, data_encryption_enabled, decrypt_bytes,
    encrypt_file_if_plaintext, file_signature, invalidate_data_encryption,
    is_encrypted, read_text, write_bytes, write_text,
)

STORAGE_LOCK = threading.RLock()
_SECTION_CACHE = OrderedDict()


def set_data_encryption(data_dir, enabled):
    """Меняет формат существующих дел и сохраняет его для новых записей."""
    if type(enabled) is not bool:
        raise ValueError("Некорректная настройка шифрования.")
    directory = Path(data_dir)
    with STORAGE_LOCK:
        originals = {}
        for name in ACCOUNT_DATA_FILENAMES:
            path = directory / name
            if path.is_file():
                raw = path.read_bytes()
                if is_encrypted(raw) != enabled:
                    originals[path] = (raw, decrypt_bytes(raw))
        if not originals and data_encryption_enabled(directory) == enabled:
            return
        changed = []
        try:
            for path, (raw, plain) in originals.items():
                changed.append(path)
                write_bytes(path, plain, encrypt=enabled)
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / "security.json.tmp"
            temporary.write_text(json.dumps({"encryption_enabled": enabled}), encoding="utf-8")
            temporary.replace(directory / "security.json")
            invalidate_data_encryption(directory)
        except Exception:
            for path in reversed(changed):
                write_bytes(path, originals[path][0], encrypt=False)
            raise


DEFAULT_DATA = {
    "tasks": [],
    "postponed": [],
    # Персональные настройки группы: разделение по датам, подпись даты
    # создания и показ счётчика выполненных дел.
    # Хранятся у каждой группы отдельно, а не в общем settings.txt.
    "groups": [{"id": "default", "name": "Без группы", "split_by_dates": True, "show_created_date": True, "show_completion_counter": True, "show_group_title": True}],
    # Дополнительное поле сохраняет правила повторения, которых нет в базовой схеме.
    "repeat_tasks": [],
    "achievements": [],
}


def empty_data():
    return deepcopy(DEFAULT_DATA)


def load_data(path):
    """Читает единый JSON-файл (используется только для переходного
    itog.json — см. Backend/json_migration.py) и возвращает корректную
    структуру даже для отсутствующего или повреждённого файла."""
    try:
        data = json.loads(read_text(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    result = empty_data()
    if isinstance(data, dict):
        for key in result:
            if isinstance(data.get(key), list):
                result[key] = data[key]
    _normalize_groups(result["groups"])
    return result


def save_data(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_groups(groups):
    """Гарантирует наличие группы «Без группы» и её персональных настроек."""
    if not any(isinstance(g, dict) and g.get("id") == "default" for g in groups):
        groups.insert(0, {"id": "default", "name": "Без группы", "split_by_dates": True, "show_created_date": True})
    for group in groups:
        if isinstance(group, dict):
            group.setdefault("type", "tasks")
            group.setdefault("split_by_dates", True)
            group.setdefault("show_created_date", True)
            group.setdefault("show_completion_counter", True)
            group.setdefault("show_group_title", True)
    return groups


# --------------------------------------------------------------------------
# Раздельное хранение: вместо одного itog.json — файл на каждую секцию.
# Это позволяет при каждом изменении читать/писать/выгружать в облако только тот файл,
# который реально изменился, а не весь итог целиком.
# --------------------------------------------------------------------------

SECTION_FILENAMES = {
    "groups": "groups.json",
    "tasks": "tasks.json",
    "postponed": "postponed.json",
    "repeat_tasks": "repeat_tasks.json",
    "achievements": "achievements.json",
}


def _default_section(key):
    if key == "groups":
        return [{"id": "default", "name": "Без группы", "split_by_dates": True, "show_created_date": True}]
    return []


def _remember_section(path, key, text, encrypted, signature, security_signature):
    """Хранит отдельный снимок: вызывающий код не получает его для изменения."""
    try:
        value = json.loads(text) if text is not None else None
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, list):
        value = _default_section(key)
    if key == "groups":
        _normalize_groups(value)
    cached = {
        "signature": (signature, security_signature),
        "text": text, "encrypted": encrypted, "value": value,
    }
    _SECTION_CACHE[path] = cached
    _SECTION_CACHE.move_to_end(path)
    # Нативное приложение обычно использует две папки; ограничение не даёт
    # удерживать удалённые временные хранилища и старые снимки бесконечно.
    if len(_SECTION_CACHE) > 128:
        _SECTION_CACHE.popitem(last=False)
    return cached


def _copy_section(cached, key):
    """Создаёт независимые JSON-объекты без обхода всего дерева через deepcopy."""
    try:
        value = json.loads(cached["text"]) if cached["text"] is not None else None
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, list):
        value = _default_section(key)
    return _normalize_groups(value) if key == "groups" else value


def _read_section(data_dir, key, security_signature):
    """Проверяет обе сигнатуры под STORAGE_LOCK перед использованием снимка."""
    path = Path(os.path.abspath(data_dir)) / SECTION_FILENAMES[key]
    try:
        signature = file_signature(path)
        cached = _SECTION_CACHE.get(path)
        if cached is not None and cached["signature"] == (signature, security_signature):
            _SECTION_CACHE.move_to_end(path)
            return cached
        _SECTION_CACHE.pop(path, None)
        if signature is None:
            return _remember_section(path, key, None, None, None, security_signature)
        raw = path.read_bytes()
        text = decrypt_bytes(raw).decode("utf-8")
        encrypted = is_encrypted(raw)
        stable = file_signature(path) == signature
        # Сохраняем прежнюю автоматическую миграцию открытого JSON в AES-GCM.
        if stable and not encrypted and data_encryption_enabled(path.parent):
            write_text(path, text, encoding="utf-8")
            signature = file_signature(path)
            encrypted = True
        cached = _remember_section(path, key, text, encrypted, signature, security_signature)
        if not stable:
            _SECTION_CACHE.pop(path, None)
        return cached
    except OSError:
        _SECTION_CACHE.pop(path, None)
        value = _default_section(key)
        return {"text": None, "value": _normalize_groups(value) if key == "groups" else value}


def load_section(data_dir, key):
    """Читает один файл секции. Возвращает корректный список даже если файла
    нет или он повреждён."""
    with STORAGE_LOCK:
        signature = file_signature(Path(data_dir) / "security.json")
        return _copy_section(_read_section(data_dir, key, signature), key)


def load_all_sections(data_dir, *, copy_data=True):
    """Возвращает копию секций из кэша, проверяя внешние изменения файлов.

    copy_data=False предназначен только для внутренних читающих методов:
    такой снимок нельзя менять, в том числе его вложенные списки и словари.
    """
    with STORAGE_LOCK:
        signature = file_signature(Path(data_dir) / "security.json")
        data = {}
        for key in SECTION_FILENAMES:
            cached = _read_section(data_dir, key, signature)
            data[key] = _copy_section(cached, key) if copy_data else cached["value"]
        return data


def save_section(data_dir, key, value):
    """Перезаписывает файл секции, только если содержимое реально изменилось
    (сравнение по итоговому тексту). Возвращает True, если файл был записан
    заново — это и есть сигнал о том, что его нужно выгрузить в облако."""
    with STORAGE_LOCK:
        return _save_section(data_dir, key, value)


def _save_section(data_dir, key, value):
    path = Path(os.path.abspath(data_dir)) / SECTION_FILENAMES[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    signature = file_signature(path)
    security_signature = file_signature(path.parent / "security.json")
    enabled = data_encryption_enabled(path.parent)
    cached = _SECTION_CACHE.get(path)
    if cached is not None and cached["signature"] == (signature, security_signature):
        if cached["encrypted"] == enabled and cached["text"] == new_text:
            return False
    elif signature is not None:
        try:
            raw = path.read_bytes()
            if is_encrypted(raw) == enabled:
                text = decrypt_bytes(raw).decode("utf-8")
                if file_signature(path) == signature:
                    _remember_section(path, key, text, enabled, signature, security_signature)
                    if text == new_text:
                        return False
        except OSError:
            pass
    write_text(path, new_text, encoding="utf-8")
    _remember_section(path, key, new_text, enabled, file_signature(path), security_signature)
    return True


def save_all_sections(data_dir, data, force=False):
    """Сохраняет секции из data (какие есть ключи — те и сохраняются).
    Возвращает множество ключей секций, файлы которых были реально
    перезаписаны (значит их нужно выгрузить в облако). force=True
    перезаписывает все секции безусловно (используется для сброса)."""
    with STORAGE_LOCK:
        return _save_all_sections(data_dir, data, force)


def replace_all_sections(data_dir, data):
    """Replace a snapshot under the sync lock; roll back a failed disk write."""
    directory = Path(data_dir)
    with STORAGE_LOCK:
        originals = {
            directory / name: (directory / name).read_bytes() if (directory / name).exists() else None
            for name in SECTION_FILENAMES.values()
        }
        try:
            save_all_sections(directory, data, force=True)
        except Exception:
            for path, raw in originals.items():
                if raw is None:
                    path.unlink(missing_ok=True)
                else:
                    write_bytes(path, raw, encrypt=False)
            raise


def _save_all_sections(data_dir, data, force=False):
    changed = set()
    for key in SECTION_FILENAMES:
        if key not in data:
            continue
        if force:
            path = Path(os.path.abspath(data_dir)) / SECTION_FILENAMES[key]
            path.parent.mkdir(parents=True, exist_ok=True)
            security_signature = file_signature(path.parent / "security.json")
            text = json.dumps(data[key], ensure_ascii=False, indent=2) + "\n"
            enabled = data_encryption_enabled(path.parent)
            write_text(path, text, encoding="utf-8")
            _remember_section(path, key, text, enabled, file_signature(path), security_signature)
            changed.add(key)
        elif save_section(data_dir, key, data[key]):
            changed.add(key)
    return changed


def ensure_split_storage(data_dir, legacy_json_path):
    """Готовит папку раздельного хранения. Если все файлы уже есть — ничего
    не делает (дешёвая проверка на каждый старт приложения).

    Если файлов ещё нет, проверяет два источника (по порядку):
    1. подпапку "data" внутри data_dir — туда файлы клала предыдущая версия
       приложения (saves/data/*.json); переносит их в корень data_dir и
       удаляет опустевшую подпапку;
    2. единый legacy_json_path (itog.json) — уже приведённый к текущей
       JSON-схеме модулем ND_Json_migration (перенос из itog.txt, если он
       был, к этому моменту уже выполнен) — переносит данные из него.
    Если не нашлось ничего — создаёт пустую структуру."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if all((data_dir / name).exists() for name in SECTION_FILENAMES.values()):
        for name in SECTION_FILENAMES.values():
            encrypt_file_if_plaintext(data_dir / name)
        return False

    # An upgrade may introduce a new section. Never replace existing task
    # files with stale legacy data just because that new file is missing.
    if any((data_dir / name).exists() for name in SECTION_FILENAMES.values()):
        legacy_json_path = Path(legacy_json_path)
        source = load_data(legacy_json_path) if legacy_json_path.exists() else empty_data()
        for key, name in SECTION_FILENAMES.items():
            path = data_dir / name
            if path.exists():
                encrypt_file_if_plaintext(path)
            else:
                save_section(data_dir, key, source[key])
        return True

    old_subfolder = data_dir / "data"
    if old_subfolder.is_dir() and any((old_subfolder / name).exists() for name in SECTION_FILENAMES.values()):
        save_all_sections(data_dir, load_all_sections(old_subfolder), force=True)
        try:
            shutil.rmtree(old_subfolder)
        except OSError:
            pass
        return True

    legacy_json_path = Path(legacy_json_path)
    data = load_data(legacy_json_path) if legacy_json_path.exists() else empty_data()
    save_all_sections(data_dir, data, force=True)
    return True
