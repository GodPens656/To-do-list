import io
import unittest
from unittest.mock import patch

from configure_dropbox import SCOPES, main


class ConfigureDropboxTests(unittest.TestCase):
    def test_offline_pkce_flow_outputs_configuration_without_app_secret(self):
        output = io.StringIO()
        with patch("configure_dropbox.input", return_value=" app-key "), \
                patch("configure_dropbox.getpass", return_value=" authorization-code "), \
                patch("configure_dropbox.DropboxOAuth2FlowNoRedirect") as flow, \
                patch("sys.stdout", output):
            flow.return_value.start.return_value = "https://www.dropbox.com/oauth2/authorize"
            flow.return_value.finish.return_value.refresh_token = "refresh-token"
            self.assertEqual(main(), 0)
        flow.assert_called_once_with("app-key", use_pkce=True,
                                     token_access_type="offline", scope=SCOPES)
        flow.return_value.finish.assert_called_once_with("authorization-code")
        self.assertIn("DROPBOX_APP_KEY = 'app-key'", output.getvalue())
        self.assertIn("DROPBOX_REFRESH_TOKEN = 'refresh-token'", output.getvalue())
        self.assertIn("ENCRYPTION_KEYWORD", output.getvalue())

    def test_failure_does_not_expose_oauth_error_details(self):
        output = io.StringIO()
        with patch("configure_dropbox.input", return_value="app"), \
                patch("configure_dropbox.getpass", return_value="code"), \
                patch("configure_dropbox.DropboxOAuth2FlowNoRedirect") as flow, \
                patch("sys.stdout", output):
            flow.return_value.start.return_value = "https://www.dropbox.com/oauth2/authorize"
            flow.return_value.finish.side_effect = RuntimeError("private authorization code")
            self.assertEqual(main(), 1)
        self.assertNotIn("private authorization code", output.getvalue())
        self.assertNotIn("DROPBOX_REFRESH_TOKEN =", output.getvalue())

    def test_missing_app_key_does_not_start_authorization(self):
        with patch("configure_dropbox.input", return_value=" "), \
                patch("configure_dropbox.DropboxOAuth2FlowNoRedirect") as flow, \
                patch("sys.stdout", io.StringIO()):
            self.assertEqual(main(), 1)
        flow.assert_not_called()

    def test_missing_refresh_token_does_not_report_success(self):
        with patch("configure_dropbox.input", return_value="app"), \
                patch("configure_dropbox.getpass", return_value="code"), \
                patch("configure_dropbox.DropboxOAuth2FlowNoRedirect") as flow, \
                patch("sys.stdout", io.StringIO()):
            flow.return_value.finish.return_value.refresh_token = None
            self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
