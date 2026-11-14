import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.attachments import make_attachment
from Backend.core import Backend
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front, task_menu


def walk(root):
    yield root
    for child in getattr(root, "controls", []) or []:
        yield from walk(child)
    content = getattr(root, "content", None)
    if isinstance(content, ft.Control):
        yield from walk(content)


def open_editor(front, note=None):
    front.open_note_editor(note)
    form = front.open_page.call_args.args[1]
    checkbox = next(c for c in walk(form) if isinstance(c, ft.Checkbox)
                    and c.label == "Сворачивать ли заметку")
    save = form.content.controls[-1].controls[0].on_click
    return front.libs.entry_task, checkbox, save


def notes_front(phone=False):
    front = make_front(phone=phone)
    front.current_group_id = front.back.create_group("Заметки", group_type="notes")
    front.open_page = Mock()
    front.close_page = Mock()
    front._update_control = Mock()
    return front


class NoteCollapseStorageTests(unittest.TestCase):
    def test_threshold_on_create_and_edit_in_native_and_browser_storage(self):
        for web in (False, True):
            with self.subTest(web=web), tempfile.TemporaryDirectory() as directory:
                back = Backend.__new__(Backend)
                back.web = web
                back.page = None
                back.data_dir = Path(directory)
                back.store = WebSessionStore(SimpleNamespace())
                group = back.create_group("Заметки", group_type="notes")
                for length in (499, 500, 501):
                    text = "Я🙂 \n" * 124 + "а" * (length - 496)
                    note_id = back.save_note(group, text, collapse=False)
                    note = next(n for n in back.read_notes(group) if n['id'] == note_id)
                    self.assertEqual(note['text'], text)
                    self.assertEqual(note['collapse'], length > 500)
                    back.save_note(group, "б" * 500, note_id, collapse=False)
                    self.assertFalse(back.read_notes(group)[-1]['collapse'])
                    back.save_note(group, text, note_id, collapse=False)
                    self.assertEqual(back.read_notes(group)[-1]['collapse'], length > 500)
                if not web:
                    reopened = Backend.__new__(Backend)
                    reopened.web = False
                    reopened.data_dir = Path(directory)
                    self.assertEqual(reopened.read_notes(group), back.read_notes(group))

    def test_manual_choice_survives_text_edits_and_undo_preserves_attachments(self):
        front = notes_front()
        back, group = front.back, front.current_group_id
        files = [make_attachment("note.txt", b"contents")]
        note_id = back.save_note(group, "Короткая заметка", collapse=True, attachments=files)
        back.save_note(group, "Изменённая заметка", note_id)
        self.assertTrue(back.read_notes(group)[0]['collapse'])
        before = back.read_notes(group)
        back.save_note(group, "Изменённая заметка", note_id, collapse=False)
        self.assertFalse(back.read_notes(group)[0]['collapse'])
        self.assertEqual(back.read_notes(group)[0]['attachments'], files)
        self.assertTrue(back.undo_last_action())
        self.assertEqual(back.read_notes(group), before)


class NoteCollapseUITests(unittest.TestCase):
    def test_create_edit_auto_enable_and_new_form_reset_on_phone_and_desktop(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = notes_front(phone)
                group = front.current_group_id
                entry, checkbox, save = open_editor(front)
                self.assertFalse(checkbox.value)
                entry.value = "Короткая заметка"
                checkbox.value = True
                save(None)
                note = front.back.read_notes(group)[0]
                self.assertTrue(note['collapse'])
                entry, checkbox, save = open_editor(front, note)
                self.assertTrue(checkbox.value)
                checkbox.value = False
                save(None)
                note = front.back.read_notes(group)[0]
                self.assertFalse(note['collapse'])
                entry, checkbox, save = open_editor(front, note)
                with patch.object(ft.TextField, "update"), patch.object(ft.Checkbox, "update"):
                    for length in (500, 501):
                        entry.value = "я" * length
                        entry.on_change(SimpleNamespace(control=entry))
                        self.assertEqual(checkbox.value, length > 500)
                        self.assertEqual(entry.helper, f"{length}/1000 символов")
                save(None)
                note = front.back.read_notes(group)[0]
                self.assertTrue(note['collapse'])
                card = next(c for c in front.tasks_cont.content.controls if c.key == note['id'])
                self.assertTrue(any(isinstance(c, ft.Text) and c.max_lines == 3 for c in walk(card)))
                self.assertFalse(any(isinstance(c, ft.Checkbox) for c in walk(card)))
                _, checkbox, _ = open_editor(front, note)
                self.assertTrue(checkbox.value)
                _, checkbox, _ = open_editor(front)
                self.assertFalse(checkbox.value)

    def test_save_auto_enables_without_text_change_event(self):
        front = notes_front()
        entry, checkbox, save = open_editor(front)
        entry.value = "я" * 501
        self.assertFalse(checkbox.value)
        save(None)
        self.assertTrue(front.back.read_notes(front.current_group_id)[0]['collapse'])

    def test_expand_search_and_copy_keep_full_note_text_and_links(self):
        front = notes_front()
        front.page.services = []
        text = "Заголовок\n\n" + "Полный текст заметки " * 30 + "https://example.org/hidden"
        note_id = front.back.save_note(front.current_group_id, text)
        front.render_daily_repeat_tasks()
        card = next(c for c in front.tasks_cont.content.controls if c.key == note_id)
        content = next(c for c in walk(card) if isinstance(c, ft.Text) and c.max_lines == 3)
        toggle = next(c for c in walk(card) if isinstance(c, ft.TextButton))
        before = front.back.read_notes(front.current_group_id)
        with patch.object(ft.Column, "update"):
            for max_lines in (None, 3):
                toggle.on_click(None)
                self.assertEqual(content.max_lines, max_lines)
        self.assertEqual(front.back.read_notes(front.current_group_id), before)
        self.assertEqual(next(span.url.url for span in content.spans if span.url),
                         "https://example.org/hidden")
        front.apply_search_filter("example.org/hidden")
        self.assertTrue(card.visible)
        with patch.object(ft.Clipboard, "set", new_callable=AsyncMock) as copy:
            asyncio.run(task_menu(card).items[1].on_click(None))
            copy.assert_awaited_once_with(text)

    def test_legacy_note_stays_expanded_until_edited(self):
        front = notes_front()
        data = front.back._load()
        group = next(g for g in data['groups'] if g['id'] == front.current_group_id)
        group['notes'] = [{'id': 'legacy', 'text': 'я' * 501}]
        front.back._save(data)
        front.render_daily_repeat_tasks()
        card = next(c for c in front.tasks_cont.content.controls if c.key == 'legacy')
        self.assertFalse(any(isinstance(c, ft.TextButton) for c in walk(card)))
        _, checkbox, save = open_editor(front, front.back.read_notes(front.current_group_id)[0])
        self.assertTrue(checkbox.value)
        save(None)
        self.assertTrue(front.back.read_notes(front.current_group_id)[0]['collapse'])


if __name__ == '__main__':
    unittest.main()
