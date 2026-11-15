import unittest
from unittest.mock import Mock, patch

import requests

from Backend.app_updates import LATEST_RELEASE_URL, check_for_update


DOWNLOAD_PREFIX = "https://github.com/GodPens656/To-do-list/releases/download/3.16.0/"


def asset(name, **values):
    return {"name": name, "browser_download_url": DOWNLOAD_PREFIX + name, **values}


class AppUpdateTests(unittest.TestCase):
    def setUp(self):
        self.release = {
            "tag_name": "3.16.0", "draft": False, "prerelease": False,
            "assets": [asset("To-Do.apk"), asset("To-do.list.2.zip")],
        }
        response = Mock()
        response.json.side_effect = lambda: self.release
        request = patch("Backend.app_updates.requests.get")
        self.request = request.start()
        self.addCleanup(request.stop)
        self.request.return_value.__enter__.return_value = response
        self.response = response

    def check(self, target="windows", current="3.15.0", machine="AMD64"):
        return check_for_update(current, target, machine=machine)

    def test_existing_release_filenames_select_the_correct_platform(self):
        for target, filename in (("windows", "To-do.list.2.zip"), ("android", "To-Do.apk")):
            with self.subTest(target=target):
                update = self.check(target)
                self.assertEqual(update.version, "3.16.0")
                self.assertEqual(update.asset_name, filename)
                self.assertEqual(update.download_url, DOWNLOAD_PREFIX + filename)
                self.assertEqual(
                    update.release_url, "https://github.com/GodPens656/To-do-list/releases/tag/3.16.0",
                )
        self.request.assert_called_with(
            LATEST_RELEASE_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "To-do-list/3.15.0",
                     "X-GitHub-Api-Version": "2022-11-28"},
            timeout=(3.05, 8),
        )

    def test_numeric_versions_and_optional_v_prefix(self):
        for current, latest in (("3.9.0", "v3.10.0"), ("3.15", "3.15.1"),
                                ("3.15.0", "4.0.0+build.1")):
            with self.subTest(current=current, latest=latest):
                self.release["tag_name"] = latest
                update = self.check(current=current)
                self.assertIsNotNone(update)
                self.assertEqual(update.release_url.rsplit("/", 1)[1], latest.replace("+", "%2B"))

    def test_equal_older_and_build_metadata_do_not_offer_a_downgrade(self):
        for latest in ("3.15.0", "v3.15", "3.15.0+build.2", "3.14.0", "2.99.99"):
            with self.subTest(latest=latest):
                self.release["tag_name"] = latest
                self.assertIsNone(self.check())

    def test_draft_prerelease_and_non_version_tags_are_ignored(self):
        for change in ({"draft": True}, {"prerelease": True}, {"tag_name": "nightly"},
                       {"tag_name": "3.16.0-rc.1"}, {"tag_name": "9" * 5000}, {"tag_name": None}):
            with self.subTest(change=change):
                original = self.release.copy()
                self.release.update(change)
                self.assertIsNone(self.check())
                self.release = original

    def test_unsupported_platform_or_invalid_current_version_does_not_use_network(self):
        self.assertIsNone(self.check("ios"))
        self.assertIsNone(self.check(current="unknown"))
        self.request.assert_not_called()

    def test_timeouts_http_errors_and_invalid_json_are_nonfatal(self):
        for error in (requests.Timeout(), requests.ConnectionError(),
                      requests.HTTPError("404 / 403 / 429 / 500"), ValueError("JSON")):
            with self.subTest(error=type(error).__name__):
                self.response.raise_for_status.side_effect = error
                self.assertIsNone(self.check())
        self.response.raise_for_status.side_effect = None
        self.response.json.side_effect = ValueError("Invalid JSON")
        self.assertIsNone(self.check())

    def test_missing_or_malformed_release_and_assets_are_ignored(self):
        for release in (None, [], {}, {"tag_name": "3.16.0", "assets": None},
                        {"tag_name": "3.16.0", "assets": [None, "file", {}, asset("To-Do.apk")]}):
            with self.subTest(release=release):
                self.release = release
                self.assertIsNone(self.check())

    def test_missing_platform_build_does_not_offer_an_unusable_update(self):
        self.release["assets"] = [asset("To-do-linux.zip"), asset("To-do-macos.zip"),
                                  asset("To-Do.apk"), asset("Source.zip"), asset("To-do.pdb")]
        self.assertIsNone(self.check())
        self.release["assets"] = [asset("To-do.exe")]
        self.assertIsNone(self.check("android"))

    def test_installer_is_preferred_and_architecture_must_match(self):
        self.release["assets"] = [asset("To-do-arm64.exe"), asset("To-do-x64.zip"),
                                  asset("To-do-x64.exe"), asset("To-do-x86.exe")]
        self.assertEqual(self.check().asset_name, "To-do-x64.exe")
        self.assertEqual(self.check(machine="ARM64").asset_name, "To-do-arm64.exe")
        self.assertIsNone(self.check(machine="unknown"))

    def test_android_uses_universal_apk_or_matching_architecture(self):
        self.release["assets"] = [asset("To-do-arm64-v8a.apk"), asset("To-do-x86_64.apk")]
        self.assertEqual(self.check("android", machine="aarch64").asset_name, "To-do-arm64-v8a.apk")
        self.assertEqual(self.check("android", machine="x86_64").asset_name, "To-do-x86_64.apk")
        self.release["assets"].append(asset("To-do-universal.apk"))
        self.assertEqual(self.check("android", machine="aarch64").asset_name, "To-do-universal.apk")

    def test_unuploaded_or_external_asset_urls_are_ignored(self):
        for change in ({"state": "new"}, {"browser_download_url": "http://github.com/file.exe"},
                       {"browser_download_url": "https://example.org/file.exe"},
                       {"browser_download_url": "https://github.com/another/repo/file.exe"},
                       {"browser_download_url": "https://[broken"}):
            with self.subTest(change=change):
                self.release["assets"] = [asset("To-do.exe", **change)]
                self.assertIsNone(self.check())


if __name__ == "__main__":
    unittest.main()
