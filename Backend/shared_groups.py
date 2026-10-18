"""Shared tasks and notes; membership and display settings belong to each client."""

import io
import json
from copy import deepcopy
from uuid import uuid4

from .crypto import decrypt_bytes, encrypt_bytes, read_text, write_text
from .storage import load_all_sections, save_all_sections

SHARED_ROOT = "/For_to-do/Shared-Groups"


def shared_folder(name, password):
    for value, label in ((name, "название группы"), (password, "пароль")):
        if (not isinstance(value, str) or not value.strip() or value in (".", "..")
                or value != value.strip() or value.endswith(".")
                or any(c in '/\\:*?"<>|' or ord(c) < 32 for c in value)):
            raise ValueError(f"Проверьте поле «{label}»: оно не должно быть пустым, содержать "
                             "символы / \\ : * ? \" < > |, пробелы по краям или точку в конце.")
    folder = f"{name}_{password}"
    if len(folder.encode("utf-8")) > 255:
        raise ValueError("Название группы и пароль слишком длинные.")
    return folder


def shared_identity(group):
    membership = group.get("shared_group")
    if group.get("type", "tasks") not in ("tasks", "notes") or not isinstance(membership, dict):
        return None
    return shared_folder(membership.get("name"), membership.get("password"))


def ordinary_tasks(data, group_id):
    return [deepcopy({k: v for k, v in task.items() if k != "group"})
            for task in data["tasks"]
            if task.get("group", "default") == group_id and not task.get("is_repeat")]


def personal_tasks(data):
    shared_ids = {g["id"] for g in data["groups"] if g.get("shared_group")}
    return [t for t in data["tasks"]
            if t.get("group", "default") not in shared_ids or t.get("is_repeat")]


def personal_groups(groups):
    """Shared notes belong to the shared file, never to an account snapshot."""
    result = deepcopy(groups)
    for group in result:
        if group.get("shared_group") and group.get("type") == "notes":
            group["notes"] = []
    return result


def shared_items(data, group):
    if group.get("type") == "notes":
        current = next((g for g in data["groups"] if g.get("id") == group["id"]), {})
        return deepcopy(current.get("notes", []))
    return ordinary_tasks(data, group["id"])


def replace_shared_items(data, group, items):
    if group.get("type") == "notes":
        current = next(g for g in data["groups"] if g.get("id") == group["id"])
        current["notes"] = deepcopy(items)
    else:
        replace_ordinary_tasks(data, group["id"], items)


def shared_payload(items, group_type):
    # Keep the existing file path and task-list format. A typed envelope makes
    # notes (including empty groups) distinguishable and creation atomic.
    value = {"type": "notes", "notes": items} if group_type == "notes" else items
    return encrypt_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def merge_tasks(baseline, local, remote):
    """Apply local changes by ID/field while retaining unrelated remote edits."""
    old = {t["id"]: t for t in baseline}
    current = {t["id"]: t for t in local}
    merged = {t["id"]: deepcopy(t) for t in remote}
    for ident in old.keys() - current.keys():
        merged.pop(ident, None)
    for ident, task in current.items():
        previous = old.get(ident)
        if task == previous:
            continue
        if previous is None or ident not in merged:
            merged[ident] = deepcopy(task)
            continue
        for key in previous.keys() | task.keys():
            if key not in task:
                merged[ident].pop(key, None)
            elif key not in previous or task[key] != previous[key]:
                merged[ident][key] = deepcopy(task[key])
    return list(merged.values())


def replace_ordinary_tasks(data, group_id, tasks):
    data["tasks"] = [t for t in data["tasks"]
                     if t.get("group", "default") != group_id or t.get("is_repeat")]
    data["tasks"].extend({**deepcopy(t), "group": group_id} for t in tasks)


