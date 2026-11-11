"""Ленивые пункты меню карточки с прежними целями привязки обработчиков."""

from dataclasses import dataclass

import flet as ft

from .controls import ActionIconButton


@dataclass(slots=True)
class TaskAction:
    """Лёгкая цель для on_click и tooltip до создания PopupMenuItem."""

    label: str
    icon: object
    on_click: object = None
    tooltip: str | None = None


class TaskActionsMenu(ft.ContextMenu):
    """Создаёт нативные PopupMenuItem только перед первым открытием меню."""

    def __init__(self, libs, task_id, *, icon_color, show_checkbox=True,
                 on_copy=None, on_repeat=None):
        self._libs = libs
        self._opening = False
        self.edit = TaskAction("Редактировать", ft.Icons.EDIT_ROUNDED)
        self.delete = TaskAction("Удалить", ft.Icons.DELETE_ROUNDED)
        self.actions = [self.edit, TaskAction("Скопировать", ft.Icons.CONTENT_COPY_ROUNDED, on_copy)]
        if show_checkbox:
            self.actions.append(TaskAction("Сделать повторяющимися", ft.Icons.REPEAT_ROUNDED, on_repeat))
        self.actions.append(self.delete)
        button = ActionIconButton(
            icon=ft.Icons.MORE_VERT, icon_color=icon_color, data=task_id,
            on_click=self._open_actions,
        )
        # Исходный PopupMenuButton наследовал тему IconButton без отдельной
        # стеклянной оболочки. Сохраняем тот же способ оформления якоря.
        button._nd_glass_toolbar_action = True
        super().__init__(content=button, data=task_id,
                         tooltip="Действия с делом" if show_checkbox else "Действия с заметкой",
                         secondary_trigger=None, tertiary_trigger=None)

    def __repr__(self):
        return f"{type(self).__name__}({self._i})"

    def build_items(self):
        """Материализует пункты один раз и сохраняет актуальные привязки."""
        if not self.items:
            self.items = [ft.PopupMenuItem(
                content=action.label,
                icon=ft.Icon(action.icon, size=18, color=self._libs.FletIconColor),
                label_text_style=ft.TextStyle(
                    size=self._libs.text_size(14), color=self._libs.TxtColor,
                ),
            ) for action in self.actions]
        for item, action in zip(self.items, self.actions):
            item.on_click = action.on_click
            item.tooltip = action.tooltip
        return self.items

    async def _open_actions(self, event):
        if self._opening:
            return
        self._opening = True
        try:
            self.build_items()
            self._libs.prepare(self)
            # Клиент должен получить пункты и их обработчики до вызова open.
            self.update()
            ft.context.disable_auto_update()
            await self.open(local_position=ft.Offset(48 if self._libs.phone else 0, 0))
        finally:
            self._opening = False
            ft.context.disable_auto_update()
