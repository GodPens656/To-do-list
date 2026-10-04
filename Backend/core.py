from pathlib import Path
from copy import deepcopy
import uuid
import os
from textwrap import fill
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .cloud import Cloud
from .storage import load_all_sections, save_all_sections, empty_data, ensure_split_storage
from .json_migration import migrate_legacy_storage
from .validation import text_length_error


DEFAULT_WEB_TIMEZONE = "Europe/Moscow"
DESKTOP_TEXT_LINE_LENGTH = 40


def _web_timezone(page=None):
    """Return the browser timezone independently of the server timezone."""
    timezone_name = getattr(page, "_nd_timezone", None)
    timezone_name = timezone_name or os.getenv("ND_TIMEZONE", DEFAULT_WEB_TIMEZONE)
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        offset_minutes = getattr(page, "_nd_timezone_offset_minutes", None)
        if isinstance(offset_minutes, int) and -840 <= offset_minutes <= 840:
            return timezone(timedelta(minutes=offset_minutes))
        return timezone(timedelta(hours=5))


def local_now(web=False, page=None):
    """Return the current local time for the native or web client."""
    if web:
        return datetime.now(_web_timezone(page))
    return datetime.now().astimezone()


def local_today(web=False, page=None):
    """Return the client's current calendar date."""
    return local_now(web, page).date()

