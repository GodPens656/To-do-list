"""Перенос данных из старых форматов хранения в текущий JSON.

Раньше приложение хранило дела в текстовом файле itog.txt: четыре секции
(обычные дела, повторяющиеся дела, отложенные дела, группы), разделённые
строкой "---", в каждой секции — по одному делу на строку в виде
"поле1|поле2|поле3|...". Позже появился промежуточный единый JSON (itog.json)
с ключами normal/repeat вместо tasks/repeat_tasks.

Вся логика распознавания и разбора этих старых форматов собрана здесь и
нужна только один раз — при первом запуске приложения на сохранениях,
сделанных старой версией. Остальной код (Backend/storage.py и всё, что
сохраняет/читает дела через него — Backend/core.py, Backend/extended.py,
Backend/cloud.py) работает только с раздельным JSON-хранилищем
(tasks.json/repeat_tasks.json/postponed.json/groups.json) и ничего не
знает про itog.txt или про единый itog.json."""
import json
from pathlib import Path

from .storage import empty_data, save_data
from .crypto import read_text


def lines_to_data(normal_lines, repeat_lines, postponed_lines, group_lines):
    """Преобразует четыре списка строк старого itog.txt
    ('normal|status|id|...' и т.п.) в словарь с ключами
    tasks/repeat_tasks/postponed/groups — текущая JSON-схема."""
    tasks, repeats, postponed, groups = [], [], [], []
    for row in normal_lines:
        parts = row.split("|")
        if len(parts) >= 3:
            tasks.append({"id": parts[2], "name": parts[0], "status": parts[1] == "True", "group": parts[3] if len(parts) > 3 and parts[3] else "default", "is_repeat": len(parts) > 4 and parts[4] == "1", "created_date": parts[5] if len(parts) > 5 else ""})
    for row in repeat_lines:
        parts = row.split("|")
        if len(parts) >= 2:
            repeats.append({"id": parts[5] if len(parts) > 5 else "", "name": parts[0], "last_date": parts[1], "repeat_type": parts[2] if len(parts) > 2 else "day", "repeat_value": parts[3] if len(parts) > 3 else 1, "group": parts[4] if len(parts) > 4 and parts[4] else "default"})
    for row in postponed_lines:
        parts = row.split("|")
        if len(parts) >= 2:
            postponed.append({"id": parts[3] if len(parts) > 3 else "", "name": parts[0], "group": parts[2] if len(parts) > 2 and parts[2] else "default", "date": parts[1]})
    for row in group_lines:
        parts = row.split("|")
        if len(parts) >= 2:
            groups.append({
                "id": parts[1],
                "name": parts[0],
                # Поддержка старых строк вида "name|id" без сохранённых настроек.
                "split_by_dates": parts[2] == "True" if len(parts) > 2 else True,
                "show_created_date": parts[3] == "True" if len(parts) > 3 else True,
            })
    if not any(group["id"] == "default" for group in groups):
        groups.insert(0, {"id": "default", "name": "Без группы", "split_by_dates": True, "show_created_date": True})
    return {"tasks": tasks, "postponed": postponed, "groups": groups, "repeat_tasks": repeats}


def migrate_txt_file(old_path, json_path, overwrite=False):
    """Однократно переносит старый itog.txt в json_path, если JSON ещё не
    создан (или overwrite=True, когда в json_path лежит промежуточная схема
    normal/repeat, которую тоже нужно заменить полноценным переносом из txt,
    если сам txt ещё жив)."""
    old_path, json_path = Path(old_path), Path(json_path)
    if (json_path.exists() and not overwrite) or not old_path.exists() or not read_text(old_path, encoding="utf-8").strip():
        return False
    parts = [part.strip().splitlines() for part in read_text(old_path, encoding="utf-8").split("---")]
    while len(parts) < 4:
        parts.append([])
    normal_lines, repeat_lines, postponed_lines, group_lines = parts[0], parts[1], parts[2], parts[3]
    save_data(json_path, lines_to_data(normal_lines, repeat_lines, postponed_lines, group_lines))
    return True


def has_legacy_json_schema(path):
    """Возвращает True для промежуточного JSON с ключами normal/repeat
    (ранняя версия приложения, ещё до текущей схемы tasks/repeat_tasks)."""
    try:
        raw = json.loads(read_text(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(raw, dict) and ("normal" in raw or "repeat" in raw)


def load_data_from_dict(data):
    """Аналог Backend.storage.load_data, но принимает уже разобранный словарь
    (используется migrate_json_schema, которому не нужно читать файл заново)."""
    result = empty_data()
    if isinstance(data, dict):
        for key in result:
            if isinstance(data.get(key), list):
                result[key] = data[key]
    if not any(group.get("id") == "default" for group in result["groups"] if isinstance(group, dict)):
        result["groups"].insert(0, {"id": "default", "name": "Без группы", "split_by_dates": True, "show_created_date": True})
    for group in result["groups"]:
        if isinstance(group, dict):
            group.setdefault("type", "tasks")
            group.setdefault("split_by_dates", True)
            group.setdefault("show_created_date", True)
            group.setdefault("show_completion_counter", True)
            group.setdefault("show_group_title", True)
    return result


def migrate_json_schema(path):
    """Приводит ранний JSON с ключами normal/repeat к текущей схеме
    tasks/postponed/groups/repeat_tasks."""
    path = Path(path)
    try:
        raw = json.loads(read_text(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if isinstance(raw, dict) and ("normal" in raw or "repeat" in raw):
        data = {
            "tasks": raw.get("normal", []),
            "postponed": raw.get("postponed", []),
            "groups": raw.get("groups", []),
            "repeat_tasks": raw.get("repeat", []),
        }
        save_data(path, load_data_from_dict(data))
        return True
    return False


def migrate_legacy_storage(save_dir, json_path):
    """Удобный единый вход для приложения: переносит itog.txt в единый
    itog.json (если он ещё не перенесён или json_path пуст/содержит только
    промежуточную схему normal/repeat), затем приводит промежуточную схему
    к текущей. json_path после этого гарантированно существует и содержит
    актуальную JSON-схему (tasks/postponed/groups/repeat_tasks). Используется
    при старте приложения перед переходом на раздельное хранение
    (Backend.storage.ensure_split_storage)."""
    save_dir, json_path = Path(save_dir), Path(json_path)
    migrate_txt_file(save_dir / "itog.txt", json_path, overwrite=has_legacy_json_schema(json_path))
    if not json_path.exists():
        save_data(json_path, empty_data())
    migrate_json_schema(json_path)
