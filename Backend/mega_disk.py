"""MEGA transport with the path/stream interface used by Cloud.

Authentication and node decoding use mega.py-v2. Transfers are implemented
here to support Windows, streams, bounded retries and verified downloads.
"""

import importlib
import os
import secrets
import shutil
import struct
import tempfile
import threading
import time
from types import SimpleNamespace

import httpx
from Crypto.Cipher import AES
from mega import Mega
from mega.crypto import (
    a32_to_base64, a32_to_str, base64_url_encode, encrypt_attr,
    encrypt_key, get_chunks, str_to_a32,
)
from mega.errors import RequestError


def load_mega_credentials():
    """Environment overrides secret.py; passwords retain their spaces."""
    try:
        settings = importlib.import_module("secret")
    except ModuleNotFoundError as exc:
        if exc.name != "secret":
            raise
        settings = None
    values = {
        key: os.environ.get(key, getattr(settings, key, ""))
        for key in ("MEGA_EMAIL", "MEGA_PASSWORD", "MEGA_MFA_CODE")
    }
    for key in ("MEGA_EMAIL", "MEGA_PASSWORD"):
        if not isinstance(values[key], str) or not values[key].strip():
            raise ValueError(f"Задайте {key} в secret.py или переменной окружения.")
    values["MEGA_EMAIL"] = values["MEGA_EMAIL"].strip()
    if not isinstance(values["MEGA_MFA_CODE"], str):
        raise ValueError("MEGA_MFA_CODE должен быть строкой.")
    return values


def is_retryable_error(exc):
    return (isinstance(exc, httpx.TransportError)
            or getattr(exc, "code", None) in (-3, -4, -18, -19)
            or (isinstance(exc, httpx.HTTPStatusError)
                and (exc.response.status_code == 429 or exc.response.status_code >= 500)))


class _MegaClient(Mega):
    def __init__(self, mfa_code=""):
        super().__init__()
        self.mfa_code = mfa_code.strip()
        self._http.timeout = httpx.Timeout(60, connect=15)

    def _api_request(self, data):
        # The upstream decorator retries EAGAIN forever. Use a bounded loop.
        if isinstance(data, dict) and data.get("a") == "us" and self.mfa_code:
            data = {**data, "mfa": self.mfa_code}
        commands = data if isinstance(data, list) else [data]
        for attempt in range(3):
            try:
                params = {"id": self.sequence_num}
                self.sequence_num += 1
                if self.sid:
                    params["sid"] = self.sid
                response = self._http.post("https://g.api.mega.co.nz/cs",
                                           params=params, json=commands)
                if response.status_code == 402 and "x-hashcash" in response.headers:
                    from mega.hashcash import solve_hashcash
                    solution = solve_hashcash(response.headers["x-hashcash"])
                    if solution:
                        response = self._http.post(
                            "https://g.api.mega.co.nz/cs", params=params, json=commands,
                            headers={"X-Hashcash": solution})
                response.raise_for_status()
                result = response.json()
                result = result[0] if isinstance(result, list) and result else result
                if isinstance(result, int) and result < 0:
                    raise RequestError(result)
                if not isinstance(result, (dict, int)):
                    raise ValueError("Некорректный ответ MEGA.")
                return result
            except Exception as exc:
                if not is_retryable_error(exc) or attempt == 2:
                    raise
                time.sleep(0.5 * 2 ** attempt)


class _FileCipher:
    """MEGA AES-CTR plus the chunk CBC-MAC (including empty files)."""

    def __init__(self, key, nonce):
        raw_key = a32_to_str(key)
        self.ctr = AES.new(raw_key, AES.MODE_CTR, nonce=b"",
                           initial_value=int.from_bytes(a32_to_str(nonce) + b"\0" * 8))
        self.ecb = AES.new(raw_key, AES.MODE_ECB)
        self.iv = a32_to_str(nonce + nonce)
        self.mac = b"\0" * 16

    @staticmethod
    def _xor(left, right):
        return bytes(a ^ b for a, b in zip(left, right))

    def authenticate(self, chunk):
        if not chunk:
            return
        state = self.iv
        for offset in range(0, len(chunk), 16):
            block = chunk[offset:offset + 16].ljust(16, b"\0")
            state = self.ecb.encrypt(self._xor(state, block))
        self.mac = self.ecb.encrypt(self._xor(self.mac, state))

    def digest(self):
        a, b, c, d = struct.unpack(">4I", self.mac)
        return (a ^ b, c ^ d)


