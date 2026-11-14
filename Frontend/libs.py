import flet as ft
from .theme import get_theme_colors
from .glass import (
    GlassHost, apply_glass, glass_background, glass_surface, is_glass, is_toolbar_glass,
)
from .controls import ActionButton, ActionIconButton
from .dayplanner import PlannerHost, FIELD_RADIUS, PILL_RADIUS
from .typography import scaled_text_size
from .links import linked_text
from .wallpaper import WallpaperManager
from Backend.core import Backend
from Backend.validation import MAX_TEXT_LENGTH, TASK_COLLAPSE_THRESHOLD, should_collapse_task


class Fr_Libs:
    SVG_ICON_PACKS = {"minimalistic", "minimalistic-blue"}
    MOBILE_TOOLBAR_ICON_SIZE = 32
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

    def linked_text(self, value, **kwargs):
        return linked_text(
            value, page=self.page, web=self.web,
            dark=self.icon_theme == "dark", **kwargs,
        )

    def collapsible_task_text(self, text, collapse=False):
        """Keep the full linked text and initially show only its first three lines."""
        if not collapse:
            return text
        text.max_lines = 3
        text.overflow = ft.TextOverflow.ELLIPSIS
        label = ft.Text("Развернуть", size=self.text_size(12), color=self.TxtColor)
        arrow = ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED, size=16, color=self.FletIconColor)
        toggle = ft.TextButton(
            content=ft.Row([arrow, label], spacing=6, tight=True),
            style=ft.ButtonStyle(padding=ft.Padding.symmetric(
                horizontal=12 if self.glass else 6,
                vertical=6 if self.glass else 0,
            )),
        )
        body = ft.Column([text, toggle], spacing=0, tight=True)

        def toggle_text(_):
            collapsed = text.max_lines is None
            text.max_lines = 3 if collapsed else None
            text.overflow = ft.TextOverflow.ELLIPSIS if collapsed else None
            label.value = "Развернуть" if collapsed else "Свернуть"
            arrow.icon = (ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED if collapsed
                          else ft.Icons.KEYBOARD_ARROW_UP_ROUNDED)
            body.update()
            ft.context.disable_auto_update()

        toggle.on_click = toggle_text
        return body

    def add_task_collapse_control(self, dialog, collapse=False, *, label="Сворачивать ли дело"):
        """Add a collapse preference and keep it in sync with the text length."""
        entry = dialog["entry_task"]
        checkbox = ft.Checkbox(
            label=label,
            value=should_collapse_task(entry.value, collapse),
            label_style=ft.TextStyle(size=self.text_size(14), color=self.TxtColor),
            tooltip=("Автоматически включается при сохранении текста длиннее "
                     f"{TASK_COLLAPSE_THRESHOLD} символов."),
        )
        controls = dialog["Main Cont"].content.controls
        controls.insert(controls.index(entry) + 1, checkbox)
        on_text_change = entry.on_change

        def update_collapse(event):
            on_text_change(event)
            if should_collapse_task(entry.value) and not checkbox.value:
                checkbox.value = True
                checkbox.update()

        entry.on_change = update_collapse
        return checkbox

    def host(self, **kwargs):
        if self.glass or self.glass_toolbar:
            return GlassHost(self.theme, self.colors, mobile=self.glass_mobile, **kwargs)
        return PlannerHost(self.theme, self.colors, **kwargs)

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

    def open_dialog(self, title, content, page, *, linkify=False):
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
            title=self.create_dialog_title(title),
            content=(self.linked_text if linkify else ft.Text)(
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
    def update_text_counter(entry, max_length=MAX_TEXT_LENGTH):
        entry.helper = f"{len(entry.value or '')}/{max_length} символов"

    def create_task_dropdown(self, **kwargs):
        """Список для горизонтального Row: поле и меню занимают его ширину."""
        return ft.Dropdown(expand=True, expanded_insets=0, **kwargs)

    def widgets_for_ask_task(
        self,
        ask,
        text_for_button,
        title,
        with_interval=False,
        warning_text="Не создавайте одинаковые дела",
        *,
        max_length=MAX_TEXT_LENGTH,
    ):
        """Постройка и возвращение виджетов для диалога с созданием нового дела.
        Если with_interval=True, добавляется выбор периодичности повторения
        (используется для повторяющихся дел). В зависимости от выбранного
        типа периодичности показывается свой набор виджетов:
        - Ежедневно: без дополнительных виджетов
        - Еженедельно: выбор одного или нескольких дней недели
        - Ежемесячно: поле ввода числа месяца (1-31)
        - Ежегодно: кнопка выбора даты и поле с выбранной датой
        - Свой интервал: поле ввода числа дней (1-367)"""

        self.entry_task = ft.TextField(
            "",
            label="Название дела",
            hint_text="Обязательно для заполнения",
            helper=f"0/{max_length} символов",
            multiline=True,
            shift_enter=not self.phone,
            width=self.width_dialogs * 0.95,
        )

        def on_text_change(event):
            self.update_text_counter(event.control, max_length)
            event.control.update()

        self.entry_task.on_change = on_text_change

        self.repeat_type_dd = self.create_task_dropdown(
            label="Периодичность повторения",
            value="day",
            options=[
                ft.dropdown.Option(key=k, text=v) for k, v in self.REPEAT_TYPE_OPTIONS
            ],
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

        self.weekday_checks = [
            ft.Checkbox(
                label=label, value=key == "1", data=int(key),
                label_style=ft.TextStyle(size=self.text_size(14), color=self.TxtColor),
            )
            for key, label in self.WEEKDAY_OPTIONS
        ]
        self.weekday_error = ft.Text(
            "Выберите хотя бы один день недели", color=ft.Colors.RED, visible=False,
        )
        self.weekday_picker = ft.Column(
            [
                ft.Text("Дни недели", color=self.TxtColor),
                ft.Row([
                    ft.Container(checkbox, width=150, alignment=ft.Alignment.CENTER_LEFT)
                    for checkbox in self.weekday_checks
                ], wrap=True, spacing=0, run_spacing=0),
                self.weekday_error,
            ],
            spacing=4,
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

        self.btn_create_task._nd_planner_primary = True

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

        schedule_settings = self.create_task_form_section(
            ft.Icons.REPEAT_ROUNDED, "Настройки повторения",
            [ft.Row([self.repeat_type_dd]), self.entry_interval, self.weekday_picker,
             self.month_day_entry, self.year_date_button, self.year_date_field],
        ) if with_interval else None

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
                    *([schedule_settings] if with_interval else []),
                    row_for_buttons,
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            bgcolor=self.ContBgColor,
            border=ft.Border.all(1, self.colors["SoftBorderColor"]),
            border_radius=16,
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
            "weekday_picker": self.weekday_picker,
            "weekday_checks": self.weekday_checks,
            "weekday_error": self.weekday_error,
            "month_day_entry": self.month_day_entry,
            "year_date_button": self.year_date_button,
            "year_date_field": self.year_date_field,
            "schedule_settings": schedule_settings,
            "cancel": self.cancel,
            "Header": header_C,
            "Main Cont": Cont_AC,
        }
        return itog

    def build_button_with_image(self, img, tooltip, size=42, *, compact=True):
        """Функция для создания кнопки с заданной картинкой и tooltip"""
        target_size = max(40 if compact else 44, size)
        size = min(size, 24 if compact else 36)
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

        button = ActionButton(
            # assets_dir уже указывает на папку assets, поэтому путь
            # задаётся относительно неё.
            content=content,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=PILL_RADIUS),
                padding=10,
                elevation=0,
                overlay_color=self.colors["HoverColor"],
            ) if compact else ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=FIELD_RADIUS),
                padding=4,
                elevation=0,
            ),
            width=target_size,
            height=target_size,
            bgcolor=self.BtnColor,
            tooltip=ft.Tooltip(tooltip, decoration=None),
        )
        if not compact:
            button._nd_planner_corner_radius = FIELD_RADIUS
        return button

    def style_glass_toolbar(self, container, row, *, labels=None):
        """Одна стеклянная капсула с равными по ширине действиями."""
        container.content.tight = True
        if self.glass_mobile:
            container.content.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        row.scroll = None
        row.wrap = False
        row.spacing = 2
        labels = labels or ("Настройки", "Аккаунт", "Отмена", "Обновить")
        for button, label in zip(row.controls, labels):
            button._nd_glass_toolbar_action = True
            icon = button.content
            if isinstance(icon, str):
                icon = ft.Icon(button.icon or ft.Icons.ADD_ROUNDED,
                               color=self.FletIconColor, size=self.MOBILE_TOOLBAR_ICON_SIZE)
                button.icon = None
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
                shape=ft.RoundedRectangleBorder(radius=32 if self.glass or self.glass_toolbar else 14),
                padding=ft.Padding.symmetric(horizontal=2, vertical=4),
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
        if self.glass or self.glass_toolbar:
            self.style_glass_toolbar_surface(container)
        else:
            container.padding = 6
            container.border_radius = 26

    def configure_action_panel(self, container, actions, position, *, progress=None):
        """Keep every action reachable, including in a short vertical sidebar."""
        if not self.phone and (self.glass or self.glass_toolbar):
            # Reuse the task cards' lightweight material without a backdrop filter.
            container._nd_glass_toolbar = True
            glass_surface(container, self.theme)
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
            if self.glass_mobile and progress is not None:
                container.content.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        return container

    def dock_action_panel(self, body, panel, position, *, scrollable=None):
        """Dock actions beside the body, or float the mobile footer over its list."""
        if self.phone and position == "bottom" and not self.glass_mobile and scrollable is not None:
            # Keep the space around the capsule transparent: cards scroll all
            # the way to the screen's bottom instead of ending above the menu.
            # The inset belongs to the list so its last item can clear the menu,
            # including the upload indicator when it appears.
            scrollable.padding = ft.Padding.only(bottom=self.MOBILE_TOOLBAR_BUTTON_HEIGHT + 42)
            body.expand = None
            return self.host(
                content=ft.Stack([
                    body,
                    ft.Container(content=panel, left=0, right=0, bottom=0),
                ], fit=ft.StackFit.EXPAND),
                expand=True,
            )
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
        glass_surface(container, self.theme, radius=40, mobile=self.glass_mobile)

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
        add_bottom = self.MOBILE_TOOLBAR_BUTTON_HEIGHT + 46
        scrollable.padding = ft.Padding.only(bottom=add_bottom + self.MOBILE_TOOLBAR_BUTTON_HEIGHT + 30)
        floating_add = ft.Container(content=add_button, right=18, bottom=add_bottom)
        if toolbar_actions is not None:
            self.style_glass_add_button(add_button, match_toolbar=True)
            # Use the toolbar's exact columns and horizontal insets so the
            # floating action stays the same size at any viewport width.
            floating_add = ft.Container(
                content=ft.Row([
                    *[ft.Container(expand=True) for _ in toolbar_actions.controls[:-1]],
                    add_button,
                ], spacing=toolbar_actions.spacing, height=add_button.height),
                left=10, right=10, bottom=add_bottom,
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


    def create_style_button(self, text, icon=None, *, primary=False):
        """Создает кнопку со стилем, стандартным для приложения"""
        btn = ActionButton(
            f"{text}",
            bgcolor=self.BtnColor,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=PILL_RADIUS),
                padding=ft.Padding.symmetric(horizontal=18, vertical=10),
                elevation=0,
                overlay_color=self.colors["HoverColor"],
                text_style=ft.TextStyle(size=self.text_size(14), weight=ft.FontWeight.W_500),
                color=self.TxtColor,
            ),
        )
        if icon is not None:
            btn.icon = icon
            btn.icon_color = self.FletIconColor
        btn._nd_planner_primary = primary
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
    height='auto', width='auto', *, framed=False):
        """Группа виджетов с прокруткой и необязательной фоновой панелью."""
        if width == 'auto':
            width = self.width_dialogs
        else:
            width = int(width)

        surface = dict(
            bgcolor=self.ContBgColor,
            border=ft.Border.all(1, self.colors["SoftBorderColor"]),
            border_radius=16,
        ) if framed else {}

        if height == 'auto':
            return self.host(
                **surface,
                content=ft.Column(content, scroll=ft.ScrollMode.AUTO, spacing=14),
                padding=self.padding,
                width=width,
                expand=True,
            )
        else:
            return self.host(
                **surface,
                content=ft.Column(content, scroll=ft.ScrollMode.AUTO, spacing=14),
                padding=self.padding,
                width=width,
                height=int(height),
            )
    def _create_category_title(self, icon, text: str):
        """Общий заголовок обычных и раскрываемых категорий настроек."""
        badge = ft.Container(
            content=ft.Icon(icon, color=self.colors["CategoryIconColor"], size=24),
            bgcolor=self.colors["CategoryIconBgColor"],
            border=ft.Border.all(1, ft.Colors.with_opacity(
                0.35, self.colors["CategoryIconColor"],
            )) if self.glass or self.glass_toolbar else None,
            border_radius=12, width=40, height=40, alignment=ft.Alignment.CENTER,
        )
        if self.glass or self.glass_toolbar:
            # The opaque icon badge supplies its own contrast and outline.
            badge._nd_glass_material = True
        return ft.Row(
            [
                badge,
                ft.Text(
                    f" {text}",
                    size=self.text_size(16),
                    weight=ft.FontWeight.W_600,
                    color=self.TxtColor,
                    expand=True,
                ),
            ],
            spacing=10,
        )

    def create_style_category_button(self, icon, text: str):
        """Кнопка-категория для главного окна настроек.
        Открывает отдельный диалог с настройками выбранной темы."""
        title = self._create_category_title(icon, text)
        title.controls.append(
            ft.Icon(
                ft.Icons.CHEVRON_RIGHT_ROUNDED,
                color=self.FletIconColor,
                size=20,
            ),
        )
        button = ActionButton(
            content=title,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.Padding.only(left=4, right=14, top=4, bottom=4),
                visual_density=ft.VisualDensity.STANDARD,
                elevation=0,
                overlay_color=self.colors["HoverColor"],
            ),
            bgcolor=self.BtnColor,
            width=self.width_dialogs * 0.92,
        )
        button._nd_planner_category = True
        return button

    def create_style_expansion_category(self, icon, text: str, controls, padding=25, *, framed=False):
        """Раскрываемая категория настроек без перехода в другой View.
        Стиль заголовка приравнен к create_style_category_button
        (иконка/шрифт/ширина одинаковые), чтобы плитка выглядела
        так же, как кнопки, ведущие в диалоги, и иконка была
        видна как в свёрнутом, так и в раскрытом состоянии."""
        # Full glass uses a surrounding surface. Let that host draw the frame
        # so the tile's different corner radius cannot add a second outline.
        shape = ft.RoundedRectangleBorder(
            radius=12,
            side=ft.BorderSide(1, self.colors["GlassEdgeColor"]
                               if self.glass or self.glass_toolbar
                               else self.colors["SoftBorderColor"]) if framed and not self.glass else None,
        )
        title = self._create_category_title(icon, text)
        # Let ExpansionTile animate the label color with its background.
        title.controls[1].color = None
        tile = ft.ExpansionTile(
            title=title,
            controls=controls,

            bgcolor=self.BgColor if framed else ft.Colors.TRANSPARENT,
            collapsed_bgcolor=self.BtnColor if framed else ft.Colors.TRANSPARENT,

            text_color=self.TxtColor,
            collapsed_text_color=self.TxtColor,
            icon_color=self.FletIconColor,
            collapsed_icon_color=self.FletIconColor,

            controls_padding=padding,
            tile_padding=ft.Padding.only(left=4, right=14),
            min_tile_height=48,

            # Ширина приравнена к create_style_category_button
            width=self.width_dialogs * 0.92,

            # Скругление
            shape=shape,
            collapsed_shape=shape,
        )
        tile._nd_planner_category = framed
        if self.glass:
            panel = self.host(
                content=tile, width=tile.width,
                bgcolor=self.ContBgColor if framed else None,
                border=ft.Border.all(1, self.colors["GlassEdgeColor"]) if framed else None,
                border_radius=14 if framed else None,
            )
            panel._nd_glass_tint = self.colors["GlassButtonTint"] if framed else None
            return panel
        return tile

    def create_task_form_section(self, icon, title, controls):
        """Раскрываемый раздел формы, сохраняющий значения скрытых полей."""
        section = self.create_style_expansion_category(
            icon, title,
            [ft.Column(controls, spacing=10,
                       horizontal_alignment=ft.CrossAxisAlignment.STRETCH)],
            padding=12, framed=True,
        )
        tile = section if isinstance(section, ft.ExpansionTile) else section.content
        tile.title.controls[1].size = self.text_size(14 if self.phone else 16)
        tile.maintain_state = True
        return section

    def create_task_form_sections(self, extra_controls, attachment_control):
        """Группирует необязательные поля дела в раскрываемые разделы."""
        return [
            self.create_task_form_section(icon, title, controls)
            for icon, title, controls in (
                (ft.Icons.INFO_OUTLINE_ROUNDED, "Дополнительная информация", extra_controls),
                (ft.Icons.ATTACH_FILE_ROUNDED, "Прикрепление файлов", [attachment_control]),
            )
        ]

    def create_style_section_title(self, icon, text: str, size=18, icon_color=None):
        """Заголовок раздела с иконкой перед надписью"""
        if self.icon_pack == "minimalistic-blue":
            icon_color = self.FletIconColor
        elif icon_color is None:
            icon_color = self.colors["ProgressColor"]
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
            padding=8,
            opacity=0.5,
            visible = v,
        )

    def create_dialog_title(self, title: str):
        return ft.Text(
            title, weight=ft.FontWeight.W_700, size=self.text_size(24),
            color=self.TxtColor,
        )

    def create_style_header(self, title: str, *, on_back=None, width=None,
                            back_tooltip="Назад"):
        """Единый заголовок диалогов со стрелкой возврата, как у расписания."""
        back = ActionIconButton(
            icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=self.TxtColor,
            tooltip=back_tooltip, on_click=on_back,
        )
        label = self.create_dialog_title(title)
        label.expand = True
        header = ft.Container(
            content=ft.Row([back, label], spacing=8),
            padding=ft.Padding.only(top=6 if self.phone else 0, bottom=6),
            width=self.width_dialogs if width is None else width,
        )
        header._nd_dialog_back = back
        return header

    def collection_widgets_fo_dialog(self, cont_title, cont_actions, border, width=None):
        """Виджеты для диалога с редактированием дела"""
        itog_cont = ft.Container(
            content=ft.Column([cont_title, cont_actions]),
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

        # Верхний spacer нужен только нативному мобильному клиенту.
        # На ПК даже его нулевая высота добавляла spacing перед заголовком.
        mobile_spacing = self.phone and not self.web
        dialog_controls = [
            self.spacer_for_phone,
            most_itog_cont,
        ] if mobile_spacing else [most_itog_cont]
        dialog_controls.append(
            ft.Container(height=20, visible=getattr(border, "visible", False))
        )

        self.new_task_dialog = self.host(
            content=ft.Column(
                dialog_controls,
                spacing=10 if mobile_spacing else 0,
            ),
            expand=True
        )

        return self.new_task_dialog
