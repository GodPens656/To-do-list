import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

from Backend.core import Backend, DESKTOP_TEXT_LINE_LENGTH
from Backend.webstorage import WebSessionStore


class TextWrappingTests(unittest.TestCase):
    def setUp(self):
        self.back = Backend.__new__(Backend)
        self.back.phone = False

    def test_phone_returns_original_text(self):
        self.back.phone = True
        text = "Длинное название дела " * 20 + "\n\n  Ручной перенос\t{N} {PR}\n"
        self.assertEqual(self.back.auto_add_new_string(text), text)

    def test_desktop_wraps_by_characters_without_losing_words(self):
        text = "Купить продукты и подготовить документы для следующей рабочей встречи " * 5
        wrapped = self.back.auto_add_new_string(text)
        self.assertEqual(wrapped.split(), text.split())
        self.assertGreater(len(wrapped.splitlines()), 1)
        for line in wrapped.splitlines():
            self.assertLessEqual(len(line), DESKTOP_TEXT_LINE_LENGTH)

    def test_word_fits_exactly_at_limit(self):
        first = "а" * (DESKTOP_TEXT_LINE_LENGTH - 5)
        text = first + " дело"
        self.assertEqual(self.back.auto_add_new_string(text), text)
        self.assertEqual(self.back.auto_add_new_string(text + " ещё"), text + "\nещё")

    def test_long_words_and_hyphens_are_not_split(self):
        word = "очень-" * DESKTOP_TEXT_LINE_LENGTH
        self.assertEqual(self.back.auto_add_new_string("до " + word + " после"),
                         "до\n" + word + "\nпосле")

    def test_manual_newlines_and_literal_markers_survive(self):
        for text in ("", "\n\n", "abc def", "abc\n\ndef\n", "x {PR} y {N} z"):
            with self.subTest(text=text):
                self.assertEqual(self.back.auto_add_new_string(text), text)


class SavedTaskNewlineTests(unittest.TestCase):
    def test_saved_and_edited_tasks_restore_newlines_before_wrapping(self):
        with tempfile.TemporaryDirectory() as directory:
            for web in (False, True):
                with self.subTest(web=web):
                    back = Backend.__new__(Backend)
                    back.web = web
                    back.page = None
                    back.data_dir = Path(directory)
                    back.store = WebSessionStore(SimpleNamespace())
                    original = "Купить продукты\n\nПозвонить маме\n"
                    back.saveB(original)
                    task_id = back.read_id(original)

                    for text in (original, "Работа\n\n" + "Подготовить документы " * 8 + "\n"):
                        with self.subTest(text=text):
                            back.redact_taskB(task_id, text)
                            stored = back._load()["tasks"][0]
                            task = back.read_tasks()[0]
                            self.assertEqual(task["name"], text)
                            self.assertEqual(back.read_id(task["name"]), task_id)
                            self.assertEqual(back.read_name(task_id), text)
                            self.assertEqual(
                                {**stored, "name": text}, task,
                            )
                            self.assertEqual(
                                back._load()["tasks"][0]["name"],
                                text.replace("\n", "{N}"),
                            )
                            for phone in (False, True):
                                with self.subTest(phone=phone):
                                    back.phone = phone
                                    displayed = back.auto_add_new_string(task["name"])
                                    self.assertEqual(displayed, back.auto_add_new_string(text))
                                    self.assertNotIn("{N}", displayed)
                                    self.assertIn("\n\n", displayed)
                                    self.assertTrue(displayed.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
