import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.app_updates import AppUpdate
from Backend.version import APP_VERSION
from Frontend.app_updates import ApplicationUpdatePrompt, check_for_update
from test_ui_state import make_front


UPDATE = AppUpdate("3.16.0", "To-Do.apk", "https://github.com/GodPens656/To-do-list/releases/download/3.16.0/To-Do.apk")


class AppUpdateUiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.front = make_front()
        self.page = self.front.page
        self.page.web = False
        self.page.platform = ft.PagePlatform.ANDROID
        self.page.services = []
        self.prompt = ApplicationUpdatePrompt(self.page, lambda: self.front.libs)

    async def test_start_is_once_per_session_and_skips_web_or_unsupported_platform(self):
        self.page.run_task.reset_mock()
        self.page.web = True
        self.prompt.start()
        self.page.run_task.assert_not_called()
        self.page.web = False
        self.page.platform = ft.PagePlatform.IOS
        self.prompt.start()
        self.page.run_task.assert_not_called()
        self.page.platform = ft.PagePlatform.ANDROID
        self.prompt.start()
        self.prompt.start()
        self.page.run_task.assert_called_once_with(self.prompt._check, "android")

    async def test_check_is_off_event_loop_and_waits_for_startup(self):
        checked = asyncio.Event()

        async def check(*args):
            checked.set()
            return UPDATE

        with patch("Frontend.app_updates.asyncio.to_thread", side_effect=check) as worker:
            task = asyncio.create_task(self.prompt._check("android"))
            await checked.wait()
            self.page.show_dialog.assert_not_called()
            self.prompt.allow_prompt()
            await task
        worker.assert_awaited_once_with(
            check_for_update, APP_VERSION, "android",
        )
        self.page.show_dialog.assert_called_once()

    async def test_allow_prompt_from_flet_worker_thread(self):
        with patch("Frontend.app_updates.check_for_update", return_value=UPDATE):
            task = asyncio.create_task(self.prompt._check("android"))
            await asyncio.to_thread(self.prompt.allow_prompt)
            await asyncio.wait_for(task, 2)
        self.page.show_dialog.assert_called_once()

    async def test_no_update_or_closed_app_does_not_show_a_dialog(self):
        self.prompt.allow_prompt()
        with patch("Frontend.app_updates.check_for_update", return_value=None):
            await self.prompt._check("android")
        self.prompt.stop()
        with patch("Frontend.app_updates.check_for_update", return_value=UPDATE):
            await self.prompt._check("android")
        self.page.show_dialog.assert_not_called()

    async def test_close_cancels_a_pending_check(self):
        self.page.run_task.reset_mock()
        self.prompt.start()
        self.prompt.stop()
        self.page.run_task.return_value.cancel.assert_called_once()
        self.prompt.start()
        self.page.run_task.assert_called_once()

    async def test_later_closes_without_downloading_and_ignores_repeated_clicks(self):
        self.prompt._show(UPDATE)
        dialog = self.page.show_dialog.call_args.args[0]
        self.assertTrue(dialog.modal)
        later, download = dialog.actions
        with patch.object(ft.UrlLauncher, "launch_url", new_callable=AsyncMock) as launch:
            later.on_click(None)
            later.on_click(None)
            await download.on_click(None)
        launch.assert_not_awaited()
        self.page.pop_dialog.assert_called_once()

    async def test_download_opens_selected_asset_in_external_browser(self):
        self.prompt._show(UPDATE)
        dialog = self.page.show_dialog.call_args.args[0]
        with patch.object(ft.UrlLauncher, "launch_url", new_callable=AsyncMock) as launch:
            await dialog.actions[1].on_click(None)
            await dialog.actions[1].on_click(None)
        launch.assert_awaited_once_with(UPDATE.download_url, mode=ft.LaunchMode.EXTERNAL_APPLICATION)
        self.page.pop_dialog.assert_called_once()

    async def test_launch_failure_keeps_retry_and_later_available(self):
        self.prompt._show(UPDATE)
        dialog = self.page.show_dialog.call_args.args[0]
        later, download = dialog.actions
        with patch.object(ft.UrlLauncher, "launch_url", new_callable=AsyncMock) as launch:
            launch.side_effect = RuntimeError("Browser unavailable")
            await download.on_click(None)
            self.page.pop_dialog.assert_not_called()
            self.assertFalse(download.disabled)
            self.assertFalse(later.disabled)
            status = dialog.content.content.controls[-1]
            self.assertTrue(status.visible)
            self.assertIn("Не удалось", status.value)
            launch.side_effect = None
            await download.on_click(None)
        self.page.pop_dialog.assert_called_once()

    async def test_first_launch_agreement_controls_when_update_can_appear(self):
        prompt = self.front.application_updates
        self.assertFalse(prompt._prompt_allowed)
        self.front.show_start_screen()
        self.assertFalse(prompt._prompt_allowed)
        notes = self.page.show_dialog.call_args.args[0]
        notes.actions[0].on_click(None)
        self.assertFalse(prompt._prompt_allowed)
        self.front.open_auth_dialog = Mock()
        notes.on_dismiss(None)
        self.assertTrue(prompt._prompt_allowed)

    async def test_native_front_starts_the_check_and_cancels_it_on_close(self):
        page = Mock(
            web=False, width=1100, height=800, platform=ft.PagePlatform.WINDOWS,
            platform_brightness=ft.Brightness.LIGHT, views=[], overlay=[],
            client_user_agent="desktop", _nd_timezone="Europe/Moscow",
        )
        front = make_front(page=page)
        page.run_task.assert_any_call(front.application_updates._check, "windows")
        task = front.application_updates._task
        page.on_close()
        task.cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
