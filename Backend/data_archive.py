"""Portable ZIP snapshots of all task sections, including inline attachments."""

import json
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from .attachments import attachment_bytes
from .crypto import decrypt_bytes
from .storage import SECTION_FILENAMES, _normalize_groups, empty_data


MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


def create_data_archive(data):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for key, filename in SECTION_FILENAMES.items():
            archive.writestr(filename, json.dumps(data[key], ensure_ascii=False, indent=2) + "\n")
    return output.getvalue()


def _validate_records(data):
    for records in data.values():
        if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
            raise ValueError("В архиве некорректная структура данных.")
    collections = [data[key] for key in ("tasks", "postponed", "repeat_tasks")]
    for group in data["groups"]:
        if not isinstance(group.get("id"), str) or not isinstance(group.get("name"), str):
            raise ValueError("В архиве некорректная группа.")
        notes = group.get("notes", [])
        if not isinstance(notes, list) or any(not isinstance(note, dict) for note in notes):
            raise ValueError("В архиве некорректные заметки.")
        collections.append(notes)
    for records in collections:
        for item in records:
            for field in ("id", "name", "text", "group", "created_date", "deadline"):
                if field in item and not isinstance(item[field], str):
                    raise ValueError("В архиве некорректная запись.")
            attachments = item.get("attachments") or []
            if not isinstance(attachments, list):
                raise ValueError("В архиве некорректные вложения.")
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    raise ValueError("В архиве некорректное вложение.")
                attachment_bytes(attachment)


def read_data_archive(content):
    """Validate the entire snapshot before any current data can be replaced."""
    if not isinstance(content, bytes) or len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError("Не удалось прочитать архив или его размер превышает 256 МБ.")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 32 or sum(item.file_size for item in entries) > MAX_ARCHIVE_BYTES:
                raise ValueError("Архив слишком большой.")
            files = {}
            for entry in entries:
                name = entry.filename
                if ("\\" in name or PurePosixPath(name).is_absolute()
                        or ".." in PurePosixPath(name).parts):
                    raise ValueError("В архиве недопустимые пути.")
                if not entry.is_dir():
                    if name in files:
                        raise ValueError("В архиве повторяются имена файлов.")
                    files[name] = entry
            # Accept the singular spelling used by older hand-made snapshots.
            if "groups.json" not in files and "group.json" in files:
                files["groups.json"] = files["group.json"]
            required = {name for key, name in SECTION_FILENAMES.items() if key != "achievements"}
            if not required.issubset(files):
                raise ValueError("В архиве должны быть groups.json, tasks.json, postponed.json и repeat_tasks.json.")
            data = empty_data()
            for key, name in SECTION_FILENAMES.items():
                if name in files:
                    raw = archive.read(files[name])
                    data[key] = json.loads(decrypt_bytes(raw).decode("utf-8-sig"))
            _validate_records(data)
            _normalize_groups(data["groups"])
            return data
    except (BadZipFile, UnicodeError, RuntimeError, NotImplementedError, RecursionError) as error:
        raise ValueError("Архив повреждён или имеет неподдерживаемый формат.") from error
