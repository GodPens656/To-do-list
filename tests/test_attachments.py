import asyncio
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
from PIL import Image

from Backend.attachments import (
    MAX_ACCOUNT_BYTES, AttachmentQuotaError, attachment_bytes, attachment_usage,
    image_preview, make_attachment,
)
from Backend.core import Backend
from Backend.crypto import is_encrypted
from Backend.storage import set_data_encryption
from Backend.webstorage import WebSessionStore
from Frontend.attachments import AttachmentEditor, attachment_controls
from test_ui_state import make_front


def image_file():
    content = BytesIO()
    Image.new("RGB", (12, 8), "blue").save(content, format="TIFF")
    return make_attachment("картинка.tiff", content.getvalue())


def editor_on_screen(front):
    body = front.screen_stack[-1].content.controls[0]
    controls = body.content.content.controls[1].content.controls
    return next(c for c in controls if isinstance(c, ft.Column)
                and c.controls and isinstance(c.controls[0], ft.TextButton)
                and c.controls[0].content == "Прикрепить файлы")


class AttachmentTests(unittest.TestCase):
    def test_account_quota_counts_all_sections_and_actual_bytes_even_offline(self):
        self.assertEqual(MAX_ACCOUNT_BYTES, 10 * 1024 * 1024)
        front = make_front()
        front.cloud.check_user_data.return_value = True
        front.cloud.connect = False
        group = front.back.create_group("Другая группа")
        with patch("Backend.attachments.MAX_ACCOUNT_BYTES", 10):
            first = make_attachment("first.txt", b"1234")
            first["size"] = 0  # Quota must not trust the declared size.
            front.back.saveB("Normal", group, attachments=[first])
            front.back2.create_repeat_task("Repeat", metadata={
                "attachments": [make_attachment("repeat.txt", b"123")],
            })
            front.back2.create_postponed_task("Postponed", "01-01-2030", metadata={
                "attachments": [make_attachment("postponed.txt", b"123")],
            })
            self.assertEqual(attachment_usage(front.back._load()), 10)
            before = front.back._load()
            undo = front.back._undo_state
            with self.assertRaises(AttachmentQuotaError):
                front.back.saveB("Too much", attachments=[make_attachment("one.txt", b"1")])
            self.assertEqual(front.back._load(), before)
            self.assertEqual(front.back._undo_state, undo)

    def test_guest_has_no_account_quota_and_existing_oversized_account_can_shrink(self):
        front = make_front()
        front.cloud.check_user_data.return_value = False
        with patch("Backend.attachments.MAX_ACCOUNT_BYTES", 10):
            ids = [front.back.saveB(str(i), attachments=[make_attachment(str(i), b"12345678")])
                   for i in range(2)]
            self.assertEqual(attachment_usage(front.back._load()), 16)
            front.cloud.check_user_data.return_value = True
            front.back.redact_taskB(ids[0], "Renamed")
            front.back.redact_statusB(ids[0], True)
            front.back.kill_taskB(ids[1])
            front.back.saveB("Fits", attachments=[make_attachment("two.txt", b"12")])
            self.assertEqual(attachment_usage(front.back._load()), 10)
            with self.assertRaises(AttachmentQuotaError):
                front.back.saveB("Exceeds", attachments=[make_attachment("one.txt", b"1")])

    def test_drafts_credit_replaced_files_and_template_references_count_once(self):
        front = make_front()
        front.page.services = []
        front.cloud.check_user_data.return_value = True
        with patch("Backend.attachments.MAX_ACCOUNT_BYTES", 10):
            old = make_attachment("old.txt", b"12345678")
            task_id = front.back.saveB("Original", attachments=[old])
            editor = AttachmentEditor(front.libs, [old], back=front.back, task_id=task_id)
            self.assertTrue(editor.limit.visible)
            editor.remove(editor.attachments[0])
            replacement = SimpleNamespace(name="new.txt", bytes=b"0123456789", size=10, path=None)
            with patch.object(ft.FilePicker, "pick_files", new=AsyncMock(return_value=[replacement])):
                asyncio.run(editor.pick(None))
            self.assertFalse(editor.error.visible)
            self.assertEqual(len(editor.values()), 1)
            front.back.redact_taskB(task_id, "Replaced", {"attachments": editor.values()})
            shared = editor.values()
            front.back2.create_repeat_task("Repeat", metadata={"attachments": shared})
            data = front.back._load()
            data["repeat_tasks"][0]["last_date"] = "01-01-2000"
            front.back._save(data)
            front.check_and_add_repeat_task()
            self.assertEqual(attachment_usage(front.back._load()), 10)

            extra = SimpleNamespace(name="extra.txt", bytes=b"1", size=1, path=None)
            with patch.object(ft.FilePicker, "pick_files", new=AsyncMock(return_value=[extra])):
                asyncio.run(editor.pick(None))
            self.assertTrue(editor.error.visible)
            self.assertIn("10 МБ", editor.error.value)
            self.assertEqual(editor.values(), shared)

    def test_quota_rechecked_at_save_and_failed_form_is_preserved(self):
        for special in (None, "repeat", "postponed"):
            with self.subTest(special=special):
                front = make_front()
                front.page.services = []
                front.cloud.check_user_data.return_value = True
                front._set_screen(front.main_cont, reset=True)
                with patch("Backend.attachments.MAX_ACCOUNT_BYTES", 10):
                    if special == "repeat":
                        front.open_repeat_dialog()
                    elif special == "postponed":
                        front.open_postponed_dialog()
                    else:
                        front.button_add_task.on_click(None)
                    editor = editor_on_screen(front).controls[0].on_click.__self__
                    selected = SimpleNamespace(name="draft.txt", bytes=b"12", size=2, path=None)
                    with patch.object(ft.FilePicker, "pick_files", new=AsyncMock(return_value=[selected])):
                        asyncio.run(editor.pick(None))
                    front.back.saveB("Meanwhile", attachments=[make_attachment("other.txt", b"123456789")])
                    screen = front.screen_stack[-1]
                    front.libs.entry_task.value = "Draft"
                    if special == "postponed":
                        form = screen.content.controls[0].content.content.controls[1]
                        next(c for c in form.content.controls
                             if isinstance(c, ft.TextField) and c.label == "Дата добавления").value = "01-01-2030"
                    front.libs.entry_task.on_submit(None)
                    self.assertIs(front.screen_stack[-1], screen)
                    self.assertEqual(len(front.back.read_tasks()), 1)
                    self.assertEqual(front.back2.read_repeat_tasks(), [])
                    self.assertEqual(front.back2.read_postponed_tasks(), [])
                    self.assertEqual(front.page.show_dialog.call_args.args[0].title.value, " Лимит вложений")
                    self.assertEqual(len(editor.values()), 1)

    def test_binary_roundtrip_and_image_detection_use_content(self):
        document = make_attachment("../../данные.bin", bytes(range(256)))
        self.assertEqual(document["name"], "данные.bin")
        self.assertEqual(attachment_bytes(document), bytes(range(256)))
        self.assertFalse(make_attachment("fake.png", b"not an image")["is_image"])
        image = image_file()
        self.assertTrue(image["is_image"])
        self.assertTrue(image_preview(image).startswith(b"\x89PNG"))
        with self.assertRaises(ValueError):
            attachment_bytes({"content": "broken@"})
        with patch("Backend.attachments.MAX_FILE_BYTES", 2):
            with self.assertRaises(ValueError):
                make_attachment("large.bin", b"123")

    def test_local_encrypted_storage_and_undo_keep_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend.__new__(Backend)
            back.web = False
            back.page = None
            back.data_dir = Path(directory)
            set_data_encryption(directory, True)
            attachment = make_attachment("test.txt", b"file contents")
            task_id = back.saveB("Task", attachments=[attachment])
            raw = (back.data_dir / "tasks.json").read_bytes()
            self.assertTrue(is_encrypted(raw))
            self.assertNotIn(b"file contents", raw)
            reopened = Backend.__new__(Backend)
            reopened.web = False
            reopened.data_dir = back.data_dir
            self.assertEqual(attachment_bytes(reopened.get_task(task_id)["attachments"][0]),
                             b"file contents")
            back.kill_taskB(task_id)
            self.assertTrue(back.undo_last_action())
            self.assertEqual(back.get_task(task_id)["attachments"], [attachment])

    def test_create_edit_cancel_remove_and_fresh_form_on_both_layouts(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                front.page.services = []
                front._set_screen(front.main_cont, reset=True)
                front.button_add_task.on_click(None)
                editor = editor_on_screen(front)
                selected = SimpleNamespace(name="файл.txt", bytes=b"original", size=8, path=None)
                with patch.object(ft.FilePicker, "pick_files", new=AsyncMock(return_value=[selected])):
                    asyncio.run(editor.controls[0].on_click(None))
                front.entry_task.value = "Дело с вложением"
                front.create_task.on_click(None)
                task = front.back.read_tasks()[0]
                self.assertEqual(attachment_bytes(task["attachments"][0]), b"original")
                self.assertEqual(front.back.get_task(task["id"])["attachments"], task["attachments"])

                def edit():
                    card = next(c for c in front.tasks_cont.content.controls if c.key == task["id"])
                    actions = card.content.controls[-1 if phone else 0].content
                    actions.controls[0].on_click(None)
                    return editor_on_screen(front)

                edit_controls = edit()
                edit_controls.controls[1].controls[0].controls[-1].controls[-1].on_click(None)
                front.close_page()  # Discard the removal.
                self.assertEqual(front.back.get_task(task["id"])["attachments"], task["attachments"])
                edit_controls = edit()
                edit_controls.controls[1].controls[0].controls[-1].controls[-1].on_click(None)
                front.libs.entry_task.on_submit(None)
                self.assertEqual(front.back.get_task(task["id"])["attachments"], [])
                self.assertTrue(front.back.undo_last_action())
                self.assertEqual(front.back.get_task(task["id"])["attachments"], task["attachments"])
                front.button_add_task.on_click(None)
                self.assertFalse(editor_on_screen(front).controls[1].visible)

    def test_preview_and_download_actions_match_file_type(self):
        front = make_front()
        front.page.services = []
        image = image_file()
        document = make_attachment("report.pdf", b"document")
        controls = attachment_controls(front.libs, [image, document])
        self.assertEqual(len(controls.controls[0].controls[-1].controls), 2)
        self.assertEqual(len(controls.controls[1].controls[-1].controls), 1)
        controls.controls[0].controls[-1].controls[0].on_click(None)
        dialog = front.page.show_dialog.call_args.args[0]
        self.assertIsInstance(dialog.content.content, ft.Image)
        self.assertEqual(len(dialog.actions), 2)
        for web, mobile in ((True, False), (False, True), (False, False)):
            with self.subTest(web=web, mobile=mobile), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "report.pdf"
                front.page.web = web
                front.page.platform.is_mobile.return_value = mobile
                with patch.object(ft.FilePicker, "save_file", new=AsyncMock(return_value=str(destination))) as save:
                    controls.controls[1].controls[-1].controls[0].on_click(None)
                    call = front.page.run_task.call_args
                    asyncio.run(call.args[0](*call.args[1:]))
                    self.assertEqual(save.call_args.kwargs["src_bytes"], b"document")
                if not web and not mobile:
                    self.assertEqual(destination.read_bytes(), b"document")
                else:
                    self.assertFalse(destination.exists())
        self.assertEqual(len(front.page.services), 1)

    def test_selection_cancel_and_invalid_batch_leave_existing_files(self):
        front = make_front()
        front.page.services = []
        existing = make_attachment("first.txt", b"first")
        editor = AttachmentEditor(front.libs, [existing])
        for selection in ([], [SimpleNamespace(name="unreadable.txt", bytes=None, size=0, path=None)]):
            with patch.object(ft.FilePicker, "pick_files", new=AsyncMock(return_value=selection)):
                asyncio.run(editor.pick(None))
            self.assertEqual(editor.values(), [existing])
            self.assertFalse(editor.add.disabled)
        self.assertTrue(editor.error.visible)

    def test_special_tasks_generate_with_attachments_and_browser_roundtrip(self):
        front = make_front()
        attachment = make_attachment("plan.txt", b"plan")
        metadata = {"attachments": [attachment]}
        rule_id = front.back2.create_repeat_task("Repeat", metadata=metadata)
        data = front.back._load()
        data["repeat_tasks"][0]["last_date"] = "01-01-2000"
        front.back._save(data)
        front.back2.create_postponed_task("Postponed", "01-01-2000", metadata=metadata)
        self.assertEqual(front.back2.read_repeat_tasks()[0][-1]["attachments"], [attachment])
        self.assertEqual(front.back2.read_postponed_tasks()[0][-1]["attachments"], [attachment])
        front.check_and_add_repeat_task()
        front.check_and_add_postponed_task()
        self.assertEqual(len(front.back.read_tasks()), 2)
        for task in front.back.read_tasks():
            self.assertEqual(task["attachments"], [attachment])
        front.back2.update_repeat_task(rule_id, "Repeat edited", "day", 1, "default", {"attachments": []})
        self.assertEqual(front.back2.read_repeat_tasks()[0][-1]["attachments"], [])

        preferences = {}
        page = Mock(shared_preferences=SimpleNamespace(
            set=lambda key, value: preferences.update({key: value}),
            get=lambda key: preferences.get(key),
        ))
        store = front.back.store
        store.page = page
        asyncio.run(store._persist_async())
        restored = WebSessionStore(page)
        asyncio.run(restored.load())
        self.assertEqual(restored.load_all_sections(), store.load_all_sections())


if __name__ == "__main__":
    unittest.main()
