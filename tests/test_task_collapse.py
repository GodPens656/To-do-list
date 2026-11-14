import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

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


def collapse_checkbox(form):
    return next(c for c in walk(form)
                if isinstance(c, ft.Checkbox) and c.label == "Сворачивать ли дело")


class TaskCollapseStorageTests(unittest.TestCase):
    def test_threshold_counts_original_text_in_file_and_browser_storage(self):
        for web in (False, True):
            with self.subTest(web=web), tempfile.TemporaryDirectory() as directory:
                back = Backend.__new__(Backend)
                back.web = web
                back.page = None
                back.data_dir = Path(directory)
                back.store = WebSessionStore(SimpleNamespace())
                for length in (499, 500, 501):
                    # The stored {N} markers must not inflate the character count.
                    name = "Я🙂 \n" * 124 + "а" * (length - 496)
                    task_id = back.saveB(name)
                    self.assertEqual(back.get_task(task_id)["collapse"], length > 500)
                    self.assertEqual(back.read_name(task_id), name)
                    back.redact_taskB(task_id, name, {"collapse": False})
                    self.assertEqual(back.get_task(task_id)["collapse"], length > 500)

    def test_manual_choice_edit_and_undo(self):
        back = make_front().back
        task_id = back.saveB("Короткое дело", collapse=True)
        back.redact_taskB(task_id, "Новое название")
        self.assertTrue(back.get_task(task_id)["collapse"])
        back.redact_taskB(task_id, "Новое название", {"collapse": False})
        self.assertFalse(back.get_task(task_id)["collapse"])
        back.redact_taskB(task_id, "я" * 501, {"collapse": False})
        self.assertTrue(back.get_task(task_id)["collapse"])
        self.assertTrue(back.undo_last_action())
        self.assertFalse(back.get_task(task_id)["collapse"])

    def test_special_task_storage_and_generated_tasks_keep_preference(self):
        front = make_front()
        front.back2.create_repeat_task("Короткий повтор", metadata={"collapse": True})
        front.back2.create_postponed_task(
            "Короткое отложенное", "01-01-2000", metadata={"collapse": True},
        )
        data = front.back._load()
        data["repeat_tasks"][0]["last_date"] = "01-01-2000"
        front.back._save(data)
        front.check_and_add_repeat_task()
        front.check_and_add_postponed_task()
        self.assertEqual(len(front.back.read_tasks()), 2)
        self.assertTrue(all(t["collapse"] for t in front.back.read_tasks()))
        for create, edit, read in (
            (lambda name: front.back2.create_repeat_task(name),
             lambda ident, name: front.back2.update_repeat_task(
                 ident, name, "day", 1, "default", {"collapse": False}),
             front.back2.read_repeat_tasks),
            (lambda name: front.back2.create_postponed_task(name, "01-01-2030"),
             lambda ident, name: front.back2.update_postponed_task(
                 ident, name, "01-01-2030", "default", {"collapse": False}),
             front.back2.read_postponed_tasks),
        ):
            ident = create("я" * 501)
            self.assertTrue(next(row[-1]["collapse"] for row in read() if row[-2] == ident))
            edit(ident, "я" * 500)
            self.assertFalse(next(row[-1]["collapse"] for row in read() if row[-2] == ident))
            edit(ident, "я" * 501)
            self.assertTrue(next(row[-1]["collapse"] for row in read() if row[-2] == ident))


