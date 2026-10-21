import asyncio
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
from PIL import Image

from Backend.attachments import attachment_bytes, image_preview, make_attachment
from Backend.clipboard import clipboard_image_png, windows_clipboard_formats
from Frontend.attachments import AttachmentEditor, attachment_controls, copy_attachment
from test_ui_state import make_front


def picture(size=(30, 40)):
    content = BytesIO()
    Image.new("RGB", size, "red").save(content, "PNG")
    return make_attachment("фото.png", content.getvalue())


class ClipboardAttachmentTests(unittest.TestCase):
    def front(self, web=True, phone=False):
        front = make_front(phone=phone)
        front.page.services = []
        front.page.web = web
        front.page.platform = ft.PagePlatform.WINDOWS if not web else ft.PagePlatform.LINUX
        return front

    def test_desktop_actions_are_under_filename_and_mobile_actions_stay_in_row(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = self.front(phone=phone)
                files = attachment_controls(front.libs, [picture()])
                row = files.controls[0]
                self.assertIsInstance(row, ft.Row if phone else ft.Column)
                self.assertEqual(row.controls[0].value, "фото.png")
                self.assertEqual([b.icon for b in row.controls[1].controls], [
                    ft.Icons.VISIBILITY_OUTLINED, ft.Icons.DOWNLOAD_ROUNDED, ft.Icons.COPY_ROUNDED,
                ])

    def test_paste_browser_image_and_empty_text_clipboard_preserves_draft(self):
        front = self.front()
        editor = AttachmentEditor(front.libs, back=front.back)
        image = picture()
        with patch.object(ft.Clipboard, "get_image", new=AsyncMock(return_value=attachment_bytes(image))):
            asyncio.run(editor.paste(None))
        self.assertTrue(editor.values()[0]["is_image"])
        self.assertEqual(attachment_bytes(editor.values()[0]), attachment_bytes(image))
        before = editor.values()
        with patch.object(ft.Clipboard, "get_image", new=AsyncMock(return_value=None)):
            asyncio.run(editor.paste(None, quiet=True))
            self.assertFalse(editor.error.visible)
            asyncio.run(editor.paste(None))
        self.assertIn("нет файлов", editor.error.value)
        self.assertEqual(editor.values(), before)
        self.assertFalse(editor.paste_button.disabled)
        self.assertEqual(len(front.page.services), 1)

    def test_native_files_and_screenshot_can_be_pasted_without_picker(self):
        front = self.front(web=False)
        editor = AttachmentEditor(front.libs)
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / "первый.txt", Path(directory) / "второй.bin"]
            for path in paths:
                path.write_bytes(path.name.encode())
            with patch.object(ft.Clipboard, "get_files", new=AsyncMock(return_value=list(map(str, paths)))), \
                    patch.object(ft.FilePicker, "pick_files", new=AsyncMock()) as picker:
                asyncio.run(editor.paste(None))
            picker.assert_not_called()
            self.assertEqual([a["name"] for a in editor.values()], [p.name for p in paths])
            self.assertEqual([attachment_bytes(a) for a in editor.values()], [p.read_bytes() for p in paths])
        with patch.object(ft.Clipboard, "get_files", new=AsyncMock(return_value=[])), \
                patch("Frontend.attachments.desktop_clipboard_image", return_value=attachment_bytes(picture())):
            asyncio.run(editor.paste(None))
        self.assertTrue(editor.values()[-1]["is_image"])

    def test_invalid_batch_and_quota_errors_preserve_files(self):
        front = self.front(web=False)
        existing = make_attachment("first.txt", b"first")
        editor = AttachmentEditor(front.libs, [existing], back=front.back)
        with tempfile.TemporaryDirectory() as directory:
            small, large = Path(directory) / "small.txt", Path(directory) / "large.txt"
            small.write_bytes(b"1")
            large.write_bytes(b"123456")
            with patch.object(ft.Clipboard, "get_files", new=AsyncMock(return_value=[str(small), str(large)])), \
                    patch("Frontend.attachments.MAX_FILE_BYTES", 5), \
                    patch("Frontend.attachments.Path.open") as read:
                asyncio.run(editor.paste(None))
                read.assert_not_called()
            self.assertEqual(editor.values(), [existing])
            self.assertTrue(editor.error.visible)
            with patch.object(ft.Clipboard, "get_files", new=AsyncMock(return_value=[directory])):
                asyncio.run(editor.paste(None))
            self.assertIn("не папки", editor.error.value)
            front.back.validate_attachment_selection = Mock(side_effect=ValueError("Лимит аккаунта"))
            with patch.object(ft.Clipboard, "get_files", new=AsyncMock(return_value=[str(small)])):
                asyncio.run(editor.paste(None))
            self.assertEqual(editor.error.value, "Лимит аккаунта")
            self.assertEqual(editor.values(), [existing])
            self.assertFalse(editor.add.disabled)

    def test_copy_native_files_publishes_real_bytes_and_reports_failure(self):
        front = self.front(web=False)
        file = make_attachment("данные.bin", b"original data")
        with tempfile.TemporaryDirectory() as directory, \
                patch("Backend.clipboard._export_directory", Mock(name=directory)) as cache:
            cache.name = directory
            with patch.object(ft.Clipboard, "set_files", new=AsyncMock(return_value=True)) as put:
                asyncio.run(copy_attachment(front.libs, file))
                path = Path(put.call_args.args[0][0])
                self.assertEqual(path.name, "данные.bin")
                self.assertEqual(path.read_bytes(), b"original data")
            with patch.object(ft.Clipboard, "set_files", new=AsyncMock(return_value=False)):
                with self.assertRaisesRegex(RuntimeError, "Не удалось скопировать"):
                    asyncio.run(copy_attachment(front.libs, file))

    def test_copy_images_to_browser_preserves_resolution_and_windows_offers_file_and_image(self):
        front = self.front()
        image = picture((1800, 2400))
        with patch.object(ft.Clipboard, "set_image", new=AsyncMock()) as put:
            asyncio.run(copy_attachment(front.libs, image))
        with Image.open(BytesIO(put.call_args.args[0])) as copied:
            self.assertEqual(copied.size, (1800, 2400))
        front.page.web = False
        front.page.platform = ft.PagePlatform.WINDOWS
        with patch("Frontend.attachments.clipboard_export_path", return_value="C:/temp/фото.png"), \
                patch("Frontend.attachments.copy_windows_image") as put:
            asyncio.run(copy_attachment(front.libs, image))
        put.assert_called_once_with(image, "C:/temp/фото.png")
        formats = dict(windows_clipboard_formats(image, "C:/temp/фото.png"))
        self.assertEqual(struct.unpack("<IiiII", formats[15][:20]), (20, 0, 0, 0, 1))
        self.assertEqual(formats[15][20:].decode("utf-16-le"), "C:/temp/фото.png\0\0")
        with Image.open(BytesIO(formats["PNG"])) as copied:
            self.assertEqual(copied.size, (1800, 2400))
        self.assertEqual(struct.unpack("<ii", formats[8][4:12]), (1800, 2400))

    def test_preview_rotates_90_degrees_without_changing_attachment(self):
        front = self.front()
        image = picture()
        original = deepcopy(image)
        controls = attachment_controls(front.libs, [image])
        controls.controls[0].controls[-1].controls[0].on_click(None)
        dialog = front.page.show_dialog.call_args.args[0]
        preview = dialog.content.content.controls[0].content
        rotate = dialog.actions[0]
        for size in ((40, 30), (30, 40), (40, 30), (30, 40)):
            asyncio.run(rotate.on_click(None))
            with Image.open(BytesIO(preview.src)) as rendered:
                self.assertEqual(rendered.size, size)
        self.assertEqual(image, original)
        self.assertFalse(rotate.disabled)
        # Clipboard confirmation is visible inside the image dialog.
        with patch("Frontend.attachments.copy_attachment", new=AsyncMock()):
            dialog.actions[1].on_click(None)
            call = front.page.run_task.call_args.args
            asyncio.run(call[0](*call[1:]))
        self.assertTrue(dialog.content.content.controls[1].visible)

    def test_keyboard_pastes_only_into_editor_on_current_screen(self):
        front = self.front()
        front._set_screen(front.main_cont, reset=True)
        front.button_add_task.on_click(None)
        front.page.run_task.reset_mock()
        front.exit_from_pc(Mock(key="V", ctrl=True, meta=False, alt=False))
        callback, _ = front.page.run_task.call_args.args
        self.assertIsInstance(callback.__self__, AttachmentEditor)
        self.assertTrue(front.page.run_task.call_args.kwargs["quiet"])
        front.close_page()
        front.page.run_task.reset_mock()
        front.exit_from_pc(Mock(key="V", ctrl=True, meta=False, alt=False))
        front.page.run_task.assert_not_called()

    def test_image_preview_respects_exif_orientation(self):
        content = BytesIO()
        image = Image.new("RGB", (30, 40), "red")
        exif = image.getexif()
        exif[274] = 6
        image.save(content, "JPEG", exif=exif)
        attachment = make_attachment("фото.jpg", content.getvalue())
        for png in (image_preview(attachment), clipboard_image_png(attachment)):
            with Image.open(BytesIO(png)) as rendered:
                self.assertEqual(rendered.size, (40, 30))


if __name__ == "__main__":
    unittest.main()
