import asyncio
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.extended import Backend2
from Backend.security import hash_password, verify_password
from Backend.webstorage import WebSessionStore
from Frontend.init_page import Front
from test_ui_state import make_front


class PasswordStorageTests(unittest.TestCase):
    def test_hash_is_salted_and_preserves_unicode_and_spaces(self):
        password = "  пароль 🔒  "
        first, second = hash_password(password), hash_password(password)
        self.assertNotEqual(first, second)
        self.assertNotIn(password, first)
        self.assertTrue(verify_password(password, first))
        self.assertFalse(verify_password(password.strip(), first))
        for malformed in ("", "plain text", None, "pbkdf2_sha256$999999999$a$b"):
            self.assertFalse(verify_password(password, malformed))
        for invalid in ("", "   ", "x" * 1025):
            with self.assertRaises(ValueError):
                hash_password(invalid)

    def exercise_settings(self, back):
        back.set_default_settings()
        self.assertFalse(back.read_settings()["password_enabled"])
        back.set_app_password("первый пароль")
        back.set_default_settings()
        self.assertTrue(back.read_settings()["password_enabled"])
        self.assertTrue(back.verify_app_password("первый пароль"))
        for action in (
            lambda: back.set_app_password("второй пароль", "неверный"),
            lambda: back.disable_app_password("неверный"),
        ):
            with self.assertRaises(ValueError):
                action()
            self.assertTrue(back.verify_app_password("первый пароль"))
        back.set_app_password("второй пароль", "первый пароль")
        self.assertFalse(back.verify_app_password("первый пароль"))
        self.assertTrue(back.verify_app_password("второй пароль"))
        back.disable_app_password("второй пароль")
        self.assertFalse(back.read_settings()["password_enabled"])
        self.assertEqual(back._settings_read()["password_hash"], "")

    def test_native_setting_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            back = Backend2.__new__(Backend2)
            back.web = False
            back.settings = Path(directory) / "settings.txt"
            self.exercise_settings(back)

    def test_browser_setting_lifecycle_and_reload(self):
        saved = {}
        page = Mock(shared_preferences=SimpleNamespace(get=saved.get, set=saved.__setitem__))
        back = Backend2.__new__(Backend2)
        back.web = True
        back.store = WebSessionStore(page)
        self.exercise_settings(back)
        back.set_app_password("сохранённый пароль")
        asyncio.run(back.store._persist_async())
        back.store = WebSessionStore(page)
        asyncio.run(back.store.load())
        self.assertTrue(back.read_settings()["password_enabled"])
        self.assertTrue(back.verify_app_password("сохранённый пароль"))
        self.assertNotIn("сохранённый пароль", str(saved))


class SecurityUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_enable_validate_change_and_disable(self):
        front = make_front(phone=True)
        controls = front.utils2.build_widgets_for_security(front.page).controls
        switch, _, current, password, confirmation, save, status = controls
        self.assertFalse(current.visible)
        self.assertFalse(password.visible)
        self.assertFalse(save.visible)
        switch.value = True
        switch.on_change(None)
        self.assertTrue(password.visible)
        self.assertFalse(front.back2.read_settings()["password_enabled"])
        password.value, confirmation.value = "пароль", "ошибка"
        await save.on_click(None)
        self.assertIn("не совпадают", status.value)
        self.assertFalse(front.back2.read_settings()["password_enabled"])
        confirmation.value = "пароль"
        await save.on_click(None)
        self.assertTrue(front.back2.verify_app_password("пароль"))
        self.assertTrue(current.visible)
        self.assertEqual(password.value, "")
        current.value = "пароль"
        password.value = confirmation.value = "новый пароль"
        await confirmation.on_submit(None)
        self.assertTrue(front.back2.verify_app_password("новый пароль"))
        switch.value = False
        switch.on_change(None)
        self.assertFalse(password.visible)
        self.assertTrue(current.visible)
        current.value = "неверный пароль"
        await save.on_click(None)
        self.assertTrue(front.back2.read_settings()["password_enabled"])
        self.assertIn("неверный", status.value)
        current.value = "новый пароль"
        await save.on_click(None)
        self.assertFalse(front.back2.read_settings()["password_enabled"])
        self.assertFalse(current.visible)
        self.assertFalse(save.visible)

    async def test_security_opens_a_fresh_dialog_and_back_returns_to_settings(self):
        for web in (False, True):
            with self.subTest(web=web):
                front = make_front()
                front.web = web
                front.page.push_route = AsyncMock()
                front.cloud.read_user_data_text.return_value = "account~~login~~password"
                front.cloud.load_account_encryption.return_value = False
                front.open_settings()
                settings_screen = front.modified_dialog
                security = next(control for control in front.utils2.settings_cont.content.controls
                                if isinstance(control, ft.Button)
                                and control.content.controls[1].value.strip() == "Безопасность")
                await security.on_click(None)
                first = front.modified_dialog2
                if web:
                    self.assertIs(front.screen_host.content, first)
                else:
                    self.assertIs(front.page.views[-1].controls[0], first)
                # Build the dialog controls again when reopening the category.
                front.close_page()
                if web:
                    self.assertIs(front.screen_host.content, settings_screen)
                await security.on_click(None)
                self.assertIsNot(front.modified_dialog2, first)

    async def test_account_encryption_ui_applies_on_toggle_and_restores_on_failure(self):
        front = make_front()
        front.cloud.read_user_data_text.return_value = "account~~login~~password"
        front.cloud.load_account_encryption.return_value = True
        widgets, load = front.utils2.build_widgets_for_account_encryption(front.page)
        switch, _, status = widgets.controls
        self.assertTrue(switch.disabled)
        await load()
        self.assertFalse(switch.disabled)
        switch.value = False
        front.cloud.set_account_encryption.side_effect = OSError("offline")
        await switch.on_change(None)
        self.assertIn("Не удалось", status.value)
        self.assertTrue(switch.value)
        self.assertFalse(switch.disabled)
        front.cloud.set_account_encryption.side_effect = None
        switch.value = False
        await switch.on_change(None)
        front.cloud.set_account_encryption.assert_called_with("account", False)
        self.assertIn("отключено", status.value)
        self.assertFalse(switch.value)
        self.assertFalse(switch.disabled)

    async def test_guest_and_failed_loading_cannot_change_encryption(self):
        front = make_front()
        for account in ("", "account~~login~~password"):
            front.cloud.read_user_data_text.return_value = account
            front.cloud.load_account_encryption.side_effect = OSError("offline")
            widgets, load = front.utils2.build_widgets_for_account_encryption(front.page)
            await load()
            switch, _, status = widgets.controls
            self.assertTrue(switch.disabled)
            self.assertTrue(status.value)

    async def test_lock_blocks_navigation_until_correct_password_on_both_platforms(self):
        for web in (False, True):
            with self.subTest(web=web):
                front = make_front()
                front.back2.set_app_password("пароль входа")
                front.web = web
                front._app_locked = True
                front.show_app_lock()
                if web:
                    body = front.screen_host.content
                else:
                    self.assertEqual(front.page.views[0].route, "/unlock")
                    body = front.page.views[0].controls[0]
                _, _, password, unlock, status = body.content.content.controls
                front.update_tasks = Mock()
                front.notification_service.start.reset_mock()
                front.auto_update_service.start.reset_mock()
                front.close_page()
                front.exit_from_pc(Mock(key="Escape"))
                front._on_view_pop()
                front.show_groups()
                self.assertTrue(front._app_locked)
                if web:
                    self.assertIs(front.screen_host.content, body)
                else:
                    self.assertEqual(front.page.views[0].route, "/unlock")
                password.value = "ошибка"
                await password.on_submit(None)
                self.assertIn("Неверный пароль", status.value)
                self.assertEqual(password.value, "")
                front.update_tasks.assert_not_called()
                front.notification_service.start.assert_not_called()
                front.auto_update_service.start.assert_not_called()
                password.value = "пароль входа"
                await unlock.on_click(None)
                self.assertFalse(front._app_locked)
                self.assertEqual(password.value, "")
                front.update_tasks.assert_called_once_with(front.show_start_screen)
                front.notification_service.start.assert_called_once()
                front.auto_update_service.start.assert_called_once()

    async def test_theme_change_keeps_lock_screen(self):
        front = make_front()
        front._app_locked = True
        front.show_app_lock()
        with ExitStack() as stack:
            for target in ("Backend.core.Cloud", "Backend.extended.Cloud"):
                stack.enter_context(patch(target, return_value=Mock(connect=True)))
            front.apply_theme_style("dark")
        self.assertTrue(front._app_locked)
        self.assertIsNone(front._groups_screen)
        self.assertEqual(front.screen_host.content.content.content.controls[1].value,
                         "Вход в приложение")

    async def test_protected_start_does_not_start_services_or_load_tasks(self):
        front = make_front()
        front.back2.set_app_password("пароль")
        page, store = front.page, front.web_store
        page.views.clear()
        with ExitStack() as stack:
            for target in ("Frontend.init_page.Cloud", "Backend.core.Cloud",
                           "Backend.extended.Cloud", "Frontend.init_page.NotificationService",
                           "Frontend.init_page.AutoUpdateService"):
                stack.enter_context(patch(target, return_value=Mock(connect=True)))
            update = stack.enter_context(patch.object(Front, "update_tasks"))
            protected = Front(page, store)
        self.assertTrue(protected._app_locked)
        update.assert_not_called()
        protected.notification_service.setup.assert_not_called()
        protected.notification_service.start.assert_not_called()
        protected.auto_update_service.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
