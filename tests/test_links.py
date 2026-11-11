import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Frontend.links import linked_text
from test_ui_state import make_front, task_menu


def controls(root):
    yield root
    for child in getattr(root, "controls", []) or []:
        yield from controls(child)
    content = getattr(root, "content", None)
    if isinstance(content, ft.Control):
        yield from controls(content)


def links(root):
    return [span for control in controls(root) if isinstance(control, ft.Text)
            for span in control.spans or [] if span.url or span.on_click]


def text_value(control):
    return (control.value or "") + "".join(span.text or "" for span in control.spans or [])


class LinkTextTests(unittest.TestCase):
    def test_plain_text_and_non_web_schemes_stay_literal(self):
        for value in ("", "Текст\n\nбез ссылок 🙂", "<b>Текст</b> **звёздочки**",
                      "javascript:alert(1) file:///tmp/test ftp://example.org",
                      "user@www.example.org", "https://", "https://[broken"):
            with self.subTest(value=value):
                text = linked_text(value)
                self.assertEqual(text_value(text), value)
                self.assertFalse(links(text))

    def test_multiple_links_preserve_newlines_unicode_queries_and_punctuation(self):
        value = ("См. (https://example.org/a_(b)?x=1&y=2#part),\n\n"
                 "«https://пример.рф/путь» и www.example.com/docs.\n"
                 "[HTTP://example.net/test]!")
        text = linked_text(value, web=True)
        self.assertEqual(text_value(text), value)
        self.assertEqual([span.url.url for span in links(text)], [
            "https://example.org/a_(b)?x=1&y=2#part", "https://пример.рф/путь",
            "https://www.example.com/docs", "HTTP://example.net/test",
        ])
        for span in links(text):
            self.assertEqual(span.style.color, "#2563EB")
            self.assertEqual(span.url.target, ft.UrlTarget.BLANK)
            self.assertIsNone(span.on_click)

    def test_dark_theme_links_inherit_completion_decoration(self):
        style = ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH)
        text = linked_text("https://example.org", dark=True, style=style)
        self.assertIs(text.style, style)
        self.assertEqual(links(text)[0].style.color, "#60A5FA")
        self.assertIsNone(links(text)[0].style.decoration)

    def test_native_clicks_use_external_browser_and_reuse_mounted_service(self):
        page = SimpleNamespace(services=[], update=Mock())
        text = linked_text("https://example.org/a и www.example.net/b", page=page)
        self.assertEqual(page.services, [])
        first, second = links(text)
        self.assertIsNone(first.url)
        with patch.object(ft.UrlLauncher, "launch_url", new_callable=AsyncMock) as launch:
            asyncio.run(first.on_click(None))
            asyncio.run(second.on_click(None))
            asyncio.run(first.on_click(None))
        self.assertEqual([call.args[0] for call in launch.await_args_list], [
            "https://example.org/a", "https://www.example.net/b", "https://example.org/a",
        ])
        self.assertTrue(all(call.kwargs == {"mode": ft.LaunchMode.EXTERNAL_APPLICATION}
                            for call in launch.await_args_list))
        self.assertEqual(len(page.services), 1)
        page.update.assert_called_once()


class RecordLinkTests(unittest.TestCase):
    def test_tasks_and_notes_keep_long_links_on_desktop_and_phone(self):
        url = "https://example.org/" + "long-path/" * 12 + "?a=1&b=2#part"
        value = "Открыть " + url + "\n\nСледующая строка"
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                task_id = front.back.saveB(value)
                group = front.back.create_group("Заметки", group_type="notes")
                note_id = front.back.save_note(group, value)
                for group_id, record_id in (("default", task_id), (group, note_id)):
                    front.current_group_id = group_id
                    front.render_daily_repeat_tasks()
                    card = next(c for c in front.tasks_cont.content.controls if c.key == record_id)
                    self.assertEqual(card.data, value)
                    self.assertEqual([s.url.url for s in links(card)], [url])
                    self.assertIn("\n\n", next(text_value(c) for c in controls(card)
                                              if isinstance(c, ft.Text) and c.spans))
                self.assertEqual(front.back.read_name(task_id), value)
                self.assertEqual(front.back.read_notes(group)[0]["text"], value)

    def test_task_edit_rebuilds_links_and_completion_keeps_them_clickable(self):
        front = make_front()
        front._update_control = Mock()
        task_id = front.back.saveB("Без ссылки")

        def card():
            return next(c for c in front.tasks_cont.content.controls if c.key == task_id)

        front.render_daily_repeat_tasks()
        for value, expected in (("Ссылка https://example.org", ["https://example.org"]),
                                ("Ссылка удалена", [])):
            task_menu(card()).items[0].on_click(None)
            front.libs.entry_task.value = value
            front.libs.entry_task.on_submit(None)
            self.assertEqual([s.url.url for s in links(card())], expected)
            checkbox = next(c for c in controls(card()) if isinstance(c, ft.Checkbox))
            checkbox.value = True
            checkbox.on_change(Mock(control=checkbox))
            self.assertEqual([s.url.url for s in links(card())], expected)
            self.assertEqual(front.back.read_name(task_id), value)

    def test_note_edit_rebuilds_links(self):
        front = make_front()
        group = front.back.create_group("Заметки", group_type="notes")
        note_id = front.back.save_note(group, "Первая ссылка https://example.org")
        front.current_group_id = group
        for value, expected in (("Новая ссылка www.example.net", ["https://www.example.net"]),
                                ("Без ссылки", [])):
            front.open_note_editor(front.back.read_notes(group)[0])
            front.libs.entry_task.value = value
            front.libs.btn_create_task.on_click(None)
            card = next(c for c in front.tasks_cont.content.controls if c.key == note_id)
            self.assertEqual([s.url.url for s in links(card)], expected)

    def test_special_tasks_and_schedule_use_links(self):
        front = make_front()
        front.back2.create_repeat_task("Повтор https://example.org/repeat")
        front.back2.create_postponed_task("Позже https://example.org/later", "10-11-2026")
        front.open_special_tasks()
        self.assertEqual([s.url.url for s in links(front.utils2.cont_with_repeat_task)],
                         ["https://example.org/repeat"])
        self.assertEqual([s.url.url for s in links(front.utils2.cont_with_postponed_task)],
                         ["https://example.org/later"])
        front.close_page()
        front.open_settings()
        front.open_schedule()
        entry = next(e for entries in front.task_schedule.entries.values() for e in entries
                     if e.name.endswith("/repeat"))
        self.assertEqual(links(front.task_schedule.entry_card(entry))[0].url.url,
                         "https://example.org/repeat")
        front.task_schedule.show_entry(entry)
        self.assertEqual(links(front.page.show_dialog.call_args.args[0])[0].url.url,
                         "https://example.org/repeat")


if __name__ == "__main__":
    unittest.main()
