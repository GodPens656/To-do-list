"""Factories for the application's main and loading widgets.

``Utils3`` owns these factories together with informational dialogs because
they share the same theme/layout state.  This alias provides the architectural
entry point without duplicating that state.
"""

import flet as ft

from Backend.core import local_today
from .info import Utils3
from .attachments import AttachmentEditor


class MainWidgets(Utils3):
    """Main-screen widget factory facade."""

    def build_static_input(self, front):
        """Функция для постройки статического GUI
        для раздела с входными данными"""
        self = front

        self.task_heading = self.main_widgets.task_heading
        self.task_summary = self.main_widgets.task_summary
        self.task_progress = self.main_widgets.task_progress
        self.task_overview = self.main_widgets.task_overview
        self.empty_title = ft.Text(
            " Здесь пока нет дел", size=self.libs.text_size(20), weight=ft.FontWeight.W_600,
            color=self.TxtColor, text_align=ft.TextAlign.CENTER,
        )
        self.empty_hint = ft.Text(
            "Добавьте первое дело — начните с самого простого.",
            size=self.libs.text_size(14), color=self.libs.colors["MutedColor"],
            text_align=ft.TextAlign.CENTER,
        )
        self.empty_state = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.CHECKLIST_ROUNDED, size=40,
                        color=self.libs.colors["MutedColor"]),
                self.empty_title,
                self.empty_hint,
            ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=16, vertical=40),
            alignment=ft.Alignment.CENTER,
            visible=False,
        )

        def open_new_task(e):
            if self.back.get_group_type(self.current_group_id) == 'notes':
                self.open_note_editor()
                return
            self.entry_task.value = ""
            self.libs.update_text_counter(self.entry_task)
            extra_info_dropdown.value = "created_date"
            deadline_field.value = ""
            priority_dropdown.value = "Неважно"
            attachments.reset()
            update_extra_controls()
            self.open_page(cont_H, cont_AC, self.cancel, "new-task")

        self.button_add_task= self.libs.build_button_with_image(
            'plusS', 'Добавить новое дело', size=48, compact=False
        )

        self.settings = self.libs.build_button_with_image(
            'settings', 'Настройки', size=48, compact=False
        )

        self.auth_btn = self.libs.build_button_with_image(
            'auth', 'Авторизация', size=48, compact=False
        )

        self.upd_btn = self.libs.build_button_with_image(
            'update', 'Обновить дела', size=48, compact=False
        )
        self.undo_btn = self.libs.build_button_with_image(
            'undo', 'Отменить последнее действие', size=48, compact=False
        )
        self.undo_btn.disabled = not self.back.can_undo()
        self.undo_btn.on_click = self.undo_last_action
        self.back.on_undo_change = self._refresh_undo_buttons
        self.groups_btn = self.libs.build_button_with_image(
            'nazad', 'К группам', size=48, compact=False
        )
        self.groups_btn.on_click = self.close_page

        self.settings.on_click = self.open_settings
        self.auth_btn.on_click = self.open_auth_dialog
        self.upd_btn.on_click = self.update_and_show_groups

        if self.phone:
            self.upload_progress = ft.ProgressBar(
                visible=False,
                color=self.ProgressColor,
                bgcolor=self.ProgressBgColor,
                height=4,
            )
        else:
            self.upload_progress = ft.ProgressRing(
                visible=False,
                width=22,
                height=22,
                stroke_width=2.5,
                color=self.TxtColor,
            )
        self.upload_progress_cont = ft.Container(
            content=self.upload_progress,
            padding=ft.Padding.only(top=8),
            visible=False,
        )
        self.groups_progress = ft.ProgressBar(
            visible=False,
            height=4,
            color=self.ProgressColor,
            bgcolor=self.ProgressBgColor,
            expand=True,
        )
        self.groups_progress_cont = ft.Container(
            content=self.groups_progress,
            padding=ft.Padding.only(top=8),
            visible=False,
        )
        self.cloud.set_upload_state_callback(self._set_upload_indicator)

        if self.phone:
            stxt = 'Поиск'
        else:
            stxt = 'Поиск'
        
        """Поле поиска по названию дела"""
        self.current_search = ""
        self.search_btn = self.libs.create_style_button(
            icon=ft.Icons.SEARCH,
            text=stxt,
        )
        self.search_btn.on_click=self.open_search
        self.search_field = ft.TextField(
            value="",
            hint_text="Найти дело…",
            color=self.TxtColor,
            border_color=self.BorderColor,
            bgcolor=self.ContBgColor,
            content_padding=12,
            border_radius=12,
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            text_size=self.libs.text_size(14),
            expand=True,
            visible=False,
            on_change=self.filter_tasks,
        )
        self.search_close_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color=self.TxtColor,
            tooltip="Закрыть поиск",
            visible=False,
            on_click=self.close_search,
        )
        self.filter_btn = ft.IconButton(
            icon=ft.Icons.FILTER_ALT,
            icon_color=self.libs.FletIconColor,
            tooltip="Фильтр дел",
            on_click=self.open_task_filter_dialog,
        )
        if self.phone:
            # На телефоне — первая строка в контейнере с делами.
            # Изначально показываем кнопку поиска, растянутую на всю ширину
            # контейнера с делами. После нажатия на неё в этой же строке
            # появляются поле ввода и кнопка-крестик для закрытия поиска.
            self.search_field.height = 45
            self.search_btn.expand = True
            self.search_row_widget = ft.Row(
                controls=[
                    self.groups_btn,
                    self.search_btn,
                    self.search_field,
                    self.search_close_btn,
                    self.filter_btn,
                ],
                spacing=5,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            # НЕ добавляем здесь — update_tasks добавит при первом запуске
        else:
            # В Row(wrap=True) нельзя создавать Expanded, даже с flex=0:
            # Flet преобразует expand=False именно в Expanded(flex=0).
            self.search_field.expand = None
            self.search_field.width = 220

        widgets = self.libs.widgets_for_ask_task(
            "Введите название дела", "Добавить дело", "Новое дело"
        )

        extra_info_label = ft.Text(
            "Выберите дополнительную информацию о деле",
            size=self.libs.text_size(16),
            weight=ft.FontWeight.W_500,
            color=self.TxtColor,
        )
        extra_info_dropdown = ft.Dropdown(
            value="created_date",
            options=[
                ft.dropdown.Option(key="created_date", text="Дата создания дела"),
                ft.dropdown.Option(key="deadline", text="Дедлайн дела"),
                ft.dropdown.Option(key="priority", text="Важность дела"),
            ],
            width=self.libs.width_dialogs * 0.95,
        )
        deadline_field = ft.TextField(
            label="Дедлайн дела",
            hint_text="Не выбран",
            width=self.libs.width_dialogs * 0.95,
            read_only=True,
            visible=False,
        )
        deadline_button = self.libs.create_style_button(
            "Выбрать дату", ft.Icons.CALENDAR_MONTH
        )
        deadline_button.visible = False
        priority_dropdown = ft.Dropdown(
            label="Важность дела",
            value="Неважно",
            options=[
                ft.dropdown.Option(key=value, text=value)
                for value in ("Неважно", "Важно", "Очень важно")
            ],
            width=self.libs.width_dialogs * 0.95,
            visible=False,
        )

        def set_date_field(field):
            def on_change(event):
                picked = self._picker_event_date(event)
                if picked:
                    field.value = picked.strftime("%d-%m-%Y")
                    self.page.update()
            return on_change

        deadline_picker = ft.DatePicker(
            current_date=local_today(self.web, self.page),
            on_change=set_date_field(deadline_field), locale=ft.Locale("ru", "RU"),
        )
        if deadline_picker not in self.page.overlay:
            self.page.overlay.append(deadline_picker)
        deadline_button.on_click = lambda _: (
            setattr(deadline_picker, "open", True), self.page.update()
        )

        def update_extra_controls(event=None):
            selected = extra_info_dropdown.value
            deadline_field.visible = selected == "deadline"
            deadline_button.visible = selected == "deadline"
            priority_dropdown.visible = selected == "priority"
            self.page.update()

        extra_info_dropdown.on_select = update_extra_controls
        form_controls = widgets["Main Cont"].content.controls
        form_controls[-1:-1] = [
            extra_info_label, extra_info_dropdown, deadline_field, deadline_button, priority_dropdown
        ]
        attachments = AttachmentEditor(self.libs, back=self.back)
        form_controls.insert(-1, attachments.control)

        self.create_task = widgets["btn_create_task"]
        self.create_task.on_click = lambda e: self.add_task(
            e, self.entry_task.value, False, True, False,
            deadline=deadline_field.value if extra_info_dropdown.value == "deadline" else None,
            priority=priority_dropdown.value if extra_info_dropdown.value == "priority" else "Неважно",
            info_type=extra_info_dropdown.value,
            attachments=attachments.values(),
        )
        self.cancel = widgets["cancel"]
        self.cancel.on_click = self.close_dlg
        self.entry_task = widgets["entry_task"]
        self.entry_task.on_submit = self.create_task.on_click
        cont_AC = widgets.get("Main Cont")
        cont_H = widgets.get("Header")

        self.new_task_dialog = None  # страница создаётся при каждом переходе

        self.button_add_task.on_click = open_new_task

    def build_status_border(self, visible):
        """Создаёт нижний разделитель главного контейнера."""
        return ft.Container(
            content=ft.Column([]),
            height=20,
            visible=visible,
        )

    def build_main_conts(self, page):
        """Задание контейнеров"""
        pustoy_row = ft.Row(
            [], spacing=8, wrap=not self.phone, run_spacing=8,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN if self.phone else ft.MainAxisAlignment.START,
        )
        self.btns_cont = ft.Container(
            content=pustoy_row,
            bgcolor=self.ContBgColor,
            border=ft.Border.all(1, self.colors["SoftBorderColor"]),
            border_radius=16,
            padding=12,
            
            # expand = True
        )
        if self.phone:
            pustoy_row.scroll=ft.ScrollMode.AUTO

            
        spacer = ft.Row(
            [ft.Container(), ft.Container()],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            height=0,
        )

        self.tasks_cont = ft.Container(
            content=ft.Column([spacer], scroll=ft.ScrollMode.AUTO, spacing=8),
            bgcolor=self.ContBgColor,
            border=ft.Border.all(1, self.colors["SoftBorderColor"]),
            border_radius=16,
            padding=10 if self.phone else 16,
            expand=True,
        )

        self.task_heading = ft.Text(
            "Мои дела", size=self.libs.text_size(24 if self.phone else 28),
            weight=ft.FontWeight.W_600, color=self.TxtColor,
            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.task_summary = ft.Text("", size=self.libs.text_size(13), color=self.colors["MutedColor"])
        self.task_progress = ft.ProgressBar(
            value=0, height=4, border_radius=4,
            color=self.colors["ProgressColor"],
            bgcolor=self.colors["ProgressBgColor"],
        )
        overview = ft.Container(
            content=ft.Column([
                self.task_heading, self.task_summary, self.task_progress,
            ], spacing=8),
            padding=ft.Padding.symmetric(horizontal=4, vertical=10),
        )
        self.task_overview = overview

        # На сайте не добавляем искусственный верхний spacer. В нативных
        # клиентах сохраняем прежний отступ.
        leading_controls = [] if self.libs.web else [ft.Container(height=5)]

        if self.phone:
            self.main_cont = ft.Container(
                content=ft.Column(
                    controls=leading_controls + [
                        overview,
                        self.tasks_cont,
                        self.btns_cont,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                expand=True,
            )
        else:
            self.main_cont = ft.Container(
                content=ft.Column(
                    controls=leading_controls + [
                        self.btns_cont,
                        overview,
                        self.tasks_cont,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                expand=True,
            )
        return self.main_cont, self.btns_cont, self.tasks_cont

    def build_loading_widget(self):
        """Виджет загрузки"""
        text_loading = """Загрузка"""

        main = ft.Container(
            content=ft.Column(
                [
                    ft.ProgressRing(color=self.TxtColor),
                    ft.Text(
                        text_loading,
                        size=self.libs.text_size(16),
                        weight=ft.FontWeight.W_700,
                        color=self.TxtColor,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=self.LoadColor,
            border=ft.Border.all(0.5, self.BorderColor),
            border_radius=10,
            padding=30,
            height=150,
        )

        # Контейнер растягивается на всю страницу и центрирует содержимое
        # и по горизонтали, и по вертикали (раньше окно оставалось в
        # верхнем углу, т.к. не было expand=True и alignment=CENTER).
        itog = ft.Container(
            content=main,
            alignment=ft.Alignment.CENTER,
            expand=True,
        )

        return itog

__all__ = ["MainWidgets", "Utils3"]
