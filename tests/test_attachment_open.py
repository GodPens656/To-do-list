"""External apps receive the selected attachment, with its original bytes."""

import asyncio
from copy import deepcopy
import ctypes
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.attachments import make_attachment
from Backend.file_open import _OpenAsInfo, open_windows_file
from Frontend.attachments import attachment_controls, open_attachment
from test_attachments import image_file
from test_ui_state import make_front


class AttachmentOpenTests(unittest.TestCase):
    def front(self, platform=ft.PagePlatform.WINDOWS, *, web=False, phone=False):
        front = make_front(phone=phone)
        front.page.web = web
        front.page.platform = platform
        front.page.services = []
        return front

    def run_button(self, front, button):
        button.on_click(None)
        callback, *args = front.page.run_task.call_args.args
        asyncio.run(callback(*args))

    def test_only_non_images_offer_external_open_on_both_layouts(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = self.front(phone=phone)
                files = [image_file(), make_attachment("report.pdf", b"pdf"),
                         make_attachment("not-a-photo.png", b"document")]
                controls = attachment_controls(front.libs, files, on_remove=Mock())
                for index, row in enumerate(controls.controls[:-1]):
                    buttons = row.controls[-1].controls
                    opens = [b for b in buttons if b.icon == ft.Icons.OPEN_IN_NEW_ROUNDED]
                    self.assertEqual(len(opens), 0 if index == 0 else 1)
                    self.assertTrue(any(b.icon == ft.Icons.DOWNLOAD_ROUNDED for b in buttons))
                    self.assertTrue(any(b.icon == ft.Icons.CLOSE_ROUNDED for b in buttons))
                    if opens:
                        self.assertEqual(opens[0].tooltip, "Открыть в другом приложении")

    def test_windows_opens_each_selected_file_off_ui_thread_without_changing_attachment(self):
        front = self.front()
        files = [make_attachment("план проекта.txt", b"first original"),
                 make_attachment("archive.zip", b"second original")]
        original = deepcopy(files)
        controls = attachment_controls(front.libs, files)
        ui_thread = threading.get_ident()
        opened = []

        def open_file(path):
            path = Path(path)
            opened.append((path.name, path.read_bytes(), threading.get_ident()))

        with tempfile.TemporaryDirectory() as directory, \
                patch("Backend.clipboard._export_directory", Mock(name=directory)) as cache, \
                patch("Frontend.attachments.open_windows_file", side_effect=open_file):
            cache.name = directory
            for row in controls.controls[:-1]:
                button = next(b for b in row.controls[-1].controls
                              if b.icon == ft.Icons.OPEN_IN_NEW_ROUNDED)
                self.run_button(front, button)
        self.assertEqual([(name, data) for name, data, _ in opened],
                         [("план проекта.txt", b"first original"), ("archive.zip", b"second original")])
        self.assertTrue(all(thread != ui_thread for _, _, thread in opened))
        self.assertEqual(files, original)
        front.page.show_dialog.assert_not_called()

    def test_mobile_share_uses_original_bytes_filename_and_mime_and_reuses_service(self):
        for platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS, ft.PagePlatform.MACOS):
            with self.subTest(platform=platform):
                front = self.front(platform, phone=platform.is_mobile())
                for name, mime in (("отчёт.pdf", "application/pdf"),
                                   ("data.unknown-extension", "application/octet-stream")):
                    file = make_attachment(name, b"unchanged bytes")
                    with patch.object(ft.Share, "share_files", new=AsyncMock()) as share:
                        asyncio.run(open_attachment(front.libs, file))
                    exported = share.call_args.args[0][0]
                    self.assertEqual(exported.data, b"unchanged bytes")
                    self.assertEqual(exported.name, name)
                    self.assertEqual(exported.mime_type, mime)
                    self.assertIsNone(exported.path)
                self.assertEqual(len(front.page.services), 1)
                self.assertIsInstance(front.page.services[0], ft.Share)

    def test_browser_offers_download_without_invoking_server_applications(self):
        front = self.front(web=True)
        file = make_attachment("report.pdf", b"original bytes")
        controls = attachment_controls(front.libs, [file])
        button = next(b for b in controls.controls[0].controls[-1].controls
                      if b.icon == ft.Icons.OPEN_IN_NEW_ROUNDED)
        with patch("Frontend.attachments.open_attachment", new=AsyncMock()) as native:
            self.run_button(front, button)
            native.assert_not_called()
        dialog = front.page.show_dialog.call_args.args[0]
        self.assertIn("Открыть с помощью", dialog.content.value)
        with patch.object(ft.FilePicker, "save_file", new=AsyncMock(return_value=None)) as save:
            asyncio.run(dialog.actions[0].on_click(None))
        front.page.pop_dialog.assert_called_once()
        self.assertEqual(save.call_args.kwargs["file_name"], "report.pdf")
        self.assertEqual(save.call_args.kwargs["src_bytes"], b"original bytes")

    def test_external_open_failure_is_shown_in_dialog(self):
        front = self.front()
        front.libs.open_dialog = Mock()
        file = make_attachment("report.pdf", b"original")
        controls = attachment_controls(front.libs, [file])
        button = next(b for b in controls.controls[0].controls[-1].controls
                      if b.icon == ft.Icons.OPEN_IN_NEW_ROUNDED)
        with patch("Frontend.attachments.open_attachment", new=AsyncMock(side_effect=OSError("No app"))):
            self.run_button(front, button)
        front.libs.open_dialog.assert_called_once_with("Не удалось открыть файл", "No app", front.page)


class WindowsOpenWithTests(unittest.TestCase):
    def test_chooser_uses_unicode_path_and_execute_flag_and_allows_cancel(self):
        for result in (0, -2147023673, -2147467260):  # success, ERROR_CANCELLED, E_ABORT
            with self.subTest(result=result):
                ole, shell = Mock(), Mock()
                ole.CoInitializeEx.return_value = 0

                def choose(parent, pointer):
                    info = ctypes.cast(pointer, ctypes.POINTER(_OpenAsInfo)).contents
                    self.assertEqual(info.file, "C:/cache/отчёт проекта.pdf")
                    self.assertIsNone(info.file_class)
                    self.assertEqual(info.flags, 4)
                    return result

                shell.SHOpenWithDialog.side_effect = choose
                with patch("Backend.file_open.ctypes.WinDLL", side_effect=[ole, shell], create=True):
                    open_windows_file("C:/cache/отчёт проекта.pdf")
                ole.CoUninitialize.assert_called_once()

    def test_native_error_is_reported_and_com_is_released(self):
        ole, shell = Mock(), Mock()
        ole.CoInitializeEx.return_value = 0
        shell.SHOpenWithDialog.return_value = -2147467259  # E_FAIL
        with patch("Backend.file_open.ctypes.WinDLL", side_effect=[ole, shell], create=True):
            with self.assertRaises(OSError):
                open_windows_file("C:/cache/file.pdf")
        ole.CoUninitialize.assert_called_once()


if __name__ == "__main__":
    unittest.main()
