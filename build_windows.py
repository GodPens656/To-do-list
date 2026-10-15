"""Сборка Windows-приложения с собственной иконкой через PyInstaller."""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path


HIDDEN_IMPORTS = (
    "mega.hashcash",
    "plyer.platforms",
    "plyer.platforms.win",
    "plyer.platforms.win.notification",
    # Имя пакета в pip — flet-desktop, имя Python-модуля — flet_desktop.
    "flet_desktop",
)


def verify_desktop_bundle(executable, runtime_files, onefile=False):
    """Не допускает выдачу сборки без встроенного клиента Flet."""
    executable = Path(executable)
    if not executable.is_file():
        raise RuntimeError(f"Не найден собранный файл: {executable}")
    prefix = "flet_desktop/app/"
    if onefile:
        from PyInstaller.archive.readers import CArchiveReader

        archive = CArchiveReader(str(executable))
        included = {name.replace("\\", "/") for name in archive.toc}
        missing = [name for name in runtime_files if prefix + name not in included]
    else:
        runtime_dir = executable.parent / "_internal" / "flet_desktop" / "app"
        missing = [name for name in runtime_files if not (runtime_dir / name).is_file()]
    if missing:
        raise RuntimeError(
            "В сборке отсутствуют файлы клиента Flet: " + ", ".join(missing[:5])
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onefile", action="store_true", help="Один .exe вместо папки")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Сборку .exe необходимо выполнять в Windows.")

    try:
        from PyInstaller.__main__ import run
        from flet_cli.__pyinstaller import config as hook_config
        from flet_cli.__pyinstaller.win_utils import update_flet_view_icon
        from flet_desktop import get_package_bin_dir
    except ImportError as error:
        parser.error(
            f"Не найдены зависимости сборки: {error}. "
            "Установите их: python -m pip install flet-cli flet-desktop pyinstaller pillow"
        )

    root = Path(__file__).resolve().parent
    icon = root / "assets" / "dnevnik.ico"
    if not icon.is_file() or icon.read_bytes()[:4] != b"\x00\x00\x01\x00":
        parser.error(f"Не найден корректный Windows ICO: {icon}")
    client_dir = Path(get_package_bin_dir())
    if not (client_dir / "flet" / "flet.exe").is_file():
        parser.error("Не найден Windows-клиент Flet. Установите flet-desktop.")

    # Повторяем замену иконки встроенного клиента из flet pack.
    # Меняем только копию: установленный flet-desktop не затрагивается.
    previous_cwd = Path.cwd()
    previous_bin_dir = hook_config.temp_bin_dir
    executable = root / "dist" / ("Dnevnik.exe" if args.onefile else "Dnevnik/Dnevnik.exe")
    with tempfile.TemporaryDirectory(prefix="dnevnik-build-") as temporary:
        copied_client = Path(temporary) / "app"
        shutil.copytree(client_dir, copied_client)
        try:
            os.chdir(root)
            update_flet_view_icon(str(copied_client / "flet" / "flet.exe"), str(icon))
            hook_config.temp_bin_dir = str(copied_client)
            runtime_files = [
                path.relative_to(copied_client).as_posix()
                for path in copied_client.rglob("*") if path.is_file()
            ]
            run([
                str(root / "main.py"),
                "--name=Dnevnik",
                "--windowed",
                "--onefile" if args.onefile else "--onedir",
                "--noconfirm",
                "--clean",
                *(f"--hidden-import={module}" for module in HIDDEN_IMPORTS),
                f"--icon={icon}",
                f"--add-data={root / 'assets'}{os.pathsep}assets",
                # Не полагаемся только на автоматически найденный hook-flet.
                f"--add-data={copied_client}{os.pathsep}flet_desktop/app",
                f"--distpath={root / 'dist'}",
                f"--workpath={root / 'build' / 'pyinstaller'}",
                f"--specpath={root / 'build'}",
            ])
            verify_desktop_bundle(executable, runtime_files, onefile=args.onefile)
        finally:
            hook_config.temp_bin_dir = previous_bin_dir
            os.chdir(previous_cwd)

    print(f"Build complete: {executable}")


if __name__ == "__main__":
    main()