class SharedGroupsMixin:
    def _shared_load(self):
        return (self.web_store.load_all_sections() if self.web
                else load_all_sections(self.data_dir))

    def _shared_save(self, data):
        if self.web:
            self.web_store.save_all_sections(data)
        else:
            save_all_sections(self.data_dir, data)

    def _shared_cache(self):
        if self.web:
            raw = self.web_store.read_meta_text("shared_groups_sync")
        else:
            path = self.user_data_dir / "shared_groups_sync.json"
            raw = read_text(path, encoding="utf-8") if path.exists() else ""
        return json.loads(raw) if raw else {}

    def _shared_cache_key(self, folder, account=None):
        scope = account if account is not None else self.read_user_data_text().split("~~")[0].strip()
        scope = scope or "guest"
        return self._fingerprint(f"{scope.casefold()}:{folder.casefold()}".encode("utf-8"))

    def _shared_mark_synced(self, folder, tasks, account=None):
        cache = self._shared_cache()
        cache[self._shared_cache_key(folder, account)] = tasks
        text = json.dumps(cache, ensure_ascii=False)
        if self.web:
            self.web_store.write_meta_text("shared_groups_sync", text)
        else:
            self.user_data_dir.mkdir(parents=True, exist_ok=True)
            write_text(self.user_data_dir / "shared_groups_sync.json", text, encoding="utf-8")

    def _shared_download(self, folder):
        target = io.BytesIO()
        metadata = self.disk.download(self.cloud_path(SHARED_ROOT, folder, "tasks.json"), target)
        value = json.loads(decrypt_bytes(target.getvalue()).decode("utf-8"))
        group_type = "tasks"
        if isinstance(value, dict) and value.get("type") == "notes":
            group_type = "notes"
            value = value.get("notes")
        text_field = "text" if group_type == "notes" else "name"
        if (not isinstance(value, list)
                or any(not isinstance(t, dict) or not isinstance(t.get("id"), str)
                       or not t["id"] or not isinstance(t.get(text_field), str)
                       or t.get("is_repeat") for t in value)
                or len({t["id"] for t in value}) != len(value)):
            raise ValueError("Некорректный файл записей общей группы.")
        tasks = [{k: v for k, v in task.items() if k != "group"} for task in value]
        return tasks, metadata.rev, group_type

    def make_group_shared(self, group_id, password):
        with self._sync_lock:
            with self.file_lock():
                data = self._shared_load()
                group = next((g for g in data["groups"] if g.get("id") == group_id), None)
                if group is None or group.get("type", "tasks") not in ("tasks", "notes"):
                    raise ValueError("Группа дел или заметок не найдена.")
                if group.get("shared_group"):
                    raise ValueError("Эта группа уже общая.")
                name = group["name"]
                folder = shared_folder(name, password)
                tasks = shared_items(data, group)
            self.create_folder_on_cloud("/For_to-do")
            self.create_folder_on_cloud(SHARED_ROOT)
            path = self.cloud_path(SHARED_ROOT, folder, "tasks.json")
            try:
                self.disk.mkdir(self.cloud_path(SHARED_ROOT, folder))
            except FileExistsError:
                # An interrupted creation may have left an empty directory.
                if self.disk.exists(path):
                    raise ValueError("Такая общая группа уже существует. Подключите её в авторизации.") from None
            payload = shared_payload(tasks, group.get("type", "tasks"))
            try:
                self.disk.upload(io.BytesIO(payload), path)
            except FileExistsError:
                raise ValueError("Такая общая группа уже существует. Подключите её в авторизации.") from None
            with self.file_lock():
                latest = self._shared_load()
                current = next((g for g in latest["groups"] if g.get("id") == group_id), None)
                if current is None:
                    raise ValueError("Группа была удалена во время создания подключения.")
                current["shared_group"] = {"name": name, "password": password}
                self._shared_mark_synced(folder, tasks)
                self._shared_save(latest)
            self.alg_for_redact()
            return group_id

    def connect_shared_group(self, name, password):
        name = name.strip() if isinstance(name, str) else name
        folder = shared_folder(name, password)
        with self._sync_lock:
            with self.file_lock():
                for group in self._shared_load()["groups"]:
                    identity = shared_identity(group)
                    if identity and identity.casefold() == folder.casefold():
                        raise ValueError("Вы уже подключены к этой общей группе.")
            try:
                tasks, _, group_type = self._shared_download(folder)
            except FileNotFoundError:
                raise ValueError("Группа не найдена. Проверьте название и пароль.") from None
            with self.file_lock():
                data = self._shared_load()
                group_id = uuid4().hex
                group = {
                    "id": group_id, "name": name, "type": group_type,
                    "shared_group": {"name": name, "password": password},
                }
                data["groups"].append(group)
                replace_shared_items(data, group, tasks)
                self._shared_mark_synced(folder, tasks)
                self._shared_save(data)
            self.alg_for_redact()
            return group_id

    def sync_shared_groups(self):
        """Sync each membership independently; failed transfers keep local edits."""
        changed = False
        with self._sync_lock:
            with self.file_lock():
                groups = self._shared_load()["groups"]
            for group in groups:
                if not group.get("shared_group"):
                    continue
                try:
                    changed = self._sync_shared_group(group) or changed
                except Exception as exc:
                    # Provider errors may contain a folder name with a password.
                    print(f"Не удалось синхронизировать общую группу: {type(exc).__name__}")
        return changed

    def _sync_shared_group(self, group):
        folder = shared_identity(group)
        if folder is None:
            return False
        with self.file_lock():
            local = shared_items(self._shared_load(), group)
            baseline = self._shared_cache().get(self._shared_cache_key(folder), [])
        for attempt in range(5):
            remote, revision, group_type = self._shared_download(folder)
            if group_type != group.get("type", "tasks"):
                raise ValueError("Тип общей группы изменился. Подключите группу заново.")
            merged = merge_tasks(baseline, local, remote)
            if merged != remote:
                if not revision:
                    raise ValueError("Dropbox не вернул версию файла общей группы.")
                payload = shared_payload(merged, group_type)
                try:
                    self.disk.upload(io.BytesIO(payload), self.cloud_path(SHARED_ROOT, folder, "tasks.json"),
                                     revision=revision)
                except FileExistsError:
                    if attempt < 4:
                        continue
                    raise
            with self.file_lock():
                data = self._shared_load()
                current = next((g for g in data["groups"] if g.get("id") == group["id"]), None)
                if current is None or shared_identity(current) != folder:
                    return False
                # Preserve edits made while the request was in flight.
                latest = shared_items(data, current)
                applied = merge_tasks(local, latest, merged)
                replace_shared_items(data, current, applied)
                self._shared_save(data)
                self._shared_mark_synced(folder, merged)
            return applied != local

    def _shared_account_snapshot(self, result, previous, preserve_local, account):
        """Account snapshots own memberships, but never shared tasks or notes."""
        if "tasks" not in result and "groups" not in result:
            return
        groups = personal_groups(result.get("groups", previous["groups"]))
        result["groups"] = groups
        snapshot = {"tasks": result.get("tasks", previous["tasks"]), "groups": groups}
        result["tasks"] = personal_tasks(snapshot)
        if not preserve_local:
            # Explicit login discards the previous account's local cache. Its
            # absence must never be interpreted as a user's task deletions.
            for group in groups:
                if group.get("shared_group"):
                    self._shared_mark_synced(shared_identity(group), [], account=account)
        if preserve_local:
            old_groups = {g["id"]: g for g in previous["groups"]}
            for group in groups:
                if not group.get("shared_group"):
                    continue
                old = old_groups.get(group["id"])
                if old and shared_identity(old) == shared_identity(group):
                    replace_shared_items(result, group, shared_items(previous, old))
