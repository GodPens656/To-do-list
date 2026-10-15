import unittest
from unittest.mock import patch

import requests

from Backend.cloud import Cloud


class CloudConnectionTests(unittest.TestCase):
    def test_checks_website_without_dropbox_credentials(self):
        cloud = Cloud.__new__(Cloud)
        with patch("Backend.cloud.requests.get") as get, \
                patch("Backend.cloud.DropboxDisk") as disk:
            self.assertTrue(cloud.check_connect())
            get.assert_called_once_with("https://dropbox.com", timeout=5, stream=True)
            get.return_value.__enter__.return_value.raise_for_status.assert_called_once_with()
            get.return_value.__exit__.assert_called_once()
            disk.assert_not_called()

    def test_network_failures_switch_to_offline_mode(self):
        cloud = Cloud.__new__(Cloud)
        for error in (requests.Timeout, requests.ConnectionError):
            with self.subTest(error=error), \
                    patch("Backend.cloud.requests.get", side_effect=error):
                self.assertFalse(cloud.check_connect())

    def test_http_failure_switches_to_offline_mode_and_closes_response(self):
        cloud = Cloud.__new__(Cloud)
        with patch("Backend.cloud.requests.get") as get:
            response = get.return_value.__enter__.return_value
            response.raise_for_status.side_effect = requests.HTTPError
            self.assertFalse(cloud.check_connect())
            get.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
