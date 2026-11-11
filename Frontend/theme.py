import flet as ft
import re
from .glass import configure_glass_theme, is_glass, is_toolbar_glass, mix_color
from .dayplanner import color_rgb, configure_widget_theme, contrast_color


THEME_STYLE_OPTIONS = (
    ("chatgpt", "Минималистичная (по умолчанию)"),
    ("improved", "Минималистичная (синяя)"),
    ("improved_green", "Минималистичная (зеленая)"),
    ("improved_purple", "Минималистичная (фиолетовая)"),
    ("nord", "Nord"),
    ("oled", "OLED"),
    ("oled_green", "OLED (зеленая)"),
)
THEME_STYLES = {key for key, _ in THEME_STYLE_OPTIONS}
THEME_EFFECT_OPTIONS = (
    ("none", "Нет"),
    ("liquid_glass", "Liquid glass"),
    ("liquid_glass_half", "Liquid glass 0,5x"),
)
THEME_EFFECTS = {key for key, _ in THEME_EFFECT_OPTIONS}


def theme_effect_options(phone=False):
    return tuple(option for option in THEME_EFFECT_OPTIONS
                 if not phone or option[0] != "liquid_glass")


THEME_COLORS = {
    "dark": {
        "BorderColor": "#fc8787ff",
        "ContBgColor": "#FF12121F",
        "BgColor": "#141424",
        "TxtColor": ft.Colors.WHITE,
        "BtnColor": "#5659f0",
        "ProgressColor": "#2196F3",
        "ProgressBgColor": "#000000",
        "LoadColor": "#141424",
        "DialogOverlayColor": "#141424",
        "WarnTextColor": ft.Colors.YELLOW_ACCENT,
        "WarnBgColor": "#2b260d",
        "WarnBorderColor": ft.Colors.YELLOW_ACCENT,
        "AlertOverlayColor": "#801111FF",
        "BtnBorderColor": "#7477ed"
    },
    "light": {
        "BorderColor": ft.Colors.DEEP_PURPLE_900,
        "ContBgColor": "#d9e8ff",
        "BgColor": ft.Colors.WHITE,
        "TxtColor": ft.Colors.BLACK,
        "BtnColor": "#829af5",
        "ProgressColor": "#2196F3",
        "ProgressBgColor": "#FFFFFF",
        "LoadColor": "#87aade",
        "DialogOverlayColor": "#141424",
        "WarnTextColor": "#FFb89900",
        "WarnBgColor": "#FFd4ca98",
        "WarnBorderColor": "#FFb89900",
        "AlertOverlayColor": "#801111FF",
        "BtnBorderColor": "#344791"
    },
    "chatgpt_dark": {
        "BorderColor": "#4A4A4A",
        "ContBgColor": "#2F2F2F",
        "BgColor": "#212121",
        "TxtColor": "#ECECEC",
        "BtnColor": "#3A3A3A",
        "ProgressColor": "#A6A6A6",
        "ProgressBgColor": "#424242",
        "LoadColor": "#2F2F2F",
        "DialogOverlayColor": "#212121",
        "WarnTextColor": "#F5C451",
        "WarnBgColor": "#3A3424",
        "WarnBorderColor": "#7A6936",
        "AlertOverlayColor": "#99000000",
        "BtnBorderColor": "#565656",
    },
    "chatgpt_light": {
        "BorderColor": "#D9D9E3",
        "ContBgColor": "#F9FAFC",
        "BgColor": "#FFFFFF",
        "TxtColor": "#0D0D0D",
        "BtnColor": "#F3F4F7",
        "ProgressColor": "#2563EB",
        "ProgressBgColor": "#DBEAFE",
        "LoadColor": "#F7F7F8",
        "DialogOverlayColor": "#FFFFFF",
        "WarnTextColor": "#8A6116",
        "WarnBgColor": "#FFF7DF",
        "WarnBorderColor": "#E5C66B",
        "AlertOverlayColor": "#66000000",
        "BtnBorderColor": "#C5C5D2",
    },
    "improved_dark": {
        "BorderColor": "#41506A",
        "ContBgColor": "#192233",
        "BgColor": "#101522",
        "TxtColor": "#EEF2FF",
        "BtnColor": "#293653",
        "ProgressColor": "#A5B4FC",
        "ProgressBgColor": "#2B354A",
        "LoadColor": "#192233",
        "DialogOverlayColor": "#101522",
        "WarnTextColor": "#F6CE80",
        "WarnBgColor": "#332B20",
        "WarnBorderColor": "#8A6C39",
        "AlertOverlayColor": "#A6080C16",
        "BtnBorderColor": "#596A96",
    },
    "improved_light": {
        "BorderColor": "#7395CC",
        "ContBgColor": "#DFEAFC",
        "BgColor": "#F0F5FF",
        "TxtColor": "#172B4D",
        "BtnColor": "#BDD3F7",
        "ProgressColor": "#2457C5",
        "ProgressBgColor": "#C5D7F2",
        "LoadColor": "#DFEAFC",
        "DialogOverlayColor": "#F0F5FF",
        "WarnTextColor": "#895B16",
        "WarnBgColor": "#FFF5DF",
        "WarnBorderColor": "#D7B66F",
        "AlertOverlayColor": "#66101522",
        "BtnBorderColor": "#5A80BE",
    },
    "improved_green_dark": {
        "BorderColor": "#3D5A50",
        "ContBgColor": "#182B24",
        "BgColor": "#101C17",
        "TxtColor": "#ECF7F0",
        "BtnColor": "#254638",
        "ProgressColor": "#6EE7B7",
        "ProgressBgColor": "#2A4036",
        "LoadColor": "#182B24",
        "DialogOverlayColor": "#101C17",
        "WarnTextColor": "#F6CE80",
        "WarnBgColor": "#332B20",
        "WarnBorderColor": "#8A6C39",
        "AlertOverlayColor": "#A608120D",
        "BtnBorderColor": "#527D69",
    },
    "improved_green_light": {
        "BorderColor": "#6FA98A",
        "ContBgColor": "#DCF0E3",
        "BgColor": "#EFF9F2",
        "TxtColor": "#163828",
        "BtnColor": "#B4DFC5",
        "ProgressColor": "#047857",
        "ProgressBgColor": "#C0DECB",
        "LoadColor": "#DCF0E3",
        "DialogOverlayColor": "#EFF9F2",
        "WarnTextColor": "#895B16",
        "WarnBgColor": "#FFF5DF",
        "WarnBorderColor": "#D7B66F",
        "AlertOverlayColor": "#66101C17",
        "BtnBorderColor": "#4D926C",
    },
    "improved_purple_dark": {
        "BorderColor": "#46404F",
        "ContBgColor": "#211E27",
        "BgColor": "#17151C",
        "TxtColor": "#F1EEF5",
        "BtnColor": "#342B43",
        "ProgressColor": "#C4A7FF",
        "ProgressBgColor": "#393042",
        "LoadColor": "#211E27",
        "DialogOverlayColor": "#17151C",
        "WarnTextColor": "#F6CE80",
        "WarnBgColor": "#332B20",
        "WarnBorderColor": "#8A6C39",
        "AlertOverlayColor": "#A6100D16",
        "BtnBorderColor": "#655276",
    },
    "improved_purple_light": {
        "BorderColor": "#D9D2E3",
        "ContBgColor": "#FFFFFF",
        "BgColor": "#F7F5FA",
        "TxtColor": "#282332",
        "BtnColor": "#EDE5F8",
        "ProgressColor": "#7345B8",
        "ProgressBgColor": "#E8DFF2",
        "LoadColor": "#FFFFFF",
        "DialogOverlayColor": "#F7F5FA",
        "WarnTextColor": "#895B16",
        "WarnBgColor": "#FFF5DF",
        "WarnBorderColor": "#D7B66F",
        "AlertOverlayColor": "#6617151C",
        "BtnBorderColor": "#B4A0CD",
    },
    "nord_dark": {
        "BorderColor": "#4C566A",
        "ContBgColor": "#3B4252",
        "BgColor": "#2E3440",
        "TxtColor": "#ECEFF4",
        "BtnColor": "#5E81AC",
        "ProgressColor": "#88C0D0",
        "ProgressBgColor": "#434C5E",
        "LoadColor": "#3B4252",
        "DialogOverlayColor": "#2E3440",
        "WarnTextColor": "#EBCB8B",
        "WarnBgColor": "#4B4438",
        "WarnBorderColor": "#D08770",
        "AlertOverlayColor": "#99000000",
        "BtnBorderColor": "#81A1C1",
    },
    "nord_light": {
        "BorderColor": "#46688F",
        "ContBgColor": "#E3EDF9",
        "BgColor": "#F5F9FF",
        "TxtColor": "#1E2D43",
        "BtnColor": "#C3D9F2",
        "ProgressColor": "#315F99",
        "ProgressBgColor": "#D2E3F7",
        "LoadColor": "#E3EDF9",
        "DialogOverlayColor": "#F5F9FF",
        "WarnTextColor": "#8F5E00",
        "WarnBgColor": "#FFF4D6",
        "WarnBorderColor": "#D9A441",
        "AlertOverlayColor": "#66000000",
        "BtnBorderColor": "#3F6592",
    },
    "oled_dark": {
        "BorderColor": "#333333",
        "ContBgColor": "#101010",
        "BgColor": "#000000",
        "TxtColor": "#FFFFFF",
        "BtnColor": "#1A1A1A",
        "ProgressColor": "#3B82F6",
        "ProgressBgColor": "#202020",
        "LoadColor": "#080808",
        "DialogOverlayColor": "#000000",
        "WarnTextColor": "#FFD166",
        "WarnBgColor": "#2B2208",
        "WarnBorderColor": "#A67C00",
        "AlertOverlayColor": "#B3000000",
        "BtnBorderColor": "#4A4A4A",
    },
    "oled_light": {
        "BorderColor": "#D1D5DB",
        "ContBgColor": "#F3F4F6",
        "BgColor": "#FFFFFF",
        "TxtColor": "#111111",
        "BtnColor": "#E5E7EB",
        "ProgressColor": "#2563EB",
        "ProgressBgColor": "#E5E7EB",
        "LoadColor": "#F9FAFB",
        "DialogOverlayColor": "#FFFFFF",
        "WarnTextColor": "#8A5600",
        "WarnBgColor": "#FFF4D6",
        "WarnBorderColor": "#D69E2E",
        "AlertOverlayColor": "#66000000",
        "BtnBorderColor": "#9CA3AF",
    },
}

