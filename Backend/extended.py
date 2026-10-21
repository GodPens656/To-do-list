from pathlib import Path
from copy import deepcopy
from datetime import date, datetime, timedelta
import base64
import io
import json
import os
import threading
import uuid
import zipfile
from PIL import Image, UnidentifiedImageError
from .core import Backend, local_today
from .validation import text_length_error
from .security import hash_password, verify_password
from .cloud import Cloud
from .storage import save_data, empty_data, ensure_split_storage, load_all_sections, save_all_sections
from .json_migration import migrate_legacy_storage
from .crypto import (
    encrypt_file_if_plaintext,
    read_bytes as read_encrypted_bytes,
    read_text as read_encrypted_text,
    write_bytes as write_encrypted_bytes,
    write_text as write_encrypted_text,
)
from Frontend.theme import (
    normalize_button_background_mode,
    normalize_custom_color,
    normalize_theme_style,
)
from Frontend.typography import normalize_font_family, normalize_font_size

class Backend2:
    CUSTOM_ICON_NAMES = (
        "plusS.png",
        "settings.png",
        "auth.png",
        "update.png",
        "nazad.png",
        "basket1.png",
        "redact.png",
        "info.png",
    )
    OPTIONAL_CUSTOM_ICON_NAMES = ("logout.png",)
    CUSTOM_ICON_ARCHIVE_LIMIT = 20 * 1024 * 1024
    CUSTOM_ICON_FILE_LIMIT = 5 * 1024 * 1024
    CUSTOM_ICON_MAX_SIDE = 192

    def __init__(self, page=None, web_store=None, back=None, cloud=None):
        self.page = page
        self.cloud = cloud or Cloud(web_store=web_store)
        self.web = web_store is not None
        self.back = back if back is not None else Backend(
            page=page, web_store=web_store, cloud=self.cloud
        )
        self.phone = False
        if self.web:
            # Сайт: свои дела и настройки у каждого посетителя, в браузере
            # (Backend/webstorage.py) — миграции старых форматов (файлы на диске
            # сервера) тут не нужны, это всегда "чистый" визит.
            self.store = web_store
            self.date = local_today(self.web, self.page).strftime('%d-%m-%Y')
            self.set_default_settings()
            self.load_custom_icon_pack()
            return
        if os.getenv("FLET_APP_STORAGE_DATA"):  # Запуск на Android
            self.Save_in_time1 = Path(os.getenv("FLET_APP_STORAGE_DATA"))
            self.Save_in_time1.mkdir(parents=True, exist_ok=True)
            self.setting_dir = Path(os.getenv("FLET_APP_STORAGE_DATA"))
            self.setting_dir.mkdir(parents=True, exist_ok=True)
            self.phone = True
        else:  # Запуск на ПК
            self.Save_in_time1 = Path("saves")
            self.setting_dir = Path("settings")
            self.setting_dir.mkdir(parents=True, exist_ok=True)
            self.phone = False

        self.user_data = self.Save_in_time1 / "user_data"
        self.user_data.mkdir(parents=True, exist_ok=True)
        # itog.json нужен только как временный формат для однократного
        # переноса очень старых сохранений (itog.txt) — см. Backend/json_migration.py.
        self.Save_in_time = self.Save_in_time1 / "itog.json"
        migrate_legacy_storage(self.Save_in_time1, self.Save_in_time)

        self.settings = self.setting_dir / "settings.txt"
        self.accounts = self.user_data / "accounts.txt"
        self.accounts.touch(exist_ok=True)
        self.postponed_tasks = self.user_data / "postponed_tasks.txt"
        self.postponed_tasks.touch(exist_ok=True)

        self.last_update = self.user_data / "last_update.txt"
        self.last_notification = self.user_data / "last_notification.txt"
        self.last_update_tasks = self.user_data / "last_update_tasks.txt"

        for private_file in (
            self.accounts,
            self.postponed_tasks,
            self.last_update,
            self.last_notification,
            self.last_update_tasks,
        ):
            if private_file.exists():
                encrypt_file_if_plaintext(private_file)

        self.date = local_today(self.web, self.page).strftime('%d-%m-%Y')
        self.set_default_settings()
        # _migrate_group_date_settings ещё работает с единым self.Save_in_time
        # (нужно перенести старые настройки внутрь itog.json до того, как он
        # будет разложен на отдельные файлы).
        self._migrate_group_date_settings()
        # Раздельное хранение: вместо одного itog.json — 4 файла прямо в
        # папке сохранений (tasks.json, postponed.json, groups.json,
        # repeat_tasks.json). При первом запуске переносит данные из старого
        # itog.json (или из прежней подпапки saves/data) один раз, дальше
        # эта проверка — дешёвый no-op.
        self.data_dir = self.Save_in_time1
        ensure_split_storage(self.data_dir, self.Save_in_time)
        self._migrate_postponed_tasks_to_itog()
        self._migrate_special_tasks_ids()
        self.load_custom_icon_pack()

    @property
    def custom_icon_archive(self):
        """Путь к пользовательскому паку в нативной версии приложения."""
        if self.web:
            return None
        return self.setting_dir / "custom_icon_pack.zip"

    def _read_custom_icon_archive(self):
        if self.web:
            encoded = self.store.read_meta_text("custom_icon_pack")
            if not encoded:
                return None
            try:
                return base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                return None
        archive = self.custom_icon_archive
        if archive is None or not archive.is_file():
            return None
        try:
            return read_encrypted_bytes(archive)
        except OSError:
            return None

    def _validate_custom_icon_archive(self, archive_data):
        """Проверяет ZIP и возвращает PNG по имени, ничего не распаковывая."""
        if not isinstance(archive_data, bytes) or not archive_data:
            raise ValueError("Не удалось прочитать выбранный архив.")
        if len(archive_data) > self.CUSTOM_ICON_ARCHIVE_LIMIT:
            raise ValueError("Архив слишком большой (максимум 20 МБ).")

        required = set(self.CUSTOM_ICON_NAMES)
        supported = required | set(self.OPTIONAL_CUSTOM_ICON_NAMES)
        icons = {}
        try:
            with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
                members = [item for item in archive.infolist() if not item.is_dir()]
                if len(members) > 64:
                    raise ValueError("В архиве слишком много файлов.")
                total_size = sum(item.file_size for item in members)
                if total_size > self.CUSTOM_ICON_ARCHIVE_LIMIT:
                    raise ValueError("Суммарный размер файлов в архиве превышает 20 МБ.")
                for item in members:
                    # Разрешаем общую папку внутри ZIP, но учитываем только
                    # точные имена ожидаемых PNG и не извлекаем пути на диск.
                    name = Path(item.filename.replace("\\", "/")).name
                    # В тексте формата исторически указано `basket1` без
                    # расширения, поэтому принимаем оба написания.
                    if name == "basket1":
                        name = "basket1.png"
                    if name not in supported:
                        continue
                    if name in icons:
                        raise ValueError(f"Иконка {name} встречается в архиве дважды.")
                    if item.file_size > self.CUSTOM_ICON_FILE_LIMIT:
                        raise ValueError(f"Иконка {name} слишком большая (максимум 5 МБ).")
                    data = archive.read(item)
                    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ValueError(f"Файл {name} не является PNG-изображением.")
                    icons[name] = self._optimize_custom_icon(data, name)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
            raise ValueError("Выбранный файл не является корректным ZIP-архивом.") from error

        missing = [name for name in self.CUSTOM_ICON_NAMES if name not in icons]
        if missing:
            raise ValueError("В архиве не хватает файлов: " + ", ".join(missing))
        return {Path(name).stem: data for name, data in icons.items()}

    def _optimize_custom_icon(self, data, name):
        """Уменьшает PNG до размера UI, чтобы не пересылать мегабайты на кнопку."""
        try:
            with Image.open(io.BytesIO(data)) as source:
                source.verify()
            with Image.open(io.BytesIO(data)) as source:
                if source.format != "PNG" or source.width < 1 or source.height < 1:
                    raise ValueError
                if source.width > 4096 or source.height > 4096:
                    raise ValueError(
                        f"Иконка {name} имеет слишком большое разрешение "
                        "(максимум 4096×4096)."
                    )
                icon = source.convert("RGBA")
                icon.thumbnail(
                    (self.CUSTOM_ICON_MAX_SIDE, self.CUSTOM_ICON_MAX_SIDE),
                    Image.Resampling.LANCZOS,
                )
                optimized = io.BytesIO()
                icon.save(optimized, format="PNG", optimize=True)
                return optimized.getvalue()
        except ValueError:
            raise
        except (OSError, SyntaxError, UnidentifiedImageError) as error:
            raise ValueError(f"Файл {name} повреждён или не является PNG.") from error

    def load_custom_icon_pack(self):
        """Загружает сохранённый пак в память текущей страницы."""
        archive_data = self._read_custom_icon_archive()
        try:
            icons = self._validate_custom_icon_archive(archive_data)
        except ValueError:
            icons = {}
        self._cache_custom_icons_for_page(icons)
        return icons

    def _cache_custom_icons_for_page(self, icons):
        """Готовит байты для native и data URI для браузерного клиента."""
        if self.page is None:
            return
        self.page._nd_custom_icons = icons
        self.page._nd_custom_icon_sources = {
            name: "data:image/png;base64," + base64.b64encode(data).decode("ascii")
            for name, data in icons.items()
        }

    def has_custom_icon_pack(self):
        return bool(getattr(self.page, "_nd_custom_icons", {}))

    def install_custom_icon_pack(self, archive_data):
        """Проверяет, сохраняет и активирует пользовательский пак иконок."""
        icons = self._validate_custom_icon_archive(archive_data)
        if self.web:
            self.store.write_meta_text(
                "custom_icon_pack", base64.b64encode(archive_data).decode("ascii")
            )
        else:
            archive = self.custom_icon_archive
            temporary = archive.with_suffix(".tmp")
            write_encrypted_bytes(temporary, archive_data)
            temporary.replace(archive)
        self._cache_custom_icons_for_page(icons)

    def _load(self):
        """Читает все секции хранилища разом в виде словаря списков словарей."""
        if self.web:
            return self.store.load_all_sections()
        return load_all_sections(self.data_dir)

    def _save(self, data, *, undoable=True):
        """Сохраняет секции, перезаписывая только реально изменившиеся файлы."""
        self.back._save(data, undoable=undoable)

    def _migrate_postponed_tasks_to_itog(self):
        """Переносит старые отложенные дела из отдельного файла
        (saves/user_data/postponed_tasks.txt, формат 'дело|дата|группа|id')
        в общее хранилище отложенных дел."""
        old_rows = [row for row in read_encrypted_text(self.postponed_tasks, encoding='utf-8').splitlines() if row.strip()]
        if not old_rows:
            return

        data = self._load()
        existing_keys = {(p.get('name'), p.get('date'), p.get('group')) for p in data["postponed"] if isinstance(p, dict)}
        changed = False
        for row in old_rows:
            try:
                task, planned_date, group_id, task_id = self._parse_postponed_row(row)
            except ValueError:
                continue
            key = (task, planned_date, group_id)
            if key in existing_keys:
                continue
            data["postponed"].append({
                "id": task_id or uuid.uuid4().hex,
                "name": task,
                "date": planned_date,
                "group": group_id,
            })
            existing_keys.add(key)
            changed = True

        if changed:
            self._save(data, undoable=False)
        write_encrypted_text(self.postponed_tasks, "", encoding='utf-8')

    def _migrate_special_tasks_ids(self):
        """Добавляет id старым повторяющимся и отложенным делам, у которых
        его ещё нет (например, после переноса из postponed_tasks.txt)."""
        data = self._load()
        changed = False
        for item in data["repeat_tasks"]:
            if isinstance(item, dict) and not item.get("id"):
                item["id"] = uuid.uuid4().hex
                changed = True
        for item in data["postponed"]:
            if isinstance(item, dict) and not item.get("id"):
                item["id"] = uuid.uuid4().hex
                changed = True
        if changed:
            self._save(data, undoable=False)

    def delete_special_tasks(self, status):
        data = self._load()
        data["tasks"] = [task for task in data["tasks"] if str(task.get("status")) != str(status)]
        self._save(data)
        self.cloud.alg_for_redact()

    def set_default_settings(self):
        default_settings = {
            "password_enabled": "False",
            "password_hash": "",
            "notes_accepted": "False",
            "border": "False",
            "load_screen": "True",
            "special_tasks_separate_dialogs": "False",
            "theme_style": "chatgpt",
            "font_family": "default",
            "font_size": "medium",
            "icon_pack": "minimalistic",
            "button_bg_mode": "default",
            "button_custom_color": "#5659F0",
            "notifications_enabled": "False" if self.web else "True",
            "notification_interval": "15",
            "notification_important_enabled": "False",
            "notification_deadline_enabled": "False",
            "notification_quiet_enabled": "False",
            "notification_quiet_start": "22:00",
            "notification_quiet_end": "08:00",
            "default_task_sort": "disabled",
            "default_task_status_sort": "disabled",
        }
        settings = self._settings_read()
        changed = not settings
        for key, value in default_settings.items():
            if key not in settings:
                settings[key] = value
                changed = True
        if changed:
            self._settings_write(settings)

    def _settings_read(self):
        """Единая точка чтения настроек: на сайте — из браузера посетителя
        (WebSessionStore), на ПК/Android — из settings.txt."""
        if self.web:
            return self.store.read_settings_text()
        return self._read_settings_as_text()

    def _settings_write(self, settings):
        """Единая точка записи настроек: на сайте — в браузер посетителя
        (в фоне), на ПК/Android — в settings.txt."""
        if self.web:
            self.store.write_settings_text(settings)
            return
        write_encrypted_text(self.settings, self._serialize_settings(settings))

    def _serialize_settings(self, settings):
        keys = [
            "notes_accepted",
            "border",
            "load_screen",
            "special_tasks_separate_dialogs",
            "theme_style",
            "font_family",
            "font_size",
            "icon_pack",
            "button_bg_mode",
            "button_custom_color",
            "notifications_enabled",
            "notification_interval",
            "notification_important_enabled",
            "notification_deadline_enabled",
            "notification_quiet_enabled",
            "notification_quiet_start",
            "notification_quiet_end",
            "default_task_sort",
            "default_task_status_sort",
        ]
        # Неизвестные ключи сохраняем: среди них могут быть параметры
        # старого формата, которые следующая миграция ещё должна обработать.
        ordered_keys = [key for key in keys if key in settings]
        ordered_keys.extend(key for key in settings if key not in keys)
        return "\n".join(
            f"{key}: {settings[key]}" for key in ordered_keys
        ) + "\n"

    def _read_settings_as_text(self):
        settings = {}
        if not self.settings.is_file():
            return settings
        for row in read_encrypted_text(self.settings).splitlines():
            if ": " not in row:
                continue
            key, value = row.split(": ", 1)
            settings[key] = value
        return settings

    def _migrate_group_date_settings(self):
        """Однократно переносит старые общие настройки split_by_dates и
        show_created_date (из settings.txt) в характеристики каждой
        группы в itog.json, сохраняя прежнее поведение приложения.
        После переноса ключи удаляются из settings.txt, поэтому повторно
        миграция не выполняется.

        Работает напрямую с сырым itog.json (а не через load_all_sections),
        потому что чтение через общий слой совместимости уже подставляет
        группе «Без группы» значения по умолчанию True/True, если её ещё
        не было явно в файле — из-за этого нельзя было бы отличить
        «поле отсутствует, нужно взять старое глобальное значение» от
        «поле уже сохранено как True»."""
        if not self.settings.is_file():
            return
        raw_settings = self._read_settings_as_text()
        if "split_by_dates" not in raw_settings and "show_created_date" not in raw_settings:
            return

        old_split = self._to_bool(raw_settings.get("split_by_dates", "True"))
        old_show = self._to_bool(raw_settings.get("show_created_date", "True"))

        try:
            raw_data = json.loads(read_encrypted_text(self.Save_in_time, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw_data = {}
        if not isinstance(raw_data, dict):
            raw_data = {}
        groups = raw_data.get("groups")
        if not isinstance(groups, list):
            groups = []

        changed = False
        has_default = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            if group.get("id") == "default":
                has_default = True
            if "split_by_dates" not in group:
                group["split_by_dates"] = old_split
                changed = True
            if "show_created_date" not in group:
                group["show_created_date"] = old_show
                changed = True
        if not has_default:
            groups.insert(0, {
                "id": "default",
                "name": "Без группы",
                "split_by_dates": old_split,
                "show_created_date": old_show,
            })
            changed = True

        if changed:
            raw_data["groups"] = groups
            for key in ("tasks", "postponed", "repeat_tasks"):
                raw_data.setdefault(key, [])
            save_data(self.Save_in_time, raw_data)

        raw_settings.pop("split_by_dates", None)
        raw_settings.pop("show_created_date", None)
        write_encrypted_text(self.settings, "\n".join(f"{key}: {value}" for key, value in raw_settings.items()) + "\n")

    def _to_bool(self, value):
        return value == "True"

    def _normalize_notification_interval(self, value):
        try:
            interval = int(value)
        except (TypeError, ValueError):
            interval = 15
        return max(1, min(60, interval))

    def _normalize_time_value(self, value, default):
        try:
            parsed = datetime.strptime(str(value), "%H:%M")
        except (TypeError, ValueError):
            return default
        return parsed.strftime("%H:%M")

    @staticmethod
    def _normalize_task_sort(value):
        valid_values = {
            "disabled",
            "priority_desc",
            "priority_asc",
            "deadline_desc",
            "deadline_asc",
        }
        return value if value in valid_values else "disabled"

    @staticmethod
    def _normalize_task_status_sort(value):
        valid_values = {"disabled", "incomplete_first", "complete_first"}
        return value if value in valid_values else "disabled"

    def read_settings(self):
        settings = self._settings_read()
        return {
            'password_enabled': self._to_bool(settings.get("password_enabled", "False")),
            'font_family': normalize_font_family(settings.get("font_family")),
            'font_size': normalize_font_size(settings.get("font_size")),
            'border': self._to_bool(settings.get("border", "False")),
            'notes_accepted': self._to_bool(settings.get("notes_accepted", "False")),
            'load_screen': self._to_bool(settings.get("load_screen", "True")),
            'special_tasks_separate_dialogs': self._to_bool(
                settings.get("special_tasks_separate_dialogs", "False")
            ),
            'theme_style': (
                normalize_theme_style(settings.get("theme_style", "chatgpt"))
            ),
            'icon_pack': (
                settings.get("icon_pack", "minimalistic")
                if (
                    settings.get("icon_pack", "minimalistic") in {
                        "flet", "minimalistic", "minimalistic-blue", "old"
                    }
                    or (
                        settings.get("icon_pack") == "custom"
                        and self.has_custom_icon_pack()
                    )
                )
                else "minimalistic"
            ),
            'button_bg_mode': normalize_button_background_mode(
                settings.get("button_bg_mode", "default")
            ),
            'button_custom_color': normalize_custom_color(
                settings.get("button_custom_color", "#5659F0")
            ),
            'notifications_enabled': False if self.web else self._to_bool(
                settings.get("notifications_enabled", "True")
            ),
            'notification_interval': self._normalize_notification_interval(settings.get("notification_interval", "15")),
            'notification_important_enabled': False if self.web else self._to_bool(
                settings.get("notification_important_enabled", "False")
            ),
            'notification_deadline_enabled': False if self.web else self._to_bool(
                settings.get("notification_deadline_enabled", "False")
            ),
            'notification_quiet_enabled': False if self.web else self._to_bool(
                settings.get("notification_quiet_enabled", "False")
            ),
            'notification_quiet_start': self._normalize_time_value(
                settings.get("notification_quiet_start", "22:00"),
                "22:00",
            ),
            'notification_quiet_end': self._normalize_time_value(
                settings.get("notification_quiet_end", "08:00"),
                "08:00",
            ),
            'default_task_sort': self._normalize_task_sort(
                settings.get("default_task_sort", "disabled")
            ),
            'default_task_status_sort': self._normalize_task_status_sort(
                settings.get("default_task_status_sort", "disabled")
            ),
        }

    def verify_app_password(self, password):
        return verify_password(password, self._settings_read().get("password_hash", ""))

    def set_app_password(self, password, current_password=""):
        settings = self._settings_read()
        if self._to_bool(settings.get("password_enabled", "False")):
            if not verify_password(current_password, settings.get("password_hash", "")):
                raise ValueError("Текущий пароль неверный.")
        settings["password_hash"] = hash_password(password)
        settings["password_enabled"] = "True"
        self._settings_write(settings)

    def disable_app_password(self, current_password):
        settings = self._settings_read()
        if self._to_bool(settings.get("password_enabled", "False")):
            if not verify_password(current_password, settings.get("password_hash", "")):
                raise ValueError("Текущий пароль неверный.")
        settings["password_enabled"] = "False"
        settings["password_hash"] = ""
        self._settings_write(settings)

    def redact_setting(self, setting, status):
        settings = self._settings_read()
        if self.web and setting in {
            "notifications_enabled",
            "notification_important_enabled",
            "notification_deadline_enabled",
            "notification_quiet_enabled",
        }:
            status = False
        if setting == "notification_interval":
            status = self._normalize_notification_interval(status)
        elif setting == "theme_style":
            status = normalize_theme_style(status)
        elif setting == "font_family":
            status = normalize_font_family(status)
        elif setting == "font_size":
            status = normalize_font_size(status)
        elif setting == "icon_pack":
            status = (
                status
                if status in {
                    "flet", "minimalistic", "minimalistic-blue", "old", "custom"
                }
                else "minimalistic"
            )
        elif setting == "button_bg_mode":
            status = normalize_button_background_mode(status)
        elif setting == "button_custom_color":
            status = normalize_custom_color(status)
        elif setting in {
            "notification_quiet_enabled",
            "notification_important_enabled",
            "notification_deadline_enabled",
        }:
            status = self._to_bool(str(status)) if isinstance(status, str) else bool(status)
        elif setting == "notification_quiet_start":
            status = self._normalize_time_value(status, "22:00")
        elif setting == "notification_quiet_end":
            status = self._normalize_time_value(status, "08:00")
        elif setting == "default_task_sort":
            status = self._normalize_task_sort(status)
        elif setting == "default_task_status_sort":
            status = self._normalize_task_status_sort(status)
        settings[setting] = str(status)
        self._settings_write(settings)

    def _normalize_repeat_interval(self, value):
        """Приводит интервал повторения к целому числу от 1 до 367 дней"""
        try:
            interval = int(value)
        except (TypeError, ValueError):
            interval = 1
        return max(1, min(367, interval))

    def _normalize_weekday(self, value):
        """Приводит день недели к числу от 1 (понедельник) до 7 (воскресенье)"""
        try:
            weekday = int(value)
        except (TypeError, ValueError):
            weekday = 1
        return max(1, min(7, weekday))

    def _normalize_month_day(self, value):
        """Приводит число месяца к целому числу от 1 до 31"""
        try:
            day = int(value)
        except (TypeError, ValueError):
            day = 1
        return max(1, min(31, day))

    def _normalize_year_value(self, value):
        """Приводит значение дня/месяца для ежегодного повторения к строке 'ДД-ММ'"""
        try:
            day_str, month_str = str(value).split("-")
            day = max(1, min(31, int(day_str)))
            month = max(1, min(12, int(month_str)))
        except (TypeError, ValueError, AttributeError):
            day, month = 1, 1
        return f"{day:02d}-{month:02d}"

    def _normalize_repeat_rule(self, repeat_type, repeat_value):
        """Приводит тип и значение повторения к нормальному виду.
        Поддерживаемые типы: 'day' (интервал в днях, в т.ч. ежедневно=1),
        'week' (день недели 1-7), 'month' (число месяца 1-31),
        'year' (день и месяц в формате 'ДД-ММ')"""
        if repeat_type == "week":
            return "week", self._normalize_weekday(repeat_value)
        elif repeat_type == "month":
            return "month", self._normalize_month_day(repeat_value)
        elif repeat_type == "year":
            return "year", self._normalize_year_value(repeat_value)
        else:
            return "day", self._normalize_repeat_interval(repeat_value)

    def create_repeat_task(self, task, repeat_type="day", repeat_value=1, group_id='default', metadata=None):
        if text_length_error(task):
            return None
        task = task.replace('\n', '{N}')
        repeat_type, repeat_value = self._normalize_repeat_rule(repeat_type, repeat_value)
        today_str = local_today(self.web, self.page).strftime('%d-%m-%Y')
        data = self._load()
        task_id = uuid.uuid4().hex
        metadata = metadata or {}
        data["repeat_tasks"].append({
            "id": task_id,
            "name": task,
            "last_date": today_str,
            "repeat_type": repeat_type,
            "repeat_value": repeat_value,
            "disabled": False,
            "group": group_id,
            "created_date": metadata.get("created_date") or today_str,
            "deadline": metadata.get("deadline") or "",
            "deadline_days": metadata.get("deadline_days") or "",
            "priority": metadata.get("priority") or "Неважно",
            "info_type": metadata.get("info_type") or "created_date",
            "attachments": deepcopy(metadata.get("attachments") or []),
        })
        self._save(data)
        self.cloud.alg_for_redact()
        return task_id

    def _parse_postponed_row(self, row):
        """Разбирает строку старого файла postponed_tasks.txt
        ('дело|дата|группа|id') — нужно только для одноразового переноса
        в основное хранилище, см. _migrate_postponed_tasks_to_itog."""
        parts = row.split("|")
        if len(parts) < 2:
            raise ValueError
        group_id = parts[2] if len(parts) >= 3 and parts[2] else 'default'
        task_id = parts[3] if len(parts) >= 4 and parts[3] else None
        return parts[0], parts[1], group_id, task_id

    def _days_since(self, last_date_str):
        try:
            last = datetime.strptime(last_date_str, '%d-%m-%Y').date()
        except (ValueError, TypeError):
            return None
        return (local_today(self.web, self.page) - last).days

    def _generated_deadline(self, item, generated_date):
        """Возвращает дату дедлайна для создаваемого из шаблона дела."""
        try:
            days = int(item.get("deadline_days"))
            if not 1 <= days <= 3650:
                raise ValueError
        except (TypeError, ValueError):
            # Совместимость со старыми шаблонами, где хранилась готовая дата.
            return item.get("deadline") or ""
        return (generated_date + timedelta(days=days)).strftime("%d-%m-%Y")

    def _is_repeat_due(self, repeat_type, repeat_value, last_date_str):
        """Определяет, нужно ли сегодня добавить повторяющееся дело"""
        today = local_today(self.web, self.page)
        today_str = today.strftime('%d-%m-%Y')
        if last_date_str == today_str:
            return False  # уже добавляли сегодня

        if repeat_type == "week":
            return today.isoweekday() == repeat_value
        elif repeat_type == "month":
            return today.day == repeat_value
        elif repeat_type == "year":
            try:
                day_str, month_str = str(repeat_value).split("-")
                return today.day == int(day_str) and today.month == int(month_str)
            except (ValueError, AttributeError):
                return False
        else:
            days_passed = self._days_since(last_date_str)
            return days_passed is None or days_passed >= repeat_value

    def check_repeat_tasks(self):
        itog = []
        today = local_today(self.web, self.page)
        today_str = today.strftime('%d-%m-%Y')
        data = self._load()
        for item in data["repeat_tasks"]:
            if not isinstance(item, dict):
                continue
            if item.get("disabled", False):
                continue
            repeat_type, repeat_value = self._normalize_repeat_rule(item.get("repeat_type", "day"), item.get("repeat_value", 1))
            last_date = item.get("last_date", "")
            group_id = item.get("group", "default") or "default"
            item["repeat_type"] = repeat_type
            item["repeat_value"] = repeat_value
            item["group"] = group_id
            if not item.get("id"):
                item["id"] = uuid.uuid4().hex
            if self._is_repeat_due(repeat_type, repeat_value, last_date):
                metadata = {
                    "created_date": item.get("created_date") or today_str,
                    "deadline": self._generated_deadline(item, today),
                    "deadline_days": item.get("deadline_days") or "",
                    "priority": item.get("priority") or "Неважно",
                    "info_type": item.get("info_type") or "created_date",
                    "attachments": deepcopy(item.get("attachments") or []),
                }
                itog.append((str(item.get("name", "")).replace('{N}', '\n'), group_id, metadata))
                item["last_date"] = today_str

        self._save(data, undoable=False)
        self.cloud.alg_for_redact()
        return itog, today_str

    def read_repeat_tasks(self):
        """Возвращает список (текст_дела, тип_повторения, значение_повторения, группа, id)
        для повторяющихся дел"""
        itog = []
        today_str = local_today(self.web, self.page).strftime('%d-%m-%Y')
        for item in self._load()["repeat_tasks"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if not name.strip():
                continue
            repeat_type, repeat_value = self._normalize_repeat_rule(item.get("repeat_type", "day"), item.get("repeat_value", 1))
            group_id = item.get("group", "default") or "default"
            task_id = item.get("id")
            # Имя остаётся исходным: auto_add_new_string применяется только
            # при построении строки интерфейса.
            task_text = name.replace('{N}', '\n')
            metadata = {
                "created_date": item.get("created_date") or item.get("last_date") or today_str,
                "deadline": item.get("deadline") or "",
                "deadline_days": item.get("deadline_days") or "",
                "priority": item.get("priority") or "Неважно",
                "info_type": item.get("info_type") or "created_date",
                "attachments": deepcopy(item.get("attachments") or []),
                "disabled": bool(item.get("disabled", False)),
            }
            itog.append((task_text, repeat_type, repeat_value, group_id, task_id, metadata))
        return itog

    def set_repeat_task_disabled(self, task_id, disabled=True):
        """Отключает или включает создание повторяющегося дела по его ID."""
        data = self._load()
        for item in data["repeat_tasks"]:
            if item.get("id") == task_id:
                item["disabled"] = bool(disabled)
                self._save(data)
                self.cloud.alg_for_redact()
                return True
        return False

    def delete_repeat_task(self, name_task, group_id=None):
        data = self._load()
        task_for_delete = name_task.replace('\n', '{N}')
        data["repeat_tasks"] = [
            item for item in data["repeat_tasks"]
            if not (item.get("name") == task_for_delete and (group_id is None or item.get("group") == group_id))
        ]
        self._save(data)
        self.cloud.alg_for_redact()

    def update_repeat_task(self, task_id, task, repeat_type, repeat_value, group_id, metadata=None):
        """Изменяет повторяющееся дело по его ID."""
        if text_length_error(task):
            return False
        task = task.replace('\n', '{N}')
        repeat_type, repeat_value = self._normalize_repeat_rule(repeat_type, repeat_value)
        data = self._load()
        found = False
        for item in data["repeat_tasks"]:
            if item.get("id") == task_id:
                item["name"] = task
                item["repeat_type"] = repeat_type
                item["repeat_value"] = repeat_value
                item["group"] = group_id
                if metadata is not None:
                    item.update(metadata)
                found = True
        if found:
            self._save(data)
            self.cloud.alg_for_redact()
        return found

    def _normalize_postponed_date(self, value):
        try:
            return datetime.strptime(value, '%d-%m-%Y').date()
        except (TypeError, ValueError):
            return None

    def create_postponed_task(self, task, planned_date, group_id='default', metadata=None):
        if text_length_error(task):
            return False
        task = task.replace('\n', '{N}')
        normal_date = self._normalize_postponed_date(planned_date)
        if normal_date is None:
            return False

        today_str = local_today(self.web, self.page).strftime('%d-%m-%Y')
        data = self._load()
        task_id = uuid.uuid4().hex
        metadata = metadata or {}
        data["postponed"].append({
            "id": task_id,
            "name": task,
            "date": normal_date.strftime("%d-%m-%Y"),
            "group": group_id,
            "created_date": metadata.get("created_date") or today_str,
            "deadline": metadata.get("deadline") or "",
            "deadline_days": metadata.get("deadline_days") or "",
            "priority": metadata.get("priority") or "Неважно",
            "info_type": metadata.get("info_type") or "created_date",
            "attachments": deepcopy(metadata.get("attachments") or []),
        })
        self._save(data)
        self.cloud.alg_for_redact()
        return task_id

    def read_postponed_tasks(self):
        itog = []
        today_str = local_today(self.web, self.page).strftime('%d-%m-%Y')
        for item in self._load()["postponed"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if not name.strip():
                continue
            # Имя остаётся исходным: auto_add_new_string применяется только
            # при построении строки интерфейса.
            task_text = name.replace('{N}', '\n')
            metadata = {
                "created_date": item.get("created_date") or today_str,
                "deadline": item.get("deadline") or "",
                "deadline_days": item.get("deadline_days") or "",
                "priority": item.get("priority") or "Неважно",
                "info_type": item.get("info_type") or "created_date",
                "attachments": deepcopy(item.get("attachments") or []),
            }
            itog.append((task_text, item.get("date", ""), item.get("group", "default") or "default", item.get("id"), metadata))
        return itog

    def delete_postponed_task(self, name_task, planned_date, group_id=None):
        task_for_delete = name_task.replace('\n', '{N}')
        data = self._load()
        data["postponed"] = [
            item for item in data["postponed"]
            if not (
                item.get("name") == task_for_delete
                and item.get("date") == planned_date
                and (group_id is None or item.get("group") == group_id)
            )
        ]
        self._save(data)
        self.cloud.alg_for_redact()

    def update_postponed_task(self, task_id, task, planned_date, group_id, metadata=None):
        """Изменяет отложенное дело по его ID."""
        if text_length_error(task):
            return False
        normalized_date = self._normalize_postponed_date(planned_date)
        if normalized_date is None:
            return False
        task = task.replace('\n', '{N}')
        data = self._load()
        found = False
        for item in data["postponed"]:
            if item.get("id") == task_id:
                item["name"] = task
                item["date"] = normalized_date.strftime("%d-%m-%Y")
                item["group"] = group_id
                if metadata is not None:
                    item.update(metadata)
                found = True
        if found:
            self._save(data)
            self.cloud.alg_for_redact()
        return found

    def check_postponed_tasks(self):
        ready_tasks = []
        today = local_today(self.web, self.page)
        data = self._load()
        remaining = []
        for item in data["postponed"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if not name.strip():
                continue
            planned_date = item.get("date", "")
            parsed_date = self._normalize_postponed_date(planned_date)
            if parsed_date is None:
                remaining.append(item)
                continue
            if parsed_date <= today:
                metadata = {
                    "created_date": item.get("created_date") or today.strftime('%d-%m-%Y'),
                    "deadline": self._generated_deadline(item, today),
                    "deadline_days": item.get("deadline_days") or "",
                    "priority": item.get("priority") or "Неважно",
                    "info_type": item.get("info_type") or "created_date",
                    "attachments": deepcopy(item.get("attachments") or []),
                }
                ready_tasks.append((name.replace('{N}', '\n'), planned_date, item.get("group", "default") or "default", metadata))
            else:
                remaining.append(item)
        data["postponed"] = remaining
        self._save(data, undoable=False)
        self.cloud.alg_for_redact()
        return ready_tasks

    def _accounts_read(self):
        if self.web:
            return self.store.read_meta_text("accounts")
        return read_encrypted_text(self.accounts)

    def _accounts_write(self, text):
        if self.web:
            self.store.write_meta_text("accounts", text)
            return
        write_encrypted_text(self.accounts, text)

    def read_accounts(self):
        self.delete_repeat_accounts()
        a = self._accounts_read()
        itog = []
        for row in a.splitlines():
            try:
                rowSP = row.split("~~")
                itog.append([rowSP[0], rowSP[1]])
            except IndexError:
                pass
        return itog

    def check_accounts(self, login, password):
        self.delete_repeat_accounts()
        a = self.cloud.read_user_data_text()
        if a != '':
            b = a.split("~~")
            return b[1] == login and b[2] == password
        else:
            return False

    def delete_repeat_accounts(self):
        a = self._accounts_read()
        itog = []
        for item in a.split("\n"):
            if item not in itog:
                itog.append(item)
        self._accounts_write('\n'.join(itog) + '\n')

    def exit_from_auth_accounts(self, login, password):
        a = self._accounts_read()
        itog = []
        for row in a.split("\n"):
            try:
                rowSP = row.split("~~")
                if not (rowSP[0] == login and rowSP[1] == password):
                    itog.append(row)
            except IndexError:
                pass
        self._accounts_write('\n'.join(itog) + '\n')

    def check_lasts(self):
        pass

    def write_last_update_tasks(self):
        """Записывает текущие дату и время последнего автообновления дел —
        на ПК/Android в файл, на сайте — в памяти сессии."""
        now_str = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        if self.web:
            self.store.write_meta_text("last_update_tasks", now_str)
            return now_str
        self.last_update_tasks.touch(exist_ok=True)
        write_encrypted_text(self.last_update_tasks, now_str, encoding='utf-8')
        return now_str

    def read_last_update_tasks(self):
        """Возвращает дату и время последнего автообновления дел, либо None."""
        if self.web:
            return self.store.read_meta_text("last_update_tasks") or None
        if not self.last_update_tasks.exists():
            return None
        text = read_encrypted_text(self.last_update_tasks, encoding='utf-8').strip()
        return text or None
