"""AES-256-GCM шифрование локальных и облачных данных приложения."""

import hashlib
import json
import os
import threading
from collections import OrderedDict
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


try:
    from secret import ENCRYPTION_KEYWORD as KEYWORD
except ModuleNotFoundError as error:
    if error.name != "secret":
        raise
    raise RuntimeError(
        "Не найден secret.py. Скопируйте secret.example.py в secret.py "
        "и заполните настройки согласно README.md."
    ) from error

if not isinstance(KEYWORD, str) or not KEYWORD.strip():
    raise ValueError("Задайте непустой ENCRYPTION_KEYWORD в secret.py.")

# Изменение ключевого слова сделает ранее сохранённые данные недоступными.
_KEY = hashlib.sha256(KEYWORD.encode("utf-8")).digest()  # ровно 256 бит
_MAGIC = b"ND-AES256-GCM\x01"
_NONCE_SIZE = 12
ACCOUNT_DATA_FILENAMES = frozenset({
    "tasks.json", "groups.json", "postponed.json", "repeat_tasks.json", "itog.json", "itog.txt",
    "achievements.json",
})
_ENCRYPTION_CACHE = OrderedDict()
_ENCRYPTION_CACHE_LOCK = threading.RLock()


def file_signature(path):
    """Возвращает версию файла без чтения содержимого; None означает отсутствие."""
    try:
        stat = Path(path).stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def invalidate_data_encryption(directory):
    """Сбрасывает настройку после явного изменения формата хранилища."""
    path = Path(os.path.abspath(directory)) / "security.json"
    with _ENCRYPTION_CACHE_LOCK:
        _ENCRYPTION_CACHE.pop(path, None)


def data_encryption_enabled(directory):
    """Читает формат файлов дел, переиспользуя настройку до изменения файла."""
    path = Path(os.path.abspath(directory)) / "security.json"
    with _ENCRYPTION_CACHE_LOCK:
        signature = file_signature(path)
        cached = _ENCRYPTION_CACHE.get(path)
        if cached is not None and cached[0] == signature:
            _ENCRYPTION_CACHE.move_to_end(path)
            return cached[1]
        _ENCRYPTION_CACHE.pop(path, None)
        enabled = True
        if signature is not None:
            settings = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict) or type(settings.get("encryption_enabled")) is not bool:
                raise ValueError("Некорректная локальная настройка шифрования.")
            enabled = settings["encryption_enabled"]
        # Внешняя замена во время чтения не должна закрепить старую настройку
        # под новой сигнатурой. Следующее обращение проверит файл заново.
        if file_signature(path) == signature:
            _ENCRYPTION_CACHE[path] = signature, enabled
            if len(_ENCRYPTION_CACHE) > 128:
                _ENCRYPTION_CACHE.popitem(last=False)
        return enabled


def file_encryption_enabled(path):
    path = Path(path)
    if path.name == "settings.txt":
        return False
    return data_encryption_enabled(path.parent) if path.name in ACCOUNT_DATA_FILENAMES else True


class EncryptedFileError(ValueError):
    """Зашифрованный файл повреждён или создан с другим ключом."""


def is_encrypted(data):
    return bytes(data).startswith(_MAGIC)


def encrypt_bytes(data):
    nonce = os.urandom(_NONCE_SIZE)
    return _MAGIC + nonce + AESGCM(_KEY).encrypt(nonce, bytes(data), _MAGIC)


def decrypt_bytes(data, allow_plaintext=True):
    data = bytes(data)
    if not is_encrypted(data):
        if allow_plaintext:  # совместимость и автоматическая миграция старых файлов
            return data
        raise EncryptedFileError("Файл не зашифрован")
    if len(data) < len(_MAGIC) + _NONCE_SIZE + 16:
        raise EncryptedFileError("Зашифрованный файл обрезан")
    nonce = data[len(_MAGIC):len(_MAGIC) + _NONCE_SIZE]
    ciphertext = data[len(_MAGIC) + _NONCE_SIZE:]
    try:
        return AESGCM(_KEY).decrypt(nonce, ciphertext, _MAGIC)
    except InvalidTag as error:
        raise EncryptedFileError(
            "Не удалось расшифровать файл: неверный ключ или данные повреждены"
        ) from error


def read_bytes(path):
    path = Path(path)
    raw = path.read_bytes()
    plain = decrypt_bytes(raw)
    needs_decryption = path.name == "settings.txt" and is_encrypted(raw)
    if needs_decryption or (not is_encrypted(raw) and file_encryption_enabled(path)):
        write_bytes(path, plain)
    return plain


def write_bytes(path, data, *, encrypt=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".encryption_tmp")
    if encrypt is None:
        encrypt = file_encryption_enabled(path)
    temporary.write_bytes(encrypt_bytes(data) if encrypt else bytes(data))
    temporary.replace(path)


def read_text(path, encoding="utf-8"):
    return read_bytes(path).decode(encoding)


def write_text(path, text, encoding="utf-8"):
    write_bytes(path, str(text).encode(encoding))


def encrypt_file_if_plaintext(path):
    """Шифрует существующий legacy-файл на месте; возвращает факт миграции."""
    path = Path(path)
    if not path.is_file() or not file_encryption_enabled(path):
        return False
    data = path.read_bytes()
    if is_encrypted(data):
        return False
    write_bytes(path, data)
    return True
