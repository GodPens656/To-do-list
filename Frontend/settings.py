import asyncio

import flet as ft
from .attachments import attachment_controls
from flet_color_pickers import ColorLabelType, ColorPicker, PaletteType
from datetime import datetime
from pathlib import Path

from .theme import (
    BUTTON_BACKGROUND_OPTIONS,
    THEME_STYLE_OPTIONS,
    get_theme_colors,
    normalize_custom_color,
)
from .libs import Fr_Libs
from .typography import FONT_FAMILY_OPTIONS, FONT_SIZE_OPTIONS


class Utils2:
    def __init__(
        self,
        cloud,
        back,
        theme,
        back2,
        on_theme_change=None,
        on_icon_pack_change=None,
        on_button_color_change=None,
        icon_pack="minimalistic",
        button_color=None,
        on_font_change=None,
    ):
        """Импорт классов и задание переменных"""
        self.cloud = cloud
        self.back = back
        self.theme = theme
        self.back2 = back2
        self.on_theme_change = on_theme_change
        self.on_icon_pack_change = on_icon_pack_change
        self.on_button_color_change = on_button_color_change
        self.on_font_change = on_font_change
        self.on_edit_repeat = None
        self.on_edit_postponed = None

        self.phone = self.back.get_device()
        self.web = bool(getattr(self.back, "web", False))
        self.libs = Fr_Libs(
            self.theme,
            self.phone,
            page=getattr(self.back, "page", None),
            web=self.web,
            icon_pack=icon_pack,
            button_color=button_color,
        )
        self.spacer = ft.Container(
            content=ft.Row([]),
            expand=True,
        )
        self.colors = get_theme_colors(self.theme, button_color)
        self.BorderColor = self.colors["BorderColor"]
        self.ContBgColor = self.colors["ContBgColor"]
        self.BgColor = self.colors["BgColor"]
        self.TxtColor = self.colors["TxtColor"]
        self.BtnColor = self.colors["BtnColor"]
        self.LoadColor = self.colors["LoadColor"]

        """Настройки отступов и т.д."""
        if self.phone:
            self.font = 13
            self.height_dialogs = 320
            self.width_dialogs = self.libs.width_dialogs
            self.padding = 10
            self.padding_for_row = 6
            self.height_for_dlg_spacer = 20
        else:
            self.font = 17
            self.height_dialogs = 500
            self.width_dialogs = 550
            self.padding = 20
            self.padding_for_row = 10
            self.height_for_dlg_spacer = 0

    """Блок для окна настроек"""

    'Сохранить изменения'

    def build_widgets_for_settings(
        self,
        command_for_update_tasks,
        cmd_for_dlg,
        cmd_for_postponed_dlg,
        page,
        command_for_notifications_settings=None,
        command_for_battery_settings=None,
        group_id='default',
        command_for_rebuild_tasks=None,
    ):
        """Главный экран настроек.

        Общие настройки и управление делами раскрываются на месте;
        остальные категории сохраняют текущую навигацию. group_id — id
        текущей открытой группы дел: настройки "Разделять дела по датам"
        и "Подписывать дату создания дел" относятся именно к ней и
        хранятся в itog.json у самой группы. command_for_rebuild_tasks —
        лёгкая перестройка виджетов списка дел без синхронизации с
        Dropbox, используется именно для этих двух настроек
        и кнопок раздела "управление делами"."""

        btn_nazad = self.libs.create_style_button('Назад')



        management_widgets = self.build_widgets_for_management_tasks(
            command_for_rebuild_tasks
        )
        general_widgets = self.build_widgets_for_general_sets(
            command_for_update_tasks, group_id, command_for_rebuild_tasks
        )
        btn_special = self.libs.create_style_category_button(
            ft.Icons.AUTO_AWESOME_ROUNDED, 'Особые дела'
        )
        btn_customization = self.libs.create_style_category_button(
            ft.Icons.PALETTE_ROUNDED, 'Кастомизация'
        )

        btn_management = self.libs.create_style_expansion_category(
            ft.Icons.CHECKLIST_ROUNDED,
            'Управление делами',
            [management_widgets],
        )
        btn_general = self.libs.create_style_expansion_category(
            ft.Icons.TUNE_ROUNDED,
            'Общие настройки',
            [general_widgets],
        )
        btn_security = self.libs.create_style_category_button(
            ft.Icons.LOCK_ROUNDED, 'Безопасность',
        )
        btn_notifications = self.libs.create_style_category_button(
            ft.Icons.NOTIFICATIONS_ROUNDED, 'Уведомления'
        )
        primechanya_btn = self.libs.create_style_category_button(
            ft.Icons.STICKY_NOTE_2_ROUNDED, 'Примечания'
        )

        """Главный контейнер настроек - только кнопки"""
        self.settings_cont = self.libs.create_style_cont(
                [
                    btn_special,
                    btn_customization,
                    btn_management,
                    btn_general,
                    btn_security,
                    btn_notifications,
                    primechanya_btn,
                    btn_nazad,
                    ft.Text(
                        f"Версия: {self.back.version}\n\n ", size=self.libs.text_size(10), color=self.TxtColor
                    ),
                ],

        )

        """Содержимое диалогов для категорий, которые открываются отдельно"""
        notifications_header, notifications_content, notifications_back = \
            self.build_dialog_notifications(
                page,
                command_for_notifications_settings,
                command_for_battery_settings,
            )
        customization_header, customization_content, customization_back = \
            self.build_dialog_customization()

        dialogs = {
            'security': {'button': btn_security},
            'special': {
                'button': btn_special,
            },
            'notifications': {
                'button': btn_notifications,
                'header': notifications_header,
                'content': notifications_content,
                'back': notifications_back,
            },
            'customization': {
                'button': btn_customization,
                'header': customization_header,
                'content': customization_content,
                'back': customization_back,
            },
        }

        return self.settings_cont, btn_nazad, primechanya_btn, dialogs

    def build_dialog_security(self, page):
        header = self.libs.create_style_header('Безопасность')
        back = self.libs.create_style_button('Назад')
        encryption, load_encryption = self.build_widgets_for_account_encryption(page)
        content = self.libs.create_style_cont([
            self.build_widgets_for_security(page), ft.Divider(), encryption, back,
        ])
        return header, content, back, load_encryption

    def build_widgets_for_account_encryption(self, page):
        user_data = self.cloud.read_user_data_text()
        account = user_data.split("~~")[0].strip() if isinstance(user_data, str) else ""
        switch = ft.Switch(label="Шифрование данных аккаунта", value=True, disabled=True)
        status = ft.Text(
            "Загрузка настройки…" if account else "Войдите в аккаунт, чтобы изменить шифрование.",
            color=self.TxtColor, size=self.libs.text_size(12),
        )
        enabled = True
        busy = False
        ready = False

        async def load():
            nonlocal enabled, ready
            if not account:
                return
            try:
                enabled = await asyncio.to_thread(
                    self.cloud.load_account_encryption, account,
                )
                switch.value = enabled
                switch.disabled = False
                ready = True
                status.value = ""
            except Exception:
                status.value = "Не удалось загрузить настройку. Откройте раздел ещё раз."
            page.update()

        async def apply(e):
            nonlocal enabled, busy
            if busy or not ready or switch.value == enabled:
                return
            requested = bool(switch.value)
            busy = True
            switch.disabled = True
            status.value = "Изменение шифрования…"
            page.update()
            try:
                await asyncio.to_thread(self.cloud.set_account_encryption, account, requested)
                enabled = requested
                status.value = "Шифрование включено." if enabled else "Шифрование аккаунта отключено."
            except ValueError as error:
                status.value = str(error)
            except Exception:
                status.value = "Не удалось изменить шифрование. Проверьте интернет и повторите попытку."
            finally:
                busy = False
                switch.value = enabled
                switch.disabled = False
                page.update()

        switch.on_change = apply
        return ft.Column([
            switch,
            ft.Text(
                "Изменение применяется сразу к файлам дел и групп на этом устройстве и в облаке. "
                "При отключении они сохраняются без шифрования. "
                "Ранее созданные резервные копии сохраняют прежний формат.",
                color=self.TxtColor, size=self.libs.text_size(12),
            ),
            status,
        ], spacing=12), load

    def build_widgets_for_security(self, page):
        enabled = self.back2.read_settings()["password_enabled"]
        switch = ft.Switch(value=enabled, label="Пароль при входе")

        def password_field(label):
            return ft.TextField(
                label=label, password=True, can_reveal_password=True,
                autocorrect=False, enable_suggestions=False,
                color=self.TxtColor, border_color=self.BorderColor,
                text_size=self.libs.text_size(14),
            )

        current = password_field("Текущий пароль")
        password = password_field("Новый пароль" if enabled else "Пароль приложения")
        confirmation = password_field("Повторите пароль")
        save = self.libs.create_style_button("Сохранить")
        status = ft.Text(color=self.TxtColor, size=self.libs.text_size(12))

        def refresh():
            current.visible = enabled
            password.visible = confirmation.visible = switch.value
            save.visible = enabled or switch.value
            save.content = "Сохранить" if switch.value else "Отключить пароль"

        def toggle(e):
            for field in (current, password, confirmation):
                field.value = ""
            status.value = ""
            refresh()
            page.update()

        async def apply(e):
            nonlocal enabled
            if save.disabled:
                return
            if switch.value and password.value != confirmation.value:
                status.value = "Пароли не совпадают."
                page.update()
                return
            save.disabled = switch.disabled = True
            for field in (current, password, confirmation):
                field.disabled = True
            page.update()
            try:
                if switch.value:
                    await asyncio.to_thread(
                        self.back2.set_app_password, password.value, current.value,
                    )
                else:
                    await asyncio.to_thread(self.back2.disable_app_password, current.value)
                enabled = switch.value
                status.value = (
                    "Пароль сохранён. Он потребуется при следующем запуске."
                    if enabled else "Запрос пароля отключён."
                )
                password.label = "Новый пароль" if enabled else "Пароль приложения"
                for field in (current, password, confirmation):
                    field.value = ""
                refresh()
            except ValueError as error:
                status.value = str(error)
            except OSError:
                status.value = "Не удалось сохранить настройку. Попробуйте ещё раз."
            finally:
                save.disabled = switch.disabled = False
                for field in (current, password, confirmation):
                    field.disabled = False
                page.update()

        switch.on_change = toggle
        save.on_click = confirmation.on_submit = current.on_submit = apply
        refresh()
        return ft.Column([
            switch,
            ft.Text(
                "Отдельный пароль для входа в приложение на этом устройстве.",
                color=self.TxtColor, size=self.libs.text_size(12),
            ),
            current, password, confirmation, save, status,
        ], spacing=12)

    def _build_special_task_list(self, repeating, cmd_create, cmd_info, page):
        """Общие элементы списка для встроенного и отдельного диалога."""
        title = 'Повторяющиеся дела' if repeating else 'Отложенные дела'
        icon = ft.Icons.REPEAT_ROUNDED if repeating else ft.Icons.HOURGLASS_EMPTY_ROUNDED
        add = self.libs.build_button_with_image(
            'plusS',
            'Добавить повторяющееся дело' if repeating else 'Добавить отложенное дело',
            compact=False,
        )
        add.on_click = lambda e: cmd_create()
        info = self.libs.build_button_with_image(
            'info',
            'Подсказка по повторяющимся делам' if repeating else 'Подсказка по отложенным делам',
            compact=False,
        )
        info.on_click = lambda e: cmd_info()
        toolbar = ft.Row([
            self.libs.create_style_section_title(
                icon, title, size=15, icon_color=ft.Colors.WHITE,
            ),
            add,
            info,
        ], scroll=ft.ScrollMode.AUTO)
        tasks = ft.Container(
            content=ft.Column([], scroll=ft.ScrollMode.AUTO, height=page.height * 0.45),
            bgcolor=self.ContBgColor,
            border=ft.Border.all(0.5, self.BorderColor),
            border_radius=10,
            padding=self.padding,
            width=self.libs.width_dialogs * 0.95,
        )
        if repeating:
            self.cont_with_repeat_task = tasks
            self.read_repeat_tasks_and_add_to_cont()
        else:
            self.cont_with_postponed_task = tasks
            self.read_postponed_tasks_and_add_to_cont()
        return title, icon, toolbar, tasks

    def build_dialog_special_task_list(self, repeating, cmd_create, cmd_info, page):
        title, _, toolbar, tasks = self._build_special_task_list(
            repeating, cmd_create, cmd_info, page,
        )
        tasks.content.height = None
        tasks.expand = True
        back = self.libs.create_style_button('Назад')
        content = self.libs.create_style_cont([toolbar, tasks, back])
        content.content.scroll = None
        return (
            self.libs.create_style_header(title),
            content,
            back,
        )

    def build_dialog_special_tasks(
        self, cmd_for_dlg, cmd_for_postponed_dlg, page,
        cmd_open_list, cmd_repeat_info, cmd_postponed_info,
    ):
        """Строит раздел по актуальной настройке при каждом открытии."""
        blocks = []
        separate_dialogs = self.back2.read_settings()['special_tasks_separate_dialogs']
        for repeating, title, icon, cmd_create, cmd_info in (
            (True, 'Повторяющиеся дела', ft.Icons.REPEAT_ROUNDED,
             cmd_for_dlg, cmd_repeat_info),
            (False, 'Отложенные дела', ft.Icons.HOURGLASS_EMPTY_ROUNDED,
             cmd_for_postponed_dlg, cmd_postponed_info),
        ):
            if separate_dialogs:
                button = self.libs.create_style_category_button(icon, title)
                button.on_click = lambda e, repeat=repeating: cmd_open_list(repeat)
                blocks.append(button)
            else:
                _, _, toolbar, tasks = self._build_special_task_list(
                    repeating, cmd_create, cmd_info, page,
                )
                section = self.libs.create_style_expansion_category(
                    icon, title, [tasks], padding=1,
                )
                blocks.append(ft.Column([toolbar, section], spacing=10))
        back = self.libs.create_style_button('Назад')
        return (
            self.libs.create_style_header('Особые дела'),
            self.libs.create_style_cont([*blocks, back]),
            back,
        )

    def build_widgets_for_management_tasks(self, cmd_rebuild_widgets):
        """Виджеты для управления делами"""
        btn_del_all = self.libs.create_style_button("Удалить все дела")
        btn_del_all.on_click = lambda: (
            self.back2.delete_special_tasks(True),
            self.back2.delete_special_tasks(False),
            cmd_rebuild_widgets(),
        )

        btn_del_uncomp = self.libs.create_style_button("Удалить все невыполненные дела")
        btn_del_uncomp.on_click = lambda: (
            self.back2.delete_special_tasks(False),
            cmd_rebuild_widgets(),
            print('Удалено все невыполненные')
        )

        btn_del_comp = self.libs.create_style_button("Удалить все выполненные дела")
        btn_del_comp.on_click = lambda: (
            self.back2.delete_special_tasks(True),
            cmd_rebuild_widgets(),
        )

        btn_backup = self.libs.create_style_button(
            "Отправить бэкап", ft.Icons.CLOUD_UPLOAD_ROUNDED
        )
        backup_status = ft.Text(
            "Копия сохранённых в Dropbox дел — один раз в календарный день.",
            size=self.libs.text_size(12),
            color=self.TxtColor,
        )

        async def send_backup(e):
            if btn_backup.disabled:
                return
            btn_backup.disabled = True
            backup_status.value = "Отправка бэкапа…"
            self.back.page.update()
            try:
                account = self.cloud.read_user_data_text().split("~~")[0].strip()
                if not account:
                    backup_status.value = "Войдите в аккаунт, чтобы отправить бэкап."
                    return
                created = await asyncio.to_thread(self.cloud.create_manual_backup)
                if self.cloud.read_user_data_text().split("~~")[0].strip() != account:
                    backup_status.value = "Аккаунт изменился. Повторите отправку."
                elif created:
                    backup_status.value = "Бэкап отправлен в Dropbox. Следующий доступен завтра."
                else:
                    backup_status.value = "Бэкап за сегодня уже есть. Повторная отправка доступна завтра."
            except Exception:
                # Ошибки облака могут содержать путь с данными аккаунта.
                backup_status.value = "Не удалось отправить бэкап. Проверьте интернет и попробуйте ещё раз."
            finally:
                btn_backup.disabled = False
                self.back.page.update()

        btn_backup.on_click = send_backup
        return ft.Container(
            content=ft.Column([
                btn_del_all, btn_del_uncomp, btn_del_comp,
                btn_backup, backup_status,
            ])
        )

    def build_dialog_notifications(
        self,
        page,
        command_for_notifications_settings,
        command_for_battery_settings,
    ):
        """Диалог категории 'Уведомления'"""
        header = self.libs.create_style_header('Уведомления')
        widgets = self.build_widgets_for_notifications(
            page,
            command_for_notifications_settings,
            command_for_battery_settings,
        )
        back_btn = self.libs.create_style_button('Назад')
        content = self.libs.create_style_cont([widgets, back_btn])
        return header, content, back_btn

    def build_dialog_customization(self):
        """Диалог категории 'Кастомизация'."""
        header = self.libs.create_style_header('Кастомизация')
        widgets = self.build_widgets_for_customization()
        back_btn = self.libs.create_style_button('Назад')
        content = self.libs.create_style_cont([widgets, back_btn])
        return header, content, back_btn

    WEEKDAYS_RU_DAT = {
        1: "понедельникам",
        2: "вторникам",
        3: "средам",
        4: "четвергам",
        5: "пятницам",
        6: "субботам",
        7: "воскресеньям",
    }

    MONTHS_RU_GEN = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }

    def _describe_repeat_rule(self, repeat_type, repeat_value):
        """Строит человекочитаемое описание правила повторения дела"""
        if repeat_type == "week":
            try:
                weekday = int(repeat_value)
            except (TypeError, ValueError):
                weekday = 1
            return f"каждую неделю по {self.WEEKDAYS_RU_DAT.get(weekday, '')}"
        elif repeat_type == "month":
            try:
                day = int(repeat_value)
            except (TypeError, ValueError):
                day = 1
            return f"каждый месяц {day}-го числа"
        elif repeat_type == "year":
            try:
                day_str, month_str = str(repeat_value).split("-")
                day, month = int(day_str), int(month_str)
                return f"каждый год {day} {self.MONTHS_RU_GEN.get(month, '')}"
            except (ValueError, AttributeError):
                return "каждый год"
        else:
            try:
                interval = int(repeat_value)
            except (TypeError, ValueError):
                interval = 1
            if interval == 1:
                return "каждый день"
            elif interval % 10 == 1 and interval % 100 != 11:
                return f"каждые {interval} день"
            elif interval % 10 in (2, 3, 4) and not (11 <= interval % 100 <= 14):
                return f"каждые {interval} дня"
            else:
                return f"каждые {interval} дней"

    def get_group_name(self, group_id):
        for group in self.back.get_groups():
            if group["id"] == group_id:
                return group["name"]
        return "Без группы"

    def add_to_cont_with_repeat_task(self, task_name, repeat_type="day", repeat_value=1, group_id='default', task_id=None, metadata=None):
        """Функция для добавления в контейнер для повторяющихся дел"""

        metadata = metadata or {}
        interval_text = self._describe_repeat_rule(repeat_type, repeat_value)
        extra_text = (
            (
                f"Дедлайн через: {metadata.get('deadline_days')} дн."
                if metadata.get("deadline_days") not in (None, "")
                else f"Дедлайн: {metadata.get('deadline', '')}"
            ) if metadata.get("info_type") == "deadline" else
            f"Важность: {metadata.get('priority', 'Неважно')}" if metadata.get("info_type") == "priority" else
            f"Создано: {metadata.get('created_date', '')}"
        )
        disabled = bool(metadata.get("disabled", False))
        extra = ft.Text(
            "Дело отключено" if disabled else extra_text,
            size=self.libs.text_size(12),
            color=ft.Colors.YELLOW_700 if disabled else self.TxtColor,
            opacity=1 if disabled else 0.6,
        )
        delete = ft.PopupMenuItem(content="Удалить", icon=ft.Icons.DELETE_ROUNDED)
        edit = ft.PopupMenuItem(content="Редактировать", icon=ft.Icons.EDIT_ROUNDED)
        toggle = ft.PopupMenuItem(
            content="Включить" if disabled else "Отключить",
            icon=ft.Icons.PLAY_ARROW_ROUNDED if disabled else ft.Icons.PAUSE_ROUNDED,
        )
        menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT, icon_color=self.libs.colors["MutedColor"],
            tooltip="Действия с повторяющимся делом", items=[delete, edit, toggle],
        )

        display_task_name = self.back.auto_add_new_string(task_name)
        row = ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(
                                display_task_name,
                                no_wrap=False,
                                size=self.libs.text_size(16),
                                weight=ft.FontWeight.W_500,
                                color=self.TxtColor,
                            ),
                            ft.Text(
                                f"{interval_text} - {self.get_group_name(group_id)}",
                                size=self.libs.text_size(12),
                                color=self.TxtColor,
                                opacity=0.6,
                            ),
                            extra,
                        ],
                        spacing=0,
                        expand=True,
                    ),
                    menu,
                ], scroll=None if self.phone else ft.ScrollMode.AUTO,
            )

        if metadata.get("attachments"):
            row.controls[0].controls.append(attachment_controls(self.libs, metadata["attachments"]))
        self.cont_with_repeat_task.content.controls.append(row)


        delete.on_click = lambda _, r = row, t = task_name, g = group_id: cmd_for_delete(r, t, g)
        edit.on_click = lambda _, t=task_name, rt=repeat_type, rv=repeat_value, g=group_id, i=task_id, m=metadata: self.on_edit_repeat(t, rt, rv, g, i, m) if self.on_edit_repeat and i else None

        def toggle_disabled(_):
            disabled = not metadata.get("disabled", False)
            if not self.back2.set_repeat_task_disabled(task_id, disabled):
                return
            metadata["disabled"] = disabled
            extra.value = "Дело отключено" if disabled else extra_text
            extra.color = ft.Colors.YELLOW_700 if disabled else self.TxtColor
            extra.opacity = 1 if disabled else 0.6
            toggle.content = "Включить" if disabled else "Отключить"
            toggle.icon = ft.Icons.PLAY_ARROW_ROUNDED if disabled else ft.Icons.PAUSE_ROUNDED
            self.libs.page.update()

        toggle.on_click = toggle_disabled

        def cmd_for_delete(row_with_task, task_name, group_id):
            self.cont_with_repeat_task.content.controls.remove(row_with_task)
            self.back2.delete_repeat_task(task_name, group_id)


    def read_repeat_tasks_and_add_to_cont(self):
        """Функция для переноса всех повторяющихся дел в контейнер для управления ими"""
        a = self.back2.read_repeat_tasks()
        for task, repeat_type, repeat_value, group_id, task_id, metadata in a:
            self.add_to_cont_with_repeat_task(task, repeat_type, repeat_value, group_id, task_id, metadata)

    def add_to_cont_with_postponed_task(self, task_name, planned_date, group_id='default', task_id=None, metadata=None):
        if self.phone or self.libs.icon_pack in {"minimalistic", "minimalistic-blue"}:
            delete = self.libs.create_delete_button()
            edit = self.libs.create_edit_button()
        else:
            delete = self.libs.build_button_with_image(
                'basket1', "Удалить отложенное дело")
            edit = self.libs.build_button_with_image(
                'redact', "Редактировать отложенное дело")

        metadata = metadata or {}
        extra_text = (
            (
                f"Дедлайн через: {metadata.get('deadline_days')} дн."
                if metadata.get("deadline_days") not in (None, "")
                else f"Дедлайн: {metadata.get('deadline', '')}"
            ) if metadata.get("info_type") == "deadline" else
            f"Важность: {metadata.get('priority', 'Неважно')}" if metadata.get("info_type") == "priority" else
            f"Создано: {metadata.get('created_date', '')}"
        )
        display_task_name = self.back.auto_add_new_string(task_name)
        row = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(
                            display_task_name,
                            no_wrap=False,
                            size=self.libs.text_size(16),
                            weight=ft.FontWeight.W_500,
                            color=self.TxtColor,
                        ),
                        ft.Text(
                            f"Появится: {planned_date} - {self.get_group_name(group_id)}",
                            size=self.libs.text_size(12),
                            color=self.TxtColor,
                            opacity=0.6,
                        ),
                        ft.Text(extra_text, size=self.libs.text_size(12), color=self.TxtColor, opacity=0.6),
                    ],
                    spacing=0,
                    expand=True,
                ),
                edit, delete,
            ],
            scroll=None if self.phone else ft.ScrollMode.AUTO,
        )

        if metadata.get("attachments"):
            row.controls[0].controls.append(attachment_controls(self.libs, metadata["attachments"]))
        self.cont_with_postponed_task.content.controls.append(row)

        delete.on_click = lambda _, r=row, t=task_name, d=planned_date, g=group_id: cmd_for_delete(r, t, d, g)
        edit.on_click = lambda _, t=task_name, d=planned_date, g=group_id, i=task_id, m=metadata: self.on_edit_postponed(t, d, g, i, m) if self.on_edit_postponed and i else None

        def cmd_for_delete(row_with_task, task_text, task_date, group_id):
            self.cont_with_postponed_task.content.controls.remove(row_with_task)
            self.back2.delete_postponed_task(task_text, task_date, group_id)

    def read_postponed_tasks_and_add_to_cont(self):
        a = self.back2.read_postponed_tasks()
        for task, planned_date, group_id, task_id, metadata in a:
            self.add_to_cont_with_postponed_task(task, planned_date, group_id, task_id, metadata)


    def build_widgets_for_general_sets(self, command_for_update_tasks=None, group_id='default', command_for_rebuild_tasks=None):
        """Виджеты для общих настроек.

        split_by_dates, show_created_date, show_group_title и show_completion_counter относятся
        к конкретной группе дел (group_id) и хранятся в groups.json, а не в
        общем settings.txt — поэтому переключатели читают и пишут их
        через self.back.get_group_settings/update_group_settings. После
        их изменения контейнер с делами перестраивается локально
        (command_for_rebuild_tasks). Настройки названия и счётчика также ставятся
        в очередь синхронизации с облаком."""
        text1 = ft.Text(
            "Разделитель внизу приложения\n(для телефона)",
            # size=16,
            color=self.TxtColor,
        )
        text2 = ft.Text("Окно загрузки/обновления дел", color=self.TxtColor)
        text3 = ft.Text(
            "Разделять дела по датам \n(для данной группы)",
            color=self.TxtColor,
        )
        text4 = ft.Text(
            "Подписывать дату создания дел \n(в данной группе дел)",
            color=self.TxtColor,
        )

        """Выясняем статусы настроек"""
        sets = self.back2.read_settings()
        group_sets = self.back.get_group_settings(group_id)

        switch1 = ft.Switch(value=sets["border"])
        switch1.on_change = lambda: self.back2.redact_setting("border", switch1.value)

        switch2 = ft.Switch(value=sets["load_screen"])

        switch2.on_change = lambda: self.back2.redact_setting(
            "load_screen", switch2.value
        )

        separate_dialogs_switch = ft.Switch(
            value=sets["special_tasks_separate_dialogs"],
        )
        separate_dialogs_switch.on_change = lambda e: self.back2.redact_setting(
            "special_tasks_separate_dialogs", separate_dialogs_switch.value,
        )
        separate_dialogs_row = ft.Row([
            ft.Text(
                "Открытие списка повторяющихся и отложенных как отдельные диалоги",
                color=self.TxtColor,
                width=self.width_dialogs * 0.62,
            ),
            separate_dialogs_switch,
        ])

        switch3 = ft.Switch(value=group_sets["split_by_dates"])

        def change_split_by_dates(e):
            self.back.update_group_settings(group_id, split_by_dates=switch3.value)
            if command_for_rebuild_tasks is not None:
                command_for_rebuild_tasks()

        switch3.on_change = change_split_by_dates

        switch4 = ft.Switch(value=group_sets["show_created_date"])

        def change_show_created_date(e):
            self.back.update_group_settings(group_id, show_created_date=switch4.value)
            if command_for_rebuild_tasks is not None:
                command_for_rebuild_tasks()

        switch4.on_change = change_show_created_date

        title_switch = ft.Switch(
            value=group_sets["show_group_title"],
            tooltip="Показывать название текущей группы",
        )

        def change_group_title(e):
            self.back.update_group_settings(group_id, show_group_title=title_switch.value)
            self.cloud.alg_for_redact()
            if command_for_rebuild_tasks is not None:
                command_for_rebuild_tasks()

        title_switch.on_change = change_group_title
        title_row = ft.Row([
            ft.Text("Название текущей группы\n(для данной группы)", color=self.TxtColor),
            title_switch,
        ], scroll=ft.ScrollMode.AUTO)

        counter_switch = ft.Switch(
            value=group_sets["show_completion_counter"],
            tooltip="Показывать счётчик выполненных дел для этой группы",
        )

        def change_completion_counter(e):
            self.back.update_group_settings(
                group_id, show_completion_counter=counter_switch.value,
            )
            self.cloud.alg_for_redact()
            if command_for_rebuild_tasks is not None:
                command_for_rebuild_tasks()

        counter_switch.on_change = change_completion_counter
        counter_row = ft.Row([
            ft.Text("Счётчик выполненных дел\n(для данной группы)",
                    color=self.TxtColor),
            counter_switch,
        ], scroll=ft.ScrollMode.AUTO)

        row1 = ft.Row([text1, switch1], scroll=ft.ScrollMode.AUTO)
        row2 = ft.Row([text2, switch2], scroll=ft.ScrollMode.AUTO)
        row3 = ft.Row([text3, switch3], scroll=ft.ScrollMode.AUTO)
        row4 = ft.Row([text4, switch4], scroll=ft.ScrollMode.AUTO)
        if self.back.get_group_type(group_id) == 'notes':
            text3.value = "Разделять заметки по датам\n(для данной группы)"
            text4.value = "Подписывать дату создания заметок\n(в данной группе)"
            counter_row.controls[0].value = "Счётчик заметок\n(для данной группы)"
            counter_switch.tooltip = "Показывать счётчик заметок для этой группы"
        if self.phone and self.web:
            row4.scroll = ft.ScrollMode.AUTO
        return ft.Container(
            content=ft.Column([
                row1, row2, separate_dialogs_row, row3, row4, title_row, counter_row,
            ])
        )

    def build_widgets_for_customization(self):
        """Виджеты для настройки внешнего вида приложения."""
        sets = self.back2.read_settings()
        theme_dropdown = ft.Dropdown(
            label="Тема приложения",
            value=sets["theme_style"],
            options=[
                ft.dropdown.Option(key=key, text=label)
                for key, label in THEME_STYLE_OPTIONS
            ],
            width=self.width_dialogs * 0.82,
        )

        def change_theme(e):
            theme_style = theme_dropdown.value
            if theme_style == sets["theme_style"]:
                return
            self.back2.redact_setting("theme_style", theme_style)
            if self.on_theme_change is not None:
                self.on_theme_change(theme_style)

        theme_dropdown.on_select = change_theme

        font_dropdown = ft.Dropdown(
            label="Шрифт",
            value=sets["font_family"],
            options=[
                ft.dropdown.Option(key=key, text=label)
                for key, label in FONT_FAMILY_OPTIONS
            ],
            width=self.width_dialogs * 0.82,
        )
        font_size_dropdown = ft.Dropdown(
            label="Размер текста",
            value=sets["font_size"],
            options=[
                ft.dropdown.Option(key=key, text=label)
                for key, label in FONT_SIZE_OPTIONS
            ],
            width=self.width_dialogs * 0.82,
        )

        def change_font(setting, control):
            if control.value == self.back2.read_settings()[setting]:
                return
            self.back2.redact_setting(setting, control.value)
            if self.on_font_change is not None:
                self.on_font_change()

        font_dropdown.on_select = lambda _: change_font("font_family", font_dropdown)
        font_size_dropdown.on_select = lambda _: change_font("font_size", font_size_dropdown)
        font_preview = ft.Container(
            content=ft.Column([
                ft.Text("Пример текста", size=self.libs.text_size(18), weight=ft.FontWeight.W_600),
                ft.Text("Запланировать дела на сегодня.\nАа Бб Вв · Aa Bb Cc · 123", size=self.libs.text_size(16)),
            ], spacing=6),
            padding=14,
            bgcolor=self.BgColor,
            border=ft.Border.all(1, self.BorderColor),
            border_radius=10,
        )

        icon_pack_dropdown = ft.Dropdown(
            label="Пак иконок",
            value=sets["icon_pack"],
            options=[
                ft.dropdown.Option(
                    key="flet",
                    text="Flet (Material Icons)",
                ),
                ft.dropdown.Option(
                    key="minimalistic",
                    text="Минималистичный (по умолчанию)",
                ),
                ft.dropdown.Option(
                    key="minimalistic-blue",
                    text="Минималистичный (синий)",
                ),
                ft.dropdown.Option(key="old", text="Ранний"),
                ft.dropdown.Option(key="custom", text="Свой вариант"),
            ],
            width=self.width_dialogs * 0.82,
        )

        custom_pack_status = ft.Text(
            "",
            color=self.TxtColor,
            size=self.libs.text_size(12),
            visible=False,
        )
        custom_pack_button = self.libs.create_style_button(
            "Загрузить архив .zip", ft.Icons.UPLOAD_FILE_ROUNDED
        )
        custom_pack_help = ft.Column(
            [
                ft.Text(
                    "Для загрузки вы должны использовать архив в формате .zip, "
                    "иконки в нём должны назоваться так: добавления - plusS.png, "
                    "настроек - settings.png, авторизации - auth.png, обновления: "
                    "update.png, назад - nazad.png, удаления - basket1, "
                    "редактирования - redact.png, информации - info.png, "
                    "выхода - logout.png.",
                    color=self.TxtColor,
                    size=self.libs.text_size(12),
                    opacity=0.75,
                ),
                custom_pack_button,
                custom_pack_status,
            ],
            spacing=8,
            visible=icon_pack_dropdown.value == "custom",
        )

        file_picker = ft.FilePicker()

        def show_custom_pack_error(message):
            custom_pack_status.value = message
            custom_pack_status.color = ft.Colors.RED_400
            custom_pack_status.visible = True
            custom_pack_status.update()

        async def pick_custom_pack():
            try:
                files = await file_picker.pick_files(
                    dialog_title="Выберите архив с паком иконок",
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["zip"],
                    allow_multiple=False,
                    with_data=True,
                )
            except (OSError, RuntimeError) as error:
                show_custom_pack_error(f"Не удалось открыть архив: {error}")
                return
            if not files:
                return
            selected = files[0]
            archive_data = selected.bytes
            if archive_data is None and selected.path:
                try:
                    archive_data = Path(selected.path).read_bytes()
                except OSError:
                    archive_data = None
            try:
                self.back2.install_custom_icon_pack(archive_data)
            except (OSError, ValueError) as error:
                show_custom_pack_error(str(error))
                return

            self.back2.redact_setting("icon_pack", "custom")
            if self.on_icon_pack_change is not None:
                self.on_icon_pack_change("custom")

        custom_pack_button.on_click = lambda _: self.back.page.run_task(
            pick_custom_pack
        )

        def change_icon_pack(e):
            icon_pack = icon_pack_dropdown.value
            custom_pack_help.visible = icon_pack == "custom"
            custom_pack_help.update()
            if icon_pack == "custom" and not self.back2.has_custom_icon_pack():
                return
            if icon_pack == sets["icon_pack"]:
                return
            self.back2.redact_setting("icon_pack", icon_pack)
            if self.on_icon_pack_change is not None:
                self.on_icon_pack_change(icon_pack)

        icon_pack_dropdown.on_select = change_icon_pack

        custom_color_preview = ft.Container(
            width=28,
            height=28,
            bgcolor=sets["button_custom_color"],
            border=ft.Border.all(1, self.BorderColor),
            border_radius=14,
        )
        palette_button = ft.Button(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.PALETTE_ROUNDED,
                        color=self.libs.FletIconColor,
                    ),
                    ft.Text("Свой цвет", color=self.TxtColor, expand=True),
                    custom_color_preview,
                ],
                spacing=10,
            ),
            bgcolor=self.BtnColor,
            width=self.width_dialogs * 0.76,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
            ),
        )

        def apply_background_setting():
            if self.on_button_color_change is not None:
                self.on_button_color_change()

        def select_button_background(mode):
            if mode == sets["button_bg_mode"]:
                return
            self.back2.redact_setting("button_bg_mode", mode)
            apply_background_setting()

        light_check_modes = {
            "light_blue", "cyan", "light_green", "lime", "yellow",
            "amber", "orange", "white",
        }

        def create_color_button(mode, label, color):
            selected = sets["button_bg_mode"] == mode
            check_color = (
                ft.Colors.BLACK if mode in light_check_modes else ft.Colors.WHITE
            )
            return ft.Button(
                content=ft.Icon(
                    ft.Icons.CHECK_ROUNDED,
                    color=check_color if selected else ft.Colors.TRANSPARENT,
                    size=21,
                ),
                bgcolor=color,
                width=42,
                height=42,
                tooltip=label,
                style=ft.ButtonStyle(
                    shape=ft.CircleBorder(),
                    padding=0,
                    side=ft.BorderSide(
                        2 if selected else 1,
                        self.TxtColor if selected else self.BorderColor,
                    ),
                ),
                on_click=lambda _, selected_mode=mode: select_button_background(
                    selected_mode
                ),
            )

        default_color = get_theme_colors(self.theme)["BtnColor"]
        color_buttons = [
            create_color_button("default", "По умолчанию", default_color),
            *[
                create_color_button(mode, label, color)
                for mode, label, color in BUTTON_BACKGROUND_OPTIONS
            ],
        ]
        colors_grid = ft.Row(
            color_buttons,
            wrap=True,
            spacing=8,
            run_spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        def open_color_palette(e):
            page = self.back.page
            initial = normalize_custom_color(
                self.back2.read_settings()["button_custom_color"]
            )
            selected_color = {"value": initial}

            def change_picker_color(event):
                color = normalize_custom_color(event.data, None)
                if color is not None:
                    selected_color["value"] = color

            color_picker = ColorPicker(
                color=initial,
                color_picker_width=min(360, self.width_dialogs * 0.82),
                enable_alpha=False,
                hex_input_bar=True,
                label_types=[ColorLabelType.HEX, ColorLabelType.RGB],
                label_text_style=ft.TextStyle(color=self.TxtColor),
                palette_type=PaletteType.HSV,
                picker_area_border_radius=8,
                picker_area_height_percent=0.55,
                on_color_change=change_picker_color,
            )

            def close_palette(event=None):
                page.pop_dialog()

            def save_custom_color(event=None):
                color = selected_color["value"]
                self.back2.redact_setting("button_custom_color", color)
                self.back2.redact_setting("button_bg_mode", "custom")
                page.pop_dialog()
                apply_background_setting()

            dialog = ft.AlertDialog(
                modal=True,
                bgcolor=self.ContBgColor,
                title=ft.Text(
                    " Свой акцентный цвет",
                    color=self.TxtColor,
                    weight=ft.FontWeight.W_700,
                ),
                content=color_picker,
                actions=[
                    ft.Button("Отмена", on_click=close_palette),
                    ft.Button("Применить", on_click=save_custom_color),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dialog)

        palette_button.on_click = open_color_palette

        accent_color_menu = self.libs.create_style_expansion_category(
            ft.Icons.PALETTE_ROUNDED,
            "Акцентный цвет",
            [
                ft.Column(
                    [
                        colors_grid,
                        ft.Container(height=4),
                        palette_button,
                    ],
                    spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                )
            ],
            padding=12,
        )

        return ft.Container(
            content=ft.Column(
                [
                    theme_dropdown,
                    ft.Text(
                        "Светлый или тёмный вариант выбирается по настройке устройства.",
                        color=self.TxtColor,
                        size=self.libs.text_size(12),
                        opacity=0.65,
                    ),
                    ft.Divider(color=self.BorderColor),
                    icon_pack_dropdown,
                    custom_pack_help,
                    ft.Text(
                        "Для светлой и тёмной темы используются разные варианты иконок.",
                        color=self.TxtColor,
                        size=self.libs.text_size(12),
                        opacity=0.65,
                    ),
                    ft.Divider(color=self.BorderColor),
                    accent_color_menu,
                    ft.Divider(color=self.BorderColor),
                    font_dropdown,
                    font_size_dropdown,
                    font_preview,
                ],
                spacing=8,
            )
        )

    def build_widgets_for_notifications(
        self,
        page,
        command_for_notifications_settings=None,
        command_for_battery_settings=None,
    ):
        """Виджеты для настроек уведомлений."""
        sets = self.back2.read_settings()

        text_enabled = ft.Text("Отправлять уведомления", color=self.TxtColor, size=self.libs.text_size(18))
        switch_enabled = ft.Switch(
            value=False if self.web else sets["notifications_enabled"],
            disabled=self.web,
        )
        switch_important = ft.Switch(
            value=False if self.web else sets["notification_important_enabled"],
            disabled=self.web,
        )
        switch_deadline = ft.Switch(
            value=False if self.web else sets["notification_deadline_enabled"],
            disabled=self.web,
        )

        def group_notification_row(label, switch):
            return ft.Row(
                [
                    ft.Text(
                        label, color=self.TxtColor,
                        size=self.libs.text_size(18), expand=True,
                    ),
                    switch,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        important_row = group_notification_row(
            "Отправлять уведомление если в группах есть невыполненные очень важные дела",
            switch_important,
        )
        deadline_row = group_notification_row(
            "Отправлять уведомления если в группах есть дела с дедлайном, заканчивающимся через 1 день",
            switch_deadline,
        )
        quiet_text = ft.Text("Режим тишины", color=self.TxtColor, size=self.libs.text_size(18))
        switch_quiet = ft.Switch(
            value=False if self.web else sets["notification_quiet_enabled"],
            disabled=self.web,
        )

        interval_text = ft.Text(
            f"Интервал:",
            color=self.TxtColor,
            size=self.libs.text_size(18)
        )

        interval_entry = ft.TextField(
            sets["notification_interval"],
            width=60
        )

        interval_text2 = ft.Text(
            f'мин.',
            color=self.TxtColor,
            size=self.libs.text_size(18)
        )

        quiet_range_text = ft.Text(
            "Не беспокоить с",
            color=self.TxtColor,
            size=self.libs.text_size(18)
        )

        quiet_start_entry = ft.TextField(
            value=sets["notification_quiet_start"],
            width=80
        )

        quiet_range_text2 = ft.Text(
            "до",
            color=self.TxtColor,
            size=self.libs.text_size(18)
        )

        quiet_end_entry = ft.TextField(
            value=sets["notification_quiet_end"],
            width=80
        )

        quiet_range_row = ft.Row(
            [quiet_range_text, quiet_start_entry, quiet_range_text2, quiet_end_entry],
            opacity=1 if sets["notification_quiet_enabled"] else 0.45,
        )

        interval_apply = self.libs.create_style_button(
            'Сохранить изменения'
        )

        def update_notifications_settings():
            if command_for_notifications_settings is not None:
                command_for_notifications_settings()

        def sync_quiet_controls():
            is_enabled = bool(switch_quiet.value)
            quiet_start_entry.disabled = not is_enabled
            quiet_end_entry.disabled = not is_enabled
            quiet_range_row.opacity = 1 if is_enabled else 0.45
            if quiet_range_row.parent is not None:
                quiet_range_row.update()

        def change_enabled(e):
            self.back2.redact_setting("notifications_enabled", switch_enabled.value)
            update_notifications_settings()

        def change_quiet_enabled(e):
            sync_quiet_controls()
            self.back2.redact_setting("notification_quiet_enabled", switch_quiet.value)
            update_notifications_settings()

        def change_group_notification(setting, switch):
            self.back2.redact_setting(setting, switch.value)
            update_notifications_settings()

        def change_interval(e):
            interval = interval_entry.value
            try:
                interval = int(interval)
            except ValueError:
                self.libs.open_dialog(
                    'Изменения интервала',
                    'Интервал должен быть целым числом',
                    page
                )
                interval_entry.value = ''
            else:
                if not(0 <= int(interval) <= 120):
                    self.libs.open_dialog(
                        'Изменения интервала',
                        "Интервал должен быть от 0 до 120 минут",
                        page
                    )
                    interval_entry.value = ''
                else:
                    self.back2.redact_setting("notification_interval", interval)
                    update_notifications_settings()

            quiet_start = quiet_start_entry.value.strip()
            quiet_end = quiet_end_entry.value.strip()
            try:
                datetime.strptime(quiet_start, "%H:%M")
                datetime.strptime(quiet_end, "%H:%M")
            except ValueError:
                self.libs.open_dialog(
                    'Режим тишины',
                    'Введите время в формате ЧЧ:ММ, например 22:00',
                    page
                )
                quiet_start_entry.value = sets["notification_quiet_start"]
                quiet_end_entry.value = sets["notification_quiet_end"]
            else:
                self.back2.redact_setting("notification_quiet_start", quiet_start)
                self.back2.redact_setting("notification_quiet_end", quiet_end)
                update_notifications_settings()

        if not self.web:
            switch_enabled.on_change = change_enabled
            switch_quiet.on_change = change_quiet_enabled
            switch_important.on_change = lambda e: change_group_notification(
                "notification_important_enabled", switch_important
            )
            switch_deadline.on_change = lambda e: change_group_notification(
                "notification_deadline_enabled", switch_deadline
            )
        interval_apply.on_click = change_interval
        sync_quiet_controls()

        if self.phone:
            enabled_row = ft.Row(
                [text_enabled, switch_enabled],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            interval_row = ft.Row(
                [interval_text, interval_entry, interval_text2],
                wrap=True,
            )
            quiet_row = ft.Row(
                [quiet_text, switch_quiet],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            )
            quiet_range_row.wrap = True
        else:
            enabled_row = ft.Row([text_enabled, switch_enabled])
            interval_row = ft.Row([interval_text, interval_entry, interval_text2])
            quiet_row = ft.Row([quiet_text, switch_quiet])

        controls = [
            enabled_row,
            interval_row,
            important_row,
            deadline_row,
            quiet_row,
            quiet_range_row,
            interval_apply,
        ]

        if self.web:
            controls.extend(
                [
                    ft.Divider(),
                    ft.Text(
                        "На сайте уведомления не поддерживаются. Если вам нужны уведмоления, скачайте полноценный клиент",
                        color=self.TxtColor,
                        size=self.libs.text_size(18),
                    ),
                ]
            )
        elif self.phone:
            battery_button = self.libs.create_style_button(
                "Изменить ограничение батареи"
            )
            battery_button.on_click = lambda e: page.run_task(
                command_for_battery_settings
            )
            controls.extend(
                [
                    ft.Divider(),
                    ft.Text(
                        "Разрешите приложению работать в фоне (поставьте пункт 'Нет ограничений'), чтобы уведомления приходили вовремя. Если у вас кнопка не работает (ничего не происходит после нажатия), значит вы уже поставили 'Нет ограничений'",
                        color=self.TxtColor, 
                        size=self.libs.text_size(18)
                    ),
                    battery_button,
                ]
            )

        return ft.Container(
            content=ft.Column(controls)
        )
