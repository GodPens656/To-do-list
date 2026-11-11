"""Open exported attachments with desktop applications."""

import ctypes
from ctypes import wintypes
import subprocess


class _OpenAsInfo(ctypes.Structure):
    _fields_ = [
        ("file", wintypes.LPCWSTR),
        ("file_class", wintypes.LPCWSTR),
        ("flags", wintypes.DWORD),
    ]


def open_windows_file(path):
    """Show Open With, without changing the user's default application."""
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    if initialized < 0:
        raise OSError(f"Не удалось открыть выбор приложения (0x{initialized & 0xFFFFFFFF:08X}).")
    try:
        shell = ctypes.WinDLL("shell32")
        shell.SHOpenWithDialog.argtypes = [wintypes.HWND, ctypes.POINTER(_OpenAsInfo)]
        shell.SHOpenWithDialog.restype = ctypes.c_long
        info = _OpenAsInfo(str(path), None, 0x00000004)  # OAIF_EXEC
        result = shell.SHOpenWithDialog(None, ctypes.byref(info))
        # Cancelling the chooser is a normal outcome.
        if result < 0 and (result & 0xFFFFFFFF) not in (0x800704C7, 0x80004004):
            raise OSError(f"Не удалось открыть файл (0x{result & 0xFFFFFFFF:08X}).")
    finally:
        ole.CoUninitialize()


def open_linux_file(path):
    try:
        subprocess.run(["xdg-open", str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as error:
        raise RuntimeError("Не найдено приложение для этого типа файла.") from error
