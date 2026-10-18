import asyncio
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.cloud import Cloud
from Backend.core import Backend
from Backend.crypto import decrypt_bytes, encrypt_bytes
from Backend.shared_groups import SHARED_ROOT
from Backend.storage import empty_data, save_all_sections
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front


class MemoryDisk:
    """Dropbox-like case-insensitive storage with conditional revision writes."""

    def __init__(self):
        self.files = {}
        self.folders = set()
        self.revision = 0
        self.fail = False
        self.before_upload = None
        self.after_download = None

    def mkdir(self, path):
        key = path.casefold()
        if key in self.folders:
            raise FileExistsError()
        self.folders.add(key)

    def exists(self, path):
        return path.casefold() in self.files or path.casefold() in self.folders

    def upload(self, source, path, overwrite=False, revision=None):
        if self.fail:
            raise TimeoutError("private path")
        if self.before_upload:
            callback, self.before_upload = self.before_upload, None
            callback(path)
        key = path.casefold()
        if revision is not None:
            if key not in self.files or self.files[key][1] != revision:
                raise FileExistsError()
        elif not overwrite and key in self.files:
            raise FileExistsError()
        self.revision += 1
        payload = source.read() if hasattr(source, "read") else Path(source).read_bytes()
        self.files[key] = (payload, str(self.revision))

    def download(self, path, destination):
        if self.fail:
            raise TimeoutError("private path")
        try:
            payload, revision = self.files[path.casefold()]
        except KeyError:
            raise FileNotFoundError() from None
        destination.write(payload)
        if self.after_download:
            callback, self.after_download = self.after_download, None
            callback(path)
        return SimpleNamespace(rev=revision)

    def tasks(self, folder="Команда_пароль"):
        return self.json(f"{SHARED_ROOT}/{folder}/tasks.json")

    def json(self, path):
        return json.loads(decrypt_bytes(self.files[path.casefold()][0]))

    def put_json(self, path, value):
        self.upload(io.BytesIO(encrypt_bytes(json.dumps(value).encode("utf-8"))), path, overwrite=True)


