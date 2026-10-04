import asyncio
import sys
import unittest
from contextlib import ExitStack
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from Backend.notifications import NotificationService
from Backend.webstorage import WebSessionStore
from Frontend.init_page import Front


@ft.control("TestNativeService")
class NativeServiceStub(ft.Service):
    pass


class NativeServicesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.page = ft.Page(
            sess=Mock(), web=False, width=360, height=800,
            platform_brightness=ft.Brightness.LIGHT,
        )
        self.root = self.page.views[0]
        self.store = WebSessionStore(Mock())
        # Real Flet Page/services and real notification setup, with only
        # the platform extensions, transport, cloud and workers replaced.
        permission = ModuleType("flet_permission_handler")
        permission.PermissionHandler = Mock(side_effect=NativeServiceStub)
        permission_types = ModuleType("flet_permission_handler.types")
        permission_types.Permission = SimpleNamespace(NOTIFICATION="notification")
        notifications = ModuleType("flet_local_notifications")
        notifications.LocalNotifications = Mock(side_effect=NativeServiceStub)
        self.stack.enter_context(patch.dict(sys.modules, {
            permission.__name__: permission,
            permission_types.__name__: permission_types,
            notifications.__name__: notifications,
        }))
        for target in (
            "Frontend.init_page.Cloud", "Backend.core.Cloud", "Backend.extended.Cloud",
            "Frontend.init_page.AutoUpdateService",
        ):
            self.stack.enter_context(patch(target, return_value=Mock(connect=True)))
        self.stack.enter_context(patch("Backend.core.Backend.get_device", return_value=True))
        self.stack.enter_context(patch.object(ft.Page, "update"))
        self.run_task = self.stack.enter_context(patch.object(ft.Page, "run_task"))
        self.stack.enter_context(patch.object(ft.Page, "push_route", new_callable=AsyncMock))
        self.update_tasks = self.stack.enter_context(patch.object(Front, "update_tasks"))

    def assert_services_attached(self, front):
        self.assertIs(self.page.views[0], self.root)
        self.assertEqual(self.page.services, [
            front.notification_service.permission_handler,
            front.notification_service.notifications,
        ])
        self.assertEqual(len(self.page.services), 2)

    async def test_android_start_registers_services_on_existing_root(self):
        front = Front(self.page, self.store)
        self.assertIsInstance(front.notification_service, NotificationService)
        self.assert_services_attached(front)
        self.run_task.assert_called_once_with(front.notification_service._init_android_services)
        self.update_tasks.assert_called_once_with(front.show_start_screen)

    async def test_loading_navigation_and_theme_keep_android_services(self):
        front = Front(self.page, self.store)
        services = list(self.page.services)
        front._open_loading_view()
        front.show_groups()
        self.assert_services_attached(front)
        self.assertEqual(self.page.views[0].route, "/groups")
        front.show_groups()
        front.apply_theme_style("dark")
        self.assert_services_attached(front)
        self.assertEqual(self.page.services, services)
        self.assertEqual(len(self.page.views), 1)
        await asyncio.sleep(0)

    async def test_unlock_creates_services_without_emptying_views(self):
        self.store._settings = {"password_enabled": "True"}
        front = Front(self.page, self.store)
        self.assertEqual(self.page.views[0].route, "/unlock")
        self.assertEqual(self.page.services, [])
        self.run_task.assert_not_called()
        self.update_tasks.assert_not_called()
        body = self.root.controls[0]
        _, _, password, unlock, _ = body.content.content.controls
        password.value = "password"
        with patch.object(front.back2, "verify_app_password", return_value=True):
            await unlock.on_click(None)
        self.assertFalse(front._app_locked)
        self.assert_services_attached(front)
        self.update_tasks.assert_called_once_with(front.show_start_screen)


if __name__ == "__main__":
    unittest.main()
