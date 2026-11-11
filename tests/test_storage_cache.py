"""Проверки инвалидации кэша, независимости снимков и совместимости режимов."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from Backend import crypto, storage
from Backend.cloud import Cloud
from Backend.core import Backend
from Backend.extended import Backend2
from Backend.webstorage import WebSessionStore


@pytest.fixture
def back(tmp_path):
    """Создаёт нативное хранилище без запуска облака и обращения к cwd."""
    backend = Backend.__new__(Backend)
    backend.web = False
    backend.phone = False
    backend.page = None
    backend.data_dir = tmp_path / "data"
    backend.cloud = Mock()
    backend.cloud.check_user_data.return_value = False
    backend._undo_state = None
    backend.on_undo_change = None
    backend.on_data_change = None
    data = storage.empty_data()
    data["tasks"] = [{
        "id": "local", "name": "Исходное дело", "group": "default",
        "status": False, "created_date": "10-11-2026", "attachments": [],
    }]
    storage.save_all_sections(backend.data_dir, data, force=True)
    storage.save_all_sections(backend.data_dir, backend._load())
    return backend


@pytest.fixture
def cloud(tmp_path):
    """Создаёт только файловый фасад авторизации, без сети и воркера."""
    instance = Cloud.__new__(Cloud)
    instance.web = False
    instance.user_data = tmp_path / "user_data" / "user_data.txt"
    instance._upload_cv = threading.Condition()
    instance._pending_login_password = None
    instance.connect = True
    instance.write_user_data_text("account~~login~~password")
    return instance


@pytest.mark.parametrize("key", storage.SECTION_FILENAMES)
@pytest.mark.parametrize("encrypted", (False, True))
def test_external_section_write_invalidates_only_changed_section(back, key, encrypted):
    records = [{"id": "remote", "name": "Изменено внешней записью"}]
    if key == "groups":
        records[0]["id"] = "default"
    path = back.data_dir / storage.SECTION_FILENAMES[key]
    plain = json.dumps(records, ensure_ascii=False).encode("utf-8")
    path.write_bytes(crypto.encrypt_bytes(plain) if encrypted else plain)
    with patch("Backend.storage.decrypt_bytes", wraps=crypto.decrypt_bytes) as decrypt:
        assert back._load()[key][0]["name"] == records[0]["name"]
        assert decrypt.call_count == 1
        back._load()
        assert decrypt.call_count == 1


def test_size_change_is_detected_even_with_unchanged_mtime(back):
    path = back.data_dir / "tasks.json"
    before = path.stat()
    crypto.write_text(path, '[{"id":"remote","name":"Новое"}]')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert back.get_task("remote")["name"] == "Новое"


def test_deleted_and_recreated_section_does_not_reuse_old_snapshot(back):
    path = back.data_dir / "tasks.json"
    path.unlink()
    assert back.read_tasks() == []
    crypto.write_text(path, '[{"id":"new","name":"После удаления"}]')
    assert back.get_task("local") is None
    assert back.read_name("new") == "После удаления"


def test_external_replacement_during_read_does_not_poison_new_signature(back):
    path = back.data_dir / "tasks.json"
    storage._SECTION_CACHE.clear()
    original_read = Path.read_bytes
    replaced = False

    def read_and_replace(target):
        nonlocal replaced
        raw = original_read(target)
        if target == path and not replaced:
            replaced = True
            crypto.write_text(path, '[{"id":"remote","name":"Замена во время чтения"}]')
        return raw

    with patch.object(Path, "read_bytes", read_and_replace):
        back._load()
    assert back.read_name("remote") == "Замена во время чтения"
    assert back.get_task("local") is None


def test_loaded_and_returned_nested_data_cannot_change_cache(back):
    data = back._load()
    data["tasks"][0]["attachments"] = [{"name": "Файл.txt", "details": {"value": 1}}]
    back._save(data)
    expected = back._load()
    # Сохранённый кэш также не должен ссылаться на словарь, переданный в _save.
    data["tasks"][0]["attachments"][0]["details"]["value"] = 2
    for result in (back._load()["tasks"], back.read_tasks(), [back.get_task("local")]):
        result[0]["name"] = "Несохранённое изменение"
        result[0]["attachments"][0]["details"]["value"] = 3
    assert back._load() == expected


def test_reading_one_task_does_not_copy_all_sections(back):
    with patch("Backend.storage.deepcopy", wraps=deepcopy) as copy_sections, \
            patch("Backend.core.deepcopy", wraps=deepcopy) as copy_record, \
            patch("Backend.storage.decrypt_bytes", wraps=crypto.decrypt_bytes) as decrypt:
        assert back.read_name("local") == "Исходное дело"
        assert back.read_id("Исходное дело") == "local"
        assert back.read_created_date("local") == "10-11-2026"
        assert back.get_quantity_strings() == 1
        assert back.get_task("local")["id"] == "local"
        copy_sections.assert_not_called()
        decrypt.assert_not_called()
        assert copy_record.call_count == 1


def test_unchanged_save_preserves_files_and_undo(back):
    original = back._load()
    back.saveB("Добавленное дело")
    undo = back._undo_state
    paths = [back.data_dir / name for name in storage.SECTION_FILENAMES.values()]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    back.on_data_change = Mock()
    back.on_undo_change = Mock()
    with patch("Backend.storage.write_text", wraps=crypto.write_text) as write:
        back._save(back._load())
        write.assert_not_called()
    assert back._undo_state is undo
    back.on_data_change.assert_not_called()
    back.on_undo_change.assert_not_called()
    assert before == [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    assert back.undo_last_action()
    assert back._load() == original


def test_storage_comparison_does_not_read_warm_unchanged_files(back):
    data = back._load()
    with patch.object(Path, "read_bytes", side_effect=AssertionError("Повторное чтение секции")), \
            patch("Backend.storage.write_text", side_effect=AssertionError("Лишняя запись")):
        assert storage.save_all_sections(back.data_dir, data) == set()


def test_compact_external_json_is_still_rewritten_to_existing_format(back):
    path = back.data_dir / "tasks.json"
    tasks = back.read_tasks()
    crypto.write_text(path, json.dumps(tasks, ensure_ascii=False))
    data = back._load()
    assert storage.save_all_sections(back.data_dir, data) == {"tasks"}
    assert crypto.read_text(path) == json.dumps(tasks, ensure_ascii=False, indent=2) + "\n"
    assert storage.save_all_sections(back.data_dir, data) == set()


def test_same_values_with_different_key_order_still_count_as_changed(back):
    data = back._load()
    data["tasks"][0] = dict(reversed(list(data["tasks"][0].items())))
    assert storage.save_all_sections(back.data_dir, data) == {"tasks"}
    assert storage.save_all_sections(back.data_dir, data) == set()


def test_encryption_switch_and_new_writes_work_without_restart(back):
    expected = back._load()
    for enabled in (False, True, False, True):
        storage.set_data_encryption(back.data_dir, enabled)
        assert crypto.data_encryption_enabled(back.data_dir) is enabled
        assert back._load() == expected
        assert crypto.is_encrypted((back.data_dir / "tasks.json").read_bytes()) is enabled
        task_id = back.saveB("После смены шифрования")
        assert back.get_task(task_id) is not None
        assert back.undo_last_action()
        assert back._load() == expected
        assert storage.save_all_sections(back.data_dir, expected) == set()


def test_security_cache_detects_external_write_deletion_and_invalid_setting(tmp_path):
    path = tmp_path / "security.json"
    assert crypto.data_encryption_enabled(tmp_path) is True
    path.write_text('{"encryption_enabled": false}', encoding="utf-8")
    assert crypto.data_encryption_enabled(tmp_path) is False
    with patch.object(Path, "read_text", side_effect=AssertionError("Повторное чтение security.json")):
        assert crypto.data_encryption_enabled(tmp_path) is False
    path.write_text('{"encryption_enabled": "False"}', encoding="utf-8")
    with pytest.raises(ValueError, match="настройка шифрования"):
        crypto.data_encryption_enabled(tmp_path)
    path.unlink()
    assert crypto.data_encryption_enabled(tmp_path) is True


def test_security_change_invalidates_plaintext_section_snapshot(back):
    storage.set_data_encryption(back.data_dir, False)
    back._load()
    (back.data_dir / "security.json").write_text('{"encryption_enabled": true}', encoding="utf-8")
    assert back.read_name("local") == "Исходное дело"
    assert crypto.is_encrypted((back.data_dir / "tasks.json").read_bytes())


def test_overwriting_wrong_encryption_format_preserves_previous_error_behavior(back):
    path = back.data_dir / "tasks.json"
    broken = crypto.encrypt_bytes(b"[]")[:-16]
    path.write_bytes(broken)
    with pytest.raises(crypto.EncryptedFileError):
        back.read_tasks()
    # При другом целевом формате прежний save_section тоже не расшифровывал файл.
    (back.data_dir / "security.json").write_text('{"encryption_enabled": false}', encoding="utf-8")
    assert storage.save_section(back.data_dir, "tasks", [])
    assert back.read_tasks() == []


def test_undo_restores_history_and_external_write_disables_old_undo(back):
    original = back._load()
    back.redact_statusB("local", True)
    assert back._load()["achievements"][0]["task_id"] == "local"
    assert back.undo_last_action()
    assert back._load() == original
    back.redact_statusB("local", True)
    remote = back._load()
    remote["tasks"][0]["name"] = "Дело из облака"
    crypto.write_text(back.data_dir / "tasks.json", json.dumps(remote["tasks"], ensure_ascii=False))
    assert not back.can_undo()
    assert not back.undo_last_action()
    assert back.read_name("local") == "Дело из облака"


def test_replace_import_delete_and_migration_are_visible_to_warm_cache(back):
    archive = back.export_data_archive()
    replacement = back._load()
    replacement["tasks"][0]["name"] = "Замена снимка"
    storage.replace_all_sections(back.data_dir, replacement)
    assert back.read_name("local") == "Замена снимка"
    back.import_data_archive(archive)
    assert back.read_name("local") == "Исходное дело"
    back.delete_all()
    assert back.read_tasks() == []
    legacy = back.data_dir / "itog.json"
    storage.save_data(legacy, replacement)
    for name in storage.SECTION_FILENAMES.values():
        (back.data_dir / name).unlink()
    storage.ensure_split_storage(back.data_dir, legacy)
    assert back.read_name("local") == "Замена снимка"


def test_failed_import_rolls_back_files_without_leaving_cached_partial_snapshot(back):
    from Backend.data_archive import create_data_archive

    back.saveB("Дело с доступной отменой")
    expected = back._load()
    replacement = back._load()
    replacement["groups"][0]["name"] = "Незавершённый импорт"
    save = storage.save_all_sections

    def fail_after_first_section(directory, data, force=False):
        save(directory, {"groups": data["groups"]}, force=True)
        raise OSError("Сбой записи во время импорта")

    with patch("Backend.storage.save_all_sections", side_effect=fail_after_first_section):
        with pytest.raises(OSError):
            back.import_data_archive(create_data_archive(replacement))
    assert back._load() == expected
    assert back.undo_last_action()
    assert len(back.read_tasks()) == 1


def test_backend2_and_shared_groups_share_invalidation(back):
    extended = Backend2.__new__(Backend2)
    extended.web = False
    extended.back = back
    extended.data_dir = back.data_dir
    shared = Cloud.__new__(Cloud)
    shared.web = False
    shared.data_dir = back.data_dir
    data = extended._load()
    data["tasks"][0]["name"] = "Через Backend2"
    extended._save(data)
    assert back.read_name("local") == "Через Backend2"
    data = shared._shared_load()
    data["tasks"][0]["name"] = "Через общие группы"
    shared._shared_save(data)
    assert back.read_name("local") == "Через общие группы"
    assert extended._load() == back._load()


def test_parallel_readers_and_main_thread_writes_see_complete_snapshots(back):
    started = threading.Barrier(3)
    finished = threading.Event()

    def read():
        started.wait(timeout=10)
        reads = 0
        while not finished.is_set() or reads < 10:
            data = back._load()
            completed = data["tasks"][0]["status"]
            recorded = any(item["task_id"] == "local" for item in data["achievements"])
            assert completed == recorded
            assert back.get_task("local")["name"] == "Исходное дело"
            reads += 1
        return reads

    with ThreadPoolExecutor(max_workers=2) as executor:
        readers = [executor.submit(read) for _ in range(2)]
        try:
            started.wait(timeout=10)
            for index in range(30):
                back.redact_statusB("local", index % 2 == 0)
        finally:
            finished.set()
        assert all(reader.result(timeout=10) >= 10 for reader in readers)


def test_authentication_cache_tracks_external_write_and_logout(cloud):
    assert cloud.check_user_data()
    with patch("Backend.cloud.read_encrypted_text", side_effect=AssertionError("Повторная расшифровка user_data")):
        assert cloud.check_user_data()
        assert cloud.read_user_data_text() == "account~~login~~password"
    crypto.write_text(cloud.user_data, "remote~~другой~~пароль")
    assert cloud.read_user_data_text() == "remote~~другой~~пароль"
    with patch.object(cloud, "_restore_local_backup_to_active"):
        cloud.leave_from_account()
    assert not cloud.check_user_data()
    cloud.write_user_data_text("new~~login~~password")
    assert cloud.check_user_data()
    assert cloud.read_user_data_text() == "new~~login~~password"


def test_explicit_authentication_write_invalidates_even_if_signature_is_restored(cloud):
    assert cloud.check_user_data()
    before = cloud.user_data.stat()
    cloud.write_user_data_text("account~~other~~password")
    os.utime(cloud.user_data, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert cloud.user_data.stat().st_size == before.st_size
    assert cloud.read_user_data_text() == "account~~other~~password"


def test_web_mode_keeps_session_store_and_avoids_file_cache():
    page = Mock(_nd_timezone="Europe/Moscow")
    store = WebSessionStore(page)
    cloud = Cloud.__new__(Cloud)
    cloud.web = True
    cloud.web_store = store
    cloud._upload_cv = threading.Condition()
    back = Backend(page=page, web_store=store, cloud=cloud)
    with patch("Backend.storage.file_signature", side_effect=AssertionError("Файловый кэш в web")), \
            patch("Backend.cloud.file_signature", side_effect=AssertionError("Файлы авторизации в web")):
        task_id = back.saveB("В браузере")
        back.redact_statusB(task_id, True)
        assert back.undo_last_action()
        assert back.get_task(task_id)["status"] is False
        data = back._load()
        data["tasks"][0]["name"] = "Из облака в браузер"
        store.replace_from_cloud(data)
        assert back.read_name(task_id) == "Из облака в браузер"
        cloud.write_user_data_text("web~~login~~password")
        assert cloud.check_user_data()
        store.write_meta_text("user_data", "")
        assert not cloud.check_user_data()


def test_android_storage_path_and_backend2_use_the_same_cache(tmp_path, monkeypatch):
    directory = tmp_path / "android-data"
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(directory))
    guest = Mock()
    guest.check_user_data.return_value = False
    backend = Backend(cloud=guest)
    extended = Backend2(back=backend, cloud=guest)
    assert backend.phone is True
    assert backend.data_dir == directory
    task_id = backend.saveB("На телефоне")
    assert extended._load()["tasks"][0]["id"] == task_id
    data = extended._load()
    data["tasks"][0]["name"] = "После изменения на телефоне"
    extended._save(data)
    assert backend.read_name(task_id) == "После изменения на телефоне"
