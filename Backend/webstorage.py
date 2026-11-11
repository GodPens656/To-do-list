"""Персональное хранилище данных веб-версии в браузере пользователя."""

import asyncio
import inspect
import json
import logging
import threading

from flet.controls.exceptions import FletException

from .storage import empty_data


logger = logging.getLogger(__name__)
STORAGE_ERRORS = (AttributeError, TypeError, ValueError, RuntimeError, OSError,
                  TimeoutError, FletException)


class WebSessionStore:
    """Синхронный фасад над async SharedPreferences Flet.

    Backend вызывает методы хранилища синхронно, поэтому данные держатся в
    памяти, а запись в SharedPreferences запускается в фоне. Так сервер не
    создаёт общие для всех посетителей файлы с делами или настройками.
    """

    DATA_KEY = "nd.todo.data.v1"
    SETTINGS_KEY = "nd.todo.settings.v1"
    META_KEY = "nd.todo.meta.v1"

    def __init__(self, page):
        self.page = page
        self._data = empty_data()
        self._settings = {}
        # Данные, которые не относятся к спискам дел: текущий аккаунт,
        # запомненные аккаунты и служебные отметки. Они должны оставаться
        # у конкретного пользователя браузера, а не в файлах веб-сервера.
        self._meta = {}
        self._lock = threading.RLock()
        self._persist_locks = {
            key: asyncio.Lock()
            for key in (self.SETTINGS_KEY, self.META_KEY, self.DATA_KEY)
        }
        self._preferences = None
        self._section_revisions = {key: 0 for key in self._data}

    def _get_preferences(self):
        # В Flet 0.82 page.shared_preferences создаёт новый Service при каждом
        # обращении. Держим одну ссылку на всё время жизни веб-сессии, чтобы
        # Flet не удалял сервис между чтением и фоновыми записями.
        if self._preferences is None:
            self._preferences = getattr(self.page, "shared_preferences", None)
        return self._preferences

    async def _call(self, method, *args):
        result = method(*args)
        return await result if inspect.isawaitable(result) else result

    async def load(self):
        preferences = self._get_preferences()
        if preferences is None:
            return
        # Ошибка одного ключа не должна сбрасывать остальные настройки
        # браузера, включая сохранённую авторизацию.
        for key in (self.SETTINGS_KEY, self.META_KEY, self.DATA_KEY):
            try:
                raw = await self._call(preferences.get, key)
                if not raw:
                    continue
                candidate = json.loads(raw)
                if not isinstance(candidate, dict):
                    continue
                if key == self.DATA_KEY:
                    data = empty_data()
                    for section in data:
                        if isinstance(candidate.get(section), list):
                            data[section] = candidate[section]
                    self._data = data
                else:
                    values = {str(k): str(v) for k, v in candidate.items()}
                    if key == self.SETTINGS_KEY:
                        self._settings = values
                    else:
                        self._meta = values
            except STORAGE_ERRORS as error:
                logger.warning("Cannot load browser storage key %s (%s)",
                               key, type(error).__name__)

    def _persist(self, *keys):
        try:
            self.page.run_task(self._persist_async, keys or None)
        except (AttributeError, RuntimeError):
            pass

    async def _persist_async(self, keys=None):
        preferences = self._get_preferences()
        if preferences is None:
            return
        # Для каждого ключа своя очередь: старое значение не может затереть
        # новое, а медленная запись дел не задерживает сохранение настроек.
        for key in (keys if keys is not None else (
                self.SETTINGS_KEY, self.META_KEY, self.DATA_KEY)):
            async with self._persist_locks[key]:
                with self._lock:
                    values = {
                        self.SETTINGS_KEY: self._settings,
                        self.META_KEY: self._meta,
                        self.DATA_KEY: self._data,
                    }
                    value = json.dumps(values[key], ensure_ascii=False)
                try:
                    result = await self._call(preferences.set, key, value)
                    if result is False:
                        logger.warning("Cannot save browser storage key %s", key)
                except STORAGE_ERRORS as error:
                    logger.warning("Cannot save browser storage key %s (%s)",
                                   key, type(error).__name__)

    def data_lock(self):
        """Защищает проверку и замену данных при синхронизации."""
        return self._lock

    def load_all_sections(self):
        # Защищаем внутреннее состояние от изменений вызывающим кодом.
        with self._lock:
            return json.loads(json.dumps(self._data, ensure_ascii=False))

    def save_all_sections(self, data):
        clean = empty_data()
        if isinstance(data, dict):
            for key in clean:
                if isinstance(data.get(key), list):
                    clean[key] = data[key]
        changed = False
        with self._lock:
            for key, value in clean.items():
                if self._data.get(key) != value:
                    self._section_revisions[key] += 1
                    changed = True
            self._data = clean
        if changed:
            self._persist(self.DATA_KEY)

    def replace_from_cloud(self, data):
        """Атомарно заменяет активные дела скачанными из аккаунта.

        Ревизии увеличиваются до записи, а Cloud после успешной загрузки
        отмечает их синхронизированными. Это не позволяет фоновому потоку
        принять данные другого аккаунта за локальные изменения.
        """
        clean = empty_data()
        if isinstance(data, dict):
            for key in clean:
                if isinstance(data.get(key), list):
                    clean[key] = data[key]
        with self._lock:
            self._data = clean
            for key in self._section_revisions:
                self._section_revisions[key] += 1
        self._persist(self.DATA_KEY)

    def section_snapshot(self, key):
        with self._lock:
            value = json.loads(json.dumps(self._data.get(key, []), ensure_ascii=False))
            return value, self._section_revisions.get(key, 0)

    def section_revision(self, key):
        with self._lock:
            return self._section_revisions.get(key, 0)

    def backup_guest_data(self):
        with self._lock:
            self._meta["guest_data"] = json.dumps(self._data, ensure_ascii=False)
        self._persist(self.META_KEY)

    def restore_guest_data(self):
        raw = self.read_meta_text("guest_data")
        try:
            data = json.loads(raw) if raw else empty_data()
        except (TypeError, json.JSONDecodeError):
            data = empty_data()
        self.replace_from_cloud(data)

    def read_settings_text(self):
        with self._lock:
            return dict(self._settings)

    def write_settings_text(self, settings):
        with self._lock:
            self._settings = dict(settings) if isinstance(settings, dict) else {}
        self._persist(self.SETTINGS_KEY)

    def read_meta_text(self, key):
        with self._lock:
            return self._meta.get(str(key), "")

    def write_meta_text(self, key, value):
        with self._lock:
            self._meta[str(key)] = str(value)
        self._persist(self.META_KEY)
