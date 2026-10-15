"""Portable file attachments stored inside the task's encrypted JSON section."""

import base64
import binascii
from io import BytesIO
import uuid

from PIL import Image, UnidentifiedImageError


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TASK_BYTES = 20 * 1024 * 1024
MAX_ACCOUNT_BYTES = 10 * 1024 * 1024


class AttachmentQuotaError(ValueError):
    pass


def attachment_usage(data):
    """Count original bytes; generated tasks can reference the same attachment."""
    seen = set()
    total = 0
    for section in ("tasks", "repeat_tasks", "postponed"):
        for task in data.get(section, []):
            for attachment in task.get("attachments") or []:
                content = attachment.get("content", "")
                key = (attachment.get("id"), content)
                if key in seen:
                    continue
                seen.add(key)
                # Count the actual payload, independently of the stored size field.
                total += len(content) * 3 // 4 - (len(content) - len(content.rstrip("=")))
    return total


def validate_account_quota(previous, data):
    usage = attachment_usage(data)
    # Existing oversized accounts can still edit tasks and remove attachments.
    if usage > MAX_ACCOUNT_BYTES and usage > attachment_usage(previous):
        raise AttachmentQuotaError(
            "Общий объём вложений аккаунта не должен превышать 10 МБ. "
            "Удалите ненужные вложения или выберите файлы меньшего размера."
        )


def attachment_name(name):
    name = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if ord(c) >= 32).strip()
    return name if name not in ("", ".", "..") else "file"


def make_attachment(name, content):
    if not isinstance(content, bytes):
        raise ValueError("Не удалось прочитать файл.")
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("Размер одного файла не должен превышать 10 МБ.")
    is_image = False
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
        is_image = True
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        pass
    return {
        "id": uuid.uuid4().hex,
        "name": attachment_name(name),
        "size": len(content),
        "is_image": is_image,
        "content": base64.b64encode(content).decode("ascii"),
    }


def attachment_bytes(attachment):
    try:
        return base64.b64decode(attachment["content"], validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error) as error:
        raise ValueError("Содержимое вложения повреждено.") from error


def image_preview(attachment):
    """Render even TIFFs as a bounded PNG; downloads retain the original bytes."""
    with Image.open(BytesIO(attachment_bytes(attachment))) as img:
        img.thumbnail((1600, 1600))
        preview = BytesIO()
        img.convert("RGBA").save(preview, format="PNG")
        return preview.getvalue()
