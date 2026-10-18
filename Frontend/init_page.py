import asyncio
import threading
from functools import wraps
from datetime import date, datetime, timezone

import flet as ft
from Backend.app_paths import get_assets_dir
from Backend.core import Backend
from Backend.extended import Backend2
from Backend.validation import text_length_error
from Backend.attachments import AttachmentQuotaError
from Backend.cloud import Cloud
from .libs import Fr_Libs
from .auth import AuthWidgets
from .settings import Utils2
from .main import MainWidgets
from .notes import NotesMixin
from .attachments import AttachmentEditor
from Backend.notifications import NotificationService
from Backend.autoupdate import AutoUpdateService
from .theme import (
    build_flet_theme,
    get_theme_colors,
    resolve_button_color,
    resolve_theme,
)
from Backend.core import local_today
from .typography import apply_typography



class Front(NotesMixin):
    def __init__(self, page: ft.Page, web_store=None):
        self.page = page
        self.web = bool(getattr(page, "web", False))
        self.web_store = web_store
        self.modified_dialog2 = ft.Container()
        self.modified_dialog3 = ft.Container()
        self._notes_dialog = None

        """Импорт модулей"""
        self.cloud = Cloud(web_store=web_store)
        self.back = Backend(page=self.page, web_store=web_store, cloud=self.cloud)
        if self.web:
            # На сайте телефон/ПК определяем по User-Agent браузера — это
            # влияет ТОЛЬКО на вёрстку интерфейса (см. Fr_Libs ниже), а не
            # на то, какой канал уведомлений использовать: на сайте
            # уведомления отключены в любом случае (см. NotificationService
            # ниже, web=True).
            ua = (self.page.client_user_agent or "").lower()
            self.back.phone = any(marker in ua for marker in ("iphone", "android", "mobile"))
        self.back2 = Backend2(
            page=self.page, web_store=web_store, back=self.back, cloud=self.cloud
        )
        customization_settings = self.back2.read_settings()
        self._app_locked = customization_settings["password_enabled"]
        self.theme_style = customization_settings["theme_style"]
        self.icon_pack = customization_settings["icon_pack"]
        self.button_bg_mode = customization_settings["button_bg_mode"]
        self.button_custom_color = customization_settings["button_custom_color"]
        self.theme = resolve_theme(self.theme_style, self.page.platform_brightness)
        self.button_color = resolve_button_color(
            self.theme,
            self.button_bg_mode,
            self.button_custom_color,
        )
        self._apply_page_theme()

        # Все вспомогательные классы создают свои Fr_Libs в __init__.
        # Определить телефон нужно ДО их создания: иначе Utils/Utils2
        # сохраняют desktop-ширину 550 px и вложенные окна выходят за экран.
        self.utils = AuthWidgets(
            self.cloud,
            self.back,
            self.theme,
            page=self.page,
            web_store=web_store,
            icon_pack=self.icon_pack,
            button_color=self.button_color,
        )
        self.main_widgets = MainWidgets(
            self.theme,
            page=self.page,
            web_store=web_store,
            icon_pack=self.icon_pack,
            button_color=self.button_color,
        )
        self.utils2 = Utils2(
            self.cloud,
            self.back,
            self.theme,
            self.back2,
            on_theme_change=self.apply_theme_style,
            on_icon_pack_change=self.apply_icon_pack,
            on_button_color_change=self.apply_button_color,
            on_font_change=self.apply_font_settings,
            icon_pack=self.icon_pack,
            button_color=self.button_color,
        )
        self.phone = self.back.get_device()
        # Единый внешний отступ: 10 px на сайте и 20 px
        # в нативных клиентах.
        self.page_edge_padding = 10 if self.web else 20
        self.libs = Fr_Libs(
            self.theme,
            self.phone,
            page=self.page,
            web=self.web,
            icon_pack=self.icon_pack,
            button_color=self.button_color,
        )
        self.notification_service = NotificationService(
            self.page,
            self.phone,
            self.back2.read_settings,
            web=self.web,
            data_provider=self.back._load,
        )

        self.back.on_data_change = self.notification_service.data_changed

        """Фоновое автообновление дел из облака раз в 10 минут"""
        self.auto_update_service = AutoUpdateService(
            self.page,
            self.back2,
            self.refresh_tasks_silent,
        )

        def _on_close(e=None):
            self.notification_service.stop()
            self.auto_update_service.stop()

        self.page.on_close = _on_close
        """Базовые настройки страницы"""
        self.page.title = "Дневник"
        self.page.padding = 0
        #self.page.theme = ft.Theme(color_scheme_seed="#030712", use_material3=True)

        if not self.web:
            self.page.window.icon = str(get_assets_dir() / "dnevnik.ico")

        """Задание контейнеров"""
        self.main_cont, self.btns_cont, self.tasks_cont = self.main_widgets.build_main_conts(self.page)

        self.sets = self.back2.read_settings()

        self.status_border = self.sets["border"]

        self.border = self.main_widgets.build_status_border(self.status_border)
        self.main_cont.content.controls.append(self.border)

        """Выполнение функций перед запуском"""

        self.page.on_view_pop = self._on_view_pop
        self.page.on_platform_brightness_change = self._on_platform_brightness_change
        self.current_group_id = None
        self._load_default_task_filter()
        self.screen_host = None
        self.screen_stack = []
        self.root_view = self.page.views[0] if self.page.views else ft.View()
        self._reset_root_view()
        self._settings_screens = {}
        self._groups_screen = None
        self._groups_column = None
        self.main_widgets.build_static_input(self)
        self.add_main_widgets()
        # При запуске сначала показывается загрузка. После неё гостю
        # сразу открываем экран авторизации, а авторизованному пользователю —
        # обычный экран выбора групп.
        if self._app_locked:
            self.show_app_lock()
        else:
            self._start_unlocked_app()

        if self.phone:
            pass
        else:
            self.page.on_keyboard_event = self.exit_from_pc

        if not self.web:
            self.page.update()

    def _start_unlocked_app(self):
        self.notification_service.setup()
        self.notification_service.start()
        self.auto_update_service.start()
        self.update_tasks(self.show_start_screen)

    def _reset_root_view(self):
        """Сохраняет корневой View, к которому Flet привязывает сервисы."""
        self.root_view.route = "/"
        self.root_view.padding = self.page_edge_padding
        self.root_view.bgcolor = self.BgColor
        if self.web:
            self.screen_host = ft.Container(expand=True)
            self.root_view.controls = [self.screen_host]
        else:
            self.root_view.controls = []
        self.page.views[:] = [self.root_view]

    def show_app_lock(self):
        """Единственный доступный экран до проверки пароля приложения."""
        password = ft.TextField(
            label="Пароль приложения", password=True, can_reveal_password=True,
            autofocus=True, autocorrect=False, enable_suggestions=False,
            color=self.TxtColor, border_color=self.BorderColor,
            text_size=self.libs.text_size(14),
        )
        status = ft.Text(color=self.TxtColor, size=self.libs.text_size(13))
        unlock = self.libs.create_style_button("Войти", ft.Icons.LOCK_OPEN_ROUNDED)

        async def submit(e):
            if unlock.disabled or not self._app_locked:
                return
            unlock.disabled = password.disabled = True
            status.value = ""
            self.page.update()
            try:
                valid = await asyncio.to_thread(self.back2.verify_app_password, password.value)
            except (OSError, ValueError):
                valid = False
                status.value = "Не удалось проверить пароль. Попробуйте ещё раз."
            if valid:
                password.value = ""
                self._app_locked = False
                # Экран пароля не остаётся в истории навигации.
                if self.web:
                    self.screen_stack.clear()
                else:
                    self._reset_root_view()
                self._start_unlocked_app()
                return
            password.value = ""
            status.value = status.value or "Неверный пароль. Попробуйте ещё раз."
            unlock.disabled = password.disabled = False
            self.page.update()

        unlock.on_click = password.on_submit = submit
        card = self.libs.create_style_cont([
            ft.Icon(ft.Icons.LOCK_ROUNDED, color=self.TxtColor, size=36),
            ft.Text("Вход в приложение", color=self.TxtColor,
                    size=self.libs.text_size(22), weight=ft.FontWeight.W_600),
            password, unlock, status,
        ])
        body = ft.Container(content=card, alignment=ft.Alignment.CENTER, expand=True)
        if self.web:
            self._set_screen(body, reset=True)
        else:
            self.root_view.route = "/unlock"
            self.root_view.controls = [body]
            self.page.views[:] = [self.root_view]
            self.page.update()

    def _apply_page_theme(self):
        """Применяет палитру к странице и сохраняет часто используемые цвета."""
        self.colors = get_theme_colors(self.theme, self.button_color)
        self.BorderColor = self.colors["BorderColor"]
        self.ContBgColor = self.colors["ContBgColor"]
        self.BgColor = self.colors["BgColor"]
        self.TxtColor = self.colors["TxtColor"]
        self.BtnColor = self.colors["BtnColor"]
        self.ProgressColor = self.colors["ProgressColor"]
        self.ProgressBgColor = self.colors["ProgressBgColor"]
        self.page.theme_mode = (
            ft.ThemeMode.DARK if self.theme.endswith("dark") else ft.ThemeMode.LIGHT
        )
        flet_theme = build_flet_theme(self.theme, self.button_color)
        settings = self.back2.read_settings()
        apply_typography(
            self.page, flet_theme, settings["font_family"], settings["font_size"]
        )
        self.page.theme = flet_theme
        self.page.dark_theme = flet_theme
        self.page.bgcolor = self.BgColor

    def apply_theme_style(self, theme_style, platform_brightness=None):
        """Сразу перестраивает интерфейс, не перезапуская фоновые сервисы."""
        self.theme_style = theme_style
        customization_settings = self.back2.read_settings()
        self.icon_pack = customization_settings["icon_pack"]
        self.button_bg_mode = customization_settings["button_bg_mode"]
        self.button_custom_color = customization_settings["button_custom_color"]
        brightness = platform_brightness or self.page.platform_brightness
        self.theme = resolve_theme(theme_style, brightness)
        self.button_color = resolve_button_color(
            self.theme,
            self.button_bg_mode,
            self.button_custom_color,
        )
        self._apply_page_theme()

        self.utils = AuthWidgets(
            self.cloud,
            self.back,
            self.theme,
            page=self.page,
            web_store=self.web_store,
            icon_pack=self.icon_pack,
            button_color=self.button_color,
        )
        self.main_widgets = MainWidgets(
            self.theme,
            page=self.page,
            web_store=self.web_store,
            icon_pack=self.icon_pack,
            button_color=self.button_color,
        )
        self.utils2 = Utils2(
            self.cloud,
            self.back,
            self.theme,
            self.back2,
            on_theme_change=self.apply_theme_style,
            on_icon_pack_change=self.apply_icon_pack,
            on_button_color_change=self.apply_button_color,
            on_font_change=self.apply_font_settings,
            icon_pack=self.icon_pack,
            button_color=self.button_color,
        )
        self.libs = Fr_Libs(
            self.theme,
            self.phone,
            page=self.page,
            web=self.web,
            icon_pack=self.icon_pack,
            button_color=self.button_color,
        )

        self.main_cont, self.btns_cont, self.tasks_cont = (
            self.main_widgets.build_main_conts(self.page)
        )
        self.sets = self.back2.read_settings()
        self.status_border = self.sets["border"]
        self.border = self.main_widgets.build_status_border(self.status_border)
        self.main_cont.content.controls.append(self.border)

        self.current_group_id = None
        self.screen_host = None
        self.screen_stack = []
        self._reset_root_view()
        self._settings_screens = {}
        self._groups_screen = None
        self._groups_column = None
        self.main_widgets.build_static_input(self)
        self.add_main_widgets()
        if self._app_locked:
            self.show_app_lock()
        else:
            self.show_groups()

    def _on_platform_brightness_change(self, event):
        """Переключает палитру вслед за светлой или тёмной темой устройства."""
        # В Flet 0.81.0 обработчик может получить как типизированный
        # PlatformBrightnessChangeEvent, так и обычный Event с полем data.
        brightness = getattr(event, "brightness", None)
        if brightness is None:
            brightness = getattr(event, "data", None)
        if isinstance(brightness, dict):
            brightness = brightness.get("brightness")
        brightness = brightness or self.page.platform_brightness

        next_theme = resolve_theme(self.theme_style, brightness)
        if next_theme != self.theme:
            self.apply_theme_style(self.theme_style, brightness)

    def apply_icon_pack(self, icon_pack):
        """Сразу перестраивает интерфейс с выбранным паком иконок."""
        self.icon_pack = icon_pack
        self.apply_theme_style(self.theme_style)

    def apply_button_color(self):
        """Сразу перестраивает интерфейс с выбранным акцентным цветом."""
        self.apply_theme_style(self.theme_style)

    def apply_font_settings(self):
        """Rebuild text and keep customization open for further adjustments."""
        group_id = self.current_group_id
        self.apply_theme_style(self.theme_style)
        if group_id is not None:
            self.current_group_id = group_id
            self.render_daily_repeat_tasks()
            if self.web:
                self._set_screen(self.main_cont, push=True)
            else:
                self.page.views.append(ft.View(
                    route="/tasks-font", controls=[self.main_cont],
                    padding=self.page_edge_padding,
                ))
        self.open_settings()
        header, content, back = self.utils2.build_dialog_customization()
        self.open_modified_dialog2(header, content, back)

    def add_input(self, widget):
        """Функция для добавления виджета в контейнер для создания нового дела"""
        self.btns_cont.content.controls.append(widget)

    def add_main_widgets(self):
        """Добавляет созданные в ``Frontend.main`` виджеты на главную страницу."""
        self.add_input(self.button_add_task)
        self.add_input(self.settings)
        self.add_input(self.auth_btn)
        self.add_input(self.undo_btn)
        self.add_input(self.upd_btn)
        if not self.phone:
            self.add_input(self.groups_btn)

        if self.phone:
            buttons_row = self.btns_cont.content
            self.btns_cont.content = ft.Column(
                controls=[buttons_row, self.upload_progress_cont],
                spacing=0,
            )
        else:
            self.add_input(self.search_btn)
            self.add_input(self.search_field)
            self.add_input(self.search_close_btn)
            self.add_input(self.filter_btn)
            self.add_input(self.upload_progress)

    def _refresh_undo_buttons(self):
        disabled = not self.back.can_undo()
        for name in ('undo_btn', 'groups_undo_btn'):
            button = getattr(self, name, None)
            if button is not None:
                button.disabled = disabled
                try:
                    button.update()
                except RuntimeError:
                    pass

    def undo_last_action(self, e=None):
        if not self._guard_attachment_quota(self.back.undo_last_action)():
            return
        self.cloud.alg_for_redact()
        self._settings_screens.clear()
        self._refresh_special_task_lists()
        groups = self.back.get_groups()
        if self.current_group_id is None or not any(
            group['id'] == self.current_group_id for group in groups
        ):
            self.show_groups()
        else:
            self._load_default_task_filter()
            self.render_daily_repeat_tasks()
            self._update_control(self.tasks_cont)

    async def show_offline_start_dialog(self):
        """Показывает предупреждение при запуске без интернета."""
        if self.cloud.connect:
            return
        await asyncio.sleep(0.2)
        self.libs.open_dialog(
            "Подключение",
            "Нет подключения к интернету, \nпопробуйте перезапустить приложение, если интернет у вас есть. \nПриложение переведено в локальный режим",
            self.page,
        )

    def show_start_screen(self):
        """Показывает нужный экран после запуска приложения."""
        if self._notes_dialog is not None:
            return
        self.show_groups()
        if not self.back2.read_settings()["notes_accepted"]:
            self.show_notes_agreement()
            return
        self._finish_start_screen()

    def show_notes_agreement(self):
        """Сохраняет согласие только после явного нажатия кнопки."""
        if self._notes_dialog is not None:
            return

        accepted = False

        def accept_notes(e):
            nonlocal accepted
            if accepted or self._notes_dialog is not dialog:
                return
            self.back2.redact_setting("notes_accepted", True)
            accepted = True
            self.page.pop_dialog()

        def dismiss_notes(e):
            if self._notes_dialog is not dialog:
                return
            self._notes_dialog = None
            # Закрытие модального окна на клиенте асинхронное. Новый View
            # открываем после on_dismiss, чтобы окно не оставалось под ним.
            if accepted:
                self._finish_start_screen()

        accept = self.libs.create_style_button("Согласен и продолжить")
        accept.on_click = accept_notes
        dialog = ft.AlertDialog(
            modal=True,
            scrollable=True,
            bgcolor=self.ContBgColor,
            title=ft.Text(" Примечания", color=self.TxtColor,
                          size=self.libs.text_size(18), weight=ft.FontWeight.W_700),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Перед началом работы ознакомьтесь с примечаниями.",
                            color=self.TxtColor),
                    self.main_widgets.create_notes_text(),
                ], tight=True, spacing=16),
                width=self.libs.width_dialogs,
            ),
            actions=[accept],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=dismiss_notes,
        )
        self._notes_dialog = dialog
        self.page.show_dialog(dialog)

    def _finish_start_screen(self):
        """Продолжает обычный запуск после согласия с примечаниями."""
        if not self.cloud.check_user_data():
            self.open_auth_dialog()
        self.page.run_task(self.show_offline_start_dialog)

    async def _apply_upload_indicator_state(self, is_uploading):
        """Обновляет индикатор фоновой загрузки на облако.

        Виджеты (upload_progress, search_btn) находятся внутри main_cont,
        который примонтирован в screen_host только пока открыт экран дел
        конкретной группы (не на экране выбора групп). Колбэк облака может
        сработать в любой момент из фонового потока, поэтому здесь нужно
        безопасно обрабатывать случай, когда контрола ещё нет на странице.
        """
        self.upload_progress.visible = is_uploading
        self.groups_progress.visible = is_uploading
        self.upload_progress_cont.visible = is_uploading
        self.groups_progress_cont.visible = is_uploading
        if self.phone:
            self.search_btn.text = "Поиск" if is_uploading else "Поиск дел"
            try:
                self.search_btn.update()
            except RuntimeError:
                pass
        try:
            (self.upload_progress_cont if self.phone else self.upload_progress).update()
        except RuntimeError:
            pass
        try:
            self.groups_progress_cont.update()
        except RuntimeError:
            pass

    def _set_upload_indicator(self, is_uploading):
        try:
            self.page.run_task(self._apply_upload_indicator_state, is_uploading)
        except Exception:
            pass

    def to_task_content(self, widget):
        """Функция для добавления виджета в контейнер с делами"""
        self.tasks_cont.content.controls.append(widget)

    def create_date_divider(self):
        """Создает разделитель между делами, созданными в разные дни.
        Цвет совпадает с цветом текста темы: белый на тёмной теме,
        чёрный на светлой."""
        return ft.Divider(color=self.libs.colors["SoftBorderColor"], thickness=1, height=16)

    async def open_search(self, e):
        """Функция для открытия поля поиска"""
        self.search_btn.visible = False
        self.search_field.visible = True
        self.search_close_btn.visible = True
        self._update_control(self.main_cont)
        await self.search_field.focus()

    def close_search(self, e):
        """Функция для закрытия поля поиска и сброса фильтрации"""
        self.search_field.value = ""
        self.apply_search_filter("")
        self.search_field.visible = False
        self.search_close_btn.visible = False
        self.search_btn.visible = True
        self._update_control(self.main_cont)

    def apply_search_filter(self, query):
        """Функция для применения фильтрации дел по названию"""
        query = (query or "").strip().lower()
        self.current_search = query
        for control in self.tasks_cont.content.controls:
            if isinstance(control, ft.Divider):
                control.visible = not query
            name = getattr(control, "data", None)
            if name is None:
                continue  # пропускаем spacer и прочие служебные виджеты
            control.visible = (query in name.lower()) if query else True
        self._refresh_task_overview()

    def _refresh_task_overview(self):
        """Обновляет счётчики по отображаемым карточкам без чтения хранилища."""
        cards = [c for c in self.tasks_cont.content.controls
                 if isinstance(getattr(c, "data", None), str)]
        total = len(cards)
        completed = sum(
            bool(control.value) for card in cards for control in card.content.controls
            if isinstance(control, ft.Checkbox)
        )
        shown = sum(bool(c.visible) for c in cards)
        if getattr(self, '_notes_group', False):
            self._refresh_notes_overview(total, shown)
            return
        self.task_summary.value = (
            f"Найдено: {shown} из {total}" if self.current_search else
            f"Выполнено {completed} из {total}  ·  Осталось {total - completed}"
            if total else "Всё начинается с первого дела"
        )
        self.task_progress.value = completed / total if total else 0
        show_counter = getattr(self, "show_completion_counter", True)
        self.task_summary.visible = show_counter or bool(self.current_search)
        self.task_progress.visible = show_counter and total > 0
        self.task_overview.visible = self.task_heading.visible or self.task_summary.visible
        self.empty_title.value = " Ничего не найдено" if self.current_search else " Здесь пока нет дел"
        self.empty_hint.value = (
            "Попробуйте другое название или очистите поиск."
            if self.current_search else "Добавьте первое дело — начните с самого простого."
        )
        self.empty_state.visible = shown == 0
        if self.empty_state not in self.tasks_cont.content.controls:
            self.tasks_cont.content.controls.append(self.empty_state)

    def filter_tasks(self, e):
        """Функция для поиска/фильтрации дел по названию"""
        self.apply_search_filter(e.control.value)
        self._update_control(self.main_cont)

    @staticmethod
    def _deadline_sort_value(task):
        """Возвращает дедлайн в сравнимом виде; пустые/битые даты идут в конец."""
        try:
            return datetime.strptime(task.get("deadline") or "", "%d-%m-%Y")
        except (TypeError, ValueError):
            return None

    def _sort_tasks(self, tasks):
        """Применяет основной и дополнительный фильтры к списку дел."""
        tasks = list(tasks)
        if self.current_sort in ("deadline_desc", "deadline_asc"):
            with_deadline = []
            without_deadline = []
            for task in tasks:
                deadline = self._deadline_sort_value(task)
                if deadline is None:
                    without_deadline.append(task)
                else:
                    with_deadline.append((deadline, task))
            with_deadline.sort(
                key=lambda item: item[0],
                reverse=self.current_sort == "deadline_desc",
            )
            tasks = [task for _, task in with_deadline] + without_deadline

        elif self.current_sort in ("priority_desc", "priority_asc"):
            priority_order = {
                "Неважно": 0,
                "Важно": 1,
                "Очень важно": 2,
            }
            tasks = sorted(
                tasks,
                key=lambda task: priority_order.get(task.get("priority"), 0),
                reverse=self.current_sort == "priority_desc",
            )

        # Стабильная сортировка сохраняет порядок основного фильтра внутри
        # каждой из двух групп статусов.
        if self.current_status_sort == "incomplete_first":
            tasks.sort(key=lambda task: bool(task.get("status")))
        elif self.current_status_sort == "complete_first":
            tasks.sort(key=lambda task: not bool(task.get("status")))
        return tasks

    def _rebuild_sorted_tasks(self):
        """Перестраивает открытый список после выбора способа сортировки."""
        self.render_daily_repeat_tasks()
        self._update_control(self.main_cont)

    def _reorder_task_cards(self):
        """Меняет порядок готовых карточек, сохраняя обработчики и состояние.

        Исходный порядок берём из хранилища: при одинаковых ключах фильтра
        результат остаётся таким же, как после повторного открытия группы.
        """
        controls = self.tasks_cont.content.controls
        positions = [i for i, control in enumerate(controls)
                     if isinstance(getattr(control, "data", None), str)]
        cards = {controls[i].key: controls[i] for i in positions}
        tasks = self._sort_tasks(
            task for task in self.back.read_tasks()
            if task.get("group") == self.current_group_id
            and isinstance(task.get("name"), str) and task["name"].strip()
        )
        if len(tasks) != len(positions) or any(task["id"] not in cards for task in tasks):
            # Например, фоновая синхронизация уже изменила состав группы.
            self.render_daily_repeat_tasks()
            return
        for position, task in zip(positions, tasks):
            controls[position] = cards[task["id"]]

    def _load_default_task_filter(self):
        """Выбирает фильтр группы, а при его отсутствии — общий."""
        self.sets = self.back2.read_settings()
        group_filter = (
            self.back.get_group_default_filter(self.current_group_id)
            if self.current_group_id is not None else None
        )
        if group_filter is None:
            sort_mode = self.sets["default_task_sort"]
            status_sort = self.sets["default_task_status_sort"]
        else:
            sort_mode = self.back2._normalize_task_sort(group_filter["sort"])
            status_sort = self.back2._normalize_task_status_sort(group_filter["status_sort"])
        self.current_sort = None if sort_mode == "disabled" else sort_mode
        self.current_status_sort = None if status_sort == "disabled" else status_sort

    def apply_task_sort(self, sort_mode, status_sort=None):
        self.current_sort = sort_mode
        self.current_status_sort = status_sort
        self._rebuild_sorted_tasks()

    def open_task_filter_dialog(self, e=None):
        """Открывает экран комплексного фильтра в общем стиле приложения."""
        group_id = self.current_group_id
        group_filter = self.back.get_group_default_filter(group_id)
        group_name = next(
            (group["name"] for group in self.back.get_groups() if group["id"] == group_id),
            "Без группы",
        )
        main_filter = ft.Dropdown(
            value=self.current_sort or "disabled",
            width=self.libs.width_dialogs * 0.95,
            options=[
                ft.dropdown.Option(key="disabled", text="Отключено"),
                ft.dropdown.Option(key="priority_desc", text="По важности - по убыванию"),
                ft.dropdown.Option(key="priority_asc", text="По важности - по возрастанию"),
                ft.dropdown.Option(key="deadline_desc", text="По дедлайну - по убыванию"),
                ft.dropdown.Option(key="deadline_asc", text="По дедлайну - по возрастанию"),
            ],
        )
        additional_filter = ft.Dropdown(
            value=self.current_status_sort or "disabled",
            width=self.libs.width_dialogs * 0.95,
            options=[
                ft.dropdown.Option(key="disabled", text="Отключено"),
                ft.dropdown.Option(key="incomplete_first", text="Сначала невыполненные"),
                ft.dropdown.Option(key="complete_first", text="Сначала выполненные"),
            ],
        )

        def apply_filters(event=None):
            main_sort = None if main_filter.value == "disabled" else main_filter.value
            status_sort = (
                None
                if additional_filter.value == "disabled"
                else additional_filter.value
            )
            self.close_page()
            self.apply_task_sort(main_sort, status_sort)

        def apply_saved_default():
            self._load_default_task_filter()
            self.close_page()
            self._rebuild_sorted_tasks()

        def save_as_default(event=None):
            self.back2.redact_setting("default_task_sort", main_filter.value)
            self.back2.redact_setting(
                "default_task_status_sort", additional_filter.value
            )
            apply_saved_default()

        def reset_default(event=None):
            self.back2.redact_setting("default_task_sort", "disabled")
            self.back2.redact_setting("default_task_status_sort", "disabled")
            apply_saved_default()

        def save_for_group(event=None):
            if self.back.set_group_default_filter(
                group_id, main_filter.value, additional_filter.value
            ):
                self.cloud.alg_for_redact()
                apply_saved_default()

        def reset_for_group(event=None):
            if self.back.reset_group_default_filter(group_id):
                self.cloud.alg_for_redact()
                apply_saved_default()

        apply_button = self.libs.create_style_button("Применить")
        apply_button.on_click = apply_filters
        save_default_button = self.libs.create_style_button(
            "Сохранить общий фильтр", ft.Icons.SAVE_OUTLINED
        )
        save_default_button.on_click = save_as_default
        reset_default_button = self.libs.create_style_button(
            "Сбросить общий фильтр", ft.Icons.RESTART_ALT
        )
        reset_default_button.on_click = reset_default
        save_group_button = self.libs.create_style_button(
            "Сохранить для этой группы", ft.Icons.SAVE_OUTLINED
        )
        save_group_button.on_click = save_for_group
        save_group_button.disabled = group_id is None
        reset_group_button = self.libs.create_style_button(
            "Использовать общий фильтр", ft.Icons.RESTART_ALT
        )
        reset_group_button.on_click = reset_for_group
        reset_group_button.disabled = group_filter is None
        back_button = self.libs.create_style_button("Назад")

        header = self.libs.create_style_header("Фильтр дел")
        content = self.libs.create_style_cont(
            [
                ft.Text(
                    "Основной фильтр",
                    size=self.libs.text_size(16),
                    weight=ft.FontWeight.W_500,
                    color=self.TxtColor,
                ),
                main_filter,
                ft.Divider(color=self.BorderColor),
                ft.Text(
                    "Дополнительный фильтр",
                    size=self.libs.text_size(16),
                    weight=ft.FontWeight.W_500,
                    color=self.TxtColor,
                ),
                additional_filter,
                ft.Divider(color=self.BorderColor),
                ft.Text(
                    f"Группа: {group_name}. "
                    + ("Задан фильтр группы." if group_filter is not None else "Используется общий фильтр."),
                    size=self.libs.text_size(13),
                    color=self.TxtColor,
                ),
                ft.Row([save_group_button, reset_group_button], wrap=True),
                ft.Text(
                    "При открытии группы применяется её фильтр по умолчанию. "
                    "Если он не задан, применяется общий фильтр.",
                    size=self.libs.text_size(13),
                    color=self.TxtColor,
                ),
                ft.Row([save_default_button, reset_default_button], wrap=True),
                ft.Row([back_button, apply_button], wrap=True),
            ]
        )
        self.open_page(header, content, back_button, "task-filter")

    def exit_from_pc(
        self,
        e: ft.KeyboardEvent,
    ):
        """Функция для выхода из последнего диалога на ПК"""
        if e.key == "Escape":
            self.close_page()

    def _on_view_pop(self, e=None):
        self.close_page()

    def _update_control(self, control):
        """На сайте обновляет один control, на нативных клиентах — как раньше."""
        if self.web:
            control.update()
        else:
            self.page.update()

    def _update_screen_host(self):
        """Отправляет только изменение содержимого корневого экрана."""
        try:
            self.screen_host.update()
        except RuntimeError:
            # Во время начальной сборки host ещё не примонтирован.
            self.page.update()

    def _set_screen(self, body, *, push=False, reset=False):
        """Переключает экран без маршрутов и лишних полных page.update()."""
        if reset:
            self.screen_stack = [body]
        elif push:
            if not self.screen_stack or self.screen_stack[-1] is not body:
                self.screen_stack.append(body)
        elif self.screen_stack:
            self.screen_stack[-1] = body
        else:
            self.screen_stack = [body]
        self.screen_host.content = body
        self._update_screen_host()

    def close_page(self, e=None):
        """Возвращает пользователя с текущей страницы на предыдущую."""
        if self._app_locked:
            return
        if not self.web:
            if len(self.page.views) > 1:
                self.page.views.pop()
                if self.page.views[-1].route == "/groups":
                    self.show_groups()
                    return
                asyncio.create_task(self.page.push_route(self.page.views[-1].route))
            self.page.update()
            return
        if len(self.screen_stack) <= 1:
            return
        self.screen_stack.pop()
        if self.screen_stack[-1] is self._groups_screen:
            self.show_groups()
            return
        self.screen_host.content = self.screen_stack[-1]
        self._update_screen_host()

    def _refresh_special_task_lists(self):
        """Refresh special-task lists without pushing another settings screen."""
        if hasattr(self.utils2, 'cont_with_repeat_task'):
            self.utils2.cont_with_repeat_task.content.controls.clear()
            self.utils2.read_repeat_tasks_and_add_to_cont()
        if hasattr(self.utils2, 'cont_with_postponed_task'):
            self.utils2.cont_with_postponed_task.content.controls.clear()
            self.utils2.read_postponed_tasks_and_add_to_cont()

    @staticmethod
    def _normalize_picker_date(picker_value):
        """Восстанавливает локальную календарную дату из значения DatePicker."""
        if picker_value is None:
            return None

        if isinstance(picker_value, str):
            value = picker_value.strip()
            if not value:
                return None
            try:
                picker_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                try:
                    return date.fromisoformat(value[:10])
                except ValueError:
                    return None

        if isinstance(picker_value, datetime):
            if picker_value.tzinfo is not None:
                return picker_value.astimezone().date()

            # В Flet 0.81 веб/desktop-клиент может прислать локальную полночь
            # как UTC без tzinfo: для Алматы это 18:00 предыдущего дня.
            # Полночь без зоны уже является календарной датой и не переводится.
            if picker_value.time() != datetime.min.time():
                return picker_value.replace(tzinfo=timezone.utc).astimezone().date()
            return picker_value.date()

        if isinstance(picker_value, date):
            return picker_value
        return None

    def _picker_event_date(self, event):
        """Берёт исходную дату события, не полагаясь только на control.value."""
        event_value = getattr(event, "data", None)
        picked = self._normalize_picker_date(event_value)
        if picked is not None:
            return picked
        return self._normalize_picker_date(event.control.value)

    def _guard_attachment_quota(self, action):
        @wraps(action)
        def guarded(*args, **kwargs):
            try:
                return action(*args, **kwargs)
            except AttachmentQuotaError as error:
                self.libs.open_dialog("Лимит вложений", str(error), self.page)
                return False
        return guarded

    def _add_task_metadata_controls(self, dialog, metadata=None, deadline_as_days=False,
                                    *, task_id=None, attachment_section="tasks"):
        """Adds the single-choice metadata picker and returns its current values."""
        metadata = metadata or {}
        deadline = metadata.get("deadline") or ""
        deadline_days = metadata.get("deadline_days")
        if deadline_as_days and deadline_days in (None, "") and deadline:
            try:
                deadline_date = datetime.strptime(deadline, "%d-%m-%Y").date()
                deadline_days = max(1, (deadline_date - local_today(self.web, self.page)).days)
            except (TypeError, ValueError):
                deadline_days = ""
        priority = metadata.get("priority") or "Неважно"
        today = local_today(self.web, self.page)
        created_date = metadata.get("created_date") or today.strftime("%d-%m-%Y")
        kind = metadata.get("info_type") or (
            "deadline" if deadline or deadline_days not in (None, "") else
            "priority" if priority != "Неважно" else "created_date"
        )
        label = ft.Text("Выберите дополнительную информацию о деле", size=self.libs.text_size(16),
                        weight=ft.FontWeight.W_500, color=self.TxtColor)
        selector = ft.Dropdown(value=kind, width=self.libs.width_dialogs * 0.95, options=[
            ft.dropdown.Option(key="created_date", text="Дата создания дела"),
            ft.dropdown.Option(key="deadline", text="Дедлайн дела"),
            ft.dropdown.Option(key="priority", text="Важность дела"),
        ])
        deadline_field = ft.TextField(
                                      label="Дедлайн через (дней)" if deadline_as_days else "Дедлайн дела",
                                      value=str(deadline_days or "") if deadline_as_days else deadline,
                                      hint_text="Введите количество дней" if deadline_as_days else "Не выбран",
                                      read_only=not deadline_as_days,
                                      keyboard_type=ft.KeyboardType.NUMBER if deadline_as_days else ft.KeyboardType.TEXT,
                                      width=self.libs.width_dialogs * 0.95,
                                      visible=kind == "deadline")
        deadline_button = self.libs.create_style_button("Выбрать дату", ft.Icons.CALENDAR_MONTH)
        deadline_button.visible = kind == "deadline" and not deadline_as_days
        priority_dropdown = ft.Dropdown(label="Важность дела", value=priority,
            options=[ft.dropdown.Option(key=value, text=value) for value in
                     ("Неважно", "Важно", "Очень важно")],
            width=self.libs.width_dialogs * 0.95, visible=kind == "priority")

        def on_deadline_change(event):
            picked = self._picker_event_date(event)
            if picked:
                deadline_field.value = picked.strftime("%d-%m-%Y")
                self.page.update()

        picker = ft.DatePicker(current_date=today, on_change=on_deadline_change,
                               locale=ft.Locale("ru", "RU"))
        if picker not in self.page.overlay:
            self.page.overlay.append(picker)
        deadline_button.on_click = lambda _: (setattr(picker, "open", True), self.page.update())

        def update_visibility(event=None):
            deadline_field.visible = selector.value == "deadline"
            deadline_button.visible = selector.value == "deadline" and not deadline_as_days
            priority_dropdown.visible = selector.value == "priority"
            self.page.update()

        selector.on_select = update_visibility
        controls = dialog["Main Cont"].content.controls
        controls[-1:-1] = [label, selector, deadline_field, deadline_button, priority_dropdown]
        attachments = AttachmentEditor(
            self.libs, metadata.get("attachments"), back=self.back,
            task_id=task_id or metadata.get("id"), section=attachment_section,
        )
        attachments.refresh()
        controls.insert(-1, attachments.control)

        def values():
            selected = selector.value
            selected_deadline_days = ""
            if selected == "deadline" and deadline_as_days:
                try:
                    selected_deadline_days = int(deadline_field.value)
                    if not 1 <= selected_deadline_days <= 3650:
                        raise ValueError
                except (TypeError, ValueError):
                    deadline_field.label = "Введите число от 1 до 3650"
                    deadline_field.border_color = ft.Colors.RED
                    self.page.update()
                    return None
                deadline_field.label = "Дедлайн через (дней)"
                deadline_field.border_color = None
            return {
                "created_date": created_date,
                "deadline": (
                    deadline_field.value
                    if selected == "deadline" and not deadline_as_days
                    else ""
                ),
                "deadline_days": selected_deadline_days,
                "priority": priority_dropdown.value if selected == "priority" else "Неважно",
                "info_type": selected,
                "attachments": attachments.values(),
            }
        return values

    def open_page(self, header, content, cancel_button=None, route="dialog"):
        """Открывает экран оптимизированно на сайте и через View на клиентах."""
        if cancel_button is not None:
            cancel_button.on_click = self.close_page
        body = self.libs.collection_widgets_fo_dialog(header, content, self.border)
        if self.web:
            self._set_screen(body, push=True)
        else:
            path = f"/{route}-{len(self.page.views)}"
            self.page.views.append(
                ft.View(route=path, controls=[body], padding=self.page_edge_padding)
            )
            asyncio.create_task(self.page.push_route(path))
            self.page.update()
        return body

    def _validate_text_length(self, entry, text=None):
        entry.error = text_length_error(entry.value if text is None else text)
        if entry.error:
            self._update_control(entry)
            return False
        return True

    def add_task(self, e, name_task, status, new_task, repeat_task, group_id=None,
                 mark_as_daily_repeat=False, created_date=None, deadline=None,
                 priority='Неважно', info_type='created_date', *, task_id=None,
                 group_settings=None, defer_update=False, attachments=None):
        """Функция для добавления дела.

        mark_as_daily_repeat=True помечает создаваемое дело как ежедневное
        (повторяющееся) — используется при автодобавлении из
        check_and_add_repeat_task.
        """
        new_task = bool(new_task)
        if (new_task or repeat_task) and not self._validate_text_length(self.entry_task, name_task):
            return False
        if name_task.strip() == "":  # Проверка на непустое дело
            self.entry_task.label = "Вводите непустое дело"
            self.entry_task.border_color = ft.Colors.RED
            return False
        elif "---" in name_task:
            self.libs.open_dialog("Новое дело", "Недопустимый символ: ---", self.page)
            return False
        elif "|" in name_task:
            self.libs.open_dialog("Новое дело", "Недопустимый символ: |", self.page)
            return False
        else:
            self.entry_task.hint_text = "Обязательно для заполнения"
            self.entry_task.label = "Название дела"
            self.entry_task.border_color = None

            delo_obr = self.back.auto_add_new_string(name_task)
            target_group_id = group_id or self.current_group_id or 'default'
            if new_task:
                id_ = self._guard_attachment_quota(self.back.saveB)(
                    name_task, target_group_id, created_date=created_date,
                    deadline=deadline, priority=priority, info_type=info_type,
                    attachments=attachments,
                )
                if id_ is False:
                    return False
                self.close_dlg("f")  # Закрываем диалог
            elif repeat_task:
                id_ = self.back.saveB(name_task, target_group_id, is_repeat=mark_as_daily_repeat,
                                      attachments=attachments)
            else:
                id_ = task_id if task_id is not None else self.back.read_id(name_task)
            # Храним и ищем исходное название; переносы нужны только для показа.

            if (new_task or repeat_task) and target_group_id != (self.current_group_id or 'default'):
                self.cloud.alg_for_redact()
                self.back.delete_empty_lines()
                self.page.update()
                return False

            if created_date is None and id_ and task_id is None:
                created_date = self.back.read_created_date(id_)

            if new_task or repeat_task:
                self.cloud.alg_for_redact()
                self.back.delete_empty_lines()

                if new_task and (self.current_sort or self.current_status_sort):
                    self._rebuild_sorted_tasks()
                    return True

                # Полная перестройка нужна только для небольших списков:
                # она позволяет сразу правильно расположить дело по датам.
                # Для больших списков добавляем только новый виджет, чтобы
                # добавление дела не перегружало интерфейс.
                tasks_in_group = sum(
                    1
                    for task_data in self.back.read_tasks()
                    if task_data.get("group") == target_group_id
                )
                if tasks_in_group <= 10 and repeat_task:
                    self.render_daily_repeat_tasks()
                    self.page.update()
                    return True

            widgets = self.utils.create_row_with_task(
                delo_obr, status, id_, created_date, target_group_id, deadline, priority, info_type,
                group_settings=group_settings,
                attachments=attachments,
            )
            row = widgets[0]
            row.data = name_task  # Поиск не зависит от переносов для отображения.
            row.key = id_

            self.to_task_content(row)  # Добавляем GUI с делами
            if self.current_search:
                row.visible = self.current_search in name_task.lower()

            async def delete_task(e, id_task, row_widget):
                print("deleted task")
                self.back.kill_taskB(id_task)
                self.back.delete_empty_lines()
                if row_widget in self.tasks_cont.content.controls:
                    self.tasks_cont.content.controls.remove(row_widget)
                self.apply_search_filter(self.current_search)
                self.page.update()
                self.cloud.alg_for_redact()

            def redact_task(e, id_task, row_widget):
                """Функция для редактирования дела"""

                @self._guard_attachment_quota
                def real_redact(e=None):
                    """Именно редактирование дела"""
                    if not self._validate_text_length(entry_new_task):
                        return
                    new_name = entry_new_task.value
                    metadata = metadata_values()
                    if metadata is None:
                        return
                    self.back.redact_taskB(id_task, new_name, metadata)

                    # Пересобираем строку целиком, чтобы сразу обновились не
                    # только название, но и дедлайн/важность, их цвет и кнопки.
                    task_data = self.back.get_task(id_task)
                    if task_data is not None:
                        if self.current_sort or self.current_status_sort:
                            self.close_page()
                            self.cloud.alg_for_redact()
                            self._rebuild_sorted_tasks()
                            return
                        display_name = self.back.auto_add_new_string(new_name)
                        rebuilt_widgets = self.utils.create_row_with_task(
                            display_name,
                            task_data.get("status", False),
                            id_task,
                            task_data.get("created_date"),
                            task_data.get("group", "default"),
                            task_data.get("deadline", ""),
                            task_data.get("priority", "Неважно"),
                            task_data.get("info_type", "created_date"),
                            attachments=task_data.get("attachments"),
                        )
                        rebuilt_row = rebuilt_widgets[0]
                        rebuilt_row.data = new_name
                        rebuilt_row.key = id_task
                        if self.current_search:
                            rebuilt_row.visible = self.current_search in new_name.lower()

                        controls = self.tasks_cont.content.controls
                        if row_widget in controls:
                            controls[controls.index(row_widget)] = rebuilt_row
                            bind_task_actions(rebuilt_widgets, rebuilt_row)
                            self.apply_search_filter(self.current_search)

                    self.close_page()
                    self.cloud.alg_for_redact()
                    self.page.update()

                """Импорт виджетов"""
                form_widgets = self.libs.widgets_for_ask_task(
                    "Введите новое название дела",
                    "Изменить дело",
                    "Редактирование дела",
                )
                save_button = form_widgets["btn_create_task"]
                save_button.on_click = real_redact
                cancel2 = form_widgets["cancel"]
                cancel2.on_click = self.close_dlg
                entry_new_task = form_widgets["entry_task"]
                entry_new_task.value = self.back.read_name(id_task)
                self.libs.update_text_counter(entry_new_task)
                entry_new_task.on_submit = save_button.on_click
                metadata_values = self._add_task_metadata_controls(
                    form_widgets, self.back.get_task(id_task)
                )
                cont_AC = form_widgets.get("Main Cont")
                cont_H = form_widgets.get("Header")

                """Открытие диалога"""
                self.open_modified_dialog(cont_H, cont_AC, cancel2)

            def bind_task_actions(task_widgets, task_row):
                checkbox = task_widgets[4]

                def save_status_and_refresh(event):
                    self.utils.on_change_checkbox(
                        event, id_, checkbox.value, task_row, task_widgets[3], update=False,
                    )
                    if self.current_status_sort:
                        self._reorder_task_cards()
                    self._refresh_task_overview()
                    self.page.update()

                checkbox.on_change = save_status_and_refresh
                task_widgets[1].on_click = lambda e, i=id_, r=task_row: self.page.run_task(
                    delete_task, e, i, r
                )
                task_widgets[2].on_click = lambda e, i=id_, r=task_row: redact_task(
                    e, i, r
                )

            bind_task_actions(widgets, row)
            # Render the row only after its actions are bound. This makes newly
            # added tasks interactive immediately and is also safe while an
            # entire group screen is still being assembled.
            if not defer_update:
                self._refresh_task_overview()
                self.page.update()
            return True

    def close_dlg(self, e):
        self.entry_task.label = ""
        self.entry_task.hint_text = "Обязательно для заполнения"
        self.close_page()

    def open_modified_dialog(self, cont_title, cont_actions, button_for_cancel):
        """Функция для открытия диалога для редактирования дела"""
        self.modified_dialog = self.open_page(
            cont_title, cont_actions, button_for_cancel
        )

    def open_modified_dialog2(self, cont_title, cont_actions, button_for_cancel):
        """Функция для открытия диалога для редактирования дела"""
        self.modified_dialog2 = self.open_page(
            cont_title, cont_actions, button_for_cancel, "dialog-2"
        )

    def open_modified_dialog3(self, cont_title, cont_actions, button_for_cancel):
        """Функция для открытия диалога третьего уровня
        (например, добавление ежедневного дела из окна 'Особые дела')"""
        self.modified_dialog3 = self.open_page(
            cont_title, cont_actions, button_for_cancel, "dialog-3"
        )

    def open_auth_dialog(self):
        """Функция для открытия диалога авторизации"""

        widgets = self.utils.build_widgets_for_login(
            self.page, lambda: self.update_tasks(self.show_groups), self.login
        )
        btn_login = widgets["Login_act"]
        btn_register = widgets["Register_act"]
        login = widgets["Login"]
        password = widgets["Password"]
        cancel = widgets["Cancel"]

        cancel.on_click = self.close_page
        btn_login.on_click = lambda _: self.login(login.value, password.value)
        btn_register.on_click = lambda _: self.register(login.value, password.value)

        self.open_modified_dialog(widgets["Header_cont"], widgets["Main_cont"], cancel)

    def open_settings(self):
        """Функция для открытия окна настроек.
        Главный экран содержит только кнопки-категории,
        по нажатию на каждую открывается свой диалог с настройками."""
        group_id = self.current_group_id or "default"
        cached = self._settings_screens.get(group_id) if self.web else None
        if cached is not None:
            self._set_screen(cached, push=True)
            return

        self.settings_cont, a, primechanya, dialogs = (
            self.utils2.build_widgets_for_settings(
                self.update_tasks,
                self.open_repeat_dialog,
                self.open_postponed_dialog,
                self.page,
                self.notification_service.reload_settings,
                self.notification_service.request_battery_optimization_exemption,
                group_id,
                self.render_daily_repeat_tasks,
            )
        )

        # Назначаем обработчики до монтирования экрана. Иначе веб-клиент
        # сначала получает кнопки без on_click, и они начинают работать
        # только после следующего случайного обновления интерфейса.
        special = dialogs["special"]
        self.utils2.on_edit_repeat = self.open_edit_repeat_dialog
        self.utils2.on_edit_postponed = self.open_edit_postponed_dialog
        special["button"].on_click = lambda e: self.open_special_tasks()

        # «Управление делами» и «Общие настройки» теперь ExpansionTile:
        # их содержимое уже встроено в окно настроек, on_click не нужен.

        async def open_security(e):
            header, content, back, load = self.utils2.build_dialog_security(self.page)
            self.open_modified_dialog2(header, content, back)
            await load()

        dialogs["security"]["button"].on_click = open_security

        """Кастомизация"""
        customization = dialogs["customization"]
        customization["button"].on_click = lambda e: self.open_modified_dialog2(
            customization["header"],
            customization["content"],
            customization["back"],
        )

        """Уведомления"""
        notifications = dialogs["notifications"]
        notifications["button"].on_click = lambda e: self.open_modified_dialog2(
            notifications["header"], notifications["content"], notifications["back"]
        )

        """Примечания"""
        h, m, n = self.main_widgets.dialog_for_primechanya()
        primechanya.on_click = lambda e: self.open_modified_dialog2(h, m, n)

        """Основное окно (только кнопки)"""
        settings_screen = self.open_modified_dialog(
            self.libs.create_style_header(
            'Настройки'),
            self.settings_cont,
            a,
        )
        if self.web:
            self._settings_screens[group_id] = settings_screen

    def _open_special_task_info(self, repeating):
        build_info = (
            self.main_widgets.dialog_for_info_repeat if repeating
            else self.main_widgets.dialog_for_info_postponed
        )
        self.open_modified_dialog3(*build_info())

    def open_special_tasks(self):
        self.utils2.on_edit_repeat = self.open_edit_repeat_dialog
        self.utils2.on_edit_postponed = self.open_edit_postponed_dialog
        self.open_modified_dialog2(*self.utils2.build_dialog_special_tasks(
            self.open_repeat_dialog, self.open_postponed_dialog, self.page,
            self.open_special_task_list,
            lambda: self._open_special_task_info(True),
            lambda: self._open_special_task_info(False),
        ))

    def open_special_task_list(self, repeating):
        self.open_modified_dialog3(*self.utils2.build_dialog_special_task_list(
            repeating,
            self.open_repeat_dialog if repeating else self.open_postponed_dialog,
            lambda: self._open_special_task_info(repeating),
            self.page,
        ))

    def create_group_dropdown(self):
        groups = [g for g in self.back.get_groups() if g['type'] == 'tasks']
        if not any(group["id"] == 'default' for group in groups):
            groups.insert(0, {"name": "Без группы", "id": "default"})
        value = self.current_group_id if any(group["id"] == self.current_group_id for group in groups) else 'default'
        return ft.Dropdown(
            label="Группа дел",
            value=value,
            options=[
                ft.dropdown.Option(key=group["id"], text=group["name"])
                for group in groups
            ],
            width=self.libs.width_dialogs * 0.95,
        )

    def open_repeat_dialog(self):
        """Функция для открытия диалога с запросом имени повторяющегося дела
        и его периодичности: ежедневно, еженедельно (день недели),
        ежемесячно (число месяца 1-31), ежегодно (дата) или свой интервал
        (число дней от 1 до 367)."""
        dialog = self.libs.widgets_for_ask_task(
            "Введите повторяющееся дело",
            "Добавить повторяющееся дело",
            "Новое повторяющееся дело",
            with_interval=True,
        )

        btn_create_repeat = dialog["btn_create_task"]
        entry_task_rep = dialog["entry_task"]
        repeat_type_dd = dialog["repeat_type_dd"]
        entry_interval_rep = dialog["entry_interval"]
        weekday_dd = dialog["weekday_dd"]
        month_day_entry = dialog["month_day_entry"]
        year_date_button = dialog["year_date_button"]
        year_date_field = dialog["year_date_field"]
        group_dropdown = self.create_group_dropdown()
        main_cont = dialog["Main Cont"]
        main_cont.content.controls.insert(3, group_dropdown)
        metadata_values = self._add_task_metadata_controls(
            dialog, deadline_as_days=True, attachment_section="repeat_tasks",
        )

        def on_year_date_change(e):
            picker_value = self._picker_event_date(e)
            if picker_value is not None:
                year_date_field.value = picker_value.strftime("%d-%m")
                year_date_field.label = "Выбранная дата"
                year_date_field.border_color = None
            self.page.update()


        self.page.locale_configuration = ft.LocaleConfiguration(
           supported_locales=[ft.Locale("ru", "RU")],
            current_locale=ft.Locale("ru", "RU"),
)
        year_picker = ft.DatePicker(
            first_date=date(local_today(self.web, self.page).year, 1, 1),
            current_date=local_today(self.web, self.page),
            value=local_today(self.web, self.page),
            help_text="Выберите дату повторения",
            field_label_text="Выбранная дата",
            confirm_text="Выбрать",
            cancel_text="Отмена",
            on_change=on_year_date_change,
            locale=ft.Locale("ru", "RU")
        )
        if year_picker not in self.page.overlay:
            self.page.overlay.append(year_picker)

        def open_year_picker(e):
            year_picker.open = True
            self.page.update()

        year_date_button.on_click = open_year_picker

        def update_repeat_widgets(e=None):
            """Показывает набор виджетов, соответствующий выбранной
            периодичности повторения, и скрывает остальные."""
            repeat_type = repeat_type_dd.value
            entry_interval_rep.visible = repeat_type == "custom"
            weekday_dd.visible = repeat_type == "week"
            month_day_entry.visible = repeat_type == "month"
            year_date_button.visible = repeat_type == "year"
            year_date_field.visible = repeat_type == "year"
            self.page.update()

        repeat_type_dd.on_select = update_repeat_widgets
        update_repeat_widgets()

        @self._guard_attachment_quota
        def create_repeat(_):
            if not self._validate_text_length(entry_task_rep):
                return
            repeat_type = repeat_type_dd.value

            if repeat_type == "custom":
                try:
                    interval = int(entry_interval_rep.value)
                    if not (1 <= interval <= 367):
                        raise ValueError
                except (TypeError, ValueError):
                    entry_interval_rep.label = "Введите число от 1 до 367"
                    entry_interval_rep.border_color = ft.Colors.RED
                    self.page.update()
                    return
                entry_interval_rep.label = "Повторять через (дней)"
                entry_interval_rep.border_color = None
                backend_type, backend_value = "day", interval

            elif repeat_type == "week":
                backend_type, backend_value = "week", int(weekday_dd.value)

            elif repeat_type == "month":
                try:
                    month_day = int(month_day_entry.value)
                    if not (1 <= month_day <= 31):
                        raise ValueError
                except (TypeError, ValueError):
                    month_day_entry.label = "Введите число от 1 до 31"
                    month_day_entry.border_color = ft.Colors.RED
                    self.page.update()
                    return
                month_day_entry.label = "Число месяца"
                month_day_entry.border_color = None
                backend_type, backend_value = "month", month_day

            elif repeat_type == "year":
                if not year_date_field.value:
                    year_date_field.label = "Сначала выберите дату"
                    year_date_field.border_color = ft.Colors.RED
                    self.page.update()
                    return
                year_date_field.label = "Выбранная дата"
                year_date_field.border_color = None
                backend_type, backend_value = "year", year_date_field.value

            else:
                backend_type, backend_value = "day", 1

            group_id = group_dropdown.value or 'default'
            metadata = metadata_values()
            if metadata is None:
                return
            task_id = self.back2.create_repeat_task(entry_task_rep.value, backend_type, backend_value, group_id, metadata)
            self.utils2.add_to_cont_with_repeat_task(
                entry_task_rep.value, backend_type, backend_value, group_id, task_id, metadata
            )
            self.close_page()

        btn_create_repeat.on_click = create_repeat
        entry_task_rep.on_submit = create_repeat
        entry_interval_rep.on_submit = create_repeat
        month_day_entry.on_submit = create_repeat

        nazad = dialog["cancel"]
        title_cont = dialog["Header"]

        """Открывается на третьем уровне, т.к. второй занят окном 'Особые дела'"""
        self.open_modified_dialog3(title_cont, main_cont, nazad)

    def open_postponed_dialog(self):
        """Открывает диалог создания отложенного дела с выбором даты через календарь."""
        dialog = self.libs.widgets_for_ask_task(
            "Введите отложенное дело",
            "Добавить отложенное дело",
            "Новое отложенное дело",
        )

        btn_create_postponed = dialog["btn_create_task"]
        entry_task_post = dialog["entry_task"]
        main_cont = dialog["Main Cont"]
        title_cont = dialog["Header"]
        nazad = dialog["cancel"]
        group_dropdown = self.create_group_dropdown()
        metadata_values = self._add_task_metadata_controls(
            dialog, deadline_as_days=True, attachment_section="postponed",
        )

        date_field = ft.TextField(
            label="Дата добавления",
            hint_text="Выберите дату в календаре",
            width=self.libs.width_dialogs * 0.95,
            read_only=True,
        )
        date_button = self.libs.create_style_button("Выбрать дату", ft.Icons.CALENDAR_MONTH)

        def on_date_change(e):
            picker_value = self._picker_event_date(e)
            if picker_value is not None:
                date_field.value = picker_value.strftime("%d-%m-%Y")
                date_field.label = "Дата добавления"
                date_field.border_color = None
            self.page.update()

        self.page.locale_configuration = ft.LocaleConfiguration(
            supported_locales=[ft.Locale("ru", "RU"), ft.Locale("en", "GB")],
            current_locale=ft.Locale("ru", "RU"),
        )
        picker = ft.DatePicker(
            first_date=local_today(self.web, self.page),
            current_date=local_today(self.web, self.page),
            value=local_today(self.web, self.page),
            help_text="Выберите дату дела",
            field_label_text="Дата добавления",
            confirm_text="Выбрать",
            cancel_text="Отмена",
            on_change=on_date_change,
            locale = ft.Locale("ru", "RU"),
        )
        if picker not in self.page.overlay:
            self.page.overlay.append(picker)

        def open_picker(e):
            picker.open = True
            self.page.update()

        date_button.on_click = open_picker
        main_cont.content.controls.insert(3, group_dropdown)
        main_cont.content.controls.insert(4, date_field)
        main_cont.content.controls.insert(5, date_button)

        @self._guard_attachment_quota
        def create_postponed(_):
            if not self._validate_text_length(entry_task_post):
                return
            if not date_field.value:
                date_field.label = "Сначала выберите дату"
                date_field.border_color = ft.Colors.RED
                self.page.update()
                return

            metadata = metadata_values()
            if metadata is None:
                return
            created = self.back2.create_postponed_task(
                entry_task_post.value,
                date_field.value,
                group_dropdown.value or 'default',
                metadata,
            )
            if not created:
                date_field.label = "Некорректная дата"
                date_field.border_color = ft.Colors.RED
                self.page.update()
                return

            self.utils2.add_to_cont_with_postponed_task(
                entry_task_post.value,
                date_field.value,
                group_dropdown.value or 'default',
                created,
                metadata,
            )
            self.close_page()

        btn_create_postponed.on_click = create_postponed
        entry_task_post.on_submit = create_postponed
        self.open_modified_dialog3(title_cont, main_cont, nazad)

    def open_edit_repeat_dialog(self, task, repeat_type, repeat_value, group_id, task_id, metadata=None):
        """Открывает форму редактирования с теми же полями, что и добавление."""
        dialog = self.libs.widgets_for_ask_task(
            "Измените повторяющееся дело", "Сохранить",
            "Редактировать повторяющееся дело", with_interval=True,
        )
        entry = dialog["entry_task"]
        entry.value = task.replace('{N}', '\n')
        self.libs.update_text_counter(entry)
        repeat_type_dd = dialog["repeat_type_dd"]
        entry_interval = dialog["entry_interval"]
        weekday_dd = dialog["weekday_dd"]
        month_day_entry = dialog["month_day_entry"]
        year_date_button = dialog["year_date_button"]
        year_date_field = dialog["year_date_field"]
        group_dropdown = self.create_group_dropdown()
        group_dropdown.value = group_id
        dialog["Main Cont"].content.controls.insert(3, group_dropdown)
        metadata_values = self._add_task_metadata_controls(
            dialog, metadata, deadline_as_days=True,
            task_id=task_id, attachment_section="repeat_tasks",
        )

        # В хранилище ежедневное правило и свой интервал используют тип day.
        # В интерфейсе для интервала показываем отдельную опцию custom.
        ui_repeat_type = "custom" if repeat_type == "day" and int(repeat_value) != 1 else repeat_type
        repeat_type_dd.value = ui_repeat_type
        if ui_repeat_type == "custom":
            entry_interval.value = str(repeat_value)
        elif ui_repeat_type == "week":
            weekday_dd.value = str(repeat_value)
        elif ui_repeat_type == "month":
            month_day_entry.value = str(repeat_value)
        elif ui_repeat_type == "year":
            year_date_field.value = str(repeat_value)

        def on_year_date_change(e):
            picker_value = self._picker_event_date(e)
            if picker_value is not None:
                year_date_field.value = picker_value.strftime("%d-%m")
                year_date_field.border_color = None
            self.page.update()

        year_picker = ft.DatePicker(
            first_date=date(local_today(self.web, self.page).year, 1, 1), current_date=local_today(self.web, self.page), value=local_today(self.web, self.page),
            help_text="Выберите дату повторения", field_label_text="Выбранная дата",
            confirm_text="Выбрать", cancel_text="Отмена", on_change=on_year_date_change,
        )
        if year_picker not in self.page.overlay:
            self.page.overlay.append(year_picker)
        year_date_button.on_click = lambda _: (setattr(year_picker, "open", True), self.page.update())

        def update_repeat_widgets(e=None):
            selected = repeat_type_dd.value
            entry_interval.visible = selected == "custom"
            weekday_dd.visible = selected == "week"
            month_day_entry.visible = selected == "month"
            year_date_button.visible = selected == "year"
            year_date_field.visible = selected == "year"
            self.page.update()

        repeat_type_dd.on_select = update_repeat_widgets
        update_repeat_widgets()

        @self._guard_attachment_quota
        def save(_):
            if not self._validate_text_length(entry):
                return
            selected = repeat_type_dd.value
            if selected == "custom":
                try:
                    backend_type, backend_value = "day", int(entry_interval.value)
                    if not 1 <= backend_value <= 367:
                        raise ValueError
                except (TypeError, ValueError):
                    entry_interval.label, entry_interval.border_color = "Введите число от 1 до 367", ft.Colors.RED
                    self.page.update()
                    return
            elif selected == "week":
                backend_type, backend_value = "week", int(weekday_dd.value)
            elif selected == "month":
                try:
                    backend_type, backend_value = "month", int(month_day_entry.value)
                    if not 1 <= backend_value <= 31:
                        raise ValueError
                except (TypeError, ValueError):
                    month_day_entry.label, month_day_entry.border_color = "Введите число от 1 до 31", ft.Colors.RED
                    self.page.update()
                    return
            elif selected == "year":
                if not year_date_field.value:
                    year_date_field.label, year_date_field.border_color = "Сначала выберите дату", ft.Colors.RED
                    self.page.update()
                    return
                backend_type, backend_value = "year", year_date_field.value
            else:
                backend_type, backend_value = "day", 1

            updated_metadata = metadata_values()
            if updated_metadata is None:
                return
            if self.back2.update_repeat_task(task_id, entry.value, backend_type, backend_value, group_dropdown.value or 'default', updated_metadata):
                self._refresh_special_task_lists()
                self.close_page()

        dialog["btn_create_task"].on_click = save
        entry.on_submit = save
        self.open_modified_dialog3(dialog["Header"], dialog["Main Cont"], dialog["cancel"])

    def open_edit_postponed_dialog(self, task, planned_date, group_id, task_id, metadata=None):
        """Открывает форму редактирования отложенного дела."""
        dialog = self.libs.widgets_for_ask_task(
            "Введите отложенное дело", "Сохранить", "Редактировать отложенное дело"
        )
        entry = dialog["entry_task"]
        entry.value = task.replace('{N}', '\n')
        self.libs.update_text_counter(entry)
        group_dropdown = self.create_group_dropdown()
        group_dropdown.value = group_id
        metadata_values = self._add_task_metadata_controls(
            dialog, metadata, deadline_as_days=True,
            task_id=task_id, attachment_section="postponed",
        )
        date_field = ft.TextField(
            label="Дата добавления",
            hint_text="Выберите дату в календаре",
            value=planned_date,
            width=self.libs.width_dialogs * 0.95,
            read_only=True,
        )
        date_button = self.libs.create_style_button("Выбрать дату", ft.Icons.CALENDAR_MONTH)

        def on_date_change(e):
            picker_value = self._picker_event_date(e)
            if picker_value is not None:
                date_field.value = picker_value.strftime("%d-%m-%Y")
                date_field.label = "Дата добавления"
                date_field.border_color = None
            self.page.update()

        picker = ft.DatePicker(
            first_date=date(local_today(self.web, self.page).year, 1, 1),
            current_date=local_today(self.web, self.page),
            value=local_today(self.web, self.page),
            help_text="Выберите дату дела",
            field_label_text="Дата добавления",
            confirm_text="Выбрать",
            cancel_text="Отмена",
            on_change=on_date_change,
            locale=ft.Locale("ru", "RU"),
        )
        if picker not in self.page.overlay:
            self.page.overlay.append(picker)

        def open_picker(_):
            picker.open = True
            self.page.update()

        date_button.on_click = open_picker
        content = dialog["Main Cont"].content.controls
        content.insert(3, group_dropdown)
        content.insert(4, date_field)
        content.insert(5, date_button)

        @self._guard_attachment_quota
        def save(_):
            if not self._validate_text_length(entry):
                return
            if not date_field.value:
                date_field.label = "Сначала выберите дату"
                date_field.border_color = ft.Colors.RED
                self.page.update()
                return

            updated_metadata = metadata_values()
            if updated_metadata is None:
                return
            if self.back2.update_postponed_task(task_id, entry.value, date_field.value, group_dropdown.value or 'default', updated_metadata):
                self._refresh_special_task_lists()
                self.close_page()
            else:
                date_field.label = "Некорректная дата"
                date_field.border_color = ft.Colors.RED
                self.page.update()

        dialog["btn_create_task"].on_click = save
        entry.on_submit = save
        self.open_modified_dialog3(dialog["Header"], dialog["Main Cont"], dialog["cancel"])

    def _open_loading_view(self):
        """Открывает загрузку подходящим для платформы способом."""
        loading = self.main_widgets.build_loading_widget()
        if self.web:
            self._set_screen(loading, push=True)
            return loading
        loading_route = f"/loading-{len(self.page.views)}"
        self.page.views.append(
            ft.View(
                route=loading_route,
                controls=[loading],
                padding=self.page_edge_padding,
            )
        )
        asyncio.create_task(self.page.push_route(loading_route))
        self.page.update()
        return loading_route

    def _close_loading_view(self, loading_token):
        """Закрывает экран загрузки, если он всё ещё открыт."""
        if self.web:
            if self.screen_stack and self.screen_stack[-1] is loading_token:
                self.close_page()
            return
        if self.page.views and self.page.views[-1].route == loading_token:
            self.page.views.pop()
            asyncio.create_task(self.page.push_route(self.page.views[-1].route))
        self.page.update()

    def login(self, login, password):
        """Функция для начала авторизации"""
        loading = self._open_loading_view()

        async def do_login():
            try:
                vosvr = await asyncio.to_thread(self.cloud.alg_for_login, login, password)
            except Exception:
                self.libs.open_dialog(
                    "Авторизация", "Не удалось подключиться к Dropbox. Проверьте настройки хранилища и интернет.",
                    self.page,
                )
                return
            finally:
                self._close_loading_view(loading)

            connect = vosvr["Connect"]
            found_account = vosvr["Have account"]
            if not connect:
                self.libs.open_dialog(
                    "Авторизация", "Нет подключения, авторизация не удалась", self.page
                )
            elif not found_account:
                self.libs.open_dialog(
                    "Авторизация",
                    "Этот аккаунт не найден. Возможно неверный логин или пароль",
                    self.page,
                )
            else:
                self.libs.open_dialog(
                    "Авторизация", "Вы успешно вошли в аккаунт", self.page
                )

                # Возвращаемся к корневому экрану групп дел и обновляем данные —
                # так же, как это происходит при первом запуске приложения.
                self.update_tasks(self.show_groups)

        self.page.run_task(do_login)

    def register(self, login, password):
        """Функция для начала регистрации"""
        loading = self._open_loading_view()

        async def do_register():
            try:
                vosvr = await asyncio.to_thread(
                    self.cloud.alg_for_regist, login, password
                )
            except Exception:
                self.libs.open_dialog(
                    "Авторизация", "Не удалось подключиться к Dropbox. Проверьте настройки хранилища и интернет.",
                    self.page,
                )
                return
            finally:
                self._close_loading_view(loading)

            connect = vosvr["Connect"]
            found_account = vosvr["Already have account"]
            if not connect:
                self.libs.open_dialog(
                    "Авторизация", "Нет подключения, авторизация не удалась", self.page
                )
            elif found_account:
                self.libs.open_dialog(
                    "Авторизация", "Такой аккаунт уже существует", self.page
                )
            else:
                self.libs.open_dialog(
                    "Авторизация",
                    "Вы успешно создали и вошли в аккаунт.\nДанные из локального аккаунта перенесены в новый",
                    self.page,
                )
                self.close_page()
                self.update_tasks()

        self.page.run_task(do_register)

    def check_and_add_repeat_task(self):
        """Проверяет все ежедневные дела и добавляет наступившие в хранилище."""
        tasks, date = self.back2.check_repeat_tasks()
        for task, group_id, metadata in tasks:
            self.back.saveB(task, group_id, is_repeat=True,
                            deadline=metadata["deadline"], priority=metadata["priority"],
                            info_type=metadata["info_type"], attachments=metadata.get("attachments"))

        if tasks:
            self.cloud.alg_for_redact()
            self.back.delete_empty_lines()

        return bool(tasks)

    def render_daily_repeat_tasks(self):
        """Перестраивает список дел текущей группы без смены экрана."""
        self._notes_group = self.back.get_group_type(self.current_group_id) == 'notes'
        self.filter_btn.visible = not self._notes_group
        self.button_add_task.tooltip = "Добавить заметку" if self._notes_group else "Добавить новое дело"
        self.search_field.hint_text = "Найти заметку…" if self._notes_group else "Найти дело…"
        self.empty_state.content.controls[0].icon = (
            ft.Icons.NOTES_ROUNDED if self._notes_group else ft.Icons.CHECKLIST_ROUNDED
        )
        group_settings = self.back.get_group_settings(
            self.current_group_id or "default"
        )
        self.show_completion_counter = group_settings["show_completion_counter"]
        self.task_heading.visible = group_settings["show_group_title"]
        base = []
        if self.phone:
            base.append(self.search_row_widget)
        self.tasks_cont.content.controls = base

        # Все дела строятся одним списком и разделяются по дате создания.
        if self._notes_group:
            self._render_notes(group_settings)
        else:
            self.before_load(group_settings)
        groups = self.back.get_groups()
        self.task_heading.value = next(
            (g["name"] for g in groups if g["id"] == self.current_group_id), "Мои дела"
        )
        self.apply_search_filter(self.current_search)

    def check_and_add_postponed_task(self):
        """Добавляет отложенные дела в основной список, когда наступила их дата."""
        tasks = self.back2.check_postponed_tasks()
        for task, _planned_date, group_id, metadata in tasks:
            # Отложенное дело отображается в общем списке дел.
            self.back.saveB(task, group_id, is_repeat=True,
                            deadline=metadata["deadline"], priority=metadata["priority"],
                            info_type=metadata["info_type"], attachments=metadata.get("attachments"))

        if tasks:
            self.cloud.alg_for_redact()
            self.back.delete_empty_lines()
        return bool(tasks)

    def before_load(self, group_settings=None):
        """Загружает все дела текущей группы.

        Если включена настройка "Разделять дела по датам", дела, созданные
        в один день, отображаются подряд, а между делами с разными датами
        создания вставляется обычный Divider. Если настройка выключена,
        дела отображаются одним списком без разделителей."""
        self.back.migrate_groups_storage()
        tasks = self._sort_tasks(
            task for task in self.back.read_tasks()
            if task.get("group") == self.current_group_id
        )
        if group_settings is None:
            group_settings = self.back.get_group_settings(self.current_group_id or 'default')
        split_by_dates = group_settings["split_by_dates"]
        split_by_dates = (
            split_by_dates
            and self.current_sort is None
            and self.current_status_sort is None
        )
        last_date = None
        is_first = True
        for data in tasks:
            name = data.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            status = data.get("status")
            created_date = data.get("created_date")
            if split_by_dates and not is_first and created_date != last_date:
                self.to_task_content(self.create_date_divider())
            is_first = False
            last_date = created_date
            self.add_task(
                "f", name, status, False, False, created_date=created_date,
                deadline=data.get("deadline", ""), priority=data.get("priority", "Неважно"),
                info_type=data.get("info_type", "created_date"),
                task_id=data["id"], group_settings=group_settings, defer_update=True,
                attachments=data.get("attachments"),
            )

    def show_groups(self, e=None):
        """Показывает кэшированный корневой экран выбора групп."""
        if self._app_locked:
            return
        self.current_group_id = None
        if not self.web:
            groups_column = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10)

            def refresh_groups():
                groups_column.controls.clear()
                counts = self._group_task_counts()
                for group in self.back.get_groups():
                    self._append_group_row(groups_column, group, refresh_groups, counts)

            refresh_groups()
            header = self.libs.create_style_header("Группы дел и заметок")
            main = self.libs.create_style_cont([
                self._build_group_actions(),
                self.groups_progress_cont,
                groups_column,
            ])
            body = self.libs.collection_widgets_fo_dialog(header, main, self.border)

            while len(self.page.views) > 1:
                self.page.views.pop()
            self.root_view.route = "/groups"
            self.root_view.controls = [body]
            self.page.views[:] = [self.root_view]
            asyncio.create_task(self.page.push_route("/groups"))
            self.page.update()
            return

        if self._groups_screen is None:
            self._groups_column = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10)

            def refresh_groups():
                groups_column = self._groups_column
                groups_column.controls.clear()
                self._settings_screens.clear()
                self.current_group_id = None
                counts = self._group_task_counts()
                for group in self.back.get_groups():
                    self._append_group_row(groups_column, group, refresh_groups, counts)
                try:
                    groups_column.update()
                except RuntimeError:
                    pass

            self._refresh_groups = refresh_groups
            header = self.libs.create_style_header("Группы дел и заметок")
            main = self.libs.create_style_cont([
                self._build_group_actions(),
                self.groups_progress_cont,
                self._groups_column,
            ])
            self._groups_screen = self.libs.collection_widgets_fo_dialog(
                header, main, self.border
            )

        self._refresh_groups()
        self._set_screen(self._groups_screen, reset=True)

    def _build_group_actions(self):
        create = self.libs.create_style_button("Новая группа", ft.Icons.ADD_ROUNDED)
        # В прокручиваемой строке кнопка должна занимать свою ширину:
        # Expanded несовместим с неограниченной шириной содержимого.
        create.expand = None if self.phone else True
        create.on_click = self._open_create_group
        controls = [create]
        for icon, label, handler in (
            ("settings", "Настройки", self.open_settings),
            ("auth", "Аккаунт", self.open_auth_dialog),
            ("undo", "Отменить последнее действие", self.undo_last_action),
            ("update", "Обновить дела", self.update_and_show_groups),
        ):
            button = self.libs.build_button_with_image(icon, label, compact=False)
            button.on_click = handler
            if icon == 'undo':
                self.groups_undo_btn = button
                button.disabled = not self.back.can_undo()
            controls.append(button)
        return ft.Row(
            controls,
            spacing=6,
            scroll=ft.ScrollMode.AUTO if self.phone else None,
        )

    def _group_task_counts(self):
        counts = {}
        for task in self.back.read_tasks():
            total, done = counts.get(task.get("group", "default"), (0, 0))
            counts[task.get("group", "default")] = (total + 1, done + bool(task.get("status")))
        return counts

    def _append_group_row(self, groups_column, group, refresh_groups, counts=None):
        """Добавляет одну строку в уже существующий экран групп."""
        group_id = group["id"]
        group_name = group["name"]
        is_notes = group.get('type') == 'notes'

        def open_group(_=None, ident=group_id):
            self.current_group_id = ident
            self._load_default_task_filter()
            self.render_daily_repeat_tasks()
            if self.web:
                self._set_screen(self.main_cont, push=True)
            else:
                route = f"/tasks-{len(self.page.views)}"
                self.page.views.append(
                    ft.View(
                        route=route,
                        controls=[self.main_cont],
                        padding=self.page_edge_padding,
                    )
                )
                asyncio.create_task(self.page.push_route(route))
                self.page.update()

        def edit_group(_=None, ident=group_id, old_name=group_name):
            dialog = self.libs.widgets_for_ask_task(
                "Введите новое название группы", "Сохранить", "Редактирование группы"
            )
            entry = dialog["entry_task"]
            entry.value = old_name
            self.libs.update_text_counter(entry)

            def save(_):
                if not self._validate_text_length(entry):
                    return
                if self.back.rename_group(ident, entry.value):
                    self.cloud.alg_for_redact()
                    self.show_groups()
                else:
                    entry.label = "Введите корректное название"
                    entry.border_color = ft.Colors.RED
                    self._update_control(entry)

            dialog["btn_create_task"].on_click = save
            entry.on_submit = save
            self.open_modified_dialog(dialog["Header"], dialog["Main Cont"], dialog["cancel"])

        def delete_group(_=None, ident=group_id):
            if self.back.delete_group(ident):
                self.cloud.alg_for_redact()
                refresh_groups()
                if not self.web:
                    self.page.update()

        menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            icon_color=self.libs.colors["MutedColor"],
            tooltip="Действия с группой",
            items=[
                ft.PopupMenuItem(content="Редактировать", icon=ft.Icons.EDIT_ROUNDED,
                                 on_click=edit_group),
                *([] if group_id == 'default' else [
                    ft.PopupMenuItem(content="Отключить" if group.get("is_shared") else "Удалить",
                                     icon=ft.Icons.LINK_OFF_ROUNDED if group.get("is_shared") else ft.Icons.DELETE_ROUNDED,
                                     on_click=delete_group)
                ]),
                *([ft.PopupMenuItem(
                    content="Сделать группу общей",
                    icon=ft.Icons.GROUP_ADD_ROUNDED,
                    on_click=lambda _: self._open_share_group_dialog(group),
                )] if not group.get("is_shared") else []),
            ],
        )
        total, done = (counts if counts is not None else self._group_task_counts()).get(group_id, (0, 0))
        subtitle = (f"Заметок: {group.get('note_count', 0)}" if is_notes else
                    f"Выполнено {done} из {total}" if total else "Пока нет дел")
        group_btn = self.libs.create_style_button(group_name)
        group_btn.content = ft.Row([
            ft.Container(
                content=ft.Icon(ft.Icons.NOTES_ROUNDED if is_notes else ft.Icons.FOLDER_OPEN_ROUNDED,
                                size=22, color=self.libs.FletIconColor),
                bgcolor=self.libs.BgColor, padding=10, border_radius=12,
            ),
            ft.Column([
                ft.Text(group_name, size=self.libs.text_size(16), weight=ft.FontWeight.W_600,
                        color=self.TxtColor, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(subtitle,
                        size=self.libs.text_size(12), color=self.libs.colors["MutedColor"],
                        visible=group.get("show_completion_counter", True)),
            ], spacing=4, expand=True, tight=True),
            *([ft.Icon(ft.Icons.LINK_ROUNDED, size=20, color=self.libs.FletIconColor,
                       tooltip="Подключена общая группа")]
              if group.get("is_shared") else []),
            ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=20,
                    color=self.libs.colors["MutedColor"]),
        ], spacing=12)
        group_btn.style.padding = 14
        group_btn.expand = True
        group_btn.on_click = open_group
        groups_column.controls.append(ft.Row([group_btn, menu]))

    def _open_share_group_dialog(self, group):
        password = ft.TextField(label="Пароль общей группы", password=True,
                                can_reveal_password=True, color=self.TxtColor)
        shared_content = "заметки и их вложения" if group.get("type") == "notes" else "только обычные дела"
        message = ft.Text(f"Общими станут {shared_content}. Для подключения нужны название группы и пароль.",
                          size=self.libs.text_size(14), color=self.TxtColor)
        create = self.libs.create_style_button("Сделать общей")
        cancel = self.libs.create_style_button("Назад")
        progress = ft.ProgressRing(width=20, height=20, visible=False)

        async def share(_):
            if create.disabled:
                return
            create.disabled = password.disabled = cancel.disabled = True
            progress.visible = True
            self.page.update()
            success = False
            try:
                await asyncio.to_thread(self.back.make_group_shared, group["id"], password.value or "")
                success = True
            except ValueError as exc:
                message.value = str(exc)
                message.color = ft.Colors.RED
            except Exception:
                message.value = "Не удалось создать общую группу. Проверьте подключение к Dropbox и повторите."
                message.color = ft.Colors.RED
            finally:
                create.disabled = password.disabled = cancel.disabled = False
                progress.visible = False
            if success:
                password.value = ""
                self.show_groups()
            else:
                self.page.update()

        create.on_click = share
        password.on_submit = share
        content = self.libs.create_style_cont([
            ft.Text(group["name"], size=self.libs.text_size(18), color=self.TxtColor),
            password, message, ft.Row([create, progress], wrap=True), cancel,
        ])
        self.open_modified_dialog(self.libs.create_style_header("Общая группа"), content, cancel)

    def _open_create_group(self, _=None):
        """Открывает форму создания группы."""
        dialog = self.libs.widgets_for_ask_task(
            "Введите название группы",
            "Создать",
            "Новая группа",
            warning_text="Не создавайте одинаковые группы",
        )
        entry = dialog["entry_task"]
        entry.label = "Название группы"
        group_type = ft.Dropdown(
            label="Тип группы", value="tasks",
            options=[
                ft.dropdown.Option(key="tasks", text="Дела"),
                ft.dropdown.Option(key="notes", text="Заметки"),
            ],
            width=self.libs.width_dialogs * 0.95,
        )
        dialog['Main Cont'].content.controls.insert(-1, group_type)

        def save(_):
            if not self._validate_text_length(entry):
                return
            if self.back.create_group(entry.value, group_type=group_type.value):
                self.cloud.alg_for_redact()
                self.show_groups()
            else:
                entry.label = "Введите корректное название"
                entry.border_color = ft.Colors.RED
                self._update_control(entry)

        dialog["btn_create_task"].on_click = save
        entry.on_submit = save
        self.open_modified_dialog(dialog["Header"], dialog["Main Cont"], dialog["cancel"])


    def update_tasks(self, on_complete=None):
        """Функция для обновления дел.

        on_complete вызывается после завершения обновления интерфейса.
        """
        if self._app_locked:
            return
        self.back.clear_undo()
        self.sets = self.back2.read_settings()

        self.load_screen = self.sets["load_screen"]

        self.status_border = self.sets["border"]
        self.border.visible = self.status_border
        self.notification_service.start()

        base = []
        if self.phone:
            base.append(self.search_row_widget)
        else:
            base.append(ft.Row([], expand=True))

        if self.load_screen:
            loading_token = self._open_loading_view()

            async def do_update_and_finish():
                await asyncio.to_thread(self.cloud.alg_for_start_app)
                self.notification_service.data_changed()

                self.tasks_cont.content.controls = base
                if not self.web:
                    self.before_load()
                self.check_and_add_repeat_task()
                self.check_and_add_postponed_task()
                self.render_daily_repeat_tasks()

                if on_complete:
                    on_complete()
                else:
                    self._close_loading_view(loading_token)
                print("end")

            self.page.run_task(do_update_and_finish)
        else:
            self.cloud.alg_for_start_app()

            self.notification_service.data_changed()

            self.tasks_cont.content.controls = base

            if not self.web:
                self.before_load()
            self.check_and_add_repeat_task()
            self.check_and_add_postponed_task()
            self.render_daily_repeat_tasks()
            if on_complete:
                on_complete()
            else:
                try:
                    self._update_control(self.tasks_cont)
                except RuntimeError:
                    self.page.update()
            

    async def refresh_tasks_silent(self):
        """Тихо перерисовывает список дел текущей группы после фонового
        автообновления (Backend.autoupdate.AutoUpdateService), не переключая
        экраны и не показывая индикатор загрузки. Ничего не делает, если
        пользователь сейчас не находится на экране списка дел.
        """
        if self.current_group_id is None:
            return
        if self.web:
            if not self.screen_stack or self.screen_stack[-1] is not self.main_cont:
                return
        elif not self.page.views or not self.page.views[-1].route.startswith("/tasks-"):
            return

        base = []
        if self.phone:
            base.append(self.search_row_widget)
        else:
            base.append(ft.Row([], expand=True))

        # Сначала получаем свежие данные, затем строим интерфейс. Сетевой
        # вызов выполняется вне event loop, чтобы автообновление не
        # замораживало страницу в нативном приложении и на сайте.
        await asyncio.to_thread(self.cloud.alg_for_start_app)
        self.notification_service.data_changed()
        self._refresh_undo_buttons()
        self.tasks_cont.content.controls = base
        self.check_and_add_repeat_task()
        self.check_and_add_postponed_task()
        self.render_daily_repeat_tasks()
        self._update_control(self.tasks_cont)

    def update_and_show_groups(self, e=None):
        """Обновляет данные и возвращает на экран выбора групп."""
        self.update_tasks(self.show_groups)
