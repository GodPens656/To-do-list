"""Персональное хранилище данных веб-версии в браузере пользователя."""

import inspect
import json
import threading

from .storage import empty_data


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
        self._section_revisions = {key: 0 for key in self._data}

    async def _call(self, method, *args):
        result = method(*args)
        return await result if inspect.isawaitable(result) else result

    async def load(self):
        preferences = getattr(self.page, "shared_preferences", None)
        if preferences is None:
            return
        try:
            raw_data = await self._call(preferences.get, self.DATA_KEY)
            raw_settings = await self._call(preferences.get, self.SETTINGS_KEY)
            raw_meta = await self._call(preferences.get, self.META_KEY)
            if raw_data:
                candidate = json.loads(raw_data)
                if isinstance(candidate, dict):
                    data = empty_data()
                    for key in data:
                        if isinstance(candidate.get(key), list):
                            data[key] = candidate[key]
                    self._data = data
            if raw_settings:
                candidate = json.loads(raw_settings)
                if isinstance(candidate, dict):
                    self._settings = {str(key): str(value) for key, value in candidate.items()}
            if raw_meta:
                candidate = json.loads(raw_meta)
                if isinstance(candidate, dict):
                    self._meta = {str(key): str(value) for key, value in candidate.items()}
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            # В старых версиях Flet SharedPreferences может отсутствовать.
            # В этом случае приложение остаётся рабочим в пределах вкладки.
            pass

    def _persist(self):
        try:
            self.page.run_task(self._persist_async)
        except (AttributeError, RuntimeError):
            pass

    async def _persist_async(self):
        preferences = getattr(self.page, "shared_preferences", None)
        if preferences is None:
            return
        try:
            await self._call(preferences.set, self.DATA_KEY, json.dumps(self._data, ensure_ascii=False))
            await self._call(preferences.set, self.SETTINGS_KEY, json.dumps(self._settings, ensure_ascii=False))
            await self._call(preferences.set, self.META_KEY, json.dumps(self._meta, ensure_ascii=False))
        except (AttributeError, TypeError, RuntimeError):
            pass

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
            self._persist()

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
        self._persist()

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
        self._persist()

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
        self._persist()

    def read_meta_text(self, key):
        with self._lock:
            return self._meta.get(str(key), "")

    def write_meta_text(self, key, value):
        with self._lock:
            self._meta[str(key)] = str(value)
        self._persist()
