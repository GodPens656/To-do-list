"""Attachment editor and shared preview/download buttons."""

import asyncio
from copy import deepcopy
from pathlib import Path

import flet as ft

from Backend.attachments import (
    MAX_FILE_BYTES, MAX_TASK_BYTES, attachment_bytes, attachment_name,
    image_preview, make_attachment,
)


def file_picker(page):
    picker = getattr(page, "_nd_attachment_picker", None)
    if not isinstance(picker, ft.FilePicker):
        picker = ft.FilePicker()
        page._nd_attachment_picker = picker
        if picker not in page.services:
            page.services.append(picker)
        page.update()
    return picker


def prepare_attachments(selected, existing, *, web):
    """Validate metadata before reading local files; keep reads bounded."""
    for item in selected:
        if item.size and item.size > MAX_FILE_BYTES:
            raise ValueError("Размер одного файла не должен превышать 10 МБ.")
    pending = []
    total = sum(item.get("size", 0) for item in existing)
    for item in selected:
        content = item.bytes
        if not web and item.path:
            with Path(item.path).open("rb") as source:
                content = source.read(MAX_FILE_BYTES + 1)
        attachment = make_attachment(item.name, content)
        total += attachment["size"]
        if total > MAX_TASK_BYTES:
            raise ValueError("Общий размер вложений дела не должен превышать 20 МБ.")
        pending.append(attachment)
    return pending


def attachment_controls(libs, attachments, on_remove=None):
    page = libs.page

    async def download(attachment):
        try:
            content = attachment_bytes(attachment)
            path = await file_picker(page).save_file(
                dialog_title="Сохранить вложение",
                file_name=attachment_name(attachment.get("name")),
                src_bytes=content,
            )
            # Mobile and browser clients save the supplied bytes themselves.
            if path and not page.web and not page.platform.is_mobile():
                Path(path).write_bytes(content)
        except (OSError, ValueError, RuntimeError) as error:
            libs.open_dialog("Не удалось скачать файл", str(error), page)

    def preview(attachment):
        try:
            content = image_preview(attachment)
        except (OSError, ValueError, SyntaxError) as error:
            libs.open_dialog("Не удалось открыть изображение", str(error), page)
            return
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(attachment.get("name", "Изображение"), no_wrap=False),
            content=ft.Container(
                content=ft.Image(src=content, fit=ft.BoxFit.CONTAIN),
                width=min(900, max(200, (page.width or 360) - 80)),
                height=max(150, min(650, (page.height or 800) - 220)),
            ),
            actions=[
                ft.TextButton("Скачать", style=ft.ButtonStyle(color=libs.TxtColor),
                              on_click=lambda _: page.run_task(download, attachment)),
                ft.TextButton("Закрыть", style=ft.ButtonStyle(color=libs.TxtColor),
                              on_click=lambda _: page.pop_dialog()),
            ],
        ))

    rows = []
    for attachment in attachments or []:
        buttons = []
        if attachment.get("is_image"):
            buttons.append(ft.IconButton(
                icon=ft.Icons.VISIBILITY_OUTLINED, tooltip="Показать изображение",
                icon_color=libs.FletIconColor,
                on_click=lambda _, a=attachment: preview(a),
            ))
        buttons.append(ft.IconButton(
            icon=ft.Icons.DOWNLOAD_ROUNDED, tooltip="Скачать файл",
            icon_color=libs.FletIconColor,
            on_click=lambda _, a=attachment: page.run_task(download, a),
        ))
        if on_remove is not None:
            buttons.append(ft.IconButton(
                icon=ft.Icons.CLOSE_ROUNDED, tooltip="Убрать вложение",
                icon_color=libs.FletIconColor,
                on_click=lambda _, a=attachment: on_remove(a),
            ))
        rows.append(ft.Row([
            ft.Text(attachment.get("name", "Файл"), expand=True, no_wrap=False,
                    size=libs.text_size(13), color=libs.TxtColor),
            ft.Row(buttons, spacing=0, tight=True),
        ], spacing=4))
    return ft.Column(rows, spacing=2, tight=True, visible=bool(rows))


class AttachmentEditor:
    def __init__(self, libs, attachments=None, *, back=None, task_id=None, section="tasks"):
        self.libs = libs
        self.back = back
        self.task_id = task_id
        self.section = section
        self.attachments = deepcopy(attachments or [])
        self.error = ft.Text("", color=ft.Colors.RED_400, visible=False,
                             size=libs.text_size(12))
        self.files = attachment_controls(libs, self.attachments, self.remove)
        self.add = ft.TextButton("Прикрепить файлы", icon=ft.Icons.ATTACH_FILE_ROUNDED,
                                 icon_color=libs.FletIconColor,
                                 style=ft.ButtonStyle(color=libs.TxtColor),
                                 tooltip="До 10 МБ на файл и до 20 МБ на дело",
                                 on_click=self.pick)
        self.limit = ft.Text("Общий лимит вложений аккаунта — 10 МБ",
                             size=libs.text_size(12), color=libs.TxtColor, visible=False)
        self.control = ft.Column([self.add, self.files, self.error, self.limit], spacing=4)
        self.refresh()

    def values(self):
        return deepcopy(self.attachments)

    def reset(self):
        self.attachments = []
        self.error.visible = False
        self.refresh()

    def refresh(self):
        self.limit.visible = self.back is not None and self.back.is_authenticated()
        self.add.tooltip = (
            "Общий объём вложений аккаунта — до 10 МБ"
            if self.limit.visible
            else "До 10 МБ на файл и до 20 МБ на дело"
        )
        self.files.controls = attachment_controls(
            self.libs, self.attachments, self.remove,
        ).controls
        self.files.visible = bool(self.attachments)

    def remove(self, attachment):
        self.attachments.remove(attachment)
        self.error.visible = False
        self.refresh()
        self.libs.page.update()

    async def pick(self, _):
        if self.add.disabled:
            return
        self.add.disabled = True
        self.error.visible = False
        self.libs.page.update()
        try:
            selected = await file_picker(self.libs.page).pick_files(
                dialog_title="Прикрепить файлы к делу", allow_multiple=True,
                # Native paths are readable by Python. Sending file bytes through
                # Flet first can stall/disconnect the client before size validation.
                with_data=self.libs.page.web,
            )
            if not selected:
                return
            pending = await asyncio.to_thread(
                prepare_attachments, selected, self.values(), web=self.libs.page.web,
            )
            if self.back is not None:
                self.back.validate_attachment_selection(
                    self.attachments + pending, self.task_id, self.section,
                )
            self.attachments.extend(pending)
            self.refresh()
        except (OSError, ValueError, RuntimeError) as error:
            self.error.value = str(error)
            self.error.visible = True
        finally:
            self.add.disabled = False
            self.libs.page.update()
