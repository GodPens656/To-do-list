import flet as ft
from .theme import get_theme_colors
from .glass import (
    GlassHost, apply_glass, glass_background, glass_surface, is_glass, is_toolbar_glass,
)
from .controls import ActionButton, ActionIconButton, SurfaceHost
from .typography import scaled_text_size
from .wallpaper import WallpaperManager
from Backend.core import Backend
from Backend.validation import MAX_TEXT_LENGTH


class Fr_Libs:
    SVG_ICON_PACKS = {"minimalistic", "minimalistic-blue"}
    MOBILE_TOOLBAR_ICON_SIZE = 26
    MOBILE_TOOLBAR_BUTTON_HEIGHT = 62

    FLET_ICON_PACK = {
        "auth": ft.Icons.PERSON_ROUNDED,
        "basket1": ft.Icons.DELETE_ROUNDED,
        "info": ft.Icons.INFO_OUTLINE_ROUNDED,
        "logout": ft.Icons.LOGOUT_ROUNDED,
        "nazad": ft.Icons.ARROW_BACK_ROUNDED,
        "plusS": ft.Icons.ADD_ROUNDED,
        "redact": ft.Icons.EDIT_ROUNDED,
        "settings": ft.Icons.SETTINGS_ROUNDED,
        "update": ft.Icons.REFRESH_ROUNDED,
        "undo": ft.Icons.UNDO_ROUNDED,
    }

    def __init__(
        self,
        theme,
        phone,
        page=None,
        web=False,
        icon_pack="minimalistic",
        button_color=None,
    ):
        """Импорт классов"""
        self.phone = phone
        self.web = bool(web)
        self.page = page
        self.icon_pack = (
            icon_pack
            if icon_pack in {
                "flet", "minimalistic", "minimalistic-blue", "old", "custom"
            }
            else "minimalistic"
        )
        self.icon_theme = "dark" if str(theme).endswith("dark") else "light"
        self.font = int()
        self.width_dialogs = int()
        self.height_dialogs = int()
        self.padding = int()
        self.padding_for_row = int()
        self.height_for_dlg_spacer = int()

        self.theme = theme
        self.glass_toolbar = is_toolbar_glass(theme)
        self.glass = is_glass(theme) and not self.glass_toolbar
        self.glass_mobile = phone and is_glass(theme)
        self.colors = get_theme_colors(self.theme, button_color)
        self.BorderColor = self.colors["BorderColor"]
        self.ContBgColor = self.colors["ContBgColor"]
        self.BgColor = self.colors["BgColor"]
        self.TxtColor = self.colors["TxtColor"]
        self.BtnColor = self.colors["BtnColor"]
        self.BtnBorderColor = self.colors["BtnBorderColor"]
        # Material-иконки, которые дополняют SVG-пак, должны поддерживать
        # его синий акцент. В остальных паках сохраняем обычный цвет текста.
        self.FletIconColor = (
            "#60A5FA" if self.icon_theme == "dark" else "#2563EB"
        ) if self.icon_pack == "minimalistic-blue" else self.TxtColor
        self.spacer = ft.Container(
            content=ft.Row([]),
            expand=True,
        )


        """Настройки отступов и т.д."""
        if self.phone:
            self.font = 14
            # На Firefox Android CSS-viewport часто уже, чем в Chromium.
            # Фиксированные 350 px вместе с View.padding выходили за экран.
            # Ограничение применяется только к мобильной веб-версии.
            viewport_width = float(getattr(page, "width", 0) or 360)
            if self.web:
                self.height_dialogs = self.page.height * 0.95
                self.width_dialogs = max(260, min(350, viewport_width - 40))
            else:
                self.height_dialogs = self.page.height * 0.9
                # Нативные View имеют по 20 px внешнего отступа с каждой
                # стороны. Не даём диалогу выйти за доступную им ширину:
                # на узких Android-экранах переполнение смещало его вправо.
                self.width_dialogs = min(
                    self.page.width * 0.9,
                    max(0, self.page.width - 40),
                )
            self.padding = 10
            self.padding_for_row = 6
            self.height_for_dlg_spacer = 25
        else:
            self.font = 16
            self.height_dialogs = 500
            self.width_dialogs = 550
            self.padding = 15
            self.padding_for_row = 10
            self.height_for_dlg_spacer = 0

    def text_size(self, size):
        return scaled_text_size(self.page, size)

    def host(self, **kwargs):
        if self.glass or self.glass_toolbar:
            return GlassHost(self.theme, self.colors, mobile=self.glass_mobile, **kwargs)
        return SurfaceHost(**kwargs)

    def prepare(self, control):
        return apply_glass(control, self.theme, self.colors, mobile=self.glass_mobile)

    def view(self, **kwargs):
        view = ft.View(**kwargs)
        if self.glass:
            view.decoration = ft.BoxDecoration(gradient=glass_background(self.theme))
            view.bgcolor = ft.Colors.TRANSPARENT
        wallpaper = getattr(self.page, "_nd_wallpaper", None)
        if isinstance(wallpaper, WallpaperManager):
            wallpaper.wrap_view(view)
        return view

    def open_dialog(self, title, content, page):
        """Открывает информационное сообщение как AlertDialog поверх текущей страницы
        (раньше это была отдельная страница/route, из-за чего лишний раз ломался
        стек навигации)."""

        def close_dialog(e=None):
            page.pop_dialog()

        ok = ActionButton(
            "OK",
            on_click=close_dialog,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=5),
                padding=5,
                color=self.TxtColor,
            ),
            bgcolor=self.BtnColor,
        )

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=self.ContBgColor,
            shape=ft.RoundedRectangleBorder(radius=8),
            title=ft.Text(
                f" {title}",
                weight=ft.FontWeight.W_900,
                size=self.text_size(18),
                color=self.TxtColor,
            ),
            content=ft.Text(
                f"{content}",
                weight=ft.FontWeight.W_500,
                size=self.text_size(16),
                color=self.TxtColor,
            ),
            actions=[ok],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        if title == "Обновление":
            return close_dialog, ok

        page.show_dialog(self.prepare(dialog))


    REPEAT_TYPE_OPTIONS = [
        ("day", "Ежедневно"),
        ("week", "Еженедельно"),
        ("month", "Ежемесячно"),
        ("year", "Ежегодно"),
        ("custom", "Свой интервал"),
    ]

    WEEKDAY_OPTIONS = [
        ("1", "Понедельник"),
        ("2", "Вторник"),
        ("3", "Среда"),
        ("4", "Четверг"),
        ("5", "Пятница"),
        ("6", "Суббота"),
        ("7", "Воскресенье"),
    ]

    @staticmethod
    def update_text_counter(entry):
        entry.helper = f"{len(entry.value or '')}/{MAX_TEXT_LENGTH} символов"

    def widgets_for_ask_task(
        self,
        ask,
        text_for_button,
        title,
        with_interval=False,
        warning_text="Не создавайте одинаковые дела",
    ):
        """Постройка и возвращение виджетов для диалога с созданием нового дела.
        Если with_interval=True, добавляется выбор периодичности повторения
        (используется для повторяющихся дел). В зависимости от выбранного
        типа периодичности показывается свой набор виджетов:
        - Ежедневно: без дополнительных виджетов
        - Еженедельно: выпадающий список с днями недели
        - Ежемесячно: поле ввода числа месяца (1-31)
        - Ежегодно: кнопка выбора даты и поле с выбранной датой
        - Свой интервал: поле ввода числа дней (1-367)"""

        self.entry_task = ft.TextField(
            "",
            label="Название дела",
            hint_text="Обязательно для заполнения",
            helper=f"0/{MAX_TEXT_LENGTH} символов",
            multiline=True,
            shift_enter=not self.phone,
            width=self.width_dialogs * 0.95,
        )

        def on_text_change(event):
            self.update_text_counter(event.control)
            event.control.update()

        self.entry_task.on_change = on_text_change

        self.repeat_type_dd = ft.Dropdown(
            label="Периодичность повторения",
            value="day",
            options=[
                ft.dropdown.Option(key=k, text=v) for k, v in self.REPEAT_TYPE_OPTIONS
            ],
            width=self.width_dialogs * 0.95,
            visible=with_interval,
        )

        self.entry_interval = ft.TextField(
            "1",
            label="Повторять через (дней)",
            hint_text="Число от 1 до 367",
            width=self.width_dialogs * 0.95,
            keyboard_type=ft.KeyboardType.NUMBER,
            visible=False,
        )

        self.weekday_dd = ft.Dropdown(
            label="День недели",
            value="1",
            options=[
                ft.dropdown.Option(key=k, text=v) for k, v in self.WEEKDAY_OPTIONS
            ],
            width=self.width_dialogs * 0.95,
            visible=False,
        )

        self.month_day_entry = ft.TextField(
            "1",
            label="Число месяца",
            hint_text="Число от 1 до 31",
            width=self.width_dialogs * 0.95,
            keyboard_type=ft.KeyboardType.NUMBER,
            visible=False,
        )

        self.year_date_field = ft.TextField(
            label="Выбранная дата",
            hint_text="Выберите дату в календаре",
            width=self.width_dialogs * 0.95,
            read_only=True,
            visible=False,
        )

        self.year_date_button = self.create_style_button(
            "Выбрать дату", ft.Icons.CALENDAR_MONTH
        )
        self.year_date_button.visible = False

        self.btn_create_task = ActionButton(
            f"{text_for_button}",
            bgcolor=self.BtnColor,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=15,
                color=self.TxtColor,
            ),
            align=ft.Alignment.BOTTOM_CENTER,
        )

        self.cancel = ActionButton(
            "Отмена",
            bgcolor=self.BtnColor,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=15,
                color=self.TxtColor,
            ),
            align=ft.Alignment.BOTTOM_RIGHT,
        )

        row_for_buttons = ft.Row([self.btn_create_task, self.cancel])

        header_C = self.create_style_header(title)

        Cont_Warn = ft.Container(
            visible=bool(warning_text and warning_text.strip()),
            content=ft.Row(
                [
                    ft.Text(
                        f"   {warning_text}",
                        weight=ft.FontWeight.W_700,
                        color=self.colors["WarnTextColor"],
                        expand=True,
                    )
                ]
            ),
            bgcolor=self.colors["WarnBgColor"],
            border=ft.Border.all(0.5, self.colors["WarnBorderColor"]),
            border_radius=10,
            padding=8,
            width=self.width_dialogs * 0.95,
        )

        Cont_AC = ft.Container(
            content=ft.Column(
                [
                    Cont_Warn,
                    ft.Text(
                        f"{ask}",
                        size=self.text_size(16),
                        weight=ft.FontWeight.W_500,
                        color=self.TxtColor,
                    ),
                    self.entry_task,
                    self.repeat_type_dd,
                    self.entry_interval,
                    self.weekday_dd,
                    self.month_day_entry,
                    self.year_date_button,
                    self.year_date_field,
                    row_for_buttons,
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            # height = self.height_dialogs,
            bgcolor=self.ContBgColor,
            border=ft.Border.all(0.5, self.BorderColor),
            border_radius=10,
            padding=self.padding,
            width=self.width_dialogs,
            expand=True,
            #scroll = ft.ScrollMode.AUTO
        )

        itog = {
            "btn_create_task": self.btn_create_task,
            "entry_task": self.entry_task,
            "repeat_type_dd": self.repeat_type_dd,
            "entry_interval": self.entry_interval,
            "weekday_dd": self.weekday_dd,
            "month_day_entry": self.month_day_entry,
            "year_date_button": self.year_date_button,
            "year_date_field": self.year_date_field,
            "cancel": self.cancel,
            "Header": header_C,
            "Main Cont": Cont_AC,
        }
        return itog

    def build_button_with_image(self, img, tooltip, size=42, *, compact=True):
        """Функция для создания кнопки с заданной картинкой и tooltip"""
        target_size = max(44, size) if compact else None
        if compact:
            size = min(size, 24)
        if self.icon_pack == "flet" or img == "undo":
            content = ft.Icon(
                self.FLET_ICON_PACK.get(img, ft.Icons.IMAGE_ROUNDED),
                color=self.FletIconColor,
                size=size,
            )
        elif self.icon_pack == "custom":
            if self.web:
                # В браузере data URI надёжно проходит через JSON/WebSocket,
                # тогда как raw bytes в Flet 0.81 могут не стать image source.
                icon_source = getattr(
                    self.page, "_nd_custom_icon_sources", {}
                ).get(img)
            else:
                icon_source = getattr(self.page, "_nd_custom_icons", {}).get(img)
            if icon_source is not None:
                content = ft.Image(src=icon_source, width=size, height=size)
            else:
                # Для старых пользовательских архивов без logout.png.
                content = ft.Icon(
                    self.FLET_ICON_PACK.get(img, ft.Icons.IMAGE_ROUNDED),
                    color=self.TxtColor,
                    size=size,
                )
        elif self.icon_pack in self.SVG_ICON_PACKS:
            # Flet serves files from assets_dir at the web-app root.  An
            # absolute URL is important here: with a relative URL the browser
            # looks for the image below the current route (for example
            # /tasks/minimalistic/...), which works on the first page but
            # produces a 404 after navigation. В desktop-клиенте, наоборот,
            # нужен относительный путь внутри assets_dir: начальный слеш
            # заставляет Flet ошибочно добавлять путь модуля (__init__).
            relative_path = (
                f"{self.icon_pack}/{self.icon_theme}/svg/{img}.svg"
            )
            icon_path = f"/{relative_path}" if self.web else relative_path
            content = ft.Image(src=icon_path, width=size, height=size)
        else:
            # The legacy "old" pack has no SVG sources.
            relative_path = f"{self.icon_pack}/{self.icon_theme}/{img}.png"
            icon_path = f"/{relative_path}" if self.web else relative_path
            content = ft.Image(src=icon_path, width=size, height=size)

        return ActionButton(
            # assets_dir уже указывает на папку assets, поэтому путь
            # задаётся относительно неё.
            content=content,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=10,
                elevation=0,
                overlay_color=self.colors["HoverColor"],
            ) if compact else ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=2,
            ),
            width=target_size,
            height=target_size,
            bgcolor=self.BtnColor,
            tooltip=ft.Tooltip(tooltip, decoration=None),
        )

    def style_glass_toolbar(self, container, row, *, labels=None):
        """Одна стеклянная капсула с равными по ширине действиями."""
        container.content.tight = True
        row.scroll = None
        row.wrap = False
        row.spacing = 2
        labels = labels or ("Настройки", "Аккаунт", "Отмена", "Обновить")
        for button, label in zip(row.controls, labels):
            button._nd_glass_toolbar_action = True
            icon = button.content
            if isinstance(icon, ft.Icon):
                icon.size = self.MOBILE_TOOLBAR_ICON_SIZE
            elif isinstance(icon, ft.Image):
                icon.width = icon.height = self.MOBILE_TOOLBAR_ICON_SIZE
            button.content = ft.Column([
                icon,
                ft.Text(label, size=self.text_size(11), color=self.TxtColor,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        text_align=ft.TextAlign.CENTER),
            ], spacing=4, tight=True, alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            button.expand = True
            button.width = None
            button.height = self.MOBILE_TOOLBAR_BUTTON_HEIGHT
            button.bgcolor = ft.Colors.TRANSPARENT
            button.elevation = 0
            button.style = ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=32),
                padding=ft.Padding.symmetric(horizontal=2, vertical=6),
                elevation=0,
                shadow_color=ft.Colors.TRANSPARENT,
                side=ft.BorderSide(0, ft.Colors.TRANSPARENT),
                overlay_color={
                    ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                    ft.ControlState.PRESSED: ft.Colors.with_opacity(0.16, self.TxtColor),
                    ft.ControlState.HOVERED: self.colors["HoverColor"],
                },
                visual_density=ft.VisualDensity.COMPACT,
            )
        self.style_glass_toolbar_surface(container)

    def configure_action_panel(self, container, actions, position, *, progress=None):
        """Keep every action reachable, including in a short vertical sidebar."""
        if position in {"left", "right"}:
            button_width = 64
            for control in actions.controls:
                control.expand = None
                if isinstance(control, ft.TextField):
                    control.width = None
                elif isinstance(control, (ft.Button, ft.TextButton, ft.IconButton)):
                    # Keep the same button dimensions and style as horizontal panels.
                    button_width = max(button_width, control.width or 0)
            listing = ft.Column(
                list(actions.controls), scroll=ft.ScrollMode.AUTO,
                spacing=8, expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
            container.content = ft.Column(
                [listing, *([progress] if progress is not None else [])],
                spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
            # Leave room for the capsule's rounded ends outside the scroll area.
            container.padding = (ft.Padding.symmetric(horizontal=6, vertical=20)
                                 if getattr(container, "_nd_glass_toolbar", False) else 6)
            container.width = button_width + 12
        else:
            glass_actions = self.phone and actions.controls and all(
                getattr(control, "_nd_glass_toolbar_action", False) for control in actions.controls)
            for control in actions.controls:
                control.expand = True if glass_actions else None
            actions.wrap = not self.phone
            actions.scroll = ft.ScrollMode.AUTO if self.phone and not glass_actions else None
            container.content = (ft.Column([actions, progress], spacing=0)
                                 if progress is not None else actions)
        return container

    def dock_action_panel(self, body, panel, position):
        """Give the body bounded space beside a fixed, independently scrolling panel."""
        controls = [panel, body] if position in {"top", "left"} else [body, panel]
        if position in {"left", "right"}:
            return ft.Row(controls, expand=True, spacing=10,
                          vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        return ft.Column(controls, expand=True, spacing=10,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def style_glass_toolbar_surface(self, container):
        """Style only the panel, keeping the rest of the screen's material."""
        container.padding = 6
        container.margin = ft.Margin.symmetric(horizontal=4)
        container._nd_glass_toolbar = True
        glass_surface(container, self.theme, radius=40, mobile=self.glass_mobile, backdrop=True)

    def build_glass_body(self, list_container, add_button, toolbar, *, scrollable=None,
                         toolbar_actions=None):
        """Плавающие кнопки поверх списка, прокручиваемого до нижнего края."""
        if self.glass:
            list_container.bgcolor = None
            list_container.gradient = None
            list_container.border = None
            list_container.border_radius = 0
            list_container.blur = None
            list_container.shadow = None
            list_container.foreground_decoration = None
        list_container.expand = None
        list_container.left = list_container.top = list_container.right = list_container.bottom = 0
        # This space belongs to the scrolling content, so cards pass behind the
        # menu and the last item can still be scrolled clear of both buttons.
        scrollable = scrollable if scrollable is not None else list_container.content
        scrollable.padding = ft.Padding.only(bottom=200)
        floating_add = ft.Container(content=add_button, right=18, bottom=108)
        if toolbar_actions is not None:
            self.style_glass_add_button(add_button, match_toolbar=True)
            # Use the toolbar's exact columns and horizontal insets so the
            # floating action stays the same size at any viewport width.
            floating_add = ft.Container(
                content=ft.Row([
                    *[ft.Container(expand=True) for _ in toolbar_actions.controls[:-1]],
                    add_button,
                ], spacing=toolbar_actions.spacing, height=add_button.height),
                left=10, right=10, bottom=108,
                padding=ft.Padding.symmetric(horizontal=toolbar.padding + toolbar.border.left.width),
                margin=toolbar.margin,
            )
        return self.host(
            content=ft.Stack([
                list_container,
                floating_add,
                ft.Container(content=toolbar, left=10, right=10, bottom=16),
            ], fit=ft.StackFit.EXPAND),
            expand=True,
        )

    def style_glass_add_button(self, button, *, large=False, match_toolbar=False):
        """Отдельная кнопка создания справа над стеклянной панелью."""
        icon = button.content
        icon_size = self.MOBILE_TOOLBAR_ICON_SIZE if match_toolbar else (42 if large else 30)
        if isinstance(icon, ft.Icon):
            icon.size = icon_size
        elif isinstance(icon, ft.Image):
            icon.width = icon.height = icon_size
        button.width = None if match_toolbar else (72 if large else 56)
        button.height = self.MOBILE_TOOLBAR_BUTTON_HEIGHT if match_toolbar else button.width
        button.elevation = 3
        button.expand = True if match_toolbar else None
        button.margin = None if match_toolbar else ft.Margin.only(right=8)
        button.style = ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=24 if large else 19), padding=10,
            elevation=3, shadow_color=ft.Colors.with_opacity(0.18, ft.Colors.BLACK),
            side=ft.BorderSide(1, self.colors["SoftBorderColor"]),
            overlay_color=self.colors["HoverColor"],
        )

    def create_style_text_button(self, text, icon=None):
        """Создаёт textbutton со стилем, стандартным для приложения"""
        content = ft.Text(
            value=text,
            color=self.TxtColor,
            #weight=ft.FontWeight.BOLD
            size=self.text_size(16),

        )
        if icon is not None:
            content = ft.Row(
                [ft.Icon(icon, color=self.FletIconColor, size=18), content],
                spacing=8,
                tight=True,
            )
        return ft.TextButton(
        content=content,
        style=ft.ButtonStyle(
                side=ft.BorderSide(
                    color=self.BtnBorderColor,
                ),
                shape=ft.RoundedRectangleBorder(radius=16)
            )
        )


    def create_style_button(self, text, icon=None):
        """Создает кнопку со стилем, стандартным для приложения"""
        btn = ActionButton(
            f"{text}",
            bgcolor=self.BtnColor,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.Padding.symmetric(horizontal=18, vertical=14),
                elevation=0,
                overlay_color=self.colors["HoverColor"],
                text_style=ft.TextStyle(size=self.text_size(14), weight=ft.FontWeight.W_500),
                color=self.TxtColor,
            ),
        )
        if icon is not None:
            btn.icon = icon
            btn.icon_color = self.FletIconColor
        return btn

    def create_edit_button(self):
        return ActionIconButton(
                tooltip="Редактировать дело",
                icon=ft.Icons.EDIT_ROUNDED,
                icon_color=self.FletIconColor,
                icon_size=18,
                bgcolor=ft.Colors.TRANSPARENT,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=10),
                    padding=4,
                ),
            )

    def create_delete_button(self):
        return ActionIconButton(
                tooltip="Удалить дело",
                icon=ft.Icons.DELETE_ROUNDED,
                icon_color=self.FletIconColor,
                icon_size=18,
                bgcolor=ft.Colors.TRANSPARENT,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=10),
                    padding=4,
                ),
            )
    def create_style_cont(self, content: list,
    height='auto', width='auto',):
        """Создание стилизированного контейнера"""
        if width == 'auto':
            width = self.width_dialogs
        else:
            width = int(width)

        if height == 'auto':
            return self.host(
                content=ft.Column(content, scroll=ft.ScrollMode.AUTO, spacing=14),
                bgcolor=self.ContBgColor,
                border=ft.Border.all(1, self.colors["SoftBorderColor"]),
                border_radius=16,
                padding=self.padding,
                width=width,
                expand=True,
            )
        else:
            return self.host(
                content=ft.Column(content, scroll=ft.ScrollMode.AUTO, spacing=14),
                bgcolor=self.ContBgColor,
                border=ft.Border.all(1, self.colors["SoftBorderColor"]),
                border_radius=16,
                padding=self.padding,
                width=width,
                height=int(height),
            )
    def create_style_category_button(self, icon, text: str):
        """Кнопка-категория для главного окна настроек.
        Открывает отдельный диалог с настройками выбранной темы."""
        return ActionButton(
            content=ft.Row(
                [
                    ft.Icon(icon, color=self.FletIconColor, size=20),
                    ft.Text(
                        f" {text}",
                        size=self.text_size(16),
                        weight=ft.FontWeight.W_600,
                        color=self.TxtColor,
                        expand=True,
                    ),
                    ft.Icon(
                        ft.Icons.CHEVRON_RIGHT_ROUNDED,
                        color=self.FletIconColor,
                        size=20,
                    ),
                ],
                spacing=10,
            ),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=20,
                elevation=0,
                overlay_color=self.colors["HoverColor"],
            ),
            bgcolor=self.BtnColor,
            width=self.width_dialogs * 0.92,
        )

    def create_style_expansion_category(self, icon, text: str, controls, padding=25):
        """Раскрываемая категория настроек без перехода в другой View.
        Стиль заголовка приравнен к create_style_category_button
        (иконка/шрифт/ширина одинаковые), чтобы плитка выглядела
        так же, как кнопки, ведущие в диалоги, и иконка была
        видна как в свёрнутом, так и в раскрытом состоянии."""
        tile = ft.ExpansionTile(
            title=ft.Row(
                [
                    ft.Icon(icon, color=self.FletIconColor, size=20),
                    ft.Text(
                        f" {text}",
                        size=self.text_size(16),
                        weight=ft.FontWeight.W_600,
                        color=self.TxtColor,
                        expand=True,
                    ),
                ],
                spacing=10,
            ),
            controls=controls,

            bgcolor=self.BgColor,
            collapsed_bgcolor=self.BtnColor,

            text_color=self.TxtColor,
            collapsed_text_color=self.TxtColor,
            icon_color=self.FletIconColor,
            collapsed_icon_color=self.FletIconColor,

            controls_padding=padding,
            tile_padding=ft.Padding.symmetric(horizontal=25, vertical=0),
            min_tile_height=55,

            # Ширина приравнена к create_style_category_button
            width=self.width_dialogs * 0.92,

            # Скругление
            shape=ft.RoundedRectangleBorder(
                radius=10,
            ),
            collapsed_shape=ft.RoundedRectangleBorder(
                radius=10,
            ),
        )
        if self.glass:
            return self.host(
                content=tile, width=tile.width, bgcolor=self.ContBgColor,
                border=ft.Border.all(1, self.colors["GlassEdgeColor"]),
                border_radius=14,
            )
        return tile

    def create_style_section_title(self, icon, text: str, size=18, icon_color=None):
        """Заголовок раздела с иконкой перед надписью"""
        if self.icon_pack == "minimalistic-blue":
            icon_color = self.FletIconColor
        elif icon_color is None:
            icon_color = self.BtnColor
        return ft.Row(
            [
                ft.Icon(icon, color=icon_color, size=size + 2),
                ft.Text(
                    f" {text}",
                    size=self.text_size(size),
                    weight=ft.FontWeight.W_900,
                    color=self.TxtColor,
                ),
            ],
            spacing=8,
        )

    def create_stub_section(self, icon, title: str, subtitle: str = "Скоро появится"):
        """Заглушка для раздела, который ещё не реализован (например, еженедельные/отложенные дела)"""
        if subtitle == 'Скоро появится':
            v = False
        else:
            v = True
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color=self.BorderColor, size=22),
                    ft.Column(
                        [
                            ft.Text(
                                f" {title}",
                                size=self.text_size(15),
                                weight=ft.FontWeight.W_700,
                                color=self.TxtColor,
                            ),
                            ft.Text(
                                subtitle,
                                size=self.text_size(12),
                                color=self.BorderColor,
                            ),
                        ],
                        spacing=0,
                    ),
                ],
                spacing=10,
            ),
            bgcolor=self.ContBgColor,
            border=ft.Border.all(0.5, self.BorderColor),
            border_radius=10,
            padding=8,
            opacity=0.5,
            visible = v,
        )

    def create_style_header(self, title: str):
        """Создание стилизированного заголовка"""
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        f" {title}",
                        weight=ft.FontWeight.W_900,
                        size=self.text_size(18),
                        color=self.TxtColor,
                        expand=True,
                    )
                ]
            ),
            bgcolor=self.ContBgColor,
            border=ft.Border.all(0.5, self.BorderColor),
            border_radius=8,
            padding=self.padding,
            width=self.width_dialogs,

        )

    def collection_widgets_fo_dialog(self, cont_title, cont_actions, border, width=None):
        """Виджеты для диалога с редактированием дела"""
        itog_cont = ft.Container(
            content=ft.Column([cont_title, cont_actions]),
            bgcolor=self.BgColor,
            width=self.width_dialogs if width is None else width
        )

        self.spacer_for_phone = ft.Container(height=self.height_for_dlg_spacer)

        # Центрируем содержимое напрямую. Два flex-spacer'а внутри Row на
        # Android могли получать разную ширину при учёте safe-area, из-за
        # чего слева появлялся большой отступ, а справа диалог прижимался.
        most_itog_cont = ft.Container(
            content=itog_cont,
            alignment=ft.Alignment.TOP_CENTER,
            expand=True,
        )

        # В веб-версии экран должен начинаться от верхней границы.
        # Раньше мобильный spacer (25 px) вместе со стандартным spacing
        # колонки создавал заметный пустой участок сверху.
        dialog_controls = [most_itog_cont] if self.web else [
            self.spacer_for_phone,
            most_itog_cont,
        ]
        dialog_controls.append(
            ft.Container(height=20, visible=getattr(border, "visible", False))
        )

        self.new_task_dialog = self.host(
            content=ft.Column(
                dialog_controls,
                spacing=0 if self.web else 10,
            ),
            expand=True
        )

        return self.new_task_dialog