THEME_COLORS.update({
    "liquid_glass_dark": {
        "BorderColor": "#557F9DBD", "ContBgColor": "#34425B7C",
        "BgColor": "#142337", "TxtColor": "#F0F5FF",
        "BtnColor": "#386A8AB8", "BtnBorderColor": "#557F9DBD",
        "ProgressColor": "#B1D8FF", "ProgressBgColor": "#305F86AE",
        "LoadColor": "#34425B7C", "DialogOverlayColor": "#D921334D",
        "WarnTextColor": "#FFE0A3", "WarnBgColor": "#405D4723",
        "WarnBorderColor": "#808D7346", "AlertOverlayColor": "#66050E21",
    },
    "liquid_glass_light": {
        "BorderColor": "#99FFFFFF", "ContBgColor": "#66FFFFFF",
        "BgColor": "#DCE8F5", "TxtColor": "#203553",
        "BtnColor": "#75FFFFFF", "BtnBorderColor": "#BBFFFFFF",
        "ProgressColor": "#3B69B0", "ProgressBgColor": "#406B8FBE",
        "LoadColor": "#66FFFFFF", "DialogOverlayColor": "#E6E6EFFA",
        "WarnTextColor": "#795012", "WarnBgColor": "#66FFF0CB",
        "WarnBorderColor": "#99C4A165", "AlertOverlayColor": "#3D263E62",
    },
    "oled_green_dark": {
        **THEME_COLORS["oled_dark"],
        "BtnColor": "#10251D",
        "ProgressColor": "#6EE7B7",
        "ProgressBgColor": "#19352A",
        "BtnBorderColor": "#385C4B",
    },
    "oled_green_light": {
        **THEME_COLORS["oled_light"],
        "BtnColor": "#E0F2E9",
        "ProgressColor": "#047857",
        "ProgressBgColor": "#D1EADF",
        "BtnBorderColor": "#8DBBA6",
    },
})

