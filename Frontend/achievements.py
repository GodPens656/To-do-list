"""The achievements screen, rebuilt from current progress on every opening."""

from datetime import date

import flet as ft

from Backend.achievements import POINTS_PER_TASK


class AchievementsView:
    def __init__(self, front):
        self.libs = front.utils2.libs
        self.colors = self.libs.colors
        self.accent = "#FFAB66" if self.libs.icon_theme == "dark" else "#AD4500"
        self.progress = front.back.get_achievements()
        self.header = self.libs.create_style_header("Достижения")
        self.back = self.libs.create_style_button("Назад")
        self.content = self.libs.create_style_cont([
            self._streak_card(),
            ft.Row([
                self._stat(ft.Icons.STARS_ROUNDED, str(self.progress["points"]), "Баллы"),
                self._stat(ft.Icons.TASK_ALT_ROUNDED,
                           str(self.progress["completed_tasks"]), "Выполнено дел"),
            ], spacing=10),
            self._text(
                f"Каждое выполненное дело — +{POINTS_PER_TASK} баллов. "
                "Для серии выполните хотя бы одно дело за день.", muted=True,
            ),
            self._text(
                f"Награды · {self.progress['unlocked_count']} из {len(self.progress['awards'])}",
                size=17, bold=True,
            ),
            self._text("За выполненные дела", bold=True),
            *[self._award(award) for award in self.progress["awards"] if award["kind"] == "tasks"],
            self._text("За дни подряд", bold=True),
            *[self._award(award) for award in self.progress["awards"] if award["kind"] == "streak"],
            self._text(
                "День засчитывается по вашему местному времени. Пропуск дня обнуляет "
                "текущую серию, а рекорд сохраняется. Снятие галочки отменяет начисление "
                "за это дело. Удаление выполненного дела сохраняет прогресс. "
                "Ранее выполненные дела дают баллы, но не дни серии: их дата выполнения неизвестна.",
                muted=True, size=12,
            ),
            self.back,
        ])

    def _text(self, value, *, size=14, muted=False, bold=False, **kwargs):
        return ft.Text(
            value, size=self.libs.text_size(size),
            color=self.colors["MutedColor"] if muted else self.colors["TxtColor"],
            weight=ft.FontWeight.W_600 if bold else ft.FontWeight.NORMAL,
            **kwargs,
        )

    def _card(self, content, **kwargs):
        return ft.Container(
            content=content, bgcolor=self.colors["BgColor"],
            border=ft.Border.all(1, self.colors["SoftBorderColor"]),
            border_radius=14, padding=14, **kwargs,
        )

    def _stat(self, icon, value, label):
        return self._card(ft.Column([
            ft.Icon(icon, color=self.accent, size=24),
            self._text(value, size=24, bold=True),
            self._text(label, size=12, muted=True),
        ], spacing=4), expand=True)

    def _streak_card(self):
        p = self.progress
        if p["completed_today"]:
            status = "На сегодня готово! Возвращайтесь завтра."
        elif p["current_streak"]:
            status = "Выполните дело сегодня, чтобы продолжить серию."
        else:
            status = "Выполните первое дело сегодня и начните серию."
        week = []
        for day in p["week"]:
            calendar_day = date.fromisoformat(day["date"])
            week.append(ft.Container(
                content=ft.Column([
                    self._text(("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")[calendar_day.weekday()],
                               size=11, muted=True, text_align=ft.TextAlign.CENTER),
                    ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED if day["completed"]
                            else ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED,
                            size=23, color=self.accent if day["completed"] else self.colors["MutedColor"]),
                    self._text(str(calendar_day.day), size=11, bold=day["today"]),
                ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                expand=True, padding=ft.Padding.symmetric(vertical=8),
                border=ft.Border.all(1, self.accent) if day["today"] else None,
                border_radius=10,
                tooltip=calendar_day.strftime("%d.%m.%Y") + (
                    " · Выполнено" if day["completed"] else " · Пока без выполненных дел"
                ),
            ))
        return self._card(ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT_ROUNDED, color=self.accent, size=40),
                ft.Column([
                    self._text("Серия дней", bold=True),
                    self._text(str(p["current_streak"]), size=34, bold=True),
                ], spacing=0, expand=True),
            ], spacing=12),
            self._text(status, bold=p["completed_today"]),
            self._text(f"Рекорд: {p['best_streak']} дн. · Дел сегодня: {p['today_count']}",
                       muted=True, size=12),
            ft.Row(week, spacing=3),
        ], spacing=12))

    def _award(self, award):
        earned = award["unlocked"]
        return self._card(ft.Row([
            ft.Icon(
                ft.Icons.EMOJI_EVENTS_ROUNDED if earned else ft.Icons.LOCK_OUTLINE_ROUNDED,
                color=self.accent if earned else self.colors["MutedColor"], size=28,
            ),
            ft.Column([
                self._text(award["title"], bold=True),
                self._text(award["description"], size=12, muted=True),
                ft.ProgressBar(
                    value=award["value"] / award["target"], color=self.accent,
                    bgcolor=self.colors["SoftBorderColor"], height=5, border_radius=3,
                ),
                self._text("Получено" if earned else award["progress_label"],
                           size=12, muted=not earned),
            ], spacing=6, expand=True),
        ], spacing=12))
