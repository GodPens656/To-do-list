"""Dropbox transport for Cloud's path/stream interface."""

import hashlib
import importlib
import os
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace

import dropbox
from dropbox import exceptions, files
import requests


def load_dropbox_credentials():
    """Environment variables override secret.py, including empty values."""
    try:
        settings = importlib.import_module("secret")
    except ModuleNotFoundError as exc:
        if exc.name != "secret":
            raise
        settings = None
    values = {}
    for key in ("DROPBOX_ACCESS_TOKEN", "DROPBOX_REFRESH_TOKEN",
                "DROPBOX_APP_KEY", "DROPBOX_APP_SECRET"):
        value = os.environ.get(key, getattr(settings, key, ""))
        if not isinstance(value, str):
            raise ValueError(f"{key} должен быть строкой.")
        values[key] = value.strip()
    if values["DROPBOX_REFRESH_TOKEN"]:
        if not values["DROPBOX_APP_KEY"]:
            raise ValueError("Для DROPBOX_REFRESH_TOKEN задайте DROPBOX_APP_KEY.")
    elif not values["DROPBOX_ACCESS_TOKEN"]:
        raise ValueError("Задайте DROPBOX_ACCESS_TOKEN или DROPBOX_REFRESH_TOKEN и "
                         "DROPBOX_APP_KEY в secret.py или переменных окружения.")
    return values


