import flet as ft
import re


THEME_STYLE_OPTIONS = (
    ("chatgpt", "Минималистичная (по умолчанию)"),
    ("improved", "Минималистичная (синяя)"),
    ("improved_green", "Минималистичная (зеленая)"),
    ("improved_purple", "Минималистичная (фиолетовая)"),
    ("classic", "Ранняя"),
    ("nord", "Nord"),
    ("oled", "OLED"),
    ("oled_green", "OLED (зеленая)"),
    ("oled_blue", "OLED (синяя)"),
)
THEME_STYLES = {key for key, _ in THEME_STYLE_OPTIONS}


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
        "ContBgColor": "#E3E3E8",
        "BgColor": "#FFFFFF",
        "TxtColor": "#0D0D0D",
        "BtnColor": "#ECECF1",
        "ProgressColor": "#A6A6A6",
        "ProgressBgColor": "#E5E5E5",
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
    "oled_blue_dark": {
        **THEME_COLORS["oled_dark"],
        "BtnColor": "#122139",
        "ProgressColor": "#60A5FA",
        "ProgressBgColor": "#1B304D",
        "BtnBorderColor": "#3D5679",
    },
    "oled_blue_light": {
        **THEME_COLORS["oled_light"],
        "BtnColor": "#E1ECFC",
        "ProgressColor": "#2563EB",
        "ProgressBgColor": "#D6E5FA",
        "BtnBorderColor": "#92AFD8",
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


def get_theme_colors(theme, button_color=None):
    colors = dict(THEME_COLORS.get(theme, THEME_COLORS["light"]))
    dark = str(theme).endswith("dark")
    colors.update({
        "MutedColor": ft.Colors.with_opacity(0.68, colors["TxtColor"]),
        "SoftBorderColor": ft.Colors.with_opacity(0.38, colors["BorderColor"]),
        "HoverColor": ft.Colors.with_opacity(0.08, colors["TxtColor"]),
        "DangerColor": "#F28B82" if dark else "#B42318",
        "SuccessColor": "#9BC5A5" if dark else "#28734A",
    })
    if button_color is not None:
        colors["BtnColor"] = button_color
        colors["ProgressColor"] = button_color
    return colors


def normalize_theme_style(value):
    """Возвращает поддерживаемый вариант оформления."""
    return value if value in THEME_STYLES else "chatgpt"


def resolve_theme(theme_style, platform_brightness):
    """Объединяет выбранный стиль с системной светлой/тёмной схемой."""
    brightness = str(platform_brightness).lower()
    brightness = "dark" if brightness.endswith("dark") else "light"
    style = normalize_theme_style(theme_style)
    return brightness if style == "classic" else f"{style}_{brightness}"


def build_flet_theme(theme, button_color=None):
    """Настраивает стандартные контролы Flet в цветах выбранной палитры."""
    colors = get_theme_colors(theme, button_color)
    dark_text_primary_themes = {
        "chatgpt_dark", "chatgpt_light", "improved_dark", "improved_green_dark",
        "nord_dark", "improved_purple_dark", "oled_green_dark", "oled_blue_dark",
    }
    on_primary = "#171717" if theme in dark_text_primary_themes else "#FFFFFF"
    switch_theme = None
    if theme == "chatgpt_light":
        switch_theme = ft.SwitchTheme(
            thumb_color={
                ft.ControlState.SELECTED: "#FFFFFF",
                ft.ControlState.DEFAULT: "#F7F8FC",
            },
            track_color={
                ft.ControlState.SELECTED: colors["ProgressColor"],
                ft.ControlState.DEFAULT: "#B7BBC8",
            },
            track_outline_color={
                ft.ControlState.SELECTED: colors["ProgressColor"],
                ft.ControlState.DEFAULT: "#858B9A",
            },
        )
    return ft.Theme(
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
        switch_theme=switch_theme,
    )
