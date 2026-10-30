"""Monthly task calendar shared by desktop, Android, and the web client."""

import calendar
from datetime import date

import flet as ft

from Backend.core import local_today


MONTHS = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
WEEKDAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
KINDS = {
    "repeat": ("Повтор", ft.Icons.REPEAT_ROUNDED),
    "postponed": ("Отложено", ft.Icons.SCHEDULE_ROUNDED),
    "deadline": ("Дедлайн", ft.Icons.FLAG_OUTLINED),
}


class TaskSchedule:
    DAY_PREVIEW_LIMIT = 3
    DAY_PAGE_SIZE = 40

    def __init__(self, front):
        self.front = front
        self.libs = front.libs
        self.colors = self.libs.colors
        self.today = local_today(front.web, front.page)
        self.month = self.today.replace(day=1)
        # The first web frame can arrive before Flet reports the viewport.
        viewport = front.page.width or (360 if front.phone else 1280)
        self.width = min(1200, max(260, viewport - 2 * front.page_edge_padding))
        self.cell_width = max(146, (self.width - 32) / 7)
        dark = str(front.theme).endswith("dark")
        self.accents = {
            "repeat": "#C4B5FD" if dark else "#6D47B1",
            "postponed": "#86BFFA" if dark else "#2466A9",
            "deadline": "#F5BD80" if dark else "#A45119",
        }
        self.groups = {
            group["id"]: group["name"] for group in front.back.get_groups()
            if group.get("type") != "notes"
        }
        self.back = ft.IconButton(
            icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=self.colors["TxtColor"],
            tooltip="Назад к настройкам",
        )
        self.header = ft.Container(
            ft.Row([
                self.back,
                ft.Text("Расписание", size=self.libs.text_size(24),
                        color=self.colors["TxtColor"], weight=ft.FontWeight.W_700),
            ], spacing=8),
            width=self.width, padding=ft.Padding.symmetric(vertical=6),
        )
        self.month_title = ft.Text(size=self.libs.text_size(17 if front.phone else 21),
                                   color=self.colors["TxtColor"],
                                   weight=ft.FontWeight.W_600, no_wrap=True, expand=True,
                                   text_align=ft.TextAlign.CENTER)
        self.previous = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT_ROUNDED, tooltip="Предыдущий месяц",
            icon_color=self.colors["TxtColor"], on_click=lambda _: self.move_month(-1),
        )
        self.next = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT_ROUNDED, tooltip="Следующий месяц",
            icon_color=self.colors["TxtColor"], on_click=lambda _: self.move_month(1),
        )
        self.today_button = ft.TextButton(
            "Сегодня", on_click=self.go_today,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=8), color=self.colors["TxtColor"],
                text_style=ft.TextStyle(size=self.libs.text_size(12)),
            ),
        )
        self.group_filter = ft.Dropdown(
            value="", label="Группа дел", width=None if front.phone else 240,
            expand=True if front.phone else None,
            options=[ft.dropdown.Option(key="", text="Все группы"), *[
                ft.dropdown.Option(key=ident, text=name) for ident, name in self.groups.items()
            ]],
            text_size=self.libs.text_size(13), color=self.colors["TxtColor"],
            border_color=self.colors["BorderColor"],
            dense=True, on_select=lambda _: self.refresh(),
        )
        self.summary = ft.Text(size=self.libs.text_size(12), color=self.colors["MutedColor"])
        self.empty = ft.Text(
            "На этот месяц дел в расписании нет. Выберите другой месяц или группу.",
            size=self.libs.text_size(13), color=self.colors["MutedColor"], visible=False,
        )
        self.grid = ft.Column(spacing=0, tight=True)
        self.table = ft.Row([self.grid], scroll=ft.ScrollMode.AUTO, spacing=0)
        navigation = ft.Row(
            [self.previous, self.month_title, self.next], spacing=0,
            width=None if front.phone else 330,
        )
        toolbar = ([navigation, ft.Row([self.group_filter, self.today_button], spacing=8)]
                   if front.phone else [
            ft.Row([navigation, self.today_button, ft.Container(expand=True), self.group_filter], spacing=18),
        ])
        self.content = self.libs.host(
            content=ft.Column([
                ft.Container(ft.Column(toolbar, spacing=14), padding=ft.Padding.only(top=8)),
                self.summary, self.empty,
                self.table,
                ft.Text("Нажмите на дело, чтобы увидеть подробности.",
                        size=self.libs.text_size(12), color=self.colors["MutedColor"]),
            ], spacing=14, scroll=ft.ScrollMode.AUTO),
            width=self.width, expand=True, padding=14,
            bgcolor=self.colors["ContBgColor"], border_radius=16,
            border=ft.Border.all(1, self.colors["SoftBorderColor"]),
        )
        self.refresh(update=False)

    def move_month(self, offset):
        number = self.month.year * 12 + self.month.month - 1 + offset
        year, month = divmod(number, 12)
        if 1900 <= year <= 9998:
            self.month = date(year, month + 1, 1)
            self.refresh()

    def go_today(self, _=None):
        self.today = local_today(self.front.web, self.front.page)
        self.month = self.today.replace(day=1)
        self.refresh()

    def show_entry(self, entry):
        label = KINDS[entry.kind][0]
        details = [entry.name, f"{label} · {entry.date:%d.%m.%Y}",
                   f"Группа: {self.groups.get(entry.group, 'Без группы')}"]
        if entry.detail:
            details.append(entry.detail)
        if entry.completed:
            details.append("Выполнено")
        self.libs.open_dialog("Дело в расписании", "\n\n".join(details), self.front.page)

    def show_day(self, day):
        """Build only one page of a busy day, including events beyond the preview."""
        entries = self.entries.get(day, [])
        if not entries:
            return
        page_index = 0
        listing = ft.ListView(expand=True, spacing=8, build_controls_on_demand=True)
        counter = ft.Text(size=self.libs.text_size(12), color=self.colors["MutedColor"])
        previous = ft.IconButton(
            ft.Icons.CHEVRON_LEFT_ROUNDED, tooltip="Предыдущие дела",
            icon_color=self.colors["TxtColor"],
        )
        next_button = ft.IconButton(
            ft.Icons.CHEVRON_RIGHT_ROUNDED, tooltip="Следующие дела",
            icon_color=self.colors["TxtColor"],
        )

        def render():
            start = page_index * self.DAY_PAGE_SIZE
            end = min(start + self.DAY_PAGE_SIZE, len(entries))
            listing.controls = [self.entry_card(entry) for entry in entries[start:end]]
            listing.key = f"schedule-day-{day}-{page_index}"
            counter.value = f"{start + 1}–{end} из {len(entries)}"
            previous.disabled = page_index == 0
            next_button.disabled = end == len(entries)

        def move(offset):
            nonlocal page_index
            last_page = (len(entries) - 1) // self.DAY_PAGE_SIZE
            page_index = min(last_page, max(0, page_index + offset))
            render()
            self.front.page.update()

        previous.on_click = lambda _: move(-1)
        next_button.on_click = lambda _: move(1)
        render()
        dialog = ft.AlertDialog(
            title=ft.Text(f"Дела · {day:%d.%m.%Y}", size=self.libs.text_size(18),
                          color=self.colors["TxtColor"]),
            content=ft.Container(
                ft.Column([
                    listing,
                    ft.Row([previous, counter, next_button],
                           alignment=ft.MainAxisAlignment.CENTER, spacing=4),
                ], spacing=8),
                width=min(560, max(220, self.width - 48)),
                height=min(520, max(180, (self.front.page.height or 800) * 0.6)),
            ),
            actions=[ft.TextButton("Закрыть", on_click=lambda _: self.front.page.pop_dialog())],
            bgcolor=self.colors["ContBgColor"], inset_padding=16,
        )
        self.front.page.show_dialog(self.libs.prepare(dialog))

    def entry_card(self, entry):
        color = self.accents[entry.kind]
        label, icon = KINDS[entry.kind]
        group = self.groups.get(entry.group, "Без группы")
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_ROUNDED if entry.completed else icon, size=12, color=color),
                    ft.Text(label, size=self.libs.text_size(10), color=color),
                ], spacing=4),
                ft.Text(entry.name, size=self.libs.text_size(12), color=self.colors["TxtColor"],
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, weight=ft.FontWeight.W_500),
            ], spacing=4, tight=True),
            padding=8, bgcolor=ft.Colors.with_opacity(0.10, color),
            border=ft.Border(left=ft.BorderSide(3, color)), border_radius=6,
            opacity=0.55 if entry.completed else 1,
            tooltip=f"{entry.name}\n{label} · {entry.date:%d.%m.%Y}\n{group}",
            on_click=lambda _: self.show_entry(entry), data=entry,
        )

    def refresh(self, update=True):
        self.today = local_today(self.front.web, self.front.page)
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(self.month.year, self.month.month)
        self.entries = self.front.back2.read_schedule(
            weeks[0][0], weeks[-1][-1], self.group_filter.value or None,
        )
        self.month_title.value = f"{MONTHS[self.month.month - 1]} {self.month.year}"
        self.previous.disabled = self.month == date(1900, 1, 1)
        self.next.disabled = self.month == date(9998, 12, 1)
        month_days = {day: entries for day, entries in self.entries.items()
                      if day.year == self.month.year and day.month == self.month.month}
        count = sum(len(entries) for entries in month_days.values())
        self.summary.value = f"Событий в месяце: {count}   ·   Дней с делами: {len(month_days)}"
        self.empty.visible = count == 0
        rows = [ft.Row([
            ft.Container(
                ft.Text(name, size=self.libs.text_size(12), weight=ft.FontWeight.W_600,
                        color=self.colors["MutedColor"]),
                width=self.cell_width, padding=ft.Padding.symmetric(horizontal=10, vertical=12),
            ) for name in WEEKDAYS
        ], spacing=0)]
        for week in weeks:
            cells = []
            for day in week:
                current = day == self.today
                in_month = day.month == self.month.month
                entries = self.entries.get(day, [])
                day_header = ft.Row([
                    ft.Container(
                        ft.Text(str(day.day), size=self.libs.text_size(13),
                                weight=ft.FontWeight.W_600,
                                color=self.colors["BgColor"] if current else self.colors["TxtColor"]),
                        padding=5, border_radius=8,
                        bgcolor=self.colors["TxtColor"] if current else None,
                    ),
                    ft.Text("сегодня" if current else (day.strftime("%m") if not in_month else ""),
                            size=self.libs.text_size(10), color=self.colors["MutedColor"]),
                ], spacing=5)
                cells.append(ft.Container(
                    content=ft.Column([
                        day_header,
                        *[self.entry_card(entry) for entry in entries[:self.DAY_PREVIEW_LIMIT]],
                        *([ft.TextButton(
                            f"Ещё {len(entries) - self.DAY_PREVIEW_LIMIT}",
                            tooltip="Все дела за день",
                            on_click=lambda _, selected_day=day: self.show_day(selected_day),
                        )] if len(entries) > self.DAY_PREVIEW_LIMIT else []),
                        *([ft.Container(height=42)] if not entries else []),
                    ], spacing=6, tight=True),
                    width=self.cell_width, padding=8,
                    bgcolor=ft.Colors.with_opacity(0.06, self.colors["TxtColor"]) if current else (
                        self.colors["ContBgColor"] if in_month else self.colors["BgColor"]),
                    border=ft.Border.all(0.5, self.colors["SoftBorderColor"]),
                    data=day,
                ))
            rows.append(ft.Row(cells, spacing=0, intrinsic_height=True,
                               vertical_alignment=ft.CrossAxisAlignment.STRETCH))
        self.grid.controls = rows
        if update:
            self.front.page.update()
