"""Manual, isolated preview: python tests/preview_loading_game.py [--web].

All data lives in memory; cloud/notification workers are replaced. Delays and
errors here simulate network results and are never used by the application.
"""

import argparse
import asyncio
import os
from contextlib import ExitStack
from pathlib import Path
import sys
import threading
from unittest.mock import Mock, patch

import flet as ft

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Backend.webstorage import WebSessionStore
from Frontend.init_page import Front


async def preview(page):
    closed = asyncio.Event()
    gate = threading.Event()
    outcome = {"delay": 30, "error": False}
    store = WebSessionStore(page)
    store._persist = lambda *keys: None
    store._settings = {"theme_style": args.style, "theme_effect": args.effect,
                       "animated_wallpaper": "none", "notes_accepted": "True"}
    cloud = Mock(connect=True)

    def network_result():
        gate.wait(outcome["delay"])
        if outcome["error"]:
            raise RuntimeError("Simulated offline result")

    cloud.alg_for_start_app.side_effect = network_result
    with ExitStack() as stack:
        for target in ("Frontend.init_page.Cloud", "Backend.core.Cloud", "Backend.extended.Cloud"):
            stack.enter_context(patch(target, return_value=cloud))
        for target in ("Frontend.init_page.NotificationService", "Frontend.init_page.AutoUpdateService"):
            stack.enter_context(patch(target, return_value=Mock()))
        with patch.object(Front, "update_tasks"):
            front = Front(page, store)
        front.apply_theme_style(args.style, ft.Brightness.DARK if args.dark else ft.Brightness.LIGHT)
        front.show_groups()
        page.title = "Поймай галочку — изолированная проверка"
        if not page.web:
            page.window.width = 360 if args.narrow else 1000
            page.window.height = 760

        async def load(delay=30, error=False):
            ft.context.disable_auto_update()
            if front._loading_widget is not None:
                return
            gate.clear()
            outcome.update(delay=delay, error=error)
            front.update_tasks(front.show_groups)

        async def fast(event):
            await load(0.15)

        async def slow(event):
            await load()

        async def error(event):
            await load(3, True)

        async def finish(event):
            ft.context.disable_auto_update()
            gate.set()

        async def back(event):
            ft.context.disable_auto_update()
            front.close_page()
            gate.set()

        page.overlay.append(ft.Container(
            content=ft.Row([
                ft.TextButton("Быстро", on_click=fast),
                ft.TextButton("Долго", on_click=slow),
                ft.TextButton("Ошибка", on_click=error),
                ft.TextButton("Завершить", on_click=finish),
                ft.TextButton("Назад", on_click=back),
            ], wrap=True, spacing=0, run_spacing=0),
            bgcolor=front.ContBgColor, border_radius=12, padding=4,
            top=8, left=8, right=8,
        ))
        original_close, original_disconnect = page.on_close, page.on_disconnect

        def close(event=None):
            gate.set()
            original_close(event)
            closed.set()

        def disconnect(event=None):
            gate.set()
            original_disconnect(event)
            closed.set()

        page.on_close, page.on_disconnect = close, disconnect
        page.update()
        try:
            await closed.wait()
        finally:
            gate.set()
            front._stop_loading_game()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--narrow", action="store_true")
    parser.add_argument("--dark", action="store_true")
    parser.add_argument("--style", default="chatgpt")
    parser.add_argument("--effect", default="none")
    parser.add_argument("--port", type=int, default=8587)
    args = parser.parse_args()
    if args.web:
        os.environ["FLET_FORCE_WEB_SERVER"] = "true"
    ft.run(preview, view=None if args.web else ft.AppView.FLET_APP,
           host="127.0.0.1", port=args.port, assets_dir=str(ROOT / "assets"), no_cdn=True)
