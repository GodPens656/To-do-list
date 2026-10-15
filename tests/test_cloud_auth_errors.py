import unittest
from unittest.mock import Mock
from Frontend.init_page import Front


class CloudAuthErrorTests(unittest.TestCase):
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

