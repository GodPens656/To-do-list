"""Inline web links in task and note text."""

import re
from urllib.parse import urlsplit

import flet as ft


_URL = re.compile(r"(?<![\w@])(?:https?://|www\.)[^\s<>\"'«»]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?…"
_CLOSING_BRACKETS = {")": "(", "]": "[", "}": "{"}


def _link_end(candidate):
    """Leave sentence punctuation outside the link, keeping balanced brackets."""
    end = len(candidate)
    while end:
        last = candidate[end - 1]
        if last in _TRAILING_PUNCTUATION:
            end -= 1
        elif last in _CLOSING_BRACKETS and (
            candidate[:end].count(last) > candidate[:end].count(_CLOSING_BRACKETS[last])
        ):
            end -= 1
        else:
            break
    return end


def _url_launcher(page):
    launcher = getattr(page, "_nd_url_launcher", None)
    if not isinstance(launcher, ft.UrlLauncher):
        launcher = ft.UrlLauncher()
        page.services.append(launcher)
        page._nd_url_launcher = launcher
        page.update()
    return launcher


def linked_text(value, *, page=None, web=False, dark=False, **kwargs):
    """Keep plain text intact; make HTTP(S)/www links blue and clickable."""
    value = str(value)
    spans = []
    offset = 0
    for match in _URL.finditer(value):
        label = match.group()[:_link_end(match.group())]
        url = "https://" + label if label.lower().startswith("www.") else label
        try:
            if not urlsplit(url).hostname:
                continue
        except ValueError:
            continue
        if offset < match.start():
            spans.append(ft.TextSpan(value[offset:match.start()]))
        span = ft.TextSpan(
            label, style=ft.TextStyle(color="#60A5FA" if dark else "#2563EB"),
        )
        if web or page is None:
            # Open directly during the click, avoiding popup blockers on the web.
            span.url = ft.Url(url, target=ft.UrlTarget.BLANK)
        else:
            async def open_link(_, target=url):
                await _url_launcher(page).launch_url(
                    target, mode=ft.LaunchMode.EXTERNAL_APPLICATION,
                )

            span.on_click = open_link
        spans.append(span)
        offset = match.start() + len(label)
    if not spans:
        return ft.Text(value, **kwargs)
    if offset < len(value):
        spans.append(ft.TextSpan(value[offset:]))
    return ft.Text(spans=spans, **kwargs)