class SharedGroupTests(unittest.TestCase):
    web = True

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.disk = MemoryDisk()
        self.clients = 0
        self.owner, self.cloud = self.make_client()
        self.group_id = self.owner.create_group("Команда")
        self.task_id = self.owner.saveB("Первое дело", self.group_id)

    def make_client(self, directory=None, store=None):
        self.clients += 1
        root = Path(directory or Path(self.directory.name) / str(self.clients))
        root.mkdir(parents=True, exist_ok=True)
        page = Mock(_nd_timezone="Europe/Moscow")
        store = store or WebSessionStore(page)
        cloud = Cloud.__new__(Cloud)
        cloud.web = self.web
        cloud.web_store = store if self.web else None
        cloud.data_dir = root
        cloud.user_data_dir = root / "user_data"
        cloud.user_data_dir.mkdir(exist_ok=True)
        cloud.user_data = cloud.user_data_dir / "user_data.txt"
        cloud.user_data.touch(exist_ok=True)
        cloud._sync_lock = threading.RLock()
        cloud._upload_cv = threading.Condition()
        cloud._last_synced_versions = {}
        cloud._last_synced_versions_lock = threading.Lock()
        cloud._account_encryption = {}
        cloud._upload_state_callback = None
        cloud.disk = self.disk
        cloud.connect = True
        cloud.request_upload = Mock()
        if self.web:
            back = Backend(page=page, web_store=store, cloud=cloud)
        else:
            if not (root / "groups.json").exists():
                save_all_sections(root, empty_data())
            back = Backend.__new__(Backend)
            back.web = False
            back.page = page
            back.data_dir = root
            back.cloud = cloud
            back._undo_state = None
            back.on_undo_change = back.on_data_change = None
        return back, cloud

    def share_and_join(self):
        self.owner.make_group_shared(self.group_id, "пароль")
        member, cloud = self.make_client()
        member_group = member.connect_shared_group("Команда", "пароль")
        return member, cloud, member_group

    def test_creation_stores_membership_and_only_ordinary_tasks(self):
        repeat_id = self.owner.saveB("Из расписания", self.group_id, is_repeat=True)
        data = self.owner._load()
        data["postponed"].append({"id": "later", "group": self.group_id})
        data["repeat_tasks"].append({"id": "rule", "group": self.group_id})
        self.owner._save(data)
        self.owner.make_group_shared(self.group_id, "пароль")
        self.assertEqual(list(self.disk.files), [f"{SHARED_ROOT}/Команда_пароль/tasks.json".casefold()])
        tasks = self.disk.tasks()
        self.assertEqual([t["id"] for t in tasks], [self.task_id])
        self.assertNotIn("group", tasks[0])
        self.assertTrue(any(t["id"] == repeat_id for t in self.owner.read_tasks()))
        self.assertEqual(self.owner._load()["postponed"], data["postponed"])
        membership = next(g for g in self.owner._load()["groups"] if g["id"] == self.group_id)
        self.assertEqual(membership["shared_group"], {"name": "Команда", "password": "пароль"})
        self.assertFalse(self.owner.can_undo())
        self.cloud.request_upload.assert_called_with("")

    def test_connect_maps_tasks_to_local_id_and_rejects_wrong_password_and_duplicate(self):
        member, _, member_group = self.share_and_join()
        self.assertNotEqual(member_group, self.group_id)
        self.assertEqual(member.read_tasks()[0]["group"], member_group)
        self.assertEqual(member.read_tasks()[0]["id"], self.task_id)
        self.assertFalse(member.can_undo())
        before = member._load()
        for name, password in (("Команда", "неверно"), ("команда", "пароль")):
            with self.subTest(name=name, password=password), self.assertRaises(ValueError):
                member.connect_shared_group(name, password)
            self.assertEqual(member._load(), before)

    def test_shared_groups_cannot_be_renamed_by_creator_or_member(self):
        for group_type in ("tasks", "notes"):
            with self.subTest(group_type=group_type):
                name = f"Группа {group_type}"
                group_id = self.owner.create_group(name, group_type=group_type)
                self.assertTrue(self.owner.rename_group(group_id, name + " новая"))
                self.owner.make_group_shared(group_id, "пароль")
                member, _ = self.make_client()
                member_id = member.connect_shared_group(name + " новая", "пароль")
                for back, ident in ((self.owner, group_id), (member, member_id)):
                    before = back._load()
                    with patch.object(back, "_save") as save:
                        self.assertFalse(back.rename_group(ident, "Другое название"))
                    save.assert_not_called()
                    self.assertEqual(back._load(), before)

    def test_updates_additions_and_deletions_propagate_both_directions(self):
        member, cloud, member_group = self.share_and_join()
        member.redact_statusB(self.task_id, True)
        second_id = member.saveB("Второе дело", member_group)
        cloud.sync_shared_groups()
        self.cloud.sync_shared_groups()
        self.assertTrue(self.owner.get_task(self.task_id)["status"])
        self.assertEqual(self.owner.get_task(second_id)["group"], self.group_id)
        self.owner.kill_taskB(self.task_id)
        self.cloud.sync_shared_groups()
        cloud.sync_shared_groups()
        self.assertIsNone(member.get_task(self.task_id))
        self.assertEqual([t["id"] for t in self.disk.tasks()], [second_id])

    def test_concurrent_edits_merge_fields_and_independent_tasks(self):
        member, cloud, member_group = self.share_and_join()
        self.owner.redact_taskB(self.task_id, "Новое название")
        self.owner.saveB("От владельца", self.group_id)
        member.redact_statusB(self.task_id, True)
        member.saveB("От участника", member_group)
        self.cloud.sync_shared_groups()
        cloud.sync_shared_groups()
        self.cloud.sync_shared_groups()
        self.assertEqual(self.owner.get_task(self.task_id)["name"], "Новое название")
        self.assertTrue(self.owner.get_task(self.task_id)["status"])
        self.assertEqual({t["name"] for t in self.disk.tasks()},
                         {"Новое название", "От владельца", "От участника"})

    def test_revision_conflict_retries_using_new_remote_snapshot(self):
        self.owner.make_group_shared(self.group_id, "пароль")
        self.owner.redact_statusB(self.task_id, True)

        def race(path):
            remote = self.disk.tasks()
            remote.append({"id": "other", "name": "Конкурентное дело"})
            self.disk.put_json(path, remote)

        self.disk.before_upload = race
        self.cloud.sync_shared_groups()
        self.assertEqual(len(self.disk.tasks()), 2)
        self.assertTrue(self.owner.get_task(self.task_id)["status"])
        self.assertIsNotNone(self.owner.get_task("other"))

    def test_edits_during_transfer_are_preserved_for_next_sync(self):
        self.owner.make_group_shared(self.group_id, "пароль")
        self.owner.redact_taskB(self.task_id, "Перед передачей")
        self.disk.after_download = lambda _: self.owner.redact_taskB(self.task_id, "Во время передачи")
        self.cloud.sync_shared_groups()
        self.assertEqual(self.owner.get_task(self.task_id)["name"], "Во время передачи")
        self.assertEqual(self.disk.tasks()[0]["name"], "Перед передачей")
        self.cloud.sync_shared_groups()
        self.assertEqual(self.disk.tasks()[0]["name"], "Во время передачи")

    def test_failed_transfer_and_restart_keep_offline_deletions(self):
        self.owner.make_group_shared(self.group_id, "пароль")
        self.owner.kill_taskB(self.task_id)
        self.owner.saveB("Офлайн", self.group_id)
        self.disk.fail = True
        self.cloud.sync_shared_groups()
        self.assertEqual(len(self.disk.tasks()), 1)
        self.disk.fail = False
        restarted, cloud = self.make_client(directory=self.cloud.data_dir, store=self.cloud.web_store)
        cloud.sync_shared_groups()
        self.assertIsNone(restarted.get_task(self.task_id))
        self.assertEqual([t["name"] for t in self.disk.tasks()], ["Офлайн"])

    def test_reconnect_and_delete_group_never_delete_remote_tasks(self):
        member, cloud, member_group = self.share_and_join()
        member.delete_group(member_group)
        cloud.sync_shared_groups()
        self.assertEqual(len(self.disk.tasks()), 1)
        new_id = member.connect_shared_group("Команда", "пароль")
        self.assertEqual(member.get_task(self.task_id)["group"], new_id)

    def test_creation_validation_and_upload_failure_do_not_mark_group_as_shared(self):
        with self.assertRaises(ValueError):
            self.owner.make_group_shared(self.group_id, "../bad")
        with self.assertRaises(ValueError):
            self.owner.make_group_shared("missing", "пароль")
        self.disk.fail = True
        with self.assertRaises(TimeoutError):
            self.owner.make_group_shared(self.group_id, "пароль")
        self.assertFalse(next(g for g in self.owner.get_groups() if g["id"] == self.group_id)["is_shared"])
        self.disk.fail = False
        self.owner.make_group_shared(self.group_id, "пароль")
        self.assertTrue(next(g for g in self.owner.get_groups() if g["id"] == self.group_id)["is_shared"])

    def test_existing_group_cannot_be_overwritten_by_another_creator(self):
        self.owner.make_group_shared(self.group_id, "пароль")
        member, _ = self.make_client()
        group = member.create_group("Команда")
        member.saveB("Не должно затереть", group)
        with self.assertRaises(ValueError):
            member.make_group_shared(group, "пароль")
        self.assertEqual([t["name"] for t in self.disk.tasks()], ["Первое дело"])

    def test_account_upload_excludes_shared_tasks_and_refresh_restores_shared_data(self):
        self.cloud.write_user_data_text("account~~login~~password")
        self.owner.make_group_shared(self.group_id, "пароль")
        repeat_id = self.owner.saveB("Личное повторение", self.group_id, is_repeat=True)
        personal_id = self.owner.saveB("Личное дело")
        self.cloud.upload("account", force=True)
        personal = self.disk.json("/For_to-do/account/tasks.json")
        self.assertEqual({t["id"] for t in personal}, {personal_id, repeat_id})
        self.assertTrue(self.cloud.download("account", preserve_local=True))
        self.assertIsNotNone(self.owner.get_task(self.task_id))
        new_device, new_cloud = self.make_client()
        self.assertTrue(new_cloud.download("account"))
        new_cloud.write_user_data_text("account~~login~~password")
        new_cloud.sync_shared_groups()
        self.assertEqual(new_device.get_task(self.task_id)["name"], "Первое дело")
        self.assertEqual(new_device._load()["groups"], self.owner._load()["groups"])

    def test_explicit_login_resets_old_baseline_without_deleting_shared_tasks(self):
        self.cloud.write_user_data_text("account~~login~~password")
        self.owner.make_group_shared(self.group_id, "пароль")
        self.cloud.upload("account", force=True)
        # A later login has an empty local shared-task cache after replacing
        # account data, but still remembers this account's previous baseline.
        self.cloud.write_user_data_text("")
        self.assertTrue(self.cloud.download("account"))
        self.cloud.write_user_data_text("account~~login~~password")
        self.cloud.sync_shared_groups()
        self.assertEqual(len(self.disk.tasks()), 1)
        self.assertIsNotNone(self.owner.get_task(self.task_id))

    def test_guest_startup_fetches_shared_data(self):
        member, cloud, _ = self.share_and_join()
        self.owner.redact_taskB(self.task_id, "С другого устройства")
        self.cloud.sync_shared_groups()
        cloud.alg_for_start_app()
        self.assertEqual(member.get_task(self.task_id)["name"], "С другого устройства")