class Backend:
    def __init__(self, page=None, web_store=None, cloud=None):
        super().__init__()
        self.page = page
        self._undo_state = None
        self.on_undo_change = None
        # web_store не None -> сайт, page.web is True: данные каждого
        # посетителя хранятся у него в браузере (см. Backend/webstorage.py),
        # а не в файлах на сервере.
        self.web = web_store is not None
        self.Save_in_time = ""
        self.phone = False
        self.version = '3.11.0'
        if self.web:
            self.store = web_store
            self.cloud = cloud or Cloud(web_store=web_store)
            return
        if os.getenv("FLET_APP_STORAGE_DATA"):  # Запуск на Android
            self.Save_in_time = Path(os.getenv("FLET_APP_STORAGE_DATA"))
            self.Save_in_time.mkdir(parents=True, exist_ok=True)
            self.setting_dir = Path(os.getenv("FLET_APP_STORAGE_DATA"))
            self.setting_dir.mkdir(parents=True, exist_ok=True)
            self.phone = True
        else:  # Запуск на ПК
            self.Save_in_time = Path("saves")
            self.setting_dir = Path("settings")
            self.setting_dir.mkdir(parents=True, exist_ok=True)
            self.phone = False
        save_dir = self.Save_in_time
        # itog.json нужен только как временный формат для однократного
        # переноса очень старых сохранений (itog.txt) в раздельное
        # хранилище — вся эта логика вынесена в Backend/json_migration.py.
        self.Save_in_time = save_dir / "itog.json"
        self.settings = self.setting_dir / "settings.txt"
        migrate_legacy_storage(save_dir, self.Save_in_time)
        # Раздельное хранение: вместо одного itog.json — 4 файла прямо в
        # папке сохранений (tasks.json, postponed.json, groups.json,
        # repeat_tasks.json). При первом запуске переносит данные из
        # старого itog.json (или из прежней подпапки saves/data) один раз.
        self.data_dir = save_dir
        ensure_split_storage(self.data_dir, self.Save_in_time)
        self.cloud = cloud or Cloud(web_store=web_store)

    def _load(self):
        """Читает все секции хранилища (tasks/repeat_tasks/postponed/groups)
        разом в виде словаря списков словарей."""
        if self.web:
            return self.store.load_all_sections()
        return load_all_sections(self.data_dir)

    def _save(self, data, *, undoable=True):
        """Сохраняет секции. На ПК/Android — перезаписывая только реально
        изменившиеся файлы. На сайте — в браузере посетителя (в фоне)."""
        previous = self._load()
        if previous == data:
            return
        if self.web:
            self.store.save_all_sections(data)
        else:
            save_all_sections(self.data_dir, data)
        self._undo_state = (deepcopy(previous), deepcopy(data)) if undoable else None
        self._notify_undo_change()

    def _notify_undo_change(self):
        callback = getattr(self, 'on_undo_change', None)
        if callback:
            callback()

    def clear_undo(self):
        self._undo_state = None
        self._notify_undo_change()

    def can_undo(self):
        state = getattr(self, '_undo_state', None)
        # Never overwrite newer data received from the cloud or another client.
        return state is not None and self._load() == state[1]

    def undo_last_action(self):
        if not self.can_undo():
            self.clear_undo()
            return False
        previous = deepcopy(self._undo_state[0])
        self._save(previous, undoable=False)
        return True

    def get_quantity_strings(self):
        return len(self._load()["tasks"])

    def read_tasks(self):
        """Возвращает обычные дела в виде списка словарей
        {id, name, status, group, is_repeat, created_date}.
        В названиях восстанавливаются сохранённые ручные переносы строк."""
        tasks = []
        for stored_task in self._load()["tasks"]:
            task = stored_task.copy()
            if isinstance(task.get("name"), str):
                task["name"] = task["name"].replace('{N}', '\n')
            tasks.append(task)
        return tasks

    def saveB(self, name, group_id='default', is_repeat=False, created_date=None,
              deadline=None, priority='Неважно', info_type='created_date'):
        """Сохраняет дело. is_repeat=True помечает дело как автоматически
        добавленное из ежедневного (повторяющегося) правила — это позволяет
        фронтенду отрисовывать такие дела отдельным блоком, отделённым
        разделителем от остальных дел. created_date фиксирует дату создания
        дела (по умолчанию — сегодняшняя дата в формате ДД-ММ-ГГГГ)."""
        if text_length_error(name):
            return False
        name = name.replace('\n', '{N}')
        data = self._load()
        created_date = created_date or local_today(self.web, self.page).strftime('%d-%m-%Y')
        data["tasks"].append({
            "id": uuid.uuid4().hex,
            "name": name,
            "status": False,
            "group": group_id,
            "is_repeat": bool(is_repeat),
            "created_date": created_date,
            "deadline": deadline or "",
            "priority": priority or "Неважно",
            "info_type": info_type or "created_date",
        })
        self._save(data, undoable=not is_repeat)

    def get_device(self):
        return self.phone

    def kill_taskB(self, id_task):
        data = self._load()
        data["tasks"] = [t for t in data["tasks"] if t.get("id") != id_task]
        self._save(data)

    def redact_statusB(self, id_task, status):
        data = self._load()
        for task in data["tasks"]:
            if task.get("id") == id_task:
                task["status"] = bool(status)
        self._save(data)

    def get_task(self, id_task):
        for task in self._load()["tasks"]:
            if task.get("id") == id_task:
                return task.copy()
        return None

    def redact_taskB(self, id_task, new_name, metadata=None):
        if text_length_error(new_name):
            return False
        new_name = new_name.replace('\n', '{N}')
        data = self._load()
        for task in data["tasks"]:
            if task.get("id") == id_task:
                task["name"] = new_name
                if metadata is not None:
                    task.update(metadata)
        self._save(data)

    def auto_add_new_string(self, text):
        """На телефоне переносит Flet; на ПК — по длине, без разрыва слов.

        Ручные переносы и пустые строки сохраняются. Слово длиннее лимита
        остаётся целым, даже если строка превышает DESKTOP_TEXT_LINE_LENGTH.
        """
        if self.phone:
            return text
        return '\n'.join(
            fill(
                line,
                width=DESKTOP_TEXT_LINE_LENGTH,
                break_long_words=False,
                break_on_hyphens=False,
            )
            for line in text.split('\n')
        )

    def read_id(self, name_of_task):
        name_of_task = name_of_task.replace('\n', '{N}')
        for task in self._load()["tasks"]:
            if task.get("name") == name_of_task:
                return task.get("id")

    def delete_empty_lines(self):
        data = self._load()
        data["tasks"] = [t for t in data["tasks"] if str(t.get("name", "")).strip() != '']
        data["repeat_tasks"] = [t for t in data["repeat_tasks"] if str(t.get("name", "")).strip() != '']
        data["postponed"] = [t for t in data["postponed"] if str(t.get("name", "")).strip() != '']
        self._save(data, undoable=False)

    def read_name(self, id_task):
        for task in self._load()["tasks"]:
            if task.get("id") == id_task:
                return str(task.get("name", "")).replace('{N}', '\n')

    def read_created_date(self, id_task):
        """Возвращает дату создания дела (ДД-ММ-ГГГГ) или пустую строку,
        если дело не найдено или было создано до появления этого поля."""
        for task in self._load()["tasks"]:
            if task.get("id") == id_task:
                return task.get("created_date", '')
        return ''

    def delete_all(self):
        self.clear_undo()
        if self.web:
            self.store.save_all_sections(empty_data())
        else:
            save_all_sections(self.data_dir, empty_data(), force=True)
        self.cloud.del_all()

    def get_groups(self):
        """Возвращает группы. Старые дела доступны в группе «Без группы».

        Каждая группа содержит также свои персональные настройки:
        split_by_dates (разделять дела по датам создания),
        show_created_date (подписывать дату создания дел) и
        show_completion_counter (показывать счётчик выполнения),
        show_group_title (показывать название текущей группы) хранятся
        прямо у самой группы (groups.json), а не в общем settings.txt."""
        groups = []
        for group in self._load()["groups"]:
            if not isinstance(group, dict) or not group.get("id"):
                continue
            groups.append({
                'name': group.get('name', ''),
                'id': group.get('id'),
                'type': group.get('type', 'tasks'),
                'note_count': len(group.get('notes', [])),
                'split_by_dates': bool(group.get('split_by_dates', True)),
                'show_created_date': bool(group.get('show_created_date', True)),
                'show_completion_counter': bool(group.get('show_completion_counter', True)),
                'show_group_title': bool(group.get('show_group_title', True)),
            })
        return groups

    def get_group_settings(self, group_id):
        """Возвращает персональные настройки конкретной группы дел:
        Если группа не найдена, все переключатели включены по умолчанию."""
        for group in self.get_groups():
            if group['id'] == group_id:
                return {
                    'split_by_dates': group['split_by_dates'],
                    'show_created_date': group['show_created_date'],
                    'show_completion_counter': group['show_completion_counter'],
                    'show_group_title': group['show_group_title'],
                }
        return {'split_by_dates': True, 'show_created_date': True,
                'show_completion_counter': True, 'show_group_title': True}

    def update_group_settings(self, group_id, split_by_dates=None, show_created_date=None,
                              show_completion_counter=None, show_group_title=None):
        """Изменяет персональные настройки для группы
        group_id. Значения, равные None, не изменяются."""
        data = self._load()
        found = False
        for group in data["groups"]:
            if group.get("id") == group_id:
                found = True
                if split_by_dates is not None:
                    group["split_by_dates"] = bool(split_by_dates)
                if show_created_date is not None:
                    group["show_created_date"] = bool(show_created_date)
                if show_completion_counter is not None:
                    group["show_completion_counter"] = bool(show_completion_counter)
                if show_group_title is not None:
                    group["show_group_title"] = bool(show_group_title)
        if not found and group_id == 'default':
            # У группы «Без группы» может ещё не быть отдельной записи,
            # если пользователь ни разу не переименовывал её.
            data["groups"].insert(0, {
                "id": "default",
                "name": "Без группы",
                "split_by_dates": bool(split_by_dates) if split_by_dates is not None else True,
                "show_created_date": bool(show_created_date) if show_created_date is not None else True,
                "show_completion_counter": bool(show_completion_counter) if show_completion_counter is not None else True,
                "show_group_title": bool(show_group_title) if show_group_title is not None else True,
            })
            found = True
        if found:
            self._save(data)
        return found

    def get_group_default_filter(self, group_id):
        """None означает общий фильтр; disabled — явное отключение в группе."""
        for group in self._load()["groups"]:
            if group.get("id") == group_id:
                value = group.get("default_task_filter")
                if isinstance(value, dict):
                    return {
                        "sort": value.get("sort", "disabled"),
                        "status_sort": value.get("status_sort", "disabled"),
                    }
        return None

    def set_group_default_filter(self, group_id, sort_mode, status_sort):
        """Сохраняет оба параметра фильтра только для указанной группы."""
        data = self._load()
        for group in data["groups"]:
            if group.get("id") == group_id:
                group["default_task_filter"] = {
                    "sort": sort_mode,
                    "status_sort": status_sort,
                }
                self._save(data)
                return True
        return False

    def reset_group_default_filter(self, group_id):
        """Возвращает группу к общему фильтру по умолчанию."""
        data = self._load()
        for group in data["groups"]:
            if group.get("id") == group_id:
                group.pop("default_task_filter", None)
                self._save(data)
                return True
        return False

    def migrate_groups_storage(self):
        """Один раз приводит старые записи (без явной группы) к формату с
        идентификатором группы."""
        data = self._load()
        changed = False
        for task in data["tasks"]:
            if "group" not in task or not task.get("group"):
                task["group"] = "default"
                changed = True
        if data["tasks"] and not any(group.get("id") == "default" for group in data["groups"]):
            data["groups"].insert(0, {"id": "default", "name": "Без группы", "split_by_dates": True, "show_created_date": True})
            changed = True
        if changed:
            self._save(data, undoable=False)

    def create_group(self, name, split_by_dates=True, show_created_date=True, group_type='tasks'):
        if text_length_error(name):
            return None
        name = name.strip()
        if not name or '|' in name or '---' in name or group_type not in ('tasks', 'notes'):
            return None
        data = self._load()
        group_id = uuid.uuid4().hex
        data["groups"].append({
            "id": group_id,
            "name": name,
            "type": group_type,
            **({"notes": []} if group_type == 'notes' else {}),
            "split_by_dates": bool(split_by_dates),
            "show_created_date": bool(show_created_date),
            "show_completion_counter": True,
            "show_group_title": True,
        })
        self._save(data)
        return group_id

    def get_group_type(self, group_id):
        return next((g['type'] for g in self.get_groups() if g['id'] == group_id), 'tasks')

    def read_notes(self, group_id):
        """Заметки хранятся внутри группы и синхронизируются с groups.json."""
        for group in self._load()['groups']:
            if group.get('id') == group_id and group.get('type') == 'notes':
                return [note.copy() for note in group.get('notes', [])]
        return []

    def save_note(self, group_id, text, note_id=None):
        if not text or not text.strip() or text_length_error(text):
            return None
        data = self._load()
        for group in data['groups']:
            if group.get('id') != group_id or group.get('type') != 'notes':
                continue
            notes = group.setdefault('notes', [])
            if note_id is None:
                note_id = uuid.uuid4().hex
                notes.append({
                    'id': note_id, 'text': text,
                    'created_date': local_today(self.web, self.page).strftime('%d-%m-%Y'),
                })
            else:
                note = next((n for n in notes if n.get('id') == note_id), None)
                if note is None:
                    return None
                note['text'] = text
            self._save(data)
            return note_id
        return None

    def delete_note(self, group_id, note_id):
        data = self._load()
        for group in data['groups']:
            if group.get('id') == group_id and group.get('type') == 'notes':
                notes = group.get('notes', [])
                remaining = [note for note in notes if note.get('id') != note_id]
                if len(remaining) == len(notes):
                    return False
                group['notes'] = remaining
                self._save(data)
                return True
        return False

    def rename_group(self, group_id, name):
        if text_length_error(name):
            return False
        name = name.strip()
        if not name or '|' in name or '---' in name:
            return False
        data = self._load()
        for group in data["groups"]:
            if group.get("id") == group_id:
                group["name"] = name
        self._save(data)
        return True

    def delete_group(self, group_id):
        """Удаляет группу вместе с её обычными делами."""
        if group_id == 'default':
            return False
        data = self._load()
        data["tasks"] = [t for t in data["tasks"] if t.get("group", "default") != group_id]
        data["groups"] = [g for g in data["groups"] if g.get("id") != group_id]
        self._save(data)
        return True
