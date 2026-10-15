import os
import io
import json
import hashlib
from pathlib import Path
import requests
from .dropbox_disk import DropboxDisk, is_retryable_error, DropboxDiskError
import time
import threading
from datetime import date, datetime, timedelta
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import shutil
from .storage import (
    ensure_split_storage,
    save_all_sections,
    empty_data,
    SECTION_FILENAMES,
    STORAGE_LOCK,
    set_data_encryption,
)
from .json_migration import (
    lines_to_data,
    load_data_from_dict,
    migrate_legacy_storage,
)
from .crypto import (
    data_encryption_enabled,
    decrypt_bytes,
    encrypt_bytes,
    encrypt_file_if_plaintext,
    read_text as read_encrypted_text,
    write_text as write_encrypted_text,
)
CLOUD_ROOT = "/For_to-do"
BACKUP_INTERVAL = timedelta(days=7)
BACKUP_CHECK_SECONDS = 60 * 60
BACKUP_RETRY_SECONDS = 5 * 60


def _is_content_length_error(exc):
    """Определяет ошибку рассинхронизации размера файла во время передачи.

    Возникает, когда файл на диске меняется (кто-то дописал в него данные)
    прямо в момент, когда мы его читаем/отправляем по сети — сервер уже
    получил Content-Length, а тело запроса оказалось больше/меньше.
    """
    text = str(exc)
    return "Content-Length" in text or "too much data" in text.lower()


def _is_locked_error(exc):
    """Определяет, что ошибка — это именно 423 Locked (ресурс занят другой операцией)."""
    text = str(exc)
    return (
        "423" in text
        or "Locked" in text
        or getattr(exc, "status_code", None) == 423
    )


def _is_retryable_error(exc):
    """Ошибки, при которых имеет смысл повторить попытку: временная
    блокировка ресурса (423) или гонка при передаче файла по сети."""
    return is_retryable_error(exc) or _is_locked_error(exc) or _is_content_length_error(exc)