class NativeSharedGroupTests(SharedGroupTests):
    web = False


class SharedGroupUITests(unittest.TestCase):
    def test_menu_supports_tasks_and_notes_and_shows_membership_icon(self):
        front = make_front()
        front._open_share_group_dialog = Mock()
        group = front.back.create_group("Команда")
        notes = front.back.create_group("Заметки", group_type="notes")
        rows = ft.Column()
        for item in front.back.get_groups():
            front._append_group_row(rows, item, Mock())
        for row, item in zip(rows.controls, front.back.get_groups()):
            labels = [i.content for i in row.controls[1].items]
            self.assertIn("Сделать группу общей", labels)
            self.assertIn("Редактировать", labels)
        data = front.back._load()
        for item in data["groups"]:
            item["shared_group"] = {"name": item["name"], "password": "пароль"}
        front.back._save(data)
        rows.controls.clear()
        for item in front.back.get_groups():
            front._append_group_row(rows, item, Mock())
            button, menu = rows.controls[-1].controls
            self.assertIn(ft.Icons.LINK_ROUNDED, [c.icon for c in button.content.controls if isinstance(c, ft.Icon)])
            self.assertNotIn("Сделать группу общей", [i.content for i in menu.items])
            self.assertNotIn("Редактировать", [i.content for i in menu.items])
            if item["id"] != "default":
                self.assertIn("Отключить", [i.content for i in menu.items])

    def test_password_form_handles_errors_and_success_without_exposing_password(self):
        front = make_front()
        front.open_modified_dialog = Mock()
        front.show_groups = Mock()
        front.back.make_group_shared = Mock(side_effect=ValueError("Введите пароль"))
        group = front.back.get_groups()[0]
        front._open_share_group_dialog(group)
        _, content, _ = front.open_modified_dialog.call_args.args
        controls = content.content.controls
        warning = next(c for c in controls if isinstance(c, ft.Text) and "нельзя редактировать" in (c.value or ""))
        password = next(c for c in controls if isinstance(c, ft.TextField))
        create = controls[-2].controls[0]
        self.assertTrue(password.password)
        password.value = "пароль"
        asyncio.run(create.on_click(None))
        self.assertEqual(controls[2].value, "Введите пароль")
        self.assertIn("название изменить не получится", warning.value)
        self.assertFalse(create.disabled)
        front.show_groups.assert_not_called()
        front.back.make_group_shared.side_effect = None
        asyncio.run(password.on_submit(None))
        front.back.make_group_shared.assert_called_with(group["id"], "пароль")
        front.show_groups.assert_called_once()
        self.assertEqual(password.value, "")

    def test_share_dialog_copies_exact_group_name_and_handles_clipboard_failure(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.page.services = []
                front.open_modified_dialog = Mock()
                group = {"id": "test", "name": "Команда с длинным названием " * 8}
                front._open_share_group_dialog(group)
                controls = front.open_modified_dialog.call_args.args[1].content.controls
                name, copy = controls[0].controls
                self.assertEqual(name.value, group["name"])
                self.assertTrue(name.selectable)
                with patch.object(ft.Clipboard, "set", new_callable=AsyncMock) as clipboard_set:
                    asyncio.run(copy.on_click(None))
                    clipboard_set.assert_awaited_once_with(group["name"])
                    self.assertEqual(front.page.services, [front._group_name_clipboard])
                    self.assertIn("скопировано", controls[4].value)
                    clipboard_set.side_effect = RuntimeError("Clipboard unavailable")
                    asyncio.run(copy.on_click(None))
                    self.assertIn("Не удалось скопировать", controls[4].value)
                    self.assertTrue(controls[4].visible)
                    self.assertEqual(len(front.page.services), 1)

    def test_authorization_tile_lists_memberships_and_updates_after_join(self):
        front = make_front()
        front.back.connect_shared_group = Mock(side_effect=ValueError("Группа не найдена"))
        tile = front.utils.build_shared_groups_tile(front.page)
        self.assertIsInstance(tile, ft.ExpansionTile)
        memberships, name, password, actions, status = tile.controls[0].controls
        name.value, password.value = "Команда", "пароль"
        self.assertTrue(password.password)
        asyncio.run(actions.controls[0].on_click(None))
        self.assertEqual(status.value, "Группа не найдена")
        self.assertEqual(password.value, "пароль")
        self.assertFalse(actions.controls[0].disabled)

        def join(*_):
            data = front.back._load()
            data["groups"].append({"id": "shared", "name": "Команда",
                                   "shared_group": {"name": "Команда", "password": "пароль"}})
            front.back._save(data)

        front.back.connect_shared_group.side_effect = join
        asyncio.run(password.on_submit(None))
        self.assertEqual(memberships.controls[0].controls[1].value, "Команда")
        self.assertEqual(password.value, "")
        self.assertIn("подключена", status.value)
        front.utils.cloud.read_user_data.return_value = {"Start text": "", "Login": "", "Password": ""}
        widgets = front.utils.build_widgets_for_login(front.page, Mock(), Mock())
        self.assertTrue(any(isinstance(c, ft.ExpansionTile) and c.title.controls[1].value.strip() == "Общие группы"
                            for c in widgets["Main_cont"].content.controls))


if __name__ == "__main__":
    unittest.main()
