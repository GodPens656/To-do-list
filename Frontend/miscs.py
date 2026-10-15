import flet as ft
from datetime import datetime
from .theme import get_theme_colors
from .libs import Fr_Libs
from .attachments import attachment_controls
from Backend.extended import Backend2
from Backend.core import local_today

from threading import Thread
import threading


class Utils:
    def __init__(
        self,
        cloud,
        back,
        theme,
        page=None,
        web_store=None,
        icon_pack="minimalistic",
        button_color=None,
    ):
        """Импорт """
        self.back = back
        # page/web_store прокинуты из Front, чтобы на сайте этот Backend2
        # писал настройки в тот же браузерный store, что и основной
        # self.back2 во Front, а не в отдельные файлы на сервере.
        self.back2 = Backend2(page=page, web_store=web_store)
        self.theme = theme

        self.phone = self.back.get_device()
        self.libs = Fr_Libs(
            self.theme,
            self.phone,
            page=page,
            web=web_store is not None,
            icon_pack=icon_pack,
            button_color=button_color,
        )


        self.font = int()
        self.width_dialogs = int()
        self.height_dialogs = int()
        self.padding = int()
        self.padding_for_row = int()
        self.height_for_dlg_spacer = int()

        self.colors = get_theme_colors(self.theme, button_color)
        self.BorderColor = self.colors["BorderColor"]
        self.ContBgColor = self.colors["ContBgColor"]
        self.BgColor = self.colors["BgColor"]
        self.TxtColor = self.colors["TxtColor"]
        self.BtnColor = self.colors["BtnColor"]

        """Настройки отступов и т.д."""
        if self.phone:
            self.font = 14
            self.height_dialogs = 300
            self.width_dialogs = self.libs.width_dialogs
            self.padding = 10
            self.padding_for_row = 0
            self.height_for_dlg_spacer = 20
        else:
            self.font = 16
            self.height_dialogs = 500
            self.width_dialogs = 550
            self.padding = 20
            self.padding_for_row = 10
            self.height_for_dlg_spacer = 0
        self.btn_new_task = ft.Button()
        self.cloud = cloud

    def create_row_with_task(self, task, status, id_task, created_date=None, group_id='default',
                             deadline=None, priority='Неважно', info_type='created_date',
                             *, show_checkbox=True, group_settings=None, attachments=None):
        """Функция для создания и возвращения строки с делом, кнопками и т.д.
        created_date — дата создания дела (ДД-ММ-ГГГГ), отображается
        мелкой подписью под названием дела, если известна и если включена
        настройка "Подписывать дату создания дел" для группы group_id,
        которой принадлежит дело (настройка хранится у самой группы в
        itog.json, а не в общем settings.txt). Для заметок show_checkbox=False
        создаёт такую же карточку без элемента отметки выполнения."""
        taskW = ft.Text(
            f"{task}",
            no_wrap=False,
            size=self.libs.text_size(self.font),
            color=self.TxtColor,
            weight=ft.FontWeight.W_500,
            style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH)
            if status
            else None,
        )

        if group_settings is None:
            group_settings = self.back.get_group_settings(group_id or 'default')
        show_created_date = group_settings["show_created_date"]

        details = []
        # При выборе дедлайна или важности показываем только выбранную
        # дополнительную информацию, без даты создания.
        if created_date and show_created_date and info_type == "created_date":
            details.append(ft.Text(
                f"Создано: {created_date}",
                size=self.libs.text_size(12),
                color=self.colors["MutedColor"],
            ))
        if info_type == "deadline" and deadline:
            deadline_color = ft.Colors.with_opacity(0.75, self.TxtColor)
            try:
                days_left = (
                    datetime.strptime(deadline, "%d-%m-%Y").date()
                    - local_today(self.back.web, self.back.page)
                ).days
                if days_left <= 1:
                    deadline_color = self.colors["DangerColor"]
                elif days_left <= 2:
                    deadline_color = self.colors["WarnTextColor"]
                elif days_left <= 3:
                    deadline_color = self.colors["SuccessColor"]
            except (TypeError, ValueError):
                pass
            details.append(self._task_badge(
                ft.Icons.SCHEDULE_ROUNDED, f"До {deadline}", deadline_color,
            ))
        if info_type == "priority":
            priority_color = {
                "Неважно": self.colors["SuccessColor"],
                "Важно": self.colors["WarnTextColor"],
                "Очень важно": self.colors["DangerColor"],
            }.get(priority, self.TxtColor)
            details.append(self._task_badge(
                ft.Icons.FLAG_OUTLINED, priority, priority_color,
            ))
        if attachments:
            details.append(attachment_controls(self.libs, attachments))
        if details:
            task_content = ft.Column(
                controls=[taskW, *details],
                spacing=3 if self.phone else 6,
                tight=True,
            )
        else:
            task_content = taskW

        """Buttons"""
        checkbox = None
        if show_checkbox:
            checkbox = ft.Checkbox(
                value=status,
                tooltip="Отметить выполнение",
            )
            checkbox.on_change = lambda e: self.on_change_checkbox(
                e, id_task, checkbox.value, row_with_task, taskW
            )

        
        if self.phone or self.libs.icon_pack in {"minimalistic", "minimalistic-blue"}:
            # На телефоне и в минималистичных паках на ПК — компактные иконки Flet.
            redact = self.libs.create_edit_button()

            delete = self.libs.create_delete_button()
        else:
            # На ПК — прежние кнопки с картинками
            redact = self.libs.build_button_with_image(
                'redact', 'Редактировать дело'
            )

            delete = self.libs.build_button_with_image(
                'basket1', 'Удалить дело'
            )

        cont_with_actions = ft.Container(
            content=ft.Row([redact, delete], spacing=0, tight=True),
        )

        """Возвращение"""
        text_container = ft.Container(content=task_content, expand=True)
        row_controls = (
            [*([checkbox] if checkbox is not None else []), text_container, cont_with_actions]
            if self.phone else
            [cont_with_actions, *([checkbox] if checkbox is not None else []), text_container]
        )
        row_with_task = ft.Container(
            content=ft.Row(
                controls=row_controls,
                spacing=4 if self.phone else 10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=self.BgColor,
            border=ft.Border.all(1, self.colors["SoftBorderColor"]),
            border_radius=14,
            padding=ft.Padding.symmetric(
                horizontal=6 if self.phone else 12,
                vertical=6 if self.phone else 12,
            ),
            opacity=0.6 if status else 1,
            animate_opacity=160,
        )
        return [row_with_task, delete, redact, taskW, checkbox]

    def _task_badge(self, icon, text, color):
        return ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=13, color=color),
                ft.Text(text, size=self.libs.text_size(12), color=color),
            ], spacing=5, tight=True, wrap=True),
            bgcolor=ft.Colors.with_opacity(0.08, str(color).split(",")[0]),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=7, vertical=3),
        )

    def on_change_checkbox(self, e, id_task, status, row_with_task, taskW, *, update=True):
        """Функция для сохранения изменений в файле после изменения статуса,
        а также визуального отображения выполненного дела:
        строка становится полупрозрачной, а текст — зачёркнутым."""
        self.back.redact_statusB(id_task, status)
        self.cloud.alg_for_redact()

        row_with_task.opacity = 0.6 if status else 1
        taskW.style = (
            ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH)
            if status
            else None
        )
        if update:
            row_with_task.update()

    def open_warn_dialog(self, content, page):
        """Функция для открытия диалога-предупреждения перед
        удалением, добавляется для удалить всё, возможно
        добавлю для обычного удаления.

        Показывается как настоящий AlertDialog поверх текущей страницы,
        а не как контейнер для отдельного View."""

        def cancel(e=None):
            page.pop_dialog()

        def ok(e=None):
            page.pop_dialog()

        cancel_button = ft.Button(
            "Нет",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=5),
                padding=8,
                color=self.TxtColor,
            ),
            on_click=cancel,
            bgcolor=self.BtnColor,
        )

        yes_button = ft.Button(
            "Да",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=5),
                padding=8,
                color=self.TxtColor,
            ),
            on_click=ok,
            bgcolor=self.BtnColor,
        )

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=self.ContBgColor,
            shape=ft.RoundedRectangleBorder(radius=10),
            content=ft.Text(
                content,
                size=self.libs.text_size(16),
                weight=ft.FontWeight.W_500,
                color=self.TxtColor,
            ),
            actions=[yes_button, cancel_button],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        page.show_dialog(dialog)

        return dialog, yes_button, cancel_button

    def cont_auth_accounts(self, login_cmd):
        """Создание контейнера со всеми
        авторизованными аккаунтами"""
        widgets_4_main = []

        def log_out(l, p, r):
            main.content.controls.remove(r)
            self.back2.exit_from_auth_accounts(l, p)

        # Backend2 на сайте хранит список аккаунтов в browser storage, а не
        # в self.user_data (это Path только для ПК/Android). Используем его
        # единый публичный API — он работает в обоих режимах.
        for item in self.back2.read_accounts():
            log = item[0]
            pas = item[1]

            if not self.back2.check_accounts(log, pas):
                log_form = self.back.auto_add_new_string(log)

                btnIN = self.libs.create_style_button(f'Перейти в {log_form}')
                btnIN.on_click = lambda _, l=log, p=pas: login_cmd(l, p)

                btnOUT = self.libs.build_button_with_image('logout',f'Выйти из {log_form}',
                                                           size=36)

                row = ft.Row(
                    [btnIN, btnOUT],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                )

                btnOUT.on_click = lambda _, l=log, p=pas, r=row: log_out(l, p, r)

                widgets_4_main.append(row)

        main = self.libs.create_style_cont(
            widgets_4_main,
            width=self.width_dialogs*0.9
        )

        return main

    def build_widgets_for_login(self, page, function_for_update, login_cmd):
        """Постройка виджетов для диалога
        с авторизацией/регистрацией"""
        cont_title = ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        " Авторизация",
                        weight=ft.FontWeight.W_900,
                        size=self.libs.text_size(18),
                        color=self.TxtColor,
                    )
                ]
            ),
            bgcolor=self.ContBgColor,
            border=ft.Border.all(0.5, self.BorderColor),
            border_radius=8,
            padding=10,
            width=self.width_dialogs,
        )

        lblT = ft.Text(
            " Вход/Регистрация", size=self.libs.text_size(18), weight=ft.FontWeight.W_900, color=self.TxtColor
        )

        lbl1 = ft.Text("Введите логин:", size=self.libs.text_size(15), color=self.TxtColor)

        ent_with_login = ft.TextField(hint_text="Логин", color=self.TxtColor)

        lbl2 = ft.Text("Введите пароль:", size=self.libs.text_size(15), color=self.TxtColor)

        ent_with_password = ft.TextField(hint_text="Пароль", color=self.TxtColor, 
                                         password=True, can_reveal_password=True)

        texts_for_login = self.cloud.read_user_data()

        LlblT0 = ft.Text(
            " Управление аккаунтом",
            size=self.libs.text_size(18),
            weight=ft.FontWeight.W_900,
            color=self.TxtColor,

        )

        LlblT = ft.Text(texts_for_login["Start text"], size=self.libs.text_size(16), color=self.TxtColor)

        LlblL = ft.Text(texts_for_login["Login"], size=self.libs.text_size(16), color=self.TxtColor)

        LlblP = ft.Text(texts_for_login["Password"], size=self.libs.text_size(16), color=self.TxtColor)

        btn_logout = self.libs.create_style_button(
            "Выйти из аккаунта"
        )

        btn_logout.on_click = lambda: (
                self.cloud.leave_from_account(),
                self.libs.open_dialog("Авторизация", "Вы успешно вышли из аккаунта", page),
                function_for_update(),
            )

        btn_delete_account = self.libs.create_style_button(
            'Удалить аккаунт'
        )

        btn_delete_account.on_click = lambda: (
                self.cloud.delete_account(),
                self.libs.open_dialog("Авторизация", "Вы успешно удалили аккаунт", page),
                function_for_update(),
            )

        if self.cloud.check_user_data():
            btn_logout.visible = True
            btn_delete_account.visible = True
        else:
            btn_logout.visible = False
            btn_delete_account.visible = False

        cont_with_account = ft.Container(
            content=ft.Row([btn_logout, btn_delete_account]),
        )

        btn_login = self.libs.create_style_button(
            'Войти'
        )

        btn_for_register = self.libs.create_style_button(
            'Зарегистрироваться'
        )

        btn_cancel = self.libs.create_style_button(
            'Назад'
        )

        cont_with_auth = ft.Container(
            content=ft.Row([btn_login, btn_for_register]),
        )

        auth_accounts_tile = self.libs.create_style_expansion_category(
            ft.Icons.ACCOUNT_CIRCLE_ROUNDED,
            'Авторизованные аккаунты',
            [self.cont_auth_accounts(login_cmd)],
            padding=4
        )

        cont_main = self.libs.create_style_cont(
                [
                    lblT,
                    lbl1,
                    ent_with_login,
                    lbl2,
                    ent_with_password,
                    cont_with_auth,
                    auth_accounts_tile,
                    LlblT0,
                    LlblT,
                    LlblL,
                    LlblP,
                    cont_with_account,
                    btn_cancel,
                ]
        )
        itog = {
            "Main_cont": cont_main,
            "Header_cont": cont_title,
            "Login": ent_with_login,
            "Password": ent_with_password,
            "Cancel": btn_cancel,
            "Login_act": btn_login,
            "Register_act": btn_for_register,
        }
        return itog
