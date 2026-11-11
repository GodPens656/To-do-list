"""A disposable, decorative game owned by one loading-screen instance."""

import asyncio
import random
from dataclasses import dataclass
from time import monotonic

import flet as ft


@dataclass
class _Card:
    slot: int
    control: ft.Container
    checkbox: ft.Checkbox
    expires: float
    caught: bool = False


class LoadingScreen(ft.Container):
    REVEAL_DELAY = 2.0
    FADE_SECONDS = 0.18
    CARD_COUNT = 3

    def __init__(self, libs):
        super().__init__(expand=True, alignment=ft.Alignment.CENTER)
        self._libs = libs
        self._random = random.Random()
        self._cards = {}
        self._stopped = False
        self._worker = None
        self._wake = asyncio.Event()
        self.score = 0
        colors = libs.colors
        self._score_text = ft.Text(
            "Поймано: 0", size=libs.text_size(14), color=colors["TxtColor"],
            weight=ft.FontWeight.W_600,
        )
        # Six responsive cells give every card a free, non-overlapping position
        # even when a desktop window is resized down to phone width.
        self._slots = [ft.Container(height=54, expand=True) for _ in range(6)]
        self._game = ft.Column([
            ft.Text("Поймай галочку", size=libs.text_size(18),
                    weight=ft.FontWeight.W_600, color=colors["TxtColor"],
                    text_align=ft.TextAlign.CENTER),
            ft.Text("Нажимай на карточки, пока загружаются дела",
                    size=libs.text_size(13), color=colors["MutedColor"],
                    text_align=ft.TextAlign.CENTER),
            self._score_text,
            ft.Container(
                content=ft.Column([
                    ft.Row(self._slots[i:i + 2], spacing=8)
                    for i in range(0, 6, 2)
                ], spacing=8, tight=True),
                padding=8, bgcolor=colors["BgColor"], border_radius=12,
                border=ft.Border.all(1, colors["SoftBorderColor"]),
            ),
        ], spacing=10, tight=True, visible=False,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        panel = ft.Container(
            content=ft.Column([
                ft.ProgressRing(color=colors["TxtColor"]),
                ft.Text("Загрузка", size=libs.text_size(16),
                        weight=ft.FontWeight.W_700, color=colors["TxtColor"]),
                self._game,
            ], spacing=12, tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=336, padding=20, bgcolor=colors["LoadColor"],
            border=ft.Border.all(0.5, colors["BorderColor"]), border_radius=10,
        )
        self.content = libs.host(
            content=ft.Column([panel], alignment=ft.MainAxisAlignment.CENTER,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                              scroll=ft.ScrollMode.AUTO, expand=True),
            expand=True, alignment=ft.Alignment.CENTER,
        )

    def did_mount(self):
        if not self._stopped and self._worker is None:
            self._worker = self.page.run_task(self._run)

    def will_unmount(self):
        self.stop()

    def stop(self):
        """Invalidate before cancelling: queued clicks cannot change this game."""
        self._stopped = True
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

    def _spawn(self, now):
        free = [i for i in range(len(self._slots)) if i not in self._cards]
        slot = self._random.choice(free)
        colors = self._libs.colors
        checkbox = ft.Checkbox(
            value=False, semantics_label="Поймать галочку",
            active_color=colors["ProgressColor"],
            border_side=ft.BorderSide(2, colors["ProgressColor"]),
            width=30, height=30,
        )
        decoration = ft.Row([
            checkbox,
            ft.Column([
                ft.Container(height=4, border_radius=2, bgcolor=colors["MutedColor"]),
                ft.Container(height=4, width=24, border_radius=2,
                             bgcolor=colors["SoftBorderColor"]),
            ], spacing=6, expand=True, tight=True),
        ], spacing=8)
        control = ft.Container(
            content=decoration, padding=10, height=54, border_radius=12,
            bgcolor=colors["ContBgColor"],
            border=ft.Border.all(1, colors["SoftBorderColor"]),
            animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
            animate_scale=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        )
        card = _Card(slot, control, checkbox,
                     now + self._random.uniform(3.2, 5.0))

        async def catch(event):
            # Async Flet handlers run on the page loop. No await separates the
            # identity/score changes, including two clicks already in flight.
            ft.context.disable_auto_update()
            if self._stopped or self._cards.get(slot) is not card:
                return
            if card.caught:
                checkbox.value = True
                return
            card.caught = True
            card.expires = monotonic() + self.FADE_SECONDS
            self.score += 1
            self._score_text.value = f"Поймано: {self.score}"
            checkbox.value = True
            checkbox.disabled = True
            control.opacity = 0.25
            control.scale = 0.9
            self._patch_game()
            self._wake.set()

        control.on_click = catch
        checkbox.on_change = catch
        self._cards[slot] = card
        self._slots[slot].content = control

    def _replace_expired(self, now):
        for slot, card in list(self._cards.items()):
            if card.expires <= now:
                self._slots[slot].content = None
                del self._cards[slot]
        while len(self._cards) < self.CARD_COUNT:
            self._spawn(now)

    def _patch_game(self):
        if self._stopped:
            return
        try:
            self._game.update()
        except RuntimeError:
            # A parent can be removed before Flet delivers will_unmount().
            self.stop()

    async def _run(self):
        try:
            await asyncio.sleep(self.REVEAL_DELAY)
            if self._stopped:
                return
            self._replace_expired(monotonic())
            self._game.visible = True
            self._patch_game()
            while not self._stopped:
                self._wake.clear()
                delay = max(0, min(c.expires for c in self._cards.values()) - monotonic())
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    if self._stopped:
                        return
                    self._replace_expired(monotonic())
                    self._patch_game()
        except asyncio.CancelledError:
            pass
