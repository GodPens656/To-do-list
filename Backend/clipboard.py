"""Native clipboard images and temporary files for pasting attachments elsewhere."""

import ctypes
from ctypes import wintypes
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
import tempfile
import threading
import re

from PIL import Image, ImageGrab, ImageOps

from .attachments import attachment_bytes, attachment_name


_export_directory = None
_export_lock = threading.Lock()


def clipboard_export_path(attachment):
    """Keep exported files alive until the app closes, so deferred paste works."""
    global _export_directory
    content = attachment_bytes(attachment)
    with _export_lock:
        if _export_directory is None:
            _export_directory = tempfile.TemporaryDirectory(prefix="todo-clipboard-")
        folder = Path(_export_directory.name) / sha256(content).hexdigest()
        folder.mkdir(exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*]', "_", attachment_name(attachment.get("name"))).rstrip(" .")
        if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            name = "_" + name
        path = folder / (name[:200] or "file")
        path.write_bytes(content)
    return str(path)


def desktop_clipboard_image():
    """Read screenshot/bitmap data without treating clipboard text as a path."""
    image = ImageGrab.grabclipboard()
    if not isinstance(image, Image.Image):
        return None
    with image:
        result = BytesIO()
        image.save(result, format="PNG")
        return result.getvalue()


def clipboard_image_png(attachment):
    with Image.open(BytesIO(attachment_bytes(attachment))) as image:
        image = ImageOps.exif_transpose(image)
        result = BytesIO()
        image.convert("RGBA").save(result, format="PNG")
        return result.getvalue()


def windows_clipboard_formats(attachment, path):
    """Offer both a file (Explorer) and image formats (editors and messengers)."""
    with Image.open(BytesIO(attachment_bytes(attachment))) as original:
        image = ImageOps.exif_transpose(original)
        png, bmp = BytesIO(), BytesIO()
        image.convert("RGBA").save(png, format="PNG")
        image.convert("RGB").save(bmp, format="BMP")
    # DROPFILES followed by a double-NUL-terminated Unicode filename list.
    files = struct.pack("<IiiII", 20, 0, 0, 0, 1) + (str(path) + "\0\0").encode("utf-16-le")
    return [(15, files), ("PNG", png.getvalue()), (8, bmp.getvalue()[14:])]


def copy_windows_image(attachment, path):
    """Publish eager HGLOBAL formats, transferring their ownership to Windows."""
    formats = windows_clipboard_formats(attachment, path)
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    user.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = wintypes.LPVOID
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.restype = wintypes.HGLOBAL
    handles = []
    window = None
    opened = False
    try:
        # Allocate before opening/clearing, so preparation errors preserve the clipboard.
        for kind, data in formats:
            kind = user.RegisterClipboardFormatW(kind) if isinstance(kind, str) else kind
            if not kind:
                raise ctypes.WinError(ctypes.get_last_error())
            handle = kernel.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append([kind, handle])
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                ctypes.memmove(pointer, data, len(data))
            finally:
                kernel.GlobalUnlock(handle)
        # A hidden owner window avoids OpenClipboard(NULL)/EmptyClipboard ownership issues.
        window = user.CreateWindowExW(0, "STATIC", "To-do clipboard", 0,
                                      0, 0, 0, 0, None, None, None, None)
        if not window or not user.OpenClipboard(window):
            raise OSError("Буфер обмена занят. Повторите копирование.")
        opened = True
        if not user.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        for entry in handles:
            if not user.SetClipboardData(*entry):
                raise ctypes.WinError(ctypes.get_last_error())
            entry[1] = None  # Windows now owns this allocation.
    finally:
        if opened:
            user.CloseClipboard()
        if window:
            user.DestroyWindow(window)
        for _, handle in handles:
            if handle:
                kernel.GlobalFree(handle)
