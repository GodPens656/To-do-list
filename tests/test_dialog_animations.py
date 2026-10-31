import tempfile
import unittest
from pathlib import Path

import flet as ft

from Backend.extended import Backend2
from test_ui_state import make_front


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
            stack = list(front.screen_stack)
            host = front.screen_host
            for enabled in (False, True, False):
                switch.value = enabled
                switch.on_change(None)
                self.assertEqual(front.back2.read_settings()["dialog_animations"], enabled)
                self.assertIs(front.screen_host, host)
                self.assertEqual(front.screen_stack, stack)
                for platform in ("windows", "macos", "linux", "android", "ios"):
                    transition = getattr(front.page.theme.page_transitions, platform)
                    self.assertEqual(transition, None if enabled else ft.PageTransitionTheme.NONE)
            front._apply_page_theme()
            self.assertEqual(front.page.theme.page_transitions.android, ft.PageTransitionTheme.NONE)


if __name__ == "__main__":
    unittest.main()
