import unittest
from unittest.mock import Mock
from Frontend.init_page import Front
from Backend.cloud import Cloud
from Backend.dropbox_disk import DropboxDiskError
from test_ui_state import make_front


class CloudAuthErrorTests(unittest.TestCase):
    def test_successful_login_does_not_request_another_account_download(self):
        import asyncio

        front = Front.__new__(Front)
        front.page = Mock()
        front.libs = Mock()
        front.cloud = Mock()
        front.cloud.alg_for_login.return_value = {'Connect': True, 'Have account': True, 'Completed': True}
        front._open_loading_view = Mock(return_value='loading')
        front._close_loading_view = Mock()
        front.update_tasks = Mock()
        front.show_groups = Mock()
        front.login('user', 'password')
        asyncio.run(front.page.run_task.call_args.args[0]())
        front.update_tasks.assert_called_once_with(front.show_groups, refresh_cloud=False)

    def test_render_after_login_still_synchronizes_shared_groups(self):
        import asyncio

        for loading_screen in (False, True):
            with self.subTest(loading_screen=loading_screen):
                front = make_front()
                settings = dict(front.back2.read_settings(), load_screen=loading_screen)
                front.back2.read_settings = Mock(return_value=settings)
                front._open_loading_view = Mock(return_value='loading')
                front._close_loading_view = Mock()
                front._update_control = Mock()
                front.update_tasks(refresh_cloud=False)
                if loading_screen:
                    asyncio.run(front.page.run_task.call_args.args[0]())
                front.cloud.alg_for_start_app.assert_not_called()
                front.cloud.sync_shared_groups.assert_called_once()

    def test_failed_login_download_does_not_save_account_credentials(self):
        cloud = Cloud.__new__(Cloud)
        cloud.connect = True
        cloud.exists_on_cloud = Mock(return_value=True)
        cloud.check_user_data = Mock(return_value=True)
        cloud.download = Mock(return_value=False)
        cloud.write_user_data_text = Mock()
        cloud.write_accounts_text = Mock()
        with self.assertRaises(DropboxDiskError):
            cloud.alg_for_login('user', 'password')
        cloud.write_user_data_text.assert_not_called()
        cloud.write_accounts_text.assert_not_called()

    def test_cloud_authentication_errors_are_shown_without_private_details(self):
        import asyncio
        for action, cloud_method in (("login", "alg_for_login"), ("register", "alg_for_regist")):
            with self.subTest(action=action):
                front = Front.__new__(Front)
                front.page = Mock()
                front.libs = Mock()
                front.cloud = Mock()
                getattr(front.cloud, cloud_method).side_effect = RuntimeError("private session token")
                front._open_loading_view = Mock(return_value="loading")
                front._close_loading_view = Mock()
                getattr(front, action)("user", "password")
                callback = front.page.run_task.call_args.args[0]
                asyncio.run(callback())
                front._close_loading_view.assert_called_once_with("loading")
                message = front.libs.open_dialog.call_args.args[1]
                self.assertIn("Dropbox", message)
                self.assertNotIn("private session token", message)