BUTTON_BACKGROUND_OPTIONS = (
    ("red", "Красный", ft.Colors.RED),
    ("pink", "Розовый", ft.Colors.PINK),
    ("purple", "Фиолетовый", ft.Colors.PURPLE),
    ("deep_purple", "Тёмно-фиолетовый", ft.Colors.DEEP_PURPLE),
    ("indigo", "Индиго", ft.Colors.INDIGO),
    ("blue", "Синий", ft.Colors.BLUE),
    ("light_blue", "Голубой", ft.Colors.LIGHT_BLUE),
    ("cyan", "Бирюзовый", ft.Colors.CYAN),
    ("teal", "Тёмно-бирюзовый", ft.Colors.TEAL),
    ("green", "Зелёный", ft.Colors.GREEN),
    ("light_green", "Светло-зелёный", ft.Colors.LIGHT_GREEN),
    ("lime", "Лаймовый", ft.Colors.LIME),
    ("yellow", "Жёлтый", ft.Colors.YELLOW),
    ("amber", "Янтарный", ft.Colors.AMBER),
    ("orange", "Оранжевый", ft.Colors.ORANGE),
    ("deep_orange", "Тёмно-оранжевый", ft.Colors.DEEP_ORANGE),
    ("brown", "Коричневый", ft.Colors.BROWN),
    ("blue_grey", "Серо-синий", ft.Colors.BLUE_GREY),
    ("grey", "Серый", ft.Colors.GREY),
    ("black", "Чёрный", ft.Colors.BLACK),
    ("white", "Белый", ft.Colors.WHITE),
)
BUTTON_BACKGROUND_COLORS = {
    key: color for key, _, color in BUTTON_BACKGROUND_OPTIONS
}
BUTTON_BACKGROUND_MODES = {
    "default",
    "custom",
    *BUTTON_BACKGROUND_COLORS,
}


