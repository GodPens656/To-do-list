"""Shared, per-page typography settings (including offline font assets)."""

import flet as ft


FONT_FAMILY_OPTIONS = (
    ("default", "Системный (по умолчанию)"),
    ("PT Sans", "PT Sans"),
    ("PT Serif", "PT Serif"),
    ("Ubuntu", "Ubuntu"),
)
FONT_ASSETS = {
    "PT Sans": "fonts/PTSans-Regular.ttf",
    "PT Serif": "fonts/PTSerif-Regular.ttf",
    "Ubuntu": "fonts/Ubuntu-Regular.ttf",
}
FONT_SIZE_OPTIONS = (
    ("small", "Маленький"),
    ("medium", "Средний"),
    ("large", "Большой"),
)
FONT_SCALES = {"small": 0.85, "medium": 1.0, "large": 1.2}


def normalize_font_family(value):
    return value if isinstance(value, str) and value in FONT_ASSETS else "default"


def normalize_font_size(value):
    return value if isinstance(value, str) and value in FONT_SCALES else "medium"


def scaled_text_size(page, size):
    preference = normalize_font_size(getattr(page, "_nd_font_size", "medium"))
    return round(size * FONT_SCALES[preference], 2)


def apply_typography(page, theme, family, size):
    """Style implicit Material text; explicit control sizes use scaled_text_size."""
    page.fonts = {
        name: f"/{path}" if getattr(page, "web", False) else path
        for name, path in FONT_ASSETS.items()
    }
    page._nd_font_size = normalize_font_size(size)
    family = normalize_font_family(family)
    theme.font_family = None if family == "default" else family
    slots = {
        "display_large": 57, "display_medium": 45, "display_small": 36,
        "headline_large": 32, "headline_medium": 28, "headline_small": 24,
        "title_large": 22, "title_medium": 16, "title_small": 14,
        "body_large": 16, "body_medium": 14, "body_small": 12,
        "label_large": 14, "label_medium": 12, "label_small": 11,
    }
    # Set colors explicitly so implicit text does not inherit a light foreground
    # from Material defaults when the app uses a light custom palette.
    scheme = theme.color_scheme
    def text_theme(color):
        return ft.TextTheme(**{
            name: ft.TextStyle(size=scaled_text_size(page, base), color=color)
            for name, base in slots.items()
        })

    theme.text_theme = text_theme(scheme.on_surface if scheme else None)
    theme.primary_text_theme = text_theme(scheme.on_primary if scheme else None)
