"""Хранилище дел ежедневника: раздельные JSON-файлы (tasks.json, postponed.json,
groups.json, repeat_tasks.json) в папке сохранений.

Этот модуль работает только с текущей JSON-схемой и ничего не знает про
старый itog.txt или про промежуточный JSON с ключами normal/repeat — вся
логика переноса из этих устаревших форматов вынесена в Backend/json_migration.py
и используется один раз при первом запуске приложения.
"""
import json
import shutil
import threading
from copy import deepcopy
from pathlib import Path
from .crypto import (
    ACCOUNT_DATA_FILENAMES, data_encryption_enabled, decrypt_bytes,
    encrypt_file_if_plaintext, is_encrypted, read_text, write_bytes, write_text,
)

STORAGE_LOCK = threading.RLock()


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
# Раздельное хранение: вместо одного itog.json — папка с четырьмя файлами
# (tasks.json, postponed.json, groups.json, repeat_tasks.json). Это позволяет
# при каждом изменении читать/писать/выгружать в облако только тот файл,
# который реально изменился, а не весь итог целиком.
# --------------------------------------------------------------------------

SECTION_FILENAMES = {
    "groups": "groups.json",
    "tasks": "tasks.json",
    "postponed": "postponed.json",
    "repeat_tasks": "repeat_tasks.json",
}


def _default_section(key):
    if key == "groups":
        return [{"id": "default", "name": "Без группы", "split_by_dates": True, "show_created_date": True}]
    return []


def load_section(data_dir, key):
    """Читает один файл секции. Возвращает корректный список даже если файла
    нет или он повреждён."""
    path = Path(data_dir) / SECTION_FILENAMES[key]
    try:
        with STORAGE_LOCK:
            value = json.loads(read_text(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = None
    if not isinstance(value, list):
        value = _default_section(key)
    if key == "groups":
        _normalize_groups(value)
    return value


def load_all_sections(data_dir):
    """Читает все четыре файла секции разом и возвращает словарь
    {"tasks": [...], "postponed": [...], "groups": [...], "repeat_tasks": [...]}."""
    with STORAGE_LOCK:
        return {key: load_section(data_dir, key) for key in SECTION_FILENAMES}


def save_section(data_dir, key, value):
    """Перезаписывает файл секции, только если содержимое реально изменилось
    (сравнение по итоговому тексту). Возвращает True, если файл был записан
    заново — это и есть сигнал о том, что его нужно выгрузить в облако."""
    with STORAGE_LOCK:
        return _save_section(data_dir, key, value)


def _save_section(data_dir, key, value):
    path = Path(data_dir) / SECTION_FILENAMES[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        try:
            if (is_encrypted(path.read_bytes()) == data_encryption_enabled(data_dir)
                    and read_text(path, encoding="utf-8") == new_text):
                return False
        except OSError:
            pass
    write_text(path, new_text, encoding="utf-8")
    return True


def save_all_sections(data_dir, data, force=False):
    """Сохраняет секции из data (какие есть ключи — те и сохраняются).
    Возвращает множество ключей секций, файлы которых были реально
    перезаписаны (значит их нужно выгрузить в облако). force=True
    перезаписывает все секции безусловно (используется для сброса)."""
    with STORAGE_LOCK:
        return _save_all_sections(data_dir, data, force)


def _save_all_sections(data_dir, data, force=False):
    changed = set()
    for key in SECTION_FILENAMES:
        if key not in data:
            continue
        if force:
            path = Path(data_dir) / SECTION_FILENAMES[key]
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, json.dumps(data[key], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changed.add(key)
        elif save_section(data_dir, key, data[key]):
            changed.add(key)
    return changed


def ensure_split_storage(data_dir, legacy_json_path):
    """Готовит папку раздельного хранения. Если все 4 файла уже есть — ничего
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
