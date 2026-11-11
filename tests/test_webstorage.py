import asyncio
import json
import unittest
from types import SimpleNamespace

from flet.controls.exceptions import FletException

from Backend.extended import Backend2
from Backend.storage import empty_data
from Backend.webstorage import WebSessionStore


class BrowserPage:
    """A browser's preferences shared by successive page sessions."""

    def __init__(self, values):
        self.tasks = []
        self.writes = []

        async def get_value(key):
            return values.get(key)

        async def set_value(key, value):
            self.writes.append(key)
            values[key] = value
            return True

        self.shared_preferences = SimpleNamespace(get=get_value, set=set_value)

    def run_task(self, handler, *args):
        task = asyncio.create_task(handler(*args))
        self.tasks.append(task)
        return task

    async def flush(self):
        await asyncio.gather(*self.tasks)
        self.tasks.clear()


def settings_backend(store):
    back = Backend2.__new__(Backend2)
    back.web = True
    back.phone = False
    back.store = store
    return back


class BrowserStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_and_authorization_survive_a_new_page_session(self):
        values = {}
        page = BrowserPage(values)
        store = WebSessionStore(page)
        back = settings_backend(store)
        back.set_default_settings()
        changes = {
            "theme_style": "nord",
            "font_size": "large",
            "action_panel_position": "left",
            "group_panel_position": "bottom",
            "animated_wallpaper": "none",
            "border": True,
            "dialog_animations": False,
        }
        for key, value in changes.items():
            back.redact_setting(key, value)
        store.write_meta_text("user_data", "account~~login~~password")
        await page.flush()

        restored = WebSessionStore(BrowserPage(values))
        await restored.load()
        reopened = settings_backend(restored)
        reopened.set_default_settings()
        self.assertEqual({key: reopened.read_settings()[key] for key in changes}, changes)
        self.assertEqual(restored.read_meta_text("user_data"), "account~~login~~password")
        self.assertNotIn(store.DATA_KEY, page.writes)

        other_browser = WebSessionStore(BrowserPage({}))
        await other_browser.load()
        self.assertEqual(other_browser.read_settings_text(), {})
        self.assertEqual(other_browser.read_meta_text("user_data"), "")

    async def test_settings_change_does_not_rewrite_tasks_or_account_metadata(self):
        values = {
            WebSessionStore.DATA_KEY: json.dumps(empty_data()),
            WebSessionStore.META_KEY: json.dumps({"user_data": "account"}),
        }
        original = dict(values)
        page = BrowserPage(values)
        store = WebSessionStore(page)
        await store.load()
        store.write_settings_text({"theme_style": "nord"})
        await page.flush()
        self.assertEqual(page.writes, [store.SETTINGS_KEY])
        for key, value in original.items():
            self.assertEqual(values[key], value)

    async def test_bad_data_does_not_prevent_loading_settings_or_authorization(self):
        for error in ("invalid json", FletException("read failed"), TimeoutError()):
            with self.subTest(error=type(error).__name__):
                values = {
                    WebSessionStore.DATA_KEY: error,
                    WebSessionStore.SETTINGS_KEY: json.dumps({"theme_style": "nord"}),
                    WebSessionStore.META_KEY: json.dumps({"user_data": "account"}),
                }
                page = BrowserPage(values)

                async def get_value(key):
                    value = values.get(key)
                    if isinstance(value, Exception):
                        raise value
                    return value

                page.shared_preferences.get = get_value
                store = WebSessionStore(page)
                with self.assertLogs("Backend.webstorage", level="WARNING"):
                    await store.load()
                self.assertEqual(store.read_settings_text(), {"theme_style": "nord"})
                self.assertEqual(store.read_meta_text("user_data"), "account")
                self.assertEqual(store.load_all_sections(), empty_data())

    async def test_corrupt_settings_do_not_hide_saved_tasks_or_account(self):
        data = empty_data()
        data["tasks"] = [{"id": "saved", "name": "Saved task"}]
        store = WebSessionStore(BrowserPage({
            WebSessionStore.SETTINGS_KEY: "broken json",
            WebSessionStore.META_KEY: json.dumps({"user_data": "account"}),
            WebSessionStore.DATA_KEY: json.dumps(data),
        }))
        with self.assertLogs("Backend.webstorage", level="WARNING"):
            await store.load()
        self.assertEqual(store.read_settings_text(), {})
        self.assertEqual(store.load_all_sections(), data)
        self.assertEqual(store.read_meta_text("user_data"), "account")

    async def test_failed_write_does_not_skip_other_storage_keys(self):
        for failed_key in (WebSessionStore.DATA_KEY, WebSessionStore.META_KEY,
                           WebSessionStore.SETTINGS_KEY):
            with self.subTest(failed_key=failed_key):
                values = {}
                page = BrowserPage(values)
                set_value = page.shared_preferences.set

                async def fail_one_key(key, value):
                    if key == failed_key:
                        raise FletException("QuotaExceededError")
                    return await set_value(key, value)

                page.shared_preferences.set = fail_one_key
                store = WebSessionStore(page)
                store._settings = {"theme_style": "nord"}
                store._meta = {"user_data": "account"}
                with self.assertLogs("Backend.webstorage", level="WARNING"):
                    await store._persist_async()
                self.assertNotIn(failed_key, values)
                self.assertEqual(len(values), 2)

    async def test_slower_old_write_cannot_overwrite_latest_settings(self):
        values = {}
        page = BrowserPage(values)
        set_value = page.shared_preferences.set
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_first_write(key, value):
            if key == WebSessionStore.SETTINGS_KEY and json.loads(value)["theme_style"] == "nord":
                started.set()
                await release.wait()
            return await set_value(key, value)

        page.shared_preferences.set = slow_first_write
        store = WebSessionStore(page)
        store.write_settings_text({"theme_style": "nord"})
        await asyncio.wait_for(started.wait(), timeout=2)
        store.write_settings_text({"theme_style": "chatgpt", "border": "True"})
        # Let the newer background task run while the old browser reply waits.
        await asyncio.sleep(0)
        release.set()
        await page.flush()

        restored = WebSessionStore(BrowserPage(values))
        await restored.load()
        self.assertEqual(restored.read_settings_text(), {
            "theme_style": "chatgpt", "border": "True",
        })

    async def test_preferences_service_is_retained_between_load_and_save(self):
        values = {}

        class ServicePage(BrowserPage):
            @property
            def shared_preferences(self):
                self.service_requests += 1
                return self.service

            @shared_preferences.setter
            def shared_preferences(self, service):
                self.service = service
                self.service_requests = 0

        page = ServicePage(values)
        store = WebSessionStore(page)
        await store.load()
        store.write_settings_text({"border": "True"})
        store.write_meta_text("user_data", "account")
        await page.flush()
        self.assertEqual(page.service_requests, 1)
        self.assertEqual(json.loads(values[store.SETTINGS_KEY]), {"border": "True"})

    async def test_slow_data_write_does_not_delay_saving_settings(self):
        values = {}
        page = BrowserPage(values)
        set_value = page.shared_preferences.set
        data_started = asyncio.Event()
        release_data = asyncio.Event()
        settings_saved = asyncio.Event()

        async def slow_data_write(key, value):
            if key == WebSessionStore.DATA_KEY:
                data_started.set()
                await release_data.wait()
            result = await set_value(key, value)
            if key == WebSessionStore.SETTINGS_KEY:
                settings_saved.set()
            return result

        page.shared_preferences.set = slow_data_write
        store = WebSessionStore(page)
        data = empty_data()
        data["tasks"] = [{"id": "saved", "name": "Saved task"}]
        store.save_all_sections(data)
        await asyncio.wait_for(data_started.wait(), timeout=2)
        try:
            store.write_settings_text({"theme_style": "nord"})
            await asyncio.wait_for(settings_saved.wait(), timeout=2)
            self.assertNotIn(store.DATA_KEY, values)
            self.assertEqual(json.loads(values[store.SETTINGS_KEY]), {"theme_style": "nord"})
        finally:
            release_data.set()
            await page.flush()


if __name__ == "__main__":
    unittest.main()
