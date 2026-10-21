"""Attachment editor and shared preview/download buttons."""

import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import flet as ft

from Backend.attachments import (
    MAX_FILE_BYTES, MAX_TASK_BYTES, attachment_bytes, attachment_name,
    image_preview, make_attachment,
)
from Backend.clipboard import (
    clipboard_export_path, clipboard_image_png, copy_windows_image, desktop_clipboard_image,
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


def clipboard(page):
    service = getattr(page, "_nd_attachment_clipboard", None)
    if not isinstance(service, ft.Clipboard):
        service = page._nd_attachment_clipboard = ft.Clipboard()
        if service not in page.services:
            page.services.append(service)
        page.update()
    return service


def prepare_clipboard_files(paths, existing):
    selected = []
    for value in paths:
        path = Path(value)
        if not path.is_file():
            raise ValueError("Из буфера можно прикрепить только файлы, не папки.")
        selected.append(SimpleNamespace(name=path.name, path=str(path), size=path.stat().st_size, bytes=None))
    return prepare_attachments(selected, existing, web=False)


async def copy_attachment(libs, attachment):
    page = libs.page
    if not page.web and not page.platform.is_mobile():
        path = await asyncio.to_thread(clipboard_export_path, attachment)
        if attachment.get("is_image") and page.platform == ft.PagePlatform.WINDOWS:
            await asyncio.to_thread(copy_windows_image, attachment, path)
        elif not await clipboard(page).set_files([path]):
            raise RuntimeError("Не удалось скопировать файл в буфер обмена.")
    else:
        # Browser/mobile clipboard APIs accept image data, not arbitrary file objects.
        if not attachment.get("is_image"):
            raise ValueError("Копирование файлов в буфер доступно в приложении для ПК.")
        content = await asyncio.to_thread(clipboard_image_png, attachment)
        await clipboard(page).set_image(content)


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
            raise ValueError("Общий размер вложений одной записи не должен превышать 20 МБ.")
        pending.append(attachment)
    return pending


def attachment_controls(libs, attachments, on_remove=None):
    page = libs.page
    copied = ft.Text("", color=libs.TxtColor, size=libs.text_size(12), visible=False)

    async def copy(attachment, status=None):
        status = copied if status is None else status
        try:
            await copy_attachment(libs, attachment)
            status.value = "Файл скопирован в буфер обмена"
            status.color = libs.TxtColor
        except (OSError, ValueError, RuntimeError, NotImplementedError) as error:
            status.value = f"Не удалось скопировать файл: {error}"
            status.color = ft.Colors.RED_400
        status.visible = True
        page.update()

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
        preview_width = min(900, max(200, (page.width or 360) - 80))
        preview_height = max(150, min(650, (page.height or 800) - (340 if libs.phone else 220)))
        image = ft.Image(src=content, fit=ft.BoxFit.CONTAIN,
                         width=preview_width, height=preview_height)
        # Leave alignment unset: Flet 0.82 forwards it without decoding.
        viewer = ft.InteractiveViewer(
            content=image, expand=True,
            min_scale=0.25, max_scale=8,
            boundary_margin=max(preview_width, preview_height) * 2,
            trackpad_scroll_causes_scale=True,
        )

        async def zoom_in(_):
            await viewer.zoom(1.25)

        async def zoom_out(_):
            await viewer.zoom(1 / 1.25)

        async def fit_image(_):
            await viewer.reset()

        zoom_controls = ft.Row([
            ft.IconButton(ft.Icons.ZOOM_OUT_ROUNDED, tooltip="Уменьшить",
                          icon_color=libs.FletIconColor, on_click=zoom_out),
            ft.TextButton("Сбросить положение", tooltip="Сбросить масштаб и положение",
                          style=ft.ButtonStyle(color=libs.TxtColor), on_click=fit_image),
            ft.IconButton(ft.Icons.ZOOM_IN_ROUNDED, tooltip="Увеличить",
                          icon_color=libs.FletIconColor, on_click=zoom_in),
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=4)
        zoom_hint = ft.Text(
            "Масштаб — двумя пальцами. Фото можно перетаскивать." if libs.phone else
            "Масштаб — колёсиком мыши. Фото можно перетаскивать.",
            size=libs.text_size(12), color=libs.TxtColor, text_align=ft.TextAlign.CENTER,
        )
        preview_status = ft.Text("", color=libs.TxtColor, size=libs.text_size(12), visible=False)
        turns = 0

        async def rotate(_):
            nonlocal turns
            if rotate_button.disabled:
                return
            rotate_button.disabled = True
            page.update()
            try:
                rotated = await asyncio.to_thread(image_preview, attachment, (turns + 1) % 4)
                image.src = rotated
                turns = (turns + 1) % 4
            except (OSError, ValueError, SyntaxError) as error:
                libs.open_dialog("Не удалось повернуть изображение", str(error), page)
            finally:
                rotate_button.disabled = False
                page.update()

        rotate_button = ft.TextButton("Повернуть на 90°", icon=ft.Icons.ROTATE_RIGHT_ROUNDED,
                                      style=ft.ButtonStyle(color=libs.TxtColor), on_click=rotate)
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(attachment.get("name", "Изображение"), no_wrap=False),
            content=ft.Container(
                content=ft.Column([viewer, preview_status, zoom_controls, zoom_hint], spacing=4),
                width=preview_width,
                height=preview_height,
            ),
            actions=[
                rotate_button,
                ft.TextButton("В буфер обмена", icon=ft.Icons.COPY_ROUNDED,
                              style=ft.ButtonStyle(color=libs.TxtColor),
                              on_click=lambda _: page.run_task(copy, attachment, preview_status)),
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
        if attachment.get("is_image") or (not page.web and not libs.phone):
            buttons.append(ft.IconButton(
                icon=ft.Icons.COPY_ROUNDED, tooltip="Скопировать файл в буфер обмена",
                icon_color=libs.FletIconColor,
                on_click=lambda _, a=attachment: page.run_task(copy, a),
            ))
        if on_remove is not None:
            buttons.append(ft.IconButton(
                icon=ft.Icons.CLOSE_ROUNDED, tooltip="Убрать вложение",
                icon_color=libs.FletIconColor,
                on_click=lambda _, a=attachment: on_remove(a),
            ))
        name = ft.Text(attachment.get("name", "Файл"), no_wrap=False,
                       size=libs.text_size(13), color=libs.TxtColor)
        actions = ft.Row(buttons, spacing=0, tight=True)
        if libs.phone:
            name.expand = True
            rows.append(ft.Row([name, actions], spacing=4))
        else:
            # Keep desktop actions directly under the filename, at the left edge.
            rows.append(ft.Column([name, actions], spacing=0, tight=True))
    return ft.Column([*rows, copied], spacing=2, tight=True, visible=bool(rows))


class AttachmentEditor:
    def __init__(self, libs, attachments=None, *, back=None, task_id=None, section="tasks", group_id=None):
        self.libs = libs
        self.back = back
        self.task_id = task_id
        self.section = section
        self.group_id = group_id
        self.item_label = "заметку" if section == "notes" else "дело"
        self.attachments = deepcopy(attachments or [])
        self.error = ft.Text("", color=ft.Colors.RED_400, visible=False,
                             size=libs.text_size(12))
        self.files = attachment_controls(libs, self.attachments, self.remove)
        self.add = ft.TextButton("Прикрепить файлы", icon=ft.Icons.ATTACH_FILE_ROUNDED,
                                 icon_color=libs.FletIconColor,
                                 style=ft.ButtonStyle(color=libs.TxtColor),
                                 tooltip=f"До 10 МБ на файл и до 20 МБ на {self.item_label}",
                                 on_click=self.pick)
        self.paste_button = ft.TextButton("Вставить из буфера", icon=ft.Icons.CONTENT_PASTE_ROUNDED,
                                         icon_color=libs.FletIconColor,
                                         style=ft.ButtonStyle(color=libs.TxtColor), on_click=self.paste,
                                         tooltip="Вставить файлы или изображение из буфера обмена (Ctrl+V)")
        self.limit = ft.Text("Общий лимит вложений аккаунта — 10 МБ",
                             size=libs.text_size(12), color=libs.TxtColor, visible=False)
        self.control = ft.Column([self.add, self.files, self.error, self.limit, self.paste_button],
                                 spacing=4, data=self)
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
            else f"До 10 МБ на файл и до 20 МБ на {self.item_label}"
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

    def _accept(self, pending):
        if self.back is not None:
            kwargs = {"group_id": self.group_id} if self.section == "notes" else {}
            self.back.validate_attachment_selection(
                self.attachments + pending, self.task_id, self.section, **kwargs,
            )
        self.attachments.extend(pending)
        self.refresh()

    async def paste(self, _, quiet=False):
        if self.add.disabled or self.paste_button.disabled:
            return
        self.add.disabled = self.paste_button.disabled = True
        self.error.visible = False
        page = self.libs.page
        page.update()
        try:
            service = clipboard(page)
            desktop = not page.web and not page.platform.is_mobile()
            paths = await service.get_files() if desktop else []
            if paths:
                pending = await asyncio.to_thread(prepare_clipboard_files, paths, self.values())
            else:
                content = (await asyncio.to_thread(desktop_clipboard_image) if desktop
                           else await service.get_image())
                if not content:
                    if not quiet:
                        raise ValueError("В буфере обмена нет файлов или изображения.")
                    return
                selected = [SimpleNamespace(name="Изображение из буфера.png", bytes=content,
                                            path=None, size=len(content))]
                pending = await asyncio.to_thread(prepare_attachments, selected, self.values(), web=True)
            self._accept(pending)
        except (OSError, ValueError, RuntimeError, NotImplementedError) as error:
            self.error.value = str(error)
            self.error.visible = True
        finally:
            self.add.disabled = self.paste_button.disabled = False
            page.update()

    async def pick(self, _):
        if self.add.disabled:
            return
        self.add.disabled = self.paste_button.disabled = True
        self.error.visible = False
        self.libs.page.update()
        try:
            selected = await file_picker(self.libs.page).pick_files(
                dialog_title="Прикрепить файлы к заметке" if self.section == "notes" else "Прикрепить файлы к делу",
                allow_multiple=True,
                # Native paths are readable by Python. Sending file bytes through
                # Flet first can stall/disconnect the client before size validation.
                with_data=self.libs.page.web,
            )
            if not selected:
                return
            pending = await asyncio.to_thread(
                prepare_attachments, selected, self.values(), web=self.libs.page.web,
            )
            self._accept(pending)
        except (OSError, ValueError, RuntimeError) as error:
            self.error.value = str(error)
            self.error.visible = True
        finally:
            self.add.disabled = self.paste_button.disabled = False
            self.libs.page.update()
