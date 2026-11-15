"""Неблокирующая проверка версии и предложение скачать новую сборку."""

import asyncio

import flet as ft

from Backend.app_updates import SUPPORTED_PLATFORMS, check_for_update
from Backend.version import APP_VERSION
from .links import _url_launcher


class ApplicationUpdatePrompt:
    def __init__(self, page, get_libs):
        self.page = page
        self.get_libs = get_libs
        self._ready = asyncio.Event()
        self._prompt_allowed = False
        self._loop = None
        self._started = False
        self._stopped = False
        self._task = None

    def start(self):
        target = getattr(self.page.platform, "value", self.page.platform)
        if self._started or self._stopped or self.page.web or target not in SUPPORTED_PLATFORMS:
            return
        self._started = True
        self._task = self.page.run_task(self._check, target)

    def allow_prompt(self):
        """Показываем предложение после загрузки, разблокировки и примечаний."""
        self._prompt_allowed = True
        # Обработчик согласия Flet может вызывать в отдельном потоке.
        if self._loop is not None and not self._stopped:
            self._loop.call_soon_threadsafe(self._ready.set)

    def stop(self):
        self._stopped = True
        if self._task is not None:
            self._task.cancel()

    async def _check(self, target):
        self._loop = asyncio.get_running_loop()
        if self._prompt_allowed:
            self._ready.set()
        update = await asyncio.to_thread(check_for_update, APP_VERSION, target)
        if update is None or self._stopped:
            return
        await self._ready.wait()
        if not self._stopped:
            self._show(update)

    def _show(self, update):
        libs = self.get_libs()
        status = ft.Text(visible=False, color=libs.TxtColor, size=libs.text_size(14))
        later = libs.create_style_button("Позже")
        download = libs.create_style_button("Скачать", ft.Icons.DOWNLOAD_ROUNDED)
        closed = False

        def close(_=None):
            nonlocal closed
            if not closed:
                closed = True
                self.page.pop_dialog()

        def dismissed(_):
            nonlocal closed
            closed = True

        async def start_download(_):
            if closed or download.disabled:
                return
            download.disabled = later.disabled = True
            status.visible = False
            self.page.update()
            try:
                # Прямой URL файла запускает системную загрузку и на Windows,
                # и на Android, без доступа к закрытому хранилищу приложения.
                await _url_launcher(self.page).launch_url(
                    update.download_url, mode=ft.LaunchMode.EXTERNAL_APPLICATION,
                )
            except Exception:
                download.disabled = later.disabled = False
                status.value = "Не удалось начать скачивание. Проверьте подключение и попробуйте ещё раз."
                status.visible = True
                self.page.update()
                return
            close()

        later.on_click = close
        download.on_click = start_download
        dialog = ft.AlertDialog(
            modal=True,
            scrollable=True,
            bgcolor=libs.ContBgColor,
            title=libs.create_dialog_title("Доступно обновление"),
            content=ft.Container(
                width=libs.width_dialogs,
                content=ft.Column([
                    ft.Text(
                        f"Вышла версия {update.version}. У вас установлена {APP_VERSION}.",
                        color=libs.TxtColor, size=libs.text_size(16),
                    ),
                    ft.Text(
                        "Скачайте новую версию для вашего устройства. "
                        "Загрузка откроется в браузере. После скачивания установите обновление.",
                        color=libs.TxtColor, size=libs.text_size(14),
                    ),
                    status,
                ], tight=True, spacing=12),
            ),
            actions=[later, download],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=dismissed,
        )
        self.page.show_dialog(libs.prepare(dialog))
