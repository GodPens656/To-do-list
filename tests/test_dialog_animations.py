import tempfile
import unittest
from pathlib import Path

import flet as ft

from Backend.extended import Backend2
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front
from test_webstorage import BrowserPage, settings_backend


class DialogAnimationTests(unittest.TestCase):
    def test_setting_defaults_and_survives_local_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend2.__new__(Backend2)
            back.web = False
            back.settings = Path(directory) / "settings.txt"
            back.set_default_settings()
            self.assertTrue(back.read_settings()["dialog_animations"])
            back.redact_setting("dialog_animations", False)
            reopened = Backend2.__new__(Backend2)
            reopened.web, reopened.settings = False, back.settings
            reopened.set_default_settings()
            self.assertFalse(reopened.read_settings()["dialog_animations"])

    def test_switch_applies_without_navigation_and_preserves_disabled_state_on_theme_change(self):
        for phone in (False, True):
            front = make_front(phone=phone)
            front.show_groups()
            front.open_settings()
            panel = front.utils2.build_widgets_for_customization()
            row = next(c for c in panel.content.controls if isinstance(c, ft.Row)
                       and isinstance(c.controls[0], ft.Text)
                       and c.controls[0].value == "Анимации от диалогов")
            switch = row.controls[1]
            self.assertFalse(switch.value)
            stack = list(front.screen_stack)
            host = front.screen_host
            for enabled in (False, True, False):
                switch.value = enabled
                switch.on_change(None)
                self.assertEqual(front.back2.read_settings()["dialog_animations"], enabled)
                self.assertIs(front.screen_host, host)
                self.assertEqual(front.screen_stack, stack)
                if enabled:
                    self.assertIsInstance(host.content, ft.AnimatedSwitcher)
                    self.assertIs(host.content.content, stack[-1])
                else:
                    self.assertIs(host.content, stack[-1])
                for platform in ("windows", "macos", "linux", "android", "ios"):
                    transition = getattr(front.page.theme.page_transitions, platform)
                    self.assertEqual(transition, None if enabled else ft.PageTransitionTheme.NONE)
            front._apply_page_theme()
            self.assertEqual(front.page.theme.page_transitions.android, ft.PageTransitionTheme.NONE)

    def test_browser_transitions_work_forward_and_back_without_replacing_the_host(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone, settings={"dialog_animations": "True"})
                front.show_groups()
                host = front.screen_host
                switcher = host.content
                self.assertIsInstance(switcher, ft.AnimatedSwitcher)
                self.assertGreater(switcher.duration, 0)
                self.assertGreater(switcher.reverse_duration, 0)
                self.assertEqual(switcher.transition, ft.AnimatedSwitcherTransition.FADE)
                self.assertIs(switcher.content, front.main_cont)
                front.open_settings()
                settings_screen = front.screen_stack[-1]
                self.assertIs(switcher.content, settings_screen)
                header, content, back = front.utils2.build_dialog_customization()
                front.open_modified_dialog2(header, content, back)
                self.assertIs(switcher.content, front.screen_stack[-1])
                front.close_page()
                self.assertIs(switcher.content, settings_screen)
                front.close_page()
                self.assertIs(switcher.content, front.main_cont)
                self.assertIs(front.screen_host, host)
                self.assertIs(host.content, switcher)
                front.apply_theme_style("nord")
                self.assertIsInstance(front.screen_host.content, ft.AnimatedSwitcher)
                self.assertIs(front.screen_host.content.content, front.main_cont)


class BrowserDialogAnimationSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_defaults_off_and_preserves_the_choice_after_reload(self):
        for saved in (None, "True", "False"):
            with self.subTest(saved=saved):
                values = {}
                page = BrowserPage(values)
                store = WebSessionStore(page)
                # Also cover browsers whose existing settings predate the switch.
                store._settings = {"theme_style": "nord"}
                if saved is not None:
                    store._settings["dialog_animations"] = saved
                back = settings_backend(store)
                self.assertEqual(back.read_settings()["dialog_animations"], saved == "True")
                back.set_default_settings()
                self.assertEqual(back.read_settings()["dialog_animations"], saved == "True")
                await page.flush()
                for enabled in (True, False):
                    back.redact_setting("dialog_animations", enabled)
                    await page.flush()
                    reopened_page = BrowserPage(values)
                    reopened_store = WebSessionStore(reopened_page)
                    await reopened_store.load()
                    reopened = settings_backend(reopened_store)
                    reopened.set_default_settings()
                    self.assertEqual(reopened.read_settings()["dialog_animations"], enabled)
                    await reopened_page.flush()


if __name__ == "__main__":
    unittest.main()
