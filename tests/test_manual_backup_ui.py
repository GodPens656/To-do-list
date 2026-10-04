import asyncio
import unittest
from unittest.mock import Mock, patch

from Frontend.libs import Fr_Libs
from Frontend.settings import Utils2


class ManualBackupUiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Utils2.__new__(Utils2)
        self.settings.libs = Fr_Libs('light', False)
        self.settings.TxtColor = self.settings.libs.TxtColor
        self.settings.back = Mock()
        self.settings.back2 = Mock()
        self.settings.cloud = Mock()
        self.settings.cloud.read_user_data_text.return_value = 'user_password~~user~~password'
        controls = self.settings.build_widgets_for_management_tasks(Mock()).content.controls
        self.button, self.status = controls[-2:]

    async def test_success_and_daily_limit_feedback(self):
        for created, message in ((True, 'Бэкап отправлен'), (False, 'уже есть')):
            self.settings.cloud.create_manual_backup.return_value = created
            await self.button.on_click(None)
            self.assertIn(message, self.status.value)
            self.assertIn('завтра', self.status.value)
            self.assertFalse(self.button.disabled)

    async def test_guest_is_prompted_to_sign_in(self):
        self.settings.cloud.read_user_data_text.return_value = ''
        await self.button.on_click(None)
        self.assertIn('Войдите в аккаунт', self.status.value)
        self.settings.cloud.create_manual_backup.assert_not_called()
        self.assertFalse(self.button.disabled)

    async def test_failure_allows_retry_without_exposing_account_data(self):
        self.settings.cloud.create_manual_backup.side_effect = [
            TimeoutError('user_password'), True,
        ]
        await self.button.on_click(None)
        self.assertIn('попробуйте ещё раз', self.status.value)
        self.assertNotIn('user_password', self.status.value)
        self.assertFalse(self.button.disabled)
        await self.button.on_click(None)
        self.assertIn('Бэкап отправлен', self.status.value)

    async def test_double_click_is_ignored_while_sending(self):
        started = asyncio.Event()
        finish = asyncio.Event()

        async def pending_send(function):
            started.set()
            await finish.wait()
            return True

        with patch('Frontend.settings.asyncio.to_thread', side_effect=pending_send) as send:
            first_click = asyncio.create_task(self.button.on_click(None))
            await started.wait()
            self.assertTrue(self.button.disabled)
            await self.button.on_click(None)
            send.assert_called_once()
            finish.set()
            await first_click
        self.assertFalse(self.button.disabled)

    async def test_account_change_does_not_show_success_for_new_account(self):
        self.settings.cloud.read_user_data_text.side_effect = [
            'user_password~~user~~password', '',
        ]
        await self.button.on_click(None)
        self.assertIn('Аккаунт изменился', self.status.value)


if __name__ == '__main__':
    unittest.main()