def normalize_button_background_mode(value):
    return value if value in BUTTON_BACKGROUND_MODES else "default"


def normalize_custom_color(value, fallback="#5659F0"):
    color = str(value or "").strip().upper()
    if not color.startswith("#"):
        color = f"#{color}"
    # flet-color-pickers emits #AARRGGBB; button backgrounds are stored
    # without alpha because the picker has enable_alpha=False.
    if re.fullmatch(r"#[0-9A-F]{8}", color):
        color = f"#{color[-6:]}"
    return color if re.fullmatch(r"#[0-9A-F]{6}", color) else fallback


def resolve_button_color(theme, mode="default", custom_color="#5659F0"):
    mode = normalize_button_background_mode(mode)
    if mode == "custom":
        return normalize_custom_color(custom_color)
    if mode in BUTTON_BACKGROUND_COLORS:
        return BUTTON_BACKGROUND_COLORS[mode]
    # None means that both the button and accent colors come from the theme.
    return None


def _base_theme(theme):
    return str(theme).removeprefix("liquid_glass_half_").removeprefix("liquid_glass_")


def get_theme_colors(theme, button_color=None):
    base_theme = theme
    if is_glass(theme) and theme not in THEME_COLORS:
        base_theme = _base_theme(theme)
    colors = dict(THEME_COLORS.get(base_theme, THEME_COLORS["light"]))
    dark = str(theme).endswith("dark")
    colors.update({
        "InputBgColor": colors["BtnColor"],
        "MutedColor": ft.Colors.with_opacity(0.68, colors["TxtColor"]),
        "SoftBorderColor": ft.Colors.with_opacity(0.38, colors["BorderColor"]),
        "HoverColor": ft.Colors.with_opacity(0.08, colors["TxtColor"]),
        "DangerColor": "#F28B82" if dark else "#D64545",
        "SuccessColor": "#2E9E5B",
    })
    if _base_theme(theme).startswith("chatgpt_"):
        colors["DangerColor"] = "#F28B82" if dark else "#B42318"
        colors["SuccessColor"] = "#9BC5A5" if dark else "#28734A"
    if _base_theme(theme).startswith(("chatgpt_", "nord_")):
        # Keep settings icons readable over buttons, glass and wallpapers.
        colors["CategoryIconColor"] = colors["TxtColor"]
        colors["CategoryIconBgColor"] = mix_color(colors["BgColor"], colors["ProgressColor"], 0.18)
    if button_color is not None:
        colors["BtnColor"] = button_color
        colors["ProgressColor"] = button_color
    colors["PrimaryColor"] = colors["ProgressColor"]
    if button_color is not None:
        # Preserve the emphasis of primary actions when regular buttons also
        # use the selected accent. Reverse the shade near black/white so that
        # even the end points of the picker retain two distinct fills.
        target, fallback = ("#FFFFFF", "#000000") if dark else ("#000000", "#FFFFFF")
        primary = mix_color(button_color, target, 0.45)
        if max(abs(a - b) for a, b in zip(color_rgb(button_color), color_rgb(primary))) < 32:
            primary = mix_color(button_color, fallback, 0.25)
        colors["PrimaryColor"] = primary
        colors["CategoryIconColor"] = primary
        colors["CategoryIconBgColor"] = mix_color(
            "#161616" if dark else "#FFFFFF", button_color, 0.12,
        )
    elif is_glass(theme):
        # Opaque badges keep settings icons distinct from the wallpaper and
        # glass reflections, in both collapsed and expanded categories.
        icon = colors.get("CategoryIconColor", colors["PrimaryColor"]) if dark else colors["PrimaryColor"]
        colors["CategoryIconColor"] = mix_color(
            icon, "#FFFFFF" if dark else "#000000",
            0.30 if dark else 0.28,
        )
        colors["CategoryIconBgColor"] = mix_color(
            "#161616" if dark else "#FFFFFF", colors["ProgressColor"], 0.12,
        )
    colors.setdefault("CategoryIconColor", colors["ProgressColor"])
    colors.setdefault("CategoryIconBgColor", ft.Colors.with_opacity(0.18, colors["ProgressColor"]))
    if is_glass(theme):
        surface = colors["ContBgColor"]
        accent = colors["ProgressColor"]
        colors.update({
            "GlassEdgeColor": ft.Colors.with_opacity(0.30 if dark else 0.85, "#FFFFFF"),
            "GlassInputColor": ft.Colors.with_opacity(0.52 if dark else 0.65, surface),
            "GlassHoverColor": ft.Colors.with_opacity(0.20, accent),
            "GlassPressedColor": ft.Colors.with_opacity(0.30, accent),
            "GlassDisabledColor": ft.Colors.with_opacity(0.18, surface),
            "GlassPopupColor": ft.Colors.with_opacity(0.96, mix_color(surface, colors["BgColor"], 0.25)),
            "GlassButtonTint": None,
        })
        if button_color is not None:
            colors["GlassButtonTint"] = ft.Colors.with_opacity(0.30, button_color)
            if not is_toolbar_glass(theme):
                colors["BtnColor"] = colors["GlassButtonTint"]
    colors["ButtonTextColor"] = (
        colors["TxtColor"] if is_glass(theme) and not is_toolbar_glass(theme)
        else contrast_color(colors["BtnColor"])
    )
    return colors


