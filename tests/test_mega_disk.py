import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from Crypto.Cipher import AES
from mega import Mega
from mega.crypto import a32_to_str, get_chunks
from mega.errors import RequestError

from Backend.cloud import Cloud
from Backend.mega_disk import MegaDisk, _FileCipher, _MegaClient
from Frontend.init_page import Front


class ProtocolCloud:
    """API model stores encrypted bytes and decodes nodes with upstream MEGA."""

    def __init__(self):
        self.master_key = (11, 22, 33, 44)
        self.request_id = "test"
        self.nodes = {"root": {"h": "root", "t": 2, "a": {"n": "Cloud Drive"}}}
        self.payloads = {}
        self.encrypted_keys = {}
        self.pending = bytearray()
        self._http = Mock()
        self._http.post.side_effect = self.transfer
        self._http.stream.side_effect = self.stream
        self.api_calls = []

    def get_files(self):
        return dict(self.nodes)

    def transfer(self, url, content):
        self.pending.extend(content)
        return Mock(text="transfer-token")

    def stream(self, method, url):
        response = Mock()
        raw = self.payloads[url.rsplit("/", 1)[-1]]
        # Deliberately fragment across AES blocks and MEGA chunk boundaries.
        response.iter_bytes.return_value = iter(raw[i:i + 997] for i in range(0, len(raw), 997))
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context

    def _api_request(self, command):
        self.api_calls.append(command)
        if command["a"] == "u":
            self.pending.clear()
            return {"p": "https://transfer.invalid/upload"}
        if command["a"] == "g":
            node = self.nodes[command["n"]]
            return {"g": "https://transfer.invalid/" + node["h"], "s": node["s"]}
        if command["a"] == "p":
            descriptor = command["n"][0]
            handle = "node-" + str(len(self.nodes))
            raw = {**descriptor, "h": handle, "p": command["t"], "u": "owner",
                   "k": "owner:" + descriptor["k"]}
            if raw["t"] == 0:
                self.payloads[handle] = (self.payloads[descriptor["h"]]
                                         if descriptor["h"] in self.payloads else bytes(self.pending))
                raw["s"] = len(self.payloads[handle])
            # The library supplies an independent decoder for our encrypted nodes.
            node = Mega._process_file(self, raw, {})
            self.nodes[handle] = node
            self.encrypted_keys[handle] = descriptor["k"]
            if "ov" in descriptor:
                self.nodes[descriptor["ov"]]["p"] = handle
            return {"f": [node]}
        if command["a"] == "a":
            node = self.nodes[command["n"]]
            raw = {**node, "a": command["attr"],
                   "k": "owner:" + self.encrypted_keys[node["h"]]}
            self.nodes[node["h"]] = Mega._process_file(self, raw, {})
            return 0
        raise AssertionError(command)

    def destroy(self, handle):
        children = [key for key, node in self.nodes.items() if node.get("p") == handle]
        for child in children:
            self.destroy(child)
        self.nodes.pop(handle)

    def move(self, handle, parent):
        self.nodes[handle]["p"] = parent