class Cloud:

    _connect = None
    _disk = None

    # Файловые локи общие только для desktop/Android, где экземпляры Cloud
    # действительно работают с одними и теми же локальными файлами.
    _file_lock = STORAGE_LOCK

    # Раздельное хранение (tasks.json/postponed.json/groups.json/repeat_tasks.json):
    # На каждую секцию — свой лок для временного файла выгрузки.
    _section_locks = {key: threading.Lock() for key in SECTION_FILENAMES}

    # Храним отпечатки успешно синхронизированных секций между запусками.
    def __init__(self, web_store=None):
        """Задаем основные пути и переменные для работы с диском"""
        self.web_store = web_store
        self.web = web_store is not None
        # Очередь и индикатор принадлежат конкретной Flet-сессии. Глобальные
        # поля смешивали запросы разных посетителей сайта.
        self._pending_login_password = None
        self._upload_cv = threading.Condition()
        self._upload_state_callback = None
        self._last_synced_versions = {}
        self._last_synced_versions_lock = threading.Lock()
        self._sync_lock = threading.RLock()
        self._account_encryption = {}
        self._backup_checks = {}
        if self.web:
            # Веб-ветка работает с WebSessionStore и BytesIO. Никакие
            # пользовательские файлы в рабочей папке процесса на VPS ей
            # не нужны.
            self.Save_in_time1 = None
            self.Save_in_time = None
            self.data_dir = None
            self.local_save_dir = None
            self.local_data_dir = None
        else:
            """Определение папки с сохранениями"""
            if os.getenv("FLET_APP_STORAGE_DATA"):  # Запуск на Android
                self.Save_in_time1 = Path(os.getenv("FLET_APP_STORAGE_DATA"))
            else:
                self.Save_in_time1 = Path("saves")

            # self.Save_in_time (единый itog.json) больше не является основным
            # хранилищем — он используется только как временный формат при
            # переносе очень старых сохранений (txt / единый json).
            self.Save_in_time = self.Save_in_time1 / "itog.json"
            migrate_legacy_storage(self.Save_in_time1, self.Save_in_time)
            self.data_dir = self.Save_in_time1
            ensure_split_storage(self.data_dir, self.Save_in_time)

            self.local_save_dir = self.Save_in_time1 / "local"
            self.local_save_dir.mkdir(parents=True, exist_ok=True)
            self.local_data_dir = self.local_save_dir
            ensure_split_storage(
                self.local_data_dir, self.local_save_dir / "itog.json"
            )

            self.user_data = self.Save_in_time1 / "user_data" / "user_data.txt"
            self.user_data_dir = self.Save_in_time1 / "user_data"
            self.user_data_dir.mkdir(parents=True, exist_ok=True)
            self.user_data.touch(exist_ok=True)
            self.accounts = self.Save_in_time1 / "user_data" / "accounts.txt"
            self.accounts.touch(exist_ok=True)
            encrypt_file_if_plaintext(self.user_data)
            encrypt_file_if_plaintext(self.accounts)

        self._load_sync_state()

        if Cloud._connect is None:
            Cloud._connect = self.check_connect()

        self.connect = Cloud._connect

        if Cloud._disk is None:
            Cloud._disk = self.initizialise_disk()

        self.disk = Cloud._disk

        threading.Thread(target=self._upload_worker, daemon=True).start()



    def initizialise_disk(self):
        """Dropbox авторизуется при первом облачном запросе."""
        return DropboxDisk()

    def check_connect(self):
        """Проверяет доступ к dropbox.com без авторизации в Dropbox API."""
        try:
            with requests.get("https://dropbox.com", timeout=5, stream=True) as response:
                response.raise_for_status()
            return True
        except requests.RequestException:
            return False


    def file_lock(self):
        """Общий лок для синхронизации локального чтения/записи файлов
        раздельного хранилища между потоками (используется при снятии
        снимка перед выгрузкой и при скачивании из облака)."""
        return self.web_store.data_lock() if self.web else Cloud._file_lock

    def set_upload_state_callback(self, callback):
        """Регистрирует callback для показа/скрытия индикатора выгрузки."""
        self._upload_state_callback = callback

    def _notify_upload_state(self, is_uploading):
        callback = self._upload_state_callback
        if callback is None:
            return
        try:
            callback(bool(is_uploading))
        except Exception:
            pass

    def cloud_path(self, *parts):
        """Собирает путь в Dropbox с ведущим слешем."""
        cleaned = [str(part).strip("/") for part in parts if str(part).strip("/")]
        return "/" + "/".join(cleaned)

    def _copy_data_dir(self, src_dir, dst_dir):
        """Копирует все файлы секций (tasks.json/postponed.json/...) из одной
        папки раздельного хранилища в другую."""
        src_dir, dst_dir = Path(src_dir), Path(dst_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)
        for filename in SECTION_FILENAMES.values():
            src = src_dir / filename
            if src.exists():
                shutil.copyfile(src, dst_dir / filename)
        set_data_encryption(dst_dir, data_encryption_enabled(src_dir))

    def _move_active_saves_to_local_backup(self):
        """Переносит текущие локальные данные в резервную копию перед входом в аккаунт."""
        if self.web:
            self.web_store.backup_guest_data()
            return
        with Cloud._file_lock:
            self._copy_data_dir(self.data_dir, self.local_data_dir)

    def _restore_local_backup_to_active(self):
        """Возвращает локальные данные из резервной копии после выхода из аккаунта."""
        if self.web:
            self.web_store.restore_guest_data()
            return
        with Cloud._file_lock:
            self._copy_data_dir(self.local_data_dir, self.data_dir)

    def exists_on_cloud(self, path):
        """Сетевые ошибки не считаются отсутствием файла или аккаунта."""
        return self.disk.exists(path)

    def create_folder_on_cloud(self, path):
        """Создает папку в Dropbox, если ее еще нет."""
        try:
            self.disk.mkdir(path)
        except FileExistsError:
            pass

    # ------------------------------------------------------------------
    # Скачивание
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(payload):
        return hashlib.sha256(payload).hexdigest()

    def _account_key(self, login_password):
        # Отметки старого провайдера не подтверждают загрузку в Dropbox.
        return self._fingerprint(("dropbox:" + login_password).encode("utf-8"))

    def _load_sync_state(self):
        try:
            raw = (self.web_store.read_meta_text("cloud_sync") if self.web else
                   read_encrypted_text(self.user_data_dir / "cloud_sync.json", encoding="utf-8"))
            state = json.loads(raw) if raw else {}
            if isinstance(state, dict):
                self._last_synced_versions = {
                    account: {key: value for key, value in sections.items()
                              if key in SECTION_FILENAMES and (value is None or isinstance(value, str))}
                    for account, sections in state.items() if isinstance(sections, dict)
                }
        except (OSError, ValueError):
            # При первом запуске новой версии ещё нет отметок синхронизации.
            pass

    def _mark_synced(self, login_password, key, version):
        with self._last_synced_versions_lock:
            account = self._account_key(login_password)
            self._last_synced_versions.setdefault(account, {})[key] = version
            raw = json.dumps(self._last_synced_versions)
            try:
                if self.web:
                    self.web_store.write_meta_text("cloud_sync", raw)
                else:
                    write_encrypted_text(self.user_data_dir / "cloud_sync.json", raw, encoding="utf-8")
            except (OSError, ValueError) as exc:
                print(f"Не удалось сохранить отметку синхронизации: {exc}")

    def _section_version(self, key):
        if self.web:
            value, _ = self.web_store.section_snapshot(key)
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        else:
            path = self.data_dir / SECTION_FILENAMES[key]
            if not path.exists():
                return None
            payload = path.read_bytes()
        return self._fingerprint(payload)

    def _local_versions(self):
        return {key: self._section_version(key) for key in SECTION_FILENAMES}

    def _has_unsent_changes(self, login_password, versions):
        with self._last_synced_versions_lock:
            baseline = self._last_synced_versions.get(self._account_key(login_password), {})
            # Неизвестная секция при первом входе ещё не является локальной
            # правкой: иначе гостевые дела заблокировали бы загрузку аккаунта.
            return any(key in baseline and version != baseline[key]
                       for key, version in versions.items())

    def _download_payload(self, cloud_file, max_retries):
        delay = 0.5
        for attempt in range(max_retries):
            try:
                target = io.BytesIO()
                self.disk.download(cloud_file, target)
                return target.getvalue()
            except Exception as exc:
                if _is_retryable_error(exc) and attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

    def account_encryption_enabled(self, account, refresh=False):
        """Настройка облачного аккаунта общая для всех его устройств."""
        if not refresh:
            return getattr(self, "_account_encryption", {}).get(account, True)
        with self._sync_lock:
            if not hasattr(self, "_account_encryption"):
                self._account_encryption = {}
            path = self.cloud_path(CLOUD_ROOT, account, "security.json")
            enabled = True  # старые аккаунты всегда шифровались
            if self.disk.exists(path):
                settings = json.loads(self._download_payload(path, 5))
                if not isinstance(settings, dict) or type(settings.get("encryption_enabled")) is not bool:
                    raise ValueError("Некорректная настройка шифрования аккаунта.")
                enabled = settings["encryption_enabled"]
            self._account_encryption[account] = enabled
            return enabled

    def set_account_encryption(self, account, enabled):
        """Меняет формат облачных и локальных файлов, сохраняя локальные правки."""
        if type(enabled) is not bool:
            raise ValueError("Некорректная настройка шифрования.")
        with self._sync_lock:
            if not account or self.read_user_data_text().split("~~")[0].strip() != account:
                raise ValueError("Войдите в аккаунт, чтобы изменить шифрование.")
            if not self.connect:
                raise ValueError("Для изменения шифрования нужен интернет.")
            previous = self.account_encryption_enabled(account, refresh=True)
            originals = {}
            # Сначала читаем и проверяем все файлы. Локальный снимок может
            # быть устаревшим: при смене формата используем данные облака.
            for filename in (*SECTION_FILENAMES.values(), "itog.json", "itog.txt"):
                path = self.cloud_path(CLOUD_ROOT, account, filename)
                if self.disk.exists(path):
                    raw = self._download_payload(path, 5)
                    originals[path] = (raw, decrypt_bytes(raw))
            changed = []
            settings_attempted = False
            settings_path = self.cloud_path(CLOUD_ROOT, account, "security.json")
            try:
                for path, (raw, plain) in originals.items():
                    changed.append(path)
                    payload = encrypt_bytes(plain) if enabled else plain
                    self.disk.upload(io.BytesIO(payload), path, overwrite=True)
                settings_attempted = True
                self.disk.upload(io.BytesIO(json.dumps({"encryption_enabled": enabled}).encode("utf-8")),
                                 settings_path, overwrite=True)
                self._set_local_account_encryption(account, enabled)
            except Exception:
                # При сбое оставляем прежнюю настройку и пытаемся вернуть
                # уже переписанные секции; чтение поддерживает оба формата.
                if settings_attempted:
                    try:
                        self.disk.upload(io.BytesIO(json.dumps({"encryption_enabled": previous}).encode("utf-8")),
                                         settings_path, overwrite=True)
                    except Exception:
                        pass
                for path in reversed(changed):
                    try:
                        self.disk.upload(io.BytesIO(originals[path][0]), path, overwrite=True)
                    except Exception:
                        pass
                self._account_encryption[account] = previous
                raise
            self._account_encryption[account] = enabled

    def load_account_encryption(self, account):
        with self._sync_lock:
            enabled = self.account_encryption_enabled(account, refresh=True)
            self._set_local_account_encryption(account, enabled)
            return enabled

    def _set_local_account_encryption(self, account, enabled):
        if self.web:
            return
        with self.file_lock():
            before = self._local_versions()
            set_data_encryption(self.data_dir, enabled)
            # Смена формата не является правкой дел. Обновляем только
            # отметки ранее отправленных секций, сохраняя несинхронизированные.
            with self._last_synced_versions_lock:
                baseline = dict(self._last_synced_versions.get(self._account_key(account), {}))
            for key, version in before.items():
                if version is not None and baseline.get(key) == version:
                    self._mark_synced(account, key, self._section_version(key))

    def download(self, login_password, max_retries=5, preserve_local=False):
        """Применяет облачный снимок, только если локальные дела не менялись.

        Обычное обновление сохраняет неотправленные правки. Явный вход в
        аккаунт загружает его данные независимо от предыдущего аккаунта.
        Обмен с облаком сериализован с upload, но редактирование доступно
        во время сетевых запросов.
        """
        with self._sync_lock:
            with self.file_lock():
                before = self._local_versions()
                if preserve_local and self._has_unsent_changes(login_password, before):
                    self.request_upload(login_password)
                    return False

            try:
                self.account_encryption_enabled(login_password, refresh=True)
                result, legacy = self._download_snapshot(login_password, max_retries)
            except Exception as exc:
                print(f"Ошибка скачивания из облака: {type(exc).__name__}")
                return False
            if not result:
                return False

            with self.file_lock():
                if self._local_versions() != before:
                    # Правка во время скачивания важнее полученного снимка.
                    # Не отмечаем её отправленной и не заменяем данными сервера.
                    if preserve_local:
                        self.request_upload(login_password)
                    return False
                if self.web:
                    data = self.web_store.load_all_sections()
                    data.update(result)
                    self.web_store.replace_from_cloud(load_data_from_dict(data))
                else:
                    self._set_local_account_encryption(login_password, self.account_encryption_enabled(login_password))
                    save_all_sections(self.data_dir, result)
                for key in result:
                    # Старый единый файл ещё нужно перенести в облачные секции.
                    version = None if legacy else self._section_version(key)
                    self._mark_synced(login_password, key, version)
            if legacy:
                self.request_upload(login_password)
            return True

    def _download_snapshot(self, login_password, max_retries):
        paths = {key: self.cloud_path(CLOUD_ROOT, login_password, filename)
                 for key, filename in SECTION_FILENAMES.items()}
        with ThreadPoolExecutor(max_workers=len(paths)) as executor:
            futures = {key: executor.submit(self.disk.exists, path) for key, path in paths.items()}
            existing = [key for key, future in futures.items() if future.result()]
            if existing:
                futures = {key: executor.submit(self._download_payload, paths[key], max_retries)
                           for key in existing}
                result = {}
                for key, future in futures.items():
                    value = json.loads(decrypt_bytes(future.result()).decode("utf-8"))
                    if not isinstance(value, list):
                        raise ValueError("Некорректный формат секции " + key)
                    result[key] = value
                return result, False

        for filename in ("itog.json", "itog.txt"):
            path = self.cloud_path(CLOUD_ROOT, login_password, filename)
            if not self.disk.exists(path):
                continue
            text = decrypt_bytes(self._download_payload(path, max_retries)).decode("utf-8")
            if filename.endswith(".json"):
                candidate = json.loads(text)
                if not isinstance(candidate, dict):
                    raise ValueError("Некорректный формат сохранения")
                data = {
                    "tasks": candidate.get("tasks", candidate.get("normal", [])),
                    "postponed": candidate.get("postponed", []),
                    "groups": candidate.get("groups", []),
                    "repeat_tasks": candidate.get("repeat_tasks", candidate.get("repeat", [])),
                }
                if not all(isinstance(value, list) for value in data.values()):
                    raise ValueError("Некорректный формат сохранения")
                return load_data_from_dict(data), True
            parts = [part.strip().splitlines() for part in text.split("---")]
            while len(parts) < 4:
                parts.append([])
            return lines_to_data(*parts[:4]), True
        return {}, False

    # ------------------------------------------------------------------
    # Выгрузка
    # ------------------------------------------------------------------

    def _section_needs_upload(self, login_password, key):
        with self.file_lock():
            version = self._section_version(key)
        if version is None:
            return False
        with self._last_synced_versions_lock:
            last = self._last_synced_versions.get(self._account_key(login_password), {}).get(key)
        return last is None or version != last

    def _upload_section(self, login_password, key, max_retries=5):
        """Выгружает один файл секции (например, только tasks.json).

        Перед отправкой снимается "снимок" содержимого файла под общим
        локом (тем же, что используется при локальной записи), и в облако
        уходит именно этот снимок — так сетевая передача не зависит от
        того, что происходит с живым файлом после начала выгрузки.
        """
        filename = SECTION_FILENAMES[key]
        cloud_file = self.cloud_path(CLOUD_ROOT, login_password, filename)
        if self.web:
            value, _ = self.web_store.section_snapshot(key)
            version = self._fingerprint(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            payload = (
                json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            if self.account_encryption_enabled(login_password):
                payload = encrypt_bytes(payload)
            delay = 0.5
            for attempt in range(max_retries):
                try:
                    self.disk.upload(io.BytesIO(payload), cloud_file, overwrite=True)
                    self._mark_synced(login_password, key, version)
                    return
                except Exception as exc:
                    if _is_retryable_error(exc) and attempt < max_retries - 1:
                        time.sleep(delay)
                        delay *= 2
                        continue
                    print(f"Ошибка загрузки {filename} в облако: {type(exc).__name__}")
                    return

        local_path = self.data_dir / filename
        snapshot_path = local_path.with_name(filename + ".upload_tmp")
        delay = 0.5
        with Cloud._section_locks[key]:
            for attempt in range(max_retries):
                try:
                    with Cloud._file_lock:
                        if not local_path.exists():
                            return
                        payload = local_path.read_bytes()
                        version = self._fingerprint(payload)
                        plain = decrypt_bytes(payload)
                        cloud_payload = (encrypt_bytes(plain) if self.account_encryption_enabled(login_password)
                                         else plain)
                        snapshot_path.write_bytes(cloud_payload)
                    self.disk.upload(str(snapshot_path), cloud_file, overwrite=True)
                    self._mark_synced(login_password, key, version)
                    return
                except Exception as e:
                    if _is_retryable_error(e) and attempt < max_retries - 1:
                        time.sleep(delay)
                        delay *= 2
                        continue
                    print(f"Ошибка загрузки {filename} в облако: {type(e).__name__}")
                    return
                finally:
                    try:
                        snapshot_path.unlink(missing_ok=True)
                    except Exception:
                        pass

    def upload(self, login_password, max_retries=5, force=False):
        """Выгружает в облако только те файлы секций, которые реально
        изменились с прошлой выгрузки (force=True выгружает все 4, даже
        если ни один не менялся — используется при регистрации/сбросе).
        Изменившиеся секции выгружаются параллельно, а не по очереди.
        """
        with self._sync_lock:
            return self._upload(login_password, max_retries, force)

    def _upload(self, login_password, max_retries=5, force=False):
        self.account_encryption_enabled(login_password, refresh=True)
        self._set_local_account_encryption(login_password, self.account_encryption_enabled(login_password))
        pending = list(SECTION_FILENAMES) if force else [
            key for key in SECTION_FILENAMES if self._section_needs_upload(login_password, key)
        ]
        if not pending:
            return
        self._notify_upload_state(True)
        try:
            with ThreadPoolExecutor(max_workers=len(pending)) as executor:
                futures = [executor.submit(self._upload_section, login_password, key, max_retries) for key in pending]
                for future in futures:
                    future.result()
        finally:
            self._notify_upload_state(False)

    def create_weekly_backup(self, today=None):
        """Копирует облачные секции авторизованного аккаунта раз в 7 дней."""
        return self._create_backup(today, BACKUP_INTERVAL)

    def create_manual_backup(self, today=None):
        """Создаёт бэкап не чаще одного раза за календарный день на аккаунт."""
        return self._create_backup(today, timedelta(days=1))

    def _create_backup(self, today, interval):
        """Копирует облачные секции с проверкой интервала по истории в облаке.

        Завершённая папка публикуется только после копирования всех секций.
        История в облаке общая для всех устройств; локальные и гостевые
        данные здесь не читаются и не выгружаются.
        """
        today = today or date.today()
        with self._sync_lock:
            account = self.read_user_data_text().split("~~")[0].strip()
            if not account:
                return False
            account_path = self.cloud_path(CLOUD_ROOT, account)
            backups_path = self.cloud_path(account_path, "backups")
            try:
                self.disk.mkdir(backups_path)
            except FileExistsError:
                pass

            # Не принимаем незаконченные/посторонние папки за успешный бэкап.
            recent = []
            for entry in self.disk.listdir(backups_path):
                if entry.type != "dir" or not entry.name.startswith("backup_"):
                    continue
                try:
                    backup_date = datetime.strptime(entry.name, "backup_%d.%m.%Y").date()
                except ValueError:
                    continue
                if today - backup_date < interval:
                    recent.append(entry.name)
            filenames = set(SECTION_FILENAMES.values())
            for name in recent:
                contents = self.disk.listdir(self.cloud_path(backups_path, name))
                if filenames.issubset({item.name for item in contents if item.type == "file"}):
                    return False

            destination = self.cloud_path(backups_path, today.strftime("backup_%d.%m.%Y"))
            staging = self.cloud_path(backups_path, ".pending_" + uuid4().hex)
            self.disk.mkdir(staging)
            try:
                for filename in SECTION_FILENAMES.values():
                    if self.read_user_data_text().split("~~")[0].strip() != account:
                        return False
                    self.disk.copy(
                        self.cloud_path(account_path, filename),
                        self.cloud_path(staging, filename),
                        overwrite=False, wait=True, poll_timeout=120,
                    )
                if self.read_user_data_text().split("~~")[0].strip() != account:
                    return False
                # overwrite=False сохраняет уже опубликованный другим устройством
                # бэкап. Не заменяем существующие резервные копии.
                self.disk.move(staging, destination, overwrite=False, wait=True, poll_timeout=120)
                return True
            finally:
                # Удаляется только наша временная папка, в том числе после ошибки.
                try:
                    if self.disk.exists(staging):
                        self.disk.remove(staging, permanently=True, wait=True, poll_timeout=120)
                except Exception:
                    pass

    def _check_weekly_backup(self):
        """Проверяет срок в фоне; после сетевой ошибки повторяет через 5 минут."""
        account = self.read_user_data_text().split("~~")[0].strip()
        if not account:
            return
        key = self._account_key(account)
        now = time.monotonic()
        if now < self._backup_checks.get(key, 0):
            return
        try:
            self.create_weekly_backup()
        except Exception as exc:
            self._backup_checks[key] = time.monotonic() + BACKUP_RETRY_SECONDS
            # Исключение провайдера может содержать путь с паролем аккаунта.
            print(f"Не удалось создать еженедельный бэкап: {type(exc).__name__}")
        else:
            self._backup_checks[key] = time.monotonic() + BACKUP_CHECK_SECONDS

    def _upload_worker(self):
        """Единственный фоновый поток, который выполняет все выгрузки по очереди.

        Вместо того чтобы плодить отдельный поток на каждое изменение дела
        (что и вызывало гонку и ошибки 423), все запросы на выгрузку
        схлопываются (debounce) в один и обрабатываются последовательно —
        по аккаунтам. Внутри одной выгрузки изменившиеся файлы секций уже
        уходят в облако параллельно (см. upload()).
        """
        while True:
            try:
                self._check_weekly_backup()
            except Exception as exc:
                print(f"Ошибка проверки бэкапов: {type(exc).__name__}")
            with self._upload_cv:
                if self._pending_login_password is None:
                    self._upload_cv.wait(timeout=BACKUP_RETRY_SECONDS)
                if self._pending_login_password is None:
                    continue
                # Debounce: даём небольшим "пачкам" быстрых изменений схлопнуться в одну загрузку
                self._upload_cv.wait(timeout=0.7)
                login_password = self._pending_login_password
                self._pending_login_password = None
            try:
                self.upload(login_password)
            except Exception as exc:
                print(f"Ошибка фоновой выгрузки: {type(exc).__name__}")

    def request_upload(self, login_password):
        """Потокобезопасно ставит в очередь выгрузку для данного аккаунта.

        Не блокирует вызывающий код — реальная выгрузка выполняется в
        единственном фоновом воркере, поэтому конкурентных upload'ов
        на один и тот же файл больше не возникает.
        """
        with self._upload_cv:
            self._pending_login_password = login_password
            self._upload_cv.notify()

    def read_user_data_text(self):
        if self.web:
            return self.web_store.read_meta_text("user_data")
        return read_encrypted_text(self.user_data, encoding="utf-8")

    def write_user_data_text(self, text):
        if self.web:
            self.web_store.write_meta_text("user_data", text)
        else:
            write_encrypted_text(self.user_data, text, encoding="utf-8")
        # Вход будит фоновый поток, чтобы первый бэкап не ждал таймера.
        with self._upload_cv:
            self._upload_cv.notify()

    def read_accounts_text(self):
        if self.web:
            return self.web_store.read_meta_text("accounts")
        return read_encrypted_text(self.accounts, encoding="utf-8")

    def write_accounts_text(self, text):
        if self.web:
            self.web_store.write_meta_text("accounts", text)
            return
        write_encrypted_text(self.accounts, text, encoding="utf-8")

    def create_user_data(self, login, password):
        if not self.check_user_data():
            return False
        else:
            self.write_user_data_text(f"{login}_{password}")
            return True

    def check_user_data(self):
        return bool(self.read_user_data_text().strip())

    def create_dir_on_cloud(self, login_password):
        account_path = self.cloud_path(CLOUD_ROOT, login_password)
        if self.exists_on_cloud(account_path):
            return False
        else:
            self.create_folder_on_cloud(CLOUD_ROOT)
            self.create_folder_on_cloud(account_path)
            return True

    def read_user_data(self):
        itog = {"Start text": "", "Login": "", "Password": ""}
        if self.check_user_data():
            itog["Start text"] = "Вы авторизованы в этом аккаунте:"
            login_and_password = self.read_user_data_text().split("~~")
            itog["Login"] = f"Логин: {login_and_password[1]}"
            itog["Password"] = f"Пароль: {login_and_password[2]}"
        else:
            itog["Start text"] = "Вы не авторизованы ни в одном аккаунте"
        return itog

    def leave_from_account(self):
        self._restore_local_backup_to_active()
        self.write_user_data_text('')

    def delete_account(self):
        d = self.read_user_data_text().split("~~")[0]
        try:
            self.disk.remove(self.cloud_path(CLOUD_ROOT, d), permanently=True)
        except Exception:
            pass
        self.write_user_data_text('')
        self._restore_local_backup_to_active()

    def del_all(self):
        a = self.read_user_data_text().split("~~")[0]
        if self.web:
            self.web_store.save_all_sections(empty_data())
        else:
            with Cloud._file_lock:
                save_all_sections(self.data_dir, empty_data(), force=True)
        self.upload(a, force=True)

    def alg_for_start_app(self):
        s = time.time()
        itog = {"Connect": self.connect, "Have account": bool()}
        if self.connect:
            if self.check_user_data():
                a = self.read_user_data_text().split("~~")
                self.download(a[0], preserve_local=True)
                itog["Have account"] = True
                e = time.time()
                print(e-s,'старт апп')
            else:
                itog["Have account"] = False
        return itog

    def alg_for_regist(self, login, password):
        itog = {"Already have account": bool(), "Completed": bool(), "Connect": self.connect}
        if self.connect:
            if self.create_dir_on_cloud(f"{login}_{password}"):
                itog["Already have account"] = False
                itog["Completed"] = True
                if not self.check_user_data():
                    self._move_active_saves_to_local_backup()
                self.upload(f"{login}_{password}", force=True)
                self.write_user_data_text(f"{login}_{password}~~{login}~~{password}")
                a = self.read_accounts_text()
                self.write_accounts_text(a + f'\n{login}~~{password}\n')
            else:
                itog["Already have account"] = True
                itog["Completed"] = False
        return itog

    def alg_for_login(self, login, password):
        itog = {"Connect": self.connect, "Have account": bool(), "Completed": bool()}
        if not self.connect:
            return itog

        if self.exists_on_cloud(self.cloud_path(CLOUD_ROOT, f"{login}_{password}")):
            itog["Have account"] = True
            itog["Completed"] = True
            if not self.check_user_data():
                self._move_active_saves_to_local_backup()
            self.download(f"{login}_{password}")
            self.write_user_data_text(f"{login}_{password}~~{login}~~{password}")
            a = self.read_accounts_text()
            self.write_accounts_text(a + f'\n{login}~~{password}\n')
        else:
            itog["Have account"] = False
            itog["Completed"] = False
        return itog

    def alg_for_redact(self):
        """Планирует выгрузку изменений в облако.

        Раньше каждый вызов создавал собственный поток и сразу же
        выполнял upload(), из-за чего при массовых изменениях (например,
        при загрузке списка дел на старте) в облако одновременно летели
        десятки конкурентных запросов на один и тот же файл. Теперь запрос лишь
        регистрируется, а фактическую выгрузку — одну за другой —
        выполняет единственный фоновый воркер (см. _upload_worker), причём
        каждая выгрузка сама решает, какие из 4 файлов секций реально
        поменялись, и отправляет в облако только их.
        """
        if self.check_user_data():
            if self.connect:
                a = self.read_user_data_text().split("~~")
                self.request_upload(a[0])