class DropboxDiskError(RuntimeError):
    """Safe to display: never includes tokens, account names or API paths."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def is_retryable_error(exc):
    return (getattr(exc, "retryable", False)
            or isinstance(exc, (requests.Timeout, requests.ConnectionError)))


class _ContentHash:
    """Dropbox hashes the concatenated SHA-256 digests of 4 MiB blocks."""

    block_size = 4 * 1024 * 1024

    def __init__(self):
        self.outer = hashlib.sha256()
        self.block = hashlib.sha256()
        self.length = 0

    def update(self, payload):
        offset = 0
        while offset < len(payload):
            count = min(self.block_size - self.length, len(payload) - offset)
            self.block.update(payload[offset:offset + count])
            self.length += count
            offset += count
            if self.length == self.block_size:
                self.outer.update(self.block.digest())
                self.block = hashlib.sha256()
                self.length = 0

    def hexdigest(self):
        outer = self.outer.copy()
        if self.length:
            outer.update(self.block.digest())
        return outer.hexdigest()


def _content_hash(payload):
    digest = _ContentHash()
    digest.update(payload)
    return digest.hexdigest()


def _path_error(error):
    # SDK endpoints wrap LookupError/WriteError in different union variants.
    for tag in ("path", "path_lookup", "path_write", "from_lookup", "to"):
        check = getattr(error, "is_" + tag, None)
        if check and check():
            return _path_error(getattr(error, "get_" + tag)())
    return error


class DropboxDisk:
    chunk_size = 8 * 1024 * 1024

    def __init__(self):
        self._client = None
        self._lock = threading.RLock()

    def _login(self):
        if self._client is None:
            values = load_dropbox_credentials()
            refresh = values["DROPBOX_REFRESH_TOKEN"]
            self._client = dropbox.Dropbox(
                # Prefer refresh auth; a generated access token has no expiry metadata.
                oauth2_access_token=None if refresh else values["DROPBOX_ACCESS_TOKEN"],
                oauth2_refresh_token=refresh or None,
                app_key=values["DROPBOX_APP_KEY"] or None,
                app_secret=values["DROPBOX_APP_SECRET"] or None,
                timeout=60, max_retries_on_error=2, max_retries_on_rate_limit=2,
            )
        return self._client

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    @staticmethod
    def _path(path, allow_root=False):
        parts = [part for part in str(path).split("/") if part]
        if any(part in (".", "..") for part in parts):
            raise ValueError("Некорректный облачный путь.")
        if not parts and not allow_root:
            raise ValueError("Нельзя изменять корень Dropbox.")
        return "/" + "/".join(parts) if parts else ""

    def _call(self, method, *args, **kwargs):
        try:
            return getattr(self._login(), method)(*args, **kwargs)
        except exceptions.ApiError as exc:
            error = _path_error(exc.error)
            if getattr(error, "is_not_found", lambda: False)():
                raise FileNotFoundError("Ресурс отсутствует в Dropbox.") from None
            if getattr(error, "is_conflict", lambda: False)():
                raise FileExistsError("Ресурс уже существует в Dropbox.") from None
            retry = getattr(error, "is_too_many_write_operations", lambda: False)()
            raise DropboxDiskError("Dropbox не выполнил файловую операцию.", retry) from None
        except exceptions.AuthError:
            raise DropboxDiskError("Dropbox: проверьте токен и разрешения приложения.") from None
        except (exceptions.HttpError, requests.RequestException) as exc:
            status = getattr(exc, "status_code", 0)
            retry = (isinstance(exc, (exceptions.RateLimitError, exceptions.InternalServerError,
                                      requests.Timeout, requests.ConnectionError))
                     or status == 429 or status >= 500)
            raise DropboxDiskError("Ошибка соединения с Dropbox.", retry) from None

    @staticmethod
    def _meta(meta):
        return SimpleNamespace(name=meta.name,
                               type="file" if isinstance(meta, files.FileMetadata) else "dir",
                               size=getattr(meta, "size", None), sha256=None)

    def check_connection(self):
        with self._lock:
            # Works with App Folder and only files.metadata.read, even before setup.
            self._call("files_list_folder", "", limit=1)
        return True

    def exists(self, path):
        with self._lock:
            try:
                self.get_meta(path)
            except FileNotFoundError:
                return False
            return True

    def get_meta(self, path, **kwargs):
        with self._lock:
            path = self._path(path, allow_root=True)
            if not path:
                self.check_connection()
                return SimpleNamespace(name="", type="dir", size=None, sha256=None)
            return self._meta(self._call("files_get_metadata", path))

    def listdir(self, path, **kwargs):
        with self._lock:
            result = self._call("files_list_folder", self._path(path, allow_root=True))
            entries = list(result.entries)
            while result.has_more:
                result = self._call("files_list_folder_continue", result.cursor)
                entries.extend(result.entries)
            return [self._meta(entry) for entry in entries
                    if isinstance(entry, (files.FileMetadata, files.FolderMetadata))]

    def mkdir(self, path):
        with self._lock:
            self._call("files_create_folder_v2", self._path(path), autorename=False)

    def upload(self, source, destination, overwrite=False, **kwargs):
        with self._lock:
            path = self._path(destination)
            mode = files.WriteMode.overwrite if overwrite else files.WriteMode.add
            close_source = isinstance(source, (str, os.PathLike))
            stream = open(source, "rb") if close_source else source
            try:
                first = stream.read(self.chunk_size)
                following = stream.read(self.chunk_size)
                options = dict(mode=mode, autorename=False, strict_conflict=True)
                if not following:
                    self._call("files_upload", first, path,
                               content_hash=_content_hash(first), **options)
                    return
                session = self._call("files_upload_session_start", first,
                                     content_hash=_content_hash(first))
                cursor = files.UploadSessionCursor(session.session_id, len(first))
                chunk = following
                while True:
                    following = stream.read(self.chunk_size)
                    if not following:
                        self._call("files_upload_session_finish", chunk, cursor,
                                   files.CommitInfo(path, **options),
                                   content_hash=_content_hash(chunk))
                        return
                    self._call("files_upload_session_append_v2", chunk, cursor,
                               content_hash=_content_hash(chunk))
                    cursor.offset += len(chunk)
                    chunk = following
            finally:
                if close_source:
                    stream.close()

    def download(self, source, destination, **kwargs):
        with self._lock:
            meta, response = self._call("files_download", self._path(source))
            # Validate before replacing a local file or writing into a caller's stream.
            with tempfile.TemporaryFile() as temporary:
                digest, size = _ContentHash(), 0
                try:
                    for chunk in response.iter_content(1024 * 1024):
                        temporary.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                except requests.RequestException:
                    raise DropboxDiskError("Скачивание из Dropbox прервано.", True) from None
                finally:
                    response.close()
                if size != meta.size or digest.hexdigest() != meta.content_hash:
                    raise DropboxDiskError("Размер или контрольная сумма Dropbox не совпадает.", True)
                temporary.seek(0)
                if hasattr(destination, "write"):
                    shutil.copyfileobj(temporary, destination)
                    return
                target = Path(destination)
                staged = None
                try:
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                        staged = Path(output.name)
                        shutil.copyfileobj(temporary, output)
                    os.replace(staged, target)
                finally:
                    if staged is not None:
                        staged.unlink(missing_ok=True)

    def copy(self, source, destination, overwrite=False, **kwargs):
        if overwrite:
            raise ValueError("Замена файлов при копировании Dropbox не поддерживается.")
        with self._lock:
            self._call("files_copy_v2", self._path(source), self._path(destination), autorename=False)

    def move(self, source, destination, overwrite=False, **kwargs):
        if overwrite:
            raise ValueError("Замена файлов при перемещении Dropbox не поддерживается.")
        with self._lock:
            self._call("files_move_v2", self._path(source), self._path(destination), autorename=False)

    def remove(self, path, permanently=False, **kwargs):
        # Standard Dropbox deletion respects the account's recovery retention period.
        with self._lock:
            self._call("files_delete_v2", self._path(path))