def normalize_theme_style(value):
    """Возвращает поддерживаемый вариант оформления."""
    return value if value in THEME_STYLES else "chatgpt"


def normalize_theme_effect(value, *, phone=None):
    effect = value if value in THEME_EFFECTS else "none"
    if phone is True and effect == "liquid_glass":
        return "liquid_glass_half"
    return effect


def resolve_theme(theme_style, platform_brightness, effect="none"):
    """Объединяет выбранный стиль с системной светлой/тёмной схемой."""
    brightness = str(platform_brightness).lower()
    brightness = "dark" if brightness.endswith("dark") else "light"
    style = normalize_theme_style(theme_style)
    effect = normalize_theme_effect(effect)
    if effect != "none":
        return f"{effect}_{style}_{brightness}"
    return f"{style}_{brightness}"


def build_flet_theme(theme, button_color=None):
    """Настраивает стандартные контролы Flet в цветах выбранной палитры."""
    colors = get_theme_colors(theme, button_color)
    on_primary = contrast_color(colors["ProgressColor"])
    result = ft.Theme(
        use_material3=True,
        color_scheme=ft.ColorScheme(
            primary=colors["ProgressColor"],
            on_primary=on_primary,
            secondary=colors["ProgressColor"],
            surface=colors["BgColor"],
            on_surface=colors["TxtColor"],
            surface_container=colors["ContBgColor"],
            surface_container_high=colors["BtnColor"],
            outline=colors["BorderColor"],
        ),
        scaffold_bgcolor=colors["BgColor"],
        canvas_color=colors["BgColor"],
        card_bgcolor=colors["ContBgColor"],
        divider_color=colors["BorderColor"],
        dropdown_theme=ft.DropdownTheme(
            text_style=ft.TextStyle(color=colors["TxtColor"]),
        ),
    )
    configure_widget_theme(result, colors)
    return configure_glass_theme(result, theme, colors)
