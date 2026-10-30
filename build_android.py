"""Build an APK with the FileProvider required by Flet's image clipboard.

All build arguments are forwarded to ``flet build apk``. To repair an existing
Flutter project without building, use ``--patch-only path/to/flutter``.
"""

import argparse
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


ANDROID = "http://schemas.android.com/apk/res/android"
AUTHORITY = "${applicationId}.provider"
FILE_PROVIDER = "androidx.core.content.FileProvider"
PATHS_META_DATA = "android.support.FILE_PROVIDER_PATHS"


def _android(name):
    return f"{{{ANDROID}}}{name}"


def _read_xml(path):
    # Keep tools:node/tools:replace attributes and comments in existing projects.
    for _, (prefix, uri) in ET.iterparse(path, events=["start-ns"]):
        ET.register_namespace(prefix, uri)
    return ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))


def _write_if_changed(tree, path, before):
    if ET.tostring(tree.getroot()) != before:
        ET.indent(tree, space="    ")
        path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(path, encoding="utf-8", xml_declaration=True)


def configure_clipboard_provider(flutter_project):
    """Repair missing provider metadata without replacing other Android settings."""
    main = Path(flutter_project) / "android" / "app" / "src" / "main"
    manifest = main / "AndroidManifest.xml"
    if not manifest.is_file():
        raise ValueError(f"Не найден AndroidManifest.xml: {manifest}")
    ET.register_namespace("android", ANDROID)
    tree = _read_xml(manifest)
    before = ET.tostring(tree.getroot())
    application = tree.getroot().find("application")
    if application is None:
        raise ValueError(f"В {manifest} отсутствует <application>.")

    providers = application.findall("provider")
    provider = next((p for p in providers if AUTHORITY in
                     p.get(_android("authorities"), "").split(";")), None)
    if provider is None:
        # The manifest merger identifies providers by class name. Reuse an
        # existing FileProvider instead of creating a conflicting declaration.
        provider = next((p for p in providers if p.get(_android("name")) == FILE_PROVIDER), None)
        if provider is None:
            provider = ET.SubElement(application, "provider", {_android("name"): FILE_PROVIDER})
        authorities = provider.get(_android("authorities"), "")
        provider.set(_android("authorities"), f"{authorities};{AUTHORITY}" if authorities else AUTHORITY)
    provider.set(_android("exported"), "false")
    provider.set(_android("grantUriPermissions"), "true")
    metadata = next((m for m in provider.findall("meta-data")
                     if m.get(_android("name")) == PATHS_META_DATA), None)
    if metadata is None:
        metadata = ET.SubElement(provider, "meta-data", {_android("name"): PATHS_META_DATA})
    resource = metadata.get(_android("resource"), "@xml/provider_paths")
    if not re.fullmatch(r"@xml/[a-z][a-z0-9_]*", resource):
        raise ValueError(f"Неизвестный ресурс путей FileProvider: {resource}")
    metadata.set(_android("resource"), resource)
    metadata.attrib.pop(_android("value"), None)

    paths_file = main / "res" / "xml" / f"{resource.removeprefix('@xml/')}.xml"
    paths_tree = _read_xml(paths_file) if paths_file.exists() else ET.ElementTree(ET.Element("paths"))
    paths = paths_tree.getroot()
    if paths.tag != "paths":
        raise ValueError(f"В {paths_file} ожидался корневой элемент <paths>.")
    paths_before = ET.tostring(paths) if paths_file.exists() else None
    # Pasteboard.writeImage creates UUID.png directly in Context.cacheDir.
    # Only that private cache directory is needed; no storage permission.
    if not any(p.get("path") in (".", "./", "") for p in paths.findall("cache-path")):
        names = {p.get("name") for p in paths}
        name = "clipboard_images"
        while name in names:
            name += "_cache"
        ET.SubElement(paths, "cache-path", {"name": name, "path": "."})
    _write_if_changed(paths_tree, paths_file, paths_before)
    _write_if_changed(tree, manifest, before)
    return manifest


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--patch-only", type=Path, metavar="FLUTTER_PROJECT")
    options, build_args = parser.parse_known_args(argv)
    if options.patch_only is not None:
        if build_args:
            parser.error("--patch-only не принимает параметры сборки")
        print(f"FileProvider настроен: {configure_clipboard_provider(options.patch_only)}")
        return

    try:
        from flet_cli.commands.build import Command
    except ImportError as error:
        parser.error(f"Не найден Flet CLI: {error}. Установите flet-cli==0.82.0.")

    class AndroidBuildCommand(Command):
        def run_flutter(self):
            # Flet can regenerate the manifest twice. Apply the repair after
            # both passes and before Gradle merges/compiles the Android files.
            configure_clipboard_provider(self.flutter_dir)
            super().run_flutter()

    build_parser = argparse.ArgumentParser(description=__doc__)
    command = AndroidBuildCommand(build_parser)
    command.handle(build_parser.parse_args(["apk", *build_args]))


if __name__ == "__main__":
    main()