class MegaDisk:
    """One lazy MEGA login shared safely by the application's worker threads."""

    def __init__(self):
        self._client = None
        self._lock = threading.RLock()

    def _login(self):
        if self._client is None:
            credentials = load_mega_credentials()
            client = _MegaClient(credentials["MEGA_MFA_CODE"])
            try:
                client.login(credentials["MEGA_EMAIL"], credentials["MEGA_PASSWORD"])
                if not client.sid:
                    raise ValueError("MEGA не подтвердила авторизацию.")
            except Exception:
                client._http.close()
                raise
            self._client = client
        return self._client

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        with self._lock:
            if self._client is not None:
                self._client._http.close()
                self._client = None

    def _nodes(self):
        client = self._login()
        try:
            return client.get_files()
        except RequestError as exc:
            if exc.code != -15:
                raise
            # A revoked/expired session requires a fresh authenticated client.
            self.close()
            return self._login().get_files()

    @staticmethod
    def _parts(path):
        parts = [part for part in str(path).split("/") if part]
        if any(part in (".", "..") for part in parts):
            raise ValueError("Некорректный облачный путь.")
        return parts

    def _resolve(self, path, nodes):
        current = next((node for node in nodes.values() if node["t"] == 2), None)
        if current is None:
            raise ValueError("MEGA не вернула корневую папку.")
        for part in self._parts(path):
            if current["t"] not in (1, 2):
                raise NotADirectoryError()
            matches = [node for node in nodes.values()
                       if node.get("p") == current["h"] and node["a"].get("n") == part]
            if not matches:
                raise FileNotFoundError("Ресурс отсутствует в MEGA.")
            if len(matches) != 1:
                raise ValueError("В MEGA найдены ресурсы с одинаковым именем в одной папке.")
            current = matches[0]
        return current

    def _destination(self, path, nodes, overwrite):
        parts = self._parts(path)
        if not parts:
            raise ValueError("Нельзя заменить корень MEGA.")
        parent = self._resolve("/" + "/".join(parts[:-1]), nodes)
        if parent["t"] not in (1, 2):
            raise NotADirectoryError()
        try:
            existing = self._resolve(path, nodes)
        except FileNotFoundError:
            existing = None
        if existing is not None and not overwrite:
            raise FileExistsError("Ресурс уже существует в MEGA.")
        return parent, parts[-1], existing

    @staticmethod
    def _meta(node):
        return SimpleNamespace(name=node["a"]["n"],
                               type="file" if node["t"] == 0 else "dir",
                               size=node.get("s") if node["t"] == 0 else None,
                               sha256=None)

    def exists(self, path):
        with self._lock:
            try:
                self._resolve(path, self._nodes())
            except FileNotFoundError:
                return False
            return True

    def get_meta(self, path, **kwargs):
        with self._lock:
            return self._meta(self._resolve(path, self._nodes()))

    def listdir(self, path, **kwargs):
        with self._lock:
            nodes = self._nodes()
            parent = self._resolve(path, nodes)
            if parent["t"] not in (1, 2):
                raise NotADirectoryError()
            return [self._meta(node) for node in nodes.values()
                    if node.get("p") == parent["h"] and node["t"] in (0, 1)]

    def _put_node(self, parent, name, kind, key, cipher_key, handle, existing=None):
        client = self._login()
        node = {"h": handle, "t": kind,
                "a": base64_url_encode(encrypt_attr({"n": name}, cipher_key)),
                "k": a32_to_base64(encrypt_key(key, client.master_key))}
        if existing is not None:
            if kind != 0 or existing["t"] != 0:
                raise IsADirectoryError()
            # MEGA replaces the current file and retains the old version.
            node["ov"] = existing["h"]
        return client._api_request({"a": "p", "t": parent["h"], "n": [node],
                                    "i": client.request_id})

    def mkdir(self, path):
        with self._lock:
            parent, name, _ = self._destination(path, self._nodes(), False)
            key = str_to_a32(secrets.token_bytes(16))
            self._put_node(parent, name, 1, key, key, "xxxxxxxx")

    def upload(self, source, path, overwrite=False):
        with self._lock:
            parent, name, existing = self._destination(path, self._nodes(), overwrite)
            if existing is not None and existing["t"] != 0:
                raise IsADirectoryError()
            # A stable snapshot also supports BytesIO from browser sessions.
            with tempfile.TemporaryFile() as snapshot:
                if hasattr(source, "read"):
                    shutil.copyfileobj(source, snapshot)
                else:
                    with open(source, "rb") as stream:
                        shutil.copyfileobj(stream, snapshot)
                size = snapshot.tell()
                snapshot.seek(0)
                client = self._login()
                url = client._api_request({"a": "u", "s": size, "ssl": 2})["p"]
                key = str_to_a32(secrets.token_bytes(16))
                nonce = str_to_a32(secrets.token_bytes(8))
                cipher = _FileCipher(key, nonce)
                handle = ""
                for offset, length in (get_chunks(size) if size else [(0, 0)]):
                    plain = snapshot.read(length)
                    if plain:
                        cipher.authenticate(plain)
                    response = client._http.post(url + "/" + str(offset),
                                                 content=cipher.ctr.encrypt(plain))
                    response.raise_for_status()
                    handle = response.text.strip()
                    if handle.startswith("-") and handle[1:].isdigit():
                        raise RequestError(int(handle))
                if not handle:
                    raise ValueError("MEGA не подтвердила загрузку файла.")
                mac = cipher.digest()
                full_key = (key[0] ^ nonce[0], key[1] ^ nonce[1],
                            key[2] ^ mac[0], key[3] ^ mac[1], *nonce, *mac)
                self._put_node(parent, name, 0, full_key, key, handle, existing)

    def download(self, path, target, **kwargs):
        with self._lock:
            node = self._resolve(path, self._nodes())
            if node["t"] != 0:
                raise IsADirectoryError()
            client = self._login()
            info = client._api_request({"a": "g", "g": 1, "n": node["h"], "ssl": 2})
            cipher = _FileCipher(node["k"], node["iv"][:2])
            # Destination is touched only after size and MEGA MAC validation.
            with tempfile.TemporaryFile() as verified:
                with client._http.stream("GET", info["g"]) as response:
                    response.raise_for_status()
                    buffered = bytearray()
                    chunks = iter(response.iter_bytes())
                    for _, length in get_chunks(info["s"]):
                        while len(buffered) < length:
                            try:
                                buffered.extend(next(chunks))
                            except StopIteration:
                                raise ValueError("MEGA вернула неполный файл.") from None
                        plain = cipher.ctr.decrypt(bytes(buffered[:length]))
                        del buffered[:length]
                        cipher.authenticate(plain)
                        verified.write(plain)
                    if buffered or any(chunks):
                        raise ValueError("Размер файла MEGA не совпадает.")
                if cipher.digest() != tuple(node["meta_mac"]):
                    raise ValueError("Контрольная сумма MEGA не совпадает.")
                verified.seek(0)
                if hasattr(target, "write"):
                    shutil.copyfileobj(verified, target)
                else:
                    with open(target, "wb") as stream:
                        shutil.copyfileobj(verified, stream)

    def copy(self, source, target, overwrite=False, **kwargs):
        with self._lock:
            nodes = self._nodes()
            node = self._resolve(source, nodes)
            if node["t"] != 0:
                raise IsADirectoryError("Копирование ожидает файл.")
            parent, name, existing = self._destination(target, nodes, overwrite)
            self._put_node(parent, name, 0, node["key"], node["k"], node["h"], existing)

    def move(self, source, target, overwrite=False, **kwargs):
        with self._lock:
            nodes = self._nodes()
            node = self._resolve(source, nodes)
            parent, name, existing = self._destination(target, nodes, overwrite)
            if existing is not None:
                raise FileExistsError("Перемещение не заменяет существующий ресурс.")
            client = self._login()
            if node.get("p") != parent["h"]:
                client.move(node["h"], parent["h"])
            attributes = {**node["a"], "n": name}
            client._api_request({"a": "a", "n": node["h"], "i": client.request_id,
                                 "attr": base64_url_encode(encrypt_attr(attributes, node["k"]))})

    def remove(self, path, permanently=False, **kwargs):
        with self._lock:
            node = self._resolve(path, self._nodes())
            if node["t"] == 2:
                raise ValueError("Нельзя удалить корень MEGA.")
            client = self._login()
            if permanently:
                client.destroy(node["h"])
            else:
                client.delete(node["h"])
