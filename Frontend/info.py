import flet as ft
from .theme import get_theme_colors
from .libs import Fr_Libs
from Backend.extended import Backend2
from Backend.core import Backend

class Utils3:
    def __init__(
        self,
        theme,
        page=None,
        web_store=None,
        icon_pack="minimalistic",
        button_color=None,
    ):
        """Импорт классов"""
        # page/web_store прокинуты из Front — на сайте эти Backend/Backend2
        # должны работать с тем же browser-store посетителя, что и основные
        # self.back/self.back2 во Front, а не с отдельными файлами на сервере.
        self.back = Backend(page=page, web_store=web_store)
        self.back2 = Backend2(page=page, web_store=web_store, back=self.back)
        if page is not None and getattr(page, "web", False):
            # Телефон/ПК на сайте определяем по User-Agent — влияет только
            # на вёрстку (self.libs ниже), уведомления на сайте отключены
            # отдельно в Backend/notifications.py вне зависимости от этого флага.
            ua = (page.client_user_agent or "").lower()
            self.back.phone = any(marker in ua for marker in ("iphone", "android", "mobile"))
        self.phone = self.back.get_device()
        self.font = int()
        self.width_dialogs = int()
        self.height_dialogs = int()
        self.padding = int()
        self.padding_for_row = int()
        self.height_for_dlg_spacer = int()

        self.theme = theme
        self.libs = Fr_Libs(
            self.theme,
            self.phone,
            page=page,
            web=bool(page is not None and getattr(page, "web", False)),
            icon_pack=icon_pack,
            button_color=button_color,
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
            self.height_dialogs = 300
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
    def dialog_for_info_repeat(self):
        """Создает контейнеры с объяснением работы
        ежедневных дел"""

        header = self.libs.create_style_header(
            'Как работают повторяющиеся дела?'
        )

        a = \
"""В настройках вы добавляете повторяющиеся дела, которые будут автоматически появляться в основном поле по выбранному расписанию. Управлять ими (выполнять, удалять) нужно уже в основном поле, а здесь вы только прописываете, что и когда должно добавляться.

Доступные типы повторения:
• Ежедневно — дело добавляется каждый день
• Еженедельно — выберите день недели в выпадающем списке, дело будет добавляться еженедельно в этот день недели
• Ежемесячно — напишите число месяца, дело будет добавляться ежемесячно в это число
• Ежегодно — выберите дату в календаре, дело будет добавляться каждый год в этот день и месяц
• Свой интервал — дело добавляется каждые N дней (от 1 до 367)"""


        txt = ft.Text(
            a,
            size=self.libs.text_size(16),
            weight=ft.FontWeight.W_600,
            color=self.TxtColor
        )

        nazad = self.libs.create_style_button('Назад')

        main = self.libs.create_style_cont(
            [txt, nazad]
        )

        return header, main, nazad

    def dialog_for_info_postponed(self):
        """Создает контейнеры с объяснением работы отложенных дел"""

        header = self.libs.create_style_header(
            'Как работают отложенные дела?'
        )

        txt = ft.Text(
            "Добавляя здесь дела, они добавляются в основное поле залач один раз в дату, которую вы выбрали, после этого они удаляются из отложенных дел",
            size=self.libs.text_size(16),
            weight=ft.FontWeight.W_600,
            color=self.TxtColor
        )

        nazad = self.libs.create_style_button('Назад')

        main = self.libs.create_style_cont(
            [txt, nazad]
        )

        return header, main, nazad

    def dialog_for_primechanya(self):
        """Создает контейнеры с примечаниями"""

        header = self.libs.create_style_header(
            'Примечания'
        )
        nazad = self.libs.create_style_button('Назад')
        main = self.libs.create_style_cont([self.create_notes_text(), nazad])
        return header, main, nazad

    def create_notes_text(self):
        """Единый текст для настроек и согласия при первом запуске."""
        a = \
"""Если вы авторизованы в аккаунте, то могут  быть небольшие задержки в таких действиях как удаление,  редактирование, добавление дела. Также возможна долгая загрузка.

Авторизуясь и создавая аккаунт вы соглашаетесь, что разработчик имеет доступ к вашим данным, которые находятся на аккаунте. По умолчанию данные в облаке зашифрованы (с версии 3.9.0). В разделе «Безопасность» можно отключить дополнительное шифрование аккаунта: тогда текущие данные и последующие изменения можно прочитать после скачивания из Dropbox. Ранее созданные резервные копии сохраняют прежний формат. Также не гарантируется сохранность файлов дел потому что они расположены или в Dropbox или на устройстве пользователя.


Если у вас происходят баги такие как: кнопки не работают, после нажатия на кнопку редактирования название дела не появилось, то нажмите кнопку "обновить", обычно это помогает. Если обновление не помогло, то перезапустите приложение

Если у вас не разделились дела по датам после добавления дела, то нажмите на кнопку обновления, это должно помочь.

Индикатор загрузки (на ПК: кольцо в правом верхнем углу, на телефоне: полоска под кнопками) означает прогресс загрузки на облако (если у вас есть аккаунт)

Версия проекта на сайте хуже по производительности (намного дольше загрузка и др.), так что если у вас android или windows рекомендуется устоновить полноценное приложение"""

        return ft.Text(
            a,
            color=self.TxtColor,
            size=self.libs.text_size(16),
            weight=ft.FontWeight.W_600,
        )
