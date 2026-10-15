"""Скачать всё дерево /For_to-do из MEGA без запуска приложения."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile
from datetime import datetime


CLOUD_ROOT = "/For_to-do"
PROJECT_ROOT = Path(__file__).resolve().parent
MANIFEST_NAME = "_cloud_download_manifest.json"


def local_child(parent, name):
    """Преобразует облачные имена в безопасные и уникальные локальные имена."""
    if not isinstance(name, str) or not name:
        raise ValueError("В облаке найдено пустое имя ресурса.")
    is_reserved = getattr(os.path, "isreserved", None)
    encoded = "".join(
        "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))
        if char in '/\\<>:"|?*%~' or ord(char) < 32 else char
        for char in name
    )
    while encoded.endswith((".", " ")):
        encoded = encoded[:-1] + ("%2E" if encoded[-1] == "." else "%20")
    if name in (".", ".."):
        encoded = name.replace(".", "%2E")
    reserved = is_reserved(encoded) if is_reserved else PureWindowsPath(encoded).is_reserved()
    if reserved:
        encoded = "_" + encoded
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    if len(encoded) > 100 or encoded.casefold() == MANIFEST_NAME.casefold():
        encoded = encoded[:80] + "~" + digest
    # Проверяем регистр даже на файловых системах, различающих его.
    used = {child.name.casefold() for child in parent.iterdir()}
    target = parent / encoded
    if encoded.casefold() in used:
        encoded += "~" + digest
        target = parent / encoded
        index = 1
        while target.name.casefold() in used:
            target = parent / f"{encoded}~{index}"
            index += 1
    return target


def download_file(disk, cloud_path, target, resource):
    """Незавершённый файл не получает имя готовой копии."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".download-", suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
        disk.download(cloud_path, str(temporary))
        size = getattr(resource, "size", None)
        if size is not None and temporary.stat().st_size != size:
            raise ValueError("Размер скачанного файла отличается от размера в облаке.")
        expected_hash = getattr(resource, "sha256", None)
        if expected_hash:
            with temporary.open("rb") as stream:
                actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual_hash.lower() != expected_hash.lower():
                raise ValueError("Контрольная сумма скачанного файла не совпадает.")
        # Имя должно оставаться свободным и после сетевого запроса.
        if target.exists() or target.is_symlink():
            raise ValueError("Во время скачивания локальное имя файла оказалось занято.")
        temporary.rename(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download_tree(disk, output, report=print):
    """Обходит дерево MEGA и сохраняет даже пустые каталоги."""
    root = disk.get_meta(CLOUD_ROOT)
    if root.type != "dir":
        raise ValueError("/For_to-do в облаке должен быть папкой.")
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Папка назначения должна быть пустой.")
    pending = [(CLOUD_ROOT, output)]
    files = folders = total_bytes = 0
    manifest = {"cloud_root": CLOUD_ROOT, "complete": False, "entries": []}
    try:
        while pending:
            cloud_dir, local_dir = pending.pop()
            for resource in disk.listdir(cloud_dir):
                target = local_child(local_dir, resource.name)
                cloud_path = cloud_dir + "/" + resource.name
                entry = {"cloud_path": cloud_path,
                         "local_path": target.relative_to(output).as_posix(),
                         "type": resource.type, "downloaded": False}
                manifest["entries"].append(entry)
                if resource.type == "dir":
                    target.mkdir()
                    folders += 1
                    pending.append((cloud_path, target))
                elif resource.type == "file":
                    download_file(disk, cloud_path, target, resource)
                    files += 1
                    total_bytes += target.stat().st_size
                    # Имена каталогов аккаунтов могут содержать пароли.
                    report(f"Скачано файлов: {files}; байт: {total_bytes}")
                else:
                    raise ValueError("В облаке найден неизвестный тип ресурса.")
                entry["downloaded"] = True
        manifest["complete"] = True
    finally:
        (output / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return files, folders, total_bytes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        help="Пустая папка назначения (по умолчанию cloud_downloads/For_to-do_<дата>).",
    )
    args = parser.parse_args(argv)
    output = args.output if args.output is not None else (
        PROJECT_ROOT / "cloud_downloads" / datetime.now().strftime("For_to-do_%Y-%m-%d_%H-%M-%S_%f")
    )
    try:
        try:
            from Backend.mega_disk import MegaDisk, load_mega_credentials
        except ModuleNotFoundError as exc:
            if exc.name not in ("mega", "Crypto", "httpx"):
                raise
            raise ValueError('Установите зависимость: python -m pip install "mega.py-v2==2.1.0"') from exc
        load_mega_credentials()
        print("Скачивание /For_to-do/ из MEGA…")
        with MegaDisk() as disk:
            files, folders, total_bytes = download_tree(disk, output)
    except KeyboardInterrupt:
        print("Скачивание прервано. Копия неполная.", file=sys.stderr)
        return 130
    except Exception as exc:
        # Текст сетевых исключений может содержать приватные пути или URL.
        message = str(exc) if type(exc) is ValueError else type(exc).__name__
        print(f"Скачивание не завершено: {message}", file=sys.stderr)
        print("Если файлы уже скачаны, копия неполная. Для повтора выберите новую пустую папку.",
              file=sys.stderr)
        return 1
    print(f"Готово: {files} файлов, {folders} папок, {total_bytes} байт.")
    print(f"Сохранено в: {output.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
