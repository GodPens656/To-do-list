"""Android packaging regression for Pasteboard's missing provider metadata."""

from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from build_android import ANDROID, AUTHORITY, configure_clipboard_provider, main


A = f"{{{ANDROID}}}"


class AndroidClipboardBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.android_main = self.project / "android/app/src/main"
        self.android_main.mkdir(parents=True)
        self.manifest = self.android_main / "AndroidManifest.xml"

    def write_manifest(self, provider=""):
        self.manifest.write_text(f'''<manifest xmlns:android="{ANDROID}"
            xmlns:tools="http://schemas.android.com/tools">
            <uses-permission android:name="android.permission.INTERNET" />
            <application android:label="Мои дела" tools:replace="android:label">
                <!-- Keep the existing activity and notification setup. -->
                <activity android:name=".MainActivity" android:exported="true" />
                {provider}
            </application>
        </manifest>''', encoding="utf-8")

    def provider(self):
        return ET.parse(self.manifest).find("application/provider")

    def test_missing_provider_gets_metadata_and_only_private_cache_access(self):
        self.write_manifest()
        configure_clipboard_provider(self.project)
        provider = self.provider()
        self.assertEqual(provider.get(A + "authorities"), AUTHORITY)
        self.assertEqual(provider.get(A + "exported"), "false")
        self.assertEqual(provider.get(A + "grantUriPermissions"), "true")
        metadata = provider.find("meta-data")
        self.assertEqual(metadata.get(A + "name"), "android.support.FILE_PROVIDER_PATHS")
        self.assertEqual(metadata.get(A + "resource"), "@xml/provider_paths")
        paths_file = self.android_main / "res/xml/provider_paths.xml"
        paths = ET.parse(paths_file).getroot()
        self.assertEqual([p.tag for p in paths], ["cache-path"])
        self.assertEqual(paths[0].get("path"), ".")
        result = self.manifest.read_text(encoding="utf-8")
        self.assertIn("Keep the existing activity", result)
        self.assertIn('tools:replace="android:label"', result)
        manifest = ET.parse(self.manifest)
        self.assertEqual(manifest.find("application").get(A + "label"), "Мои дела")
        self.assertEqual(manifest.find("application/activity").get(A + "name"), ".MainActivity")
        self.assertEqual([p.get(A + "name") for p in manifest.findall("uses-permission")],
                         ["android.permission.INTERNET"])

        # Rebuilding or re-running --patch-only must not rewrite either file.
        originals = [p.read_bytes() for p in (self.manifest, paths_file)]
        configure_clipboard_provider(self.project)
        self.assertEqual([p.read_bytes() for p in (self.manifest, paths_file)], originals)

    def test_existing_provider_and_custom_paths_are_repaired_without_duplicates(self):
        self.write_manifest('''<provider android:name="androidx.core.content.FileProvider"
            android:authorities="com.GodPens.to_do.oldprovider">
            <meta-data android:name="android.support.FILE_PROVIDER_PATHS"
                       android:resource="@xml/custom_paths" />
        </provider>''')
        paths_file = self.android_main / "res/xml/custom_paths.xml"
        paths_file.parent.mkdir(parents=True)
        paths_file.write_text('''<paths>
            <files-path name="documents" path="documents/" />
            <cache-path name="clipboard_images" path="other-plugin/" />
        </paths>''', encoding="utf-8")
        configure_clipboard_provider(self.project)
        providers = ET.parse(self.manifest).findall("application/provider")
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].get(A + "authorities"),
                         "com.GodPens.to_do.oldprovider;" + AUTHORITY)
        paths = ET.parse(paths_file).getroot()
        self.assertEqual(paths.find("files-path").get("path"), "documents/")
        self.assertEqual([p.get("path") for p in paths.findall("cache-path")],
                         ["other-plugin/", "."])
        self.assertEqual(len({p.get("name") for p in paths}), len(paths))
        self.assertFalse((paths_file.parent / "provider_paths.xml").exists())

    def test_valid_existing_provider_resource_is_preserved_byte_for_byte(self):
        self.write_manifest(f'''<provider android:name="androidx.core.content.FileProvider"
            android:authorities="{AUTHORITY}" android:exported="false" android:grantUriPermissions="true">
            <meta-data android:name="android.support.FILE_PROVIDER_PATHS"
                       android:resource="@xml/provider_paths" />
        </provider>''')
        paths = self.android_main / "res/xml/provider_paths.xml"
        paths.parent.mkdir(parents=True)
        paths.write_text('<paths><cache-path name="cache" path="." /></paths>', encoding="utf-8")
        originals = self.manifest.read_bytes(), paths.read_bytes()
        configure_clipboard_provider(self.project)
        self.assertEqual((self.manifest.read_bytes(), paths.read_bytes()), originals)

    def test_missing_or_invalid_android_project_does_not_write_files(self):
        with self.assertRaisesRegex(ValueError, "AndroidManifest.xml"):
            configure_clipboard_provider(self.project)
        self.write_manifest('''<provider android:name="androidx.core.content.FileProvider"
            android:authorities="${applicationId}.provider">
            <meta-data android:name="android.support.FILE_PROVIDER_PATHS"
                       android:resource="@xml/../../unexpected" />
        </provider>''')
        original = self.manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, "ресурс"):
            configure_clipboard_provider(self.project)
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assertFalse((self.android_main / "res").exists())

    def test_build_repairs_regenerated_manifest_before_invoking_flutter(self):
        calls = []
        test = self

        class FletBuildStub:
            def __init__(self, parser):
                parser.add_argument("target")
                parser.add_argument("--org")
                parser.add_argument("--project")

            def handle(self, options):
                calls.append((options.target, options.org, options.project))
                self.flutter_dir = test.project
                test.write_manifest()  # Simulate Flet regenerating Android files.
                self.run_flutter()

            def run_flutter(self):
                test.assertEqual(test.provider().get(A + "authorities"), AUTHORITY)
                calls.append("flutter build")

        build = ModuleType("flet_cli.commands.build")
        build.Command = FletBuildStub
        with patch.dict(sys.modules, {build.__name__: build}):
            main(["--org", "com.GodPens", "--project", "to_do"])
        self.assertEqual(calls, [("apk", "com.GodPens", "to_do"), "flutter build"])


if __name__ == "__main__":
    unittest.main()
