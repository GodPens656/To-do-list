from Frontend.init_page import Front
import flet as ft
from Backend.webstorage import WebSessionStore
from urllib.parse import parse_qs, urlsplit
from Backend.app_paths import get_assets_dir


def _set_browser_timezone(page):
    """Сохраняет часовой пояс, переданный браузером в URL веб-сессии."""
    route = page.route or ""
    query = parse_qs(urlsplit(route).query)
    timezone_name = (query.get("_nd_tz") or [None])[0]
    offset_value = (query.get("_nd_offset") or [None])[0]
    if timezone_name and len(timezone_name) <= 64:
        page._nd_timezone = timezone_name
    try:
        offset_minutes = int(offset_value)
        if -840 <= offset_minutes <= 840:
            page._nd_timezone_offset_minutes = offset_minutes
    except (TypeError, ValueError):
        pass

async def main(page: ft.Page):
    web_store = None
    if page.web:
        _set_browser_timezone(page)
        # Сайт: подгружаем то, что раньше сохранил браузер ЭТОГО
        # посетителя (page.shared_preferences), ДО построения интерфейса —
        # дальше Front/Backend/Backend2 работают с этими данными синхронно,
        # как и раньше, а фактическая запись обратно в браузер идёт в фоне.
        web_store = WebSessionStore(page)
        await web_store.load()
    Front(page, web_store)

if __name__ == "__main__":
    import os as _os

    # Порт и хост настраиваются через переменные окружения — удобно для
    # systemd/Docker на VPS, не нужно лезть в код, чтобы поменять порт.
    _host = _os.getenv("ND_HOST", "0.0.0.0")
    _port = int(_os.getenv("ND_PORT", "8550"))
    _assets_dir = get_assets_dir()
    if not _assets_dir.is_dir():
        raise RuntimeError(
            f"Assets directory does not exist: {_assets_dir}. "
            "Set ND_ASSETS_DIR to the correct absolute path."
        )

    ft.run(
        main,
        #view=ft.AppView.WEB_BROWSER,
        #host=_host,
        #port=_port,
        assets_dir=str(_assets_dir),
    )
