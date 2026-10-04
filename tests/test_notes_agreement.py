import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from Backend.extended import Backend2
from Backend.webstorage import WebSessionStore
from test_ui_state import make_front


class NotesAgreementTests(unittest.TestCase):
    def test_first_start_requires_explicit_acceptance_then_continues(self):
        for phone in (False, True):
            for signed_in in (False, True):
                with self.subTest(phone=phone, signed_in=signed_in):
                    front = make_front(phone=phone)
                    front.show_groups = Mock()
                    front.open_auth_dialog = Mock()
                    front.cloud.check_user_data.return_value = signed_in
                    front.page.run_task.reset_mock()

                    front.show_start_screen()
                    dialog = front.page.show_dialog.call_args.args[0]
                    self.assertTrue(dialog.modal)
                    self.assertTrue(dialog.scrollable)
                    self.assertFalse(front.back2.read_settings()["notes_accepted"])
                    front.open_auth_dialog.assert_not_called()
                    front.page.run_task.assert_not_called()
                    _, notes, _ = front.main_widgets.dialog_for_primechanya()
                    self.assertEqual(
                        dialog.content.content.controls[1].value,
                        notes.content.controls[0].value,
                    )

                    front.show_start_screen()
                    front.page.show_dialog.assert_called_once()
                    dialog.actions[0].on_click(None)
                    self.assertTrue(front.back2.read_settings()["notes_accepted"])
                    front.page.pop_dialog.assert_called_once()
                    front.open_auth_dialog.assert_not_called()
                    self.assertNotIn(
                        call(front.show_offline_start_dialog), front.page.run_task.call_args_list,
                    )
                    self.assertIs(front._notes_dialog, dialog)

                    # The client dismisses the modal asynchronously. Navigation
                    # must wait until it is gone, including repeated events.
                    front.show_start_screen()
                    dialog.actions[0].on_click(None)
                    front.page.pop_dialog.assert_called_once()
                    front.open_auth_dialog.assert_not_called()
                    dialog.on_dismiss(None)
                    self.assertIsNone(front._notes_dialog)
                    self.assertEqual(front.open_auth_dialog.call_count, int(not signed_in))
                    front.page.run_task.assert_called_with(front.show_offline_start_dialog)

                    front.page.show_dialog.reset_mock()
                    front.show_start_screen()
                    front.page.show_dialog.assert_not_called()

    def test_dismissal_does_not_save_agreement(self):
        front = make_front()
        front.show_groups = Mock()
        front.show_start_screen()
        front.page.show_dialog.call_args.args[0].on_dismiss(None)
        self.assertFalse(front.back2.read_settings()["notes_accepted"])
        front.show_start_screen()
        self.assertEqual(front.page.show_dialog.call_count, 2)

    def test_agreement_survives_native_settings_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.txt"
            back = Backend2.__new__(Backend2)
            back.web = False
            back.settings = settings_path
            back.set_default_settings()
            self.assertFalse(back.read_settings()["notes_accepted"])
            back.redact_setting("notes_accepted", True)

            reopened = Backend2.__new__(Backend2)
            reopened.web = False
            reopened.settings = settings_path
            reopened.set_default_settings()
            self.assertTrue(reopened.read_settings()["notes_accepted"])

    def test_agreement_survives_browser_reload_and_is_local(self):
        saved = {}
        page = Mock(shared_preferences=SimpleNamespace(get=saved.get, set=saved.__setitem__))
        back = Backend2.__new__(Backend2)
        back.web = True
        back.store = WebSessionStore(page)
        back.set_default_settings()
        back.redact_setting("notes_accepted", True)
        asyncio.run(back.store._persist_async())

        back.store = WebSessionStore(page)
        asyncio.run(back.store.load())
        back.set_default_settings()
        self.assertTrue(back.read_settings()["notes_accepted"])

        back.store = WebSessionStore(Mock())
        back.set_default_settings()
        self.assertFalse(back.read_settings()["notes_accepted"])


class NotesAgreementNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_back_from_login_after_acceptance_returns_to_groups(self):
        for web in (False, True):
            for phone in (False, True):
                with self.subTest(web=web, phone=phone):
                    front = make_front(phone=phone)
                    front.web = web
                    front.page.push_route = AsyncMock()
                    front.cloud.check_user_data.return_value = False
                    front.cloud.read_user_data.return_value = {
                        "Start text": "Вы не авторизованы",
                        "Login": "", "Password": "",
                    }
                    front.cloud.read_auth_accounts.return_value = []
                    front.page.run_task.reset_mock()
                    front.show_start_screen()
                    dialog = front.page.show_dialog.call_args.args[0]

                    dialog.actions[0].on_click(None)
                    self.assertTrue(front.back2.read_settings()["notes_accepted"])
                    self.assertEqual(
                        len(front.screen_stack) if web else len(front.page.views), 1,
                    )
                    with patch.object(
                        front, "open_modified_dialog", wraps=front.open_modified_dialog,
                    ) as open_dialog:
                        dialog.on_dismiss(None)
                    back_button = open_dialog.call_args.args[2]
                    self.assertEqual(
                        len(front.screen_stack) if web else len(front.page.views), 2,
                    )

                    # Exercise the actual login form's Back button.
                    back_button.on_click(None)
                    self.assertIsNone(front._notes_dialog)
                    self.assertTrue(front.back2.read_settings()["notes_accepted"])
                    front.page.show_dialog.assert_called_once()
                    if web:
                        self.assertEqual(front.screen_stack, [front._groups_screen])
                        self.assertIs(front.screen_host.content, front._groups_screen)
                    else:
                        self.assertEqual(len(front.page.views), 1)
                        self.assertEqual(front.page.views[0].route, "/groups")
                    await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