class MegaDiskTests(unittest.TestCase):
    def setUp(self):
        self.remote = ProtocolCloud()
        self.disk = MegaDisk()
        self.disk._client = self.remote
        self.disk.mkdir("/For_to-do")
        self.disk.mkdir("/For_to-do/account")

    def test_encrypted_roundtrip_streams_files_and_chunk_boundaries(self):
        for size in (0, 1, 15, 16, 17, 31, 32, 131073, 393221):
            with self.subTest(size=size):
                plain = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
                path = "/For_to-do/account/data.bin"
                self.disk.upload(io.BytesIO(plain), path, overwrite=True)
                target = io.BytesIO()
                self.disk.download(path, target)
                self.assertEqual(target.getvalue(), plain)
                self.assertEqual(self.disk.get_meta(path).size, size)
                if plain:
                    self.assertNotEqual(self.remote.payloads[self.disk._resolve(path, self.remote.nodes)["h"]], plain)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.write_bytes(b"local file bytes")
            self.disk.upload(source, path, overwrite=True)
            self.disk.download(path, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_corrupt_truncated_and_extra_downloads_preserve_destination(self):
        path = "/For_to-do/account/tasks.json"
        self.disk.upload(io.BytesIO(b"private task data"), path)
        node = self.disk._resolve(path, self.remote.nodes)
        encrypted = self.remote.payloads[node["h"]]
        for broken in (bytes([encrypted[0] ^ 1]) + encrypted[1:], encrypted[:-1], encrypted + b"x"):
            with self.subTest(length=len(broken)):
                self.remote.payloads[node["h"]] = broken
                target = io.BytesIO(b"keep destination")
                with self.assertRaises(ValueError):
                    self.disk.download(path, target)
                self.assertEqual(target.getvalue(), b"keep destination")

    def test_nested_paths_never_find_other_accounts_file(self):
        self.disk.mkdir("/For_to-do/second")
        self.disk.upload(io.BytesIO(b"first"), "/For_to-do/account/tasks.json")
        self.disk.upload(io.BytesIO(b"second"), "/For_to-do/second/tasks.json")
        target = io.BytesIO()
        self.disk.download("/For_to-do/second/tasks.json", target)
        self.assertEqual(target.getvalue(), b"second")
        self.assertFalse(self.disk.exists("/For_to-do/missing/tasks.json"))
        self.remote.get_files = Mock(side_effect=RequestError(-9))
        with self.assertRaises(RequestError):
            self.disk.exists("/For_to-do/account")

    def test_server_copy_preserves_bytes_without_publishing_a_link(self):
        self.disk.upload(io.BytesIO(b"backup bytes"), "/For_to-do/account/tasks.json")
        self.disk.mkdir("/For_to-do/account/backups")
        self.disk.copy("/For_to-do/account/tasks.json", "/For_to-do/account/backups/tasks.json")
        target = io.BytesIO()
        self.disk.download("/For_to-do/account/backups/tasks.json", target)
        self.assertEqual(target.getvalue(), b"backup bytes")
        self.assertFalse(any(call["a"] == "l" for call in self.remote.api_calls))
        with self.assertRaises(FileExistsError):
            self.disk.copy("/For_to-do/account/tasks.json", "/For_to-do/account/backups/tasks.json")

    def test_failed_upload_preserves_previous_file_and_success_creates_version(self):
        path = "/For_to-do/account/tasks.json"
        self.disk.upload(io.BytesIO(b"previous"), path)
        with patch.object(self.remote._http, "post", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.disk.upload(io.BytesIO(b"changed"), path, overwrite=True)
        target = io.BytesIO()
        self.disk.download(path, target)
        self.assertEqual(target.getvalue(), b"previous")
        old = self.disk._resolve(path, self.remote.nodes)["h"]
        self.disk.upload(io.BytesIO(b"changed"), path, overwrite=True)
        self.assertEqual(self.remote.api_calls[-1]["n"][0]["ov"], old)
        self.assertEqual(len(self.disk.listdir("/For_to-do/account")), 1)

    def test_existing_folder_does_not_get_replaced_and_staging_is_renamed(self):
        with self.assertRaises(FileExistsError):
            self.disk.mkdir("/For_to-do/account")
        self.disk.mkdir("/For_to-do/account/.pending_test")
        self.disk.move("/For_to-do/account/.pending_test", "/For_to-do/account/backup_01.01.2026")
        self.assertTrue(self.disk.exists("/For_to-do/account/backup_01.01.2026"))
        self.assertFalse(self.disk.exists("/For_to-do/account/.pending_test"))
        self.disk.remove("/For_to-do/account/backup_01.01.2026", permanently=True)
        self.assertFalse(self.disk.exists("/For_to-do/account/backup_01.01.2026"))

    def test_old_provider_versions_cannot_skip_mega_uploads(self):
        cloud = Cloud.__new__(Cloud)
        self.assertNotEqual(cloud._account_key("account"), cloud._fingerprint(b"account"))


class MegaProtocolTests(unittest.TestCase):
    def test_cloud_authentication_errors_are_shown_without_private_details(self):
        import asyncio
        for action, cloud_method in (("login", "alg_for_login"), ("register", "alg_for_regist")):
            with self.subTest(action=action):
                front = Front.__new__(Front)
                front.page = Mock()
                front.libs = Mock()
                front.cloud = Mock()
                getattr(front.cloud, cloud_method).side_effect = RuntimeError("private session token")
                front._open_loading_view = Mock(return_value="loading")
                front._close_loading_view = Mock()
                getattr(front, action)("user", "password")
                callback = front.page.run_task.call_args.args[0]
                asyncio.run(callback())
                front._close_loading_view.assert_called_once_with("loading")
                message = front.libs.open_dialog.call_args.args[1]
                self.assertIn("MEGA", message)
                self.assertNotIn("private session token", message)

    def test_mac_agrees_with_independent_cbc_reference(self):
        key, nonce = (1, 2, 3, 4), (5, 6)
        for size in (0, 1, 17, 131073, 393221):
            payload = b"a" * size
            cipher = _FileCipher(key, nonce)
            aggregate = b"\0" * 16
            for start, length in get_chunks(size):
                plain = payload[start:start + length]
                cipher.authenticate(plain)
                if plain:
                    padded = plain + b"\0" * (-len(plain) % 16)
                    chunk_mac = AES.new(a32_to_str(key), AES.MODE_CBC,
                                        a32_to_str(nonce + nonce)).encrypt(padded)[-16:]
                    aggregate = AES.new(a32_to_str(key), AES.MODE_CBC, aggregate).encrypt(chunk_mac)
            import struct
            words = struct.unpack(">4I", aggregate)
            self.assertEqual(cipher.digest(), (words[0] ^ words[1], words[2] ^ words[3]))

    def test_lazy_login_uses_environment_and_closes_session(self):
        with patch.dict(os.environ, {"MEGA_EMAIL": "test@example.invalid", "MEGA_PASSWORD": " pass "}), \
                patch("Backend.mega_disk._MegaClient") as client:
            disk = MegaDisk()
            client.assert_not_called()
            self.assertIs(disk._login(), client.return_value)
            disk._login()
            client.return_value.login.assert_called_once_with("test@example.invalid", " pass ")
            disk.close()
            client.return_value._http.close.assert_called_once()

    def test_api_retry_is_bounded_and_bad_password_is_not_retried(self):
        client = _MegaClient()
        self.addCleanup(client._http.close)
        response = Mock()
        response.json.return_value = [-3]
        with patch.object(client._http, "post", return_value=response) as post, \
                patch("Backend.mega_disk.time.sleep"):
            with self.assertRaises(RequestError):
                client._api_request({"a": "f"})
            self.assertEqual(post.call_count, 3)
            post.reset_mock()
            response.json.return_value = [-9]
            with self.assertRaises(RequestError):
                client._api_request({"a": "us"})
            self.assertEqual(post.call_count, 1)

    def test_mfa_code_is_sent_only_for_login(self):
        client = _MegaClient(" 123456 ")
        self.addCleanup(client._http.close)
        response = Mock()
        response.json.return_value = [{}]
        with patch.object(client._http, "post", return_value=response) as post:
            client._api_request({"a": "us", "user": "test@example.invalid"})
            self.assertEqual(post.call_args.kwargs["json"][0]["mfa"], "123456")
            client._api_request({"a": "f"})
            self.assertNotIn("mfa", post.call_args.kwargs["json"][0])


if __name__ == "__main__":
    unittest.main()