class TaskCollapseUITests(unittest.TestCase):
    def setUp(self):
        self.front = make_front()
        self.front._update_control = Mock()
        self.front._set_screen(self.front.main_cont, reset=True)

    def card(self, task_id):
        return next(c for c in self.front.tasks_cont.content.controls if c.key == task_id)

    def edit(self, task_id):
        self.front.open_modified_dialog = Mock()
        task_menu(self.card(task_id)).items[0].on_click(None)
        return self.front.open_modified_dialog.call_args.args[1]

    def test_checkbox_auto_enables_after_500_and_resets_for_new_task(self):
        front = self.front
        front.button_add_task.on_click(None)
        self.assertFalse(front.collapse_task.value)
        with patch.object(ft.TextField, "update"), patch.object(ft.Checkbox, "update"):
            for length in (500, 501):
                front.entry_task.value = "я" * length
                front.entry_task.on_change(SimpleNamespace(control=front.entry_task))
                self.assertEqual(front.collapse_task.value, length > 500)
                self.assertEqual(front.entry_task.helper, f"{length}/1000 символов")
        front.close_page()
        front.button_add_task.on_click(None)
        self.assertFalse(front.collapse_task.value)

    def test_create_edit_and_reload_on_phone_and_desktop(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                self.front = front = make_front(phone=phone)
                front._update_control = Mock()
                front._set_screen(front.main_cont, reset=True)
                front.button_add_task.on_click(None)
                front.entry_task.value = "Короткое дело"
                front.collapse_task.value = True
                front.entry_task.on_submit(None)
                task_id = front.back.read_tasks()[0]["id"]
                self.assertTrue(front.back.get_task(task_id)["collapse"])
                self.assertTrue(any(isinstance(c, ft.Checkbox) for c in walk(self.card(task_id))))
                checkbox = collapse_checkbox(self.edit(task_id))
                self.assertTrue(checkbox.value)
                checkbox.value = False
                front.libs.entry_task.on_submit(None)
                self.assertFalse(front.back.get_task(task_id)["collapse"])
                self.assertTrue(any(isinstance(c, ft.Checkbox) for c in walk(self.card(task_id))))
                self.edit(task_id)
                front.libs.entry_task.value = "я" * 501
                front.libs.entry_task.on_submit(None)
                self.assertTrue(front.back.get_task(task_id)["collapse"])
                front.render_daily_repeat_tasks()
                completion = next(c for c in walk(self.card(task_id)) if isinstance(c, ft.Checkbox))
                completion.value = True
                completion.on_change(SimpleNamespace(control=completion))
                self.assertTrue(front.back.get_task(task_id)["status"])
                self.assertTrue(any(isinstance(c, ft.Text) and c.max_lines == 3
                                    for c in walk(self.card(task_id))))
                self.assertTrue(collapse_checkbox(self.edit(task_id)).value)

    def test_expand_preserves_links_search_and_completion(self):
        front = self.front
        name = "Первый пункт\n" + "Подробности дела " * 35 + "https://example.org/hidden"
        task_id = front.back.saveB(name)
        front.render_daily_repeat_tasks()
        card = self.card(task_id)
        text = next(c for c in walk(card) if isinstance(c, ft.Text) and c.max_lines == 3)
        button = next(c for c in walk(card) if isinstance(c, ft.TextButton))
        expected = front.back.auto_add_new_string(name)
        before = front.back._load()
        with patch.object(ft.Column, "update"):
            for max_lines, label in ((None, "Свернуть"), (3, "Развернуть")):
                button.on_click(None)
                self.assertEqual(text.max_lines, max_lines)
                self.assertTrue(any(isinstance(c, ft.Text) and c.value == label for c in walk(button)))
                self.assertTrue(any(isinstance(c, ft.Checkbox) for c in walk(card)))
                self.assertEqual("".join(span.text or "" for span in text.spans), expected)
        self.assertEqual(front.back._load(), before)
        self.assertEqual(next(span.url.url for span in text.spans if span.url),
                         "https://example.org/hidden")
        front.apply_search_filter("example.org/hidden")
        self.assertTrue(card.visible)
        completion = next(c for c in walk(card) if isinstance(c, ft.Checkbox))
        completion.value = True
        completion.on_change(SimpleNamespace(control=completion))
        self.assertTrue(front.back.get_task(task_id)["status"])
        self.assertEqual(text.style.decoration, ft.TextDecoration.LINE_THROUGH)
        self.assertTrue(front.back.get_task(task_id)["collapse"])

    def test_full_glass_keeps_one_arrow_after_repeated_toggles(self):
        front = make_front(effect="liquid_glass")
        body = front.libs.collapsible_task_text(ft.Text("Текст дела"), True)
        button = body.controls[1]
        front.libs.prepare(body)
        with patch.object(ft.Column, "update"):
            for icon in (ft.Icons.KEYBOARD_ARROW_UP_ROUNDED,
                         ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED) * 3:
                button.on_click(None)
                front.libs.prepare(body)
                arrows = [c for c in walk(button) if isinstance(c, ft.Icon)]
                self.assertEqual(len(arrows), 1)
                self.assertEqual(arrows[0].icon, icon)
                self.assertIsNone(button.icon)

    def test_legacy_task_stays_expanded_until_edited(self):
        front = self.front
        data = front.back._load()
        data["tasks"] = [{"id": "legacy", "name": "я" * 501, "group": "default"}]
        front.back._save(data)
        front.render_daily_repeat_tasks()
        self.assertFalse(any(isinstance(c, ft.TextButton) for c in walk(self.card("legacy"))))
        self.assertTrue(collapse_checkbox(self.edit("legacy")).value)
        front.libs.entry_task.on_submit(None)
        self.assertTrue(front.back.get_task("legacy")["collapse"])

    def test_special_forms_offer_checkbox_and_save_automatic_choice(self):
        front = self.front
        front.open_special_tasks()
        front.open_page = Mock()
        for open_form, read, listing in (
            (front.open_repeat_dialog, front.back2.read_repeat_tasks,
             front.utils2.cont_with_repeat_task),
            (front.open_postponed_dialog, front.back2.read_postponed_tasks,
             front.utils2.cont_with_postponed_task),
        ):
            open_form()
            form = front.open_page.call_args.args[1]
            self.assertFalse(collapse_checkbox(form).value)
            for control in walk(form):
                if isinstance(control, ft.TextField) and control.label == "Дата добавления":
                    control.value = "01-01-2030"
            front.libs.entry_task.value = "я" * 501
            front.libs.entry_task.on_submit(None)
            self.assertTrue(read()[-1][-1]["collapse"])
            self.assertTrue(any(isinstance(c, ft.Text) and c.max_lines == 3 for c in walk(listing)))


if __name__ == "__main__":
    unittest.main()
