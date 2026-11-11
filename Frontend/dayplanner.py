"""DayPlanner's shared widget geometry and Material surfaces for Flet.

Reference: MixiYT/dayplanner, build/dayplanner-pc/app/ui/style.css,
commit f00d95ff082d033a98f5157972c466e7e6149be1 (MIT).
The existing palette, font settings and event handlers remain page-local.
"""

from copy import copy

import flet as ft

from .controls import SurfaceHost


CARD_RADIUS = 26
FIELD_RADIUS = 12
SHEET_RADIUS = 28
PILL_RADIUS = 999


def color_rgb(color):
    """Resolve the named accents and RGB/ARGB colors used by Flet."""
    named = {
        "red": "F44336", "pink": "E91E63", "purple": "9C27B0",
        "deeppurple": "673AB7", "indigo": "3F51B5", "blue": "2196F3",
        "lightblue": "03A9F4", "cyan": "00BCD4", "teal": "009688",
        "green": "4CAF50", "lightgreen": "8BC34A", "lime": "CDDC39",
        "yellow": "FFEB3B", "amber": "FFC107", "orange": "FF9800",
        "deeporange": "FF5722", "brown": "795548", "bluegrey": "607D8B",
        "grey": "9E9E9E", "black": "000000", "white": "FFFFFF",
    }
    value = str(getattr(color, "value", color)).split(",", 1)[0].lstrip("#")
    value = named.get(value.lower(), value)[-6:]
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix_color(first, second, amount):
    """Mix opaque RGB tints, including named accents and ARGB colors."""
    return "#" + "".join(
        f"{round(a * (1 - amount) + b * amount):02X}"
        for a, b in zip(color_rgb(first), color_rgb(second))
    )


def contrast_color(color):
    """Choose the same readable foreground as DayPlanner's accent selector."""
    try:
        rgb = [v / 255 for v in color_rgb(color)]
    except ValueError:
        return "#FFFFFF"
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    luminance = sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#161616" if luminance > 0.2 else "#FFFFFF"


def menu_style(colors):
    return ft.MenuStyle(
        bgcolor=colors["ContBgColor"], elevation=0,
        side=ft.BorderSide(1, colors["SoftBorderColor"]),
        shape=ft.RoundedRectangleBorder(radius=FIELD_RADIUS),
    )


def style_widget(item, theme, colors):
    """Skin a widget once, without replacing it or changing its live state."""
    signature = (theme, colors["BtnColor"], colors["ProgressColor"])
    if getattr(item, "_nd_planner_styled", None) == signature:
        return
    accent, text = colors["ProgressColor"], colors["TxtColor"]
    edge = ft.BorderSide(1, colors["SoftBorderColor"])

    if isinstance(item, (ft.TextField, ft.Dropdown)):
        item.border = ft.InputBorder.OUTLINE
        item.filled = True
        item.fill_color = colors["InputBgColor"]
        item.border_radius = FIELD_RADIUS
        item.border_width = 1
        item.border_color = colors["SoftBorderColor"]
        item.focused_border_color = accent
        item.focused_border_width = 2
        item.color = text
        item.label_style = ft.TextStyle(color=colors["MutedColor"])
        item.hint_style = ft.TextStyle(color=colors["MutedColor"])
        item.helper_style = ft.TextStyle(color=colors["MutedColor"])
        item.content_padding = ft.Padding.symmetric(horizontal=12, vertical=11)
        item.hover_color = colors["HoverColor"]
        if isinstance(item, ft.TextField):
            item.bgcolor = ft.Colors.TRANSPARENT
            item.cursor_color = accent
            item.selection_color = ft.Colors.with_opacity(0.24, accent)
        else:
            item.bgcolor = colors["ContBgColor"]
            item.elevation = 0
            item.menu_style = menu_style(colors)
    elif isinstance(item, (ft.Button, ft.TextButton, ft.IconButton)):
        # Floating glass actions have their own responsive dimensions/material.
        if not getattr(item, "_nd_glass_toolbar_action", False):
            style = copy(item.style) if item.style else ft.ButtonStyle()
            icon_only = isinstance(item, ft.IconButton) or isinstance(item.content, (ft.Icon, ft.Image))
            category = getattr(item, "_nd_planner_category", False)
            swatch = isinstance(style.shape, ft.CircleBorder)
            if not swatch:
                radius = getattr(item, "_nd_planner_corner_radius",
                                 FIELD_RADIUS if category else PILL_RADIUS)
                style.shape = ft.RoundedRectangleBorder(radius=radius)
            style.elevation = 0
            style.shadow_color = ft.Colors.TRANSPARENT
            style.overlay_color = {
                ft.ControlState.HOVERED: colors["HoverColor"],
                ft.ControlState.FOCUSED: ft.Colors.with_opacity(0.14, accent),
                ft.ControlState.PRESSED: ft.Colors.with_opacity(0.18, accent),
            }
            if not swatch:
                style.side = ft.BorderSide(0, ft.Colors.TRANSPARENT) if icon_only else edge
            if style.padding is None:
                style.padding = 8 if icon_only else ft.Padding.symmetric(horizontal=18, vertical=10)
            if getattr(item, "_nd_planner_primary", False):
                item.bgcolor = colors["PrimaryColor"]
                style.color = contrast_color(colors["PrimaryColor"])
                style.icon_color = style.color
                item.icon_color = style.color
                style.side = ft.BorderSide(0, ft.Colors.TRANSPARENT)
                if isinstance(item.content, (ft.Icon, ft.Image)):
                    item.content.color = style.color
            elif getattr(item, "bgcolor", None) == colors["BtnColor"]:
                foreground = colors["ButtonTextColor"]
                style.color = foreground
                style.icon_color = foreground
                item.icon_color = foreground
                if isinstance(item.content, (ft.Icon, ft.Image)):
                    item.content.color = foreground
                if category:
                    for label in item.content.controls:
                        if isinstance(label, (ft.Text, ft.Icon)):
                            label.color = foreground
            elif style.color is None:
                style.color = text
            item.style = style
            if not isinstance(item, ft.IconButton):
                item.elevation = 0
    elif isinstance(item, ft.Container):
        if (item.bgcolor in {colors["BgColor"], colors["ContBgColor"], colors["LoadColor"]}
                and item.border_radius is not None
                and not getattr(item, "_nd_glass_material", False)
                and not getattr(item, "_nd_glass_toolbar", False)):
            item.border_radius = CARD_RADIUS
            item.border = ft.Border.all(1, colors["SoftBorderColor"])
    elif isinstance(item, ft.TabBar):
        # Flet 0.82 supports UnderlineTabIndicator; a thick rounded stroke
        # paints the selected capsule while preserving native tab semantics.
        item.indicator = ft.UnderlineTabIndicator(
            border_side=ft.BorderSide(32, accent),
            border_radius=16, insets=ft.Padding.only(left=3, right=3, bottom=4),
        )
        item.indicator_size = ft.TabBarIndicatorSize.TAB
        item.label_color = contrast_color(accent)
        item.unselected_label_color = colors["MutedColor"]
        item.divider_color = ft.Colors.TRANSPARENT
        item.divider_height = 0
        item.splash_border_radius = PILL_RADIUS
    elif isinstance(item, ft.ExpansionTile):
        side = item.shape.side if isinstance(item.shape, ft.RoundedRectangleBorder) else None
        item.shape = item.collapsed_shape = ft.RoundedRectangleBorder(radius=FIELD_RADIUS, side=side)
        if getattr(item, "_nd_planner_category", False):
            foreground = colors["ButtonTextColor"]
            item.collapsed_text_color = item.collapsed_icon_color = foreground
            item.text_color = item.icon_color = text
        else:
            item.icon_color = item.collapsed_icon_color = colors["MutedColor"]
    elif isinstance(item, ft.PopupMenuButton):
        item.bgcolor = colors["ContBgColor"]
        item.shape = ft.RoundedRectangleBorder(radius=FIELD_RADIUS, side=edge)
        item.elevation = 0
        item.icon_color = text
    elif isinstance(item, ft.AlertDialog):
        item.bgcolor = colors["ContBgColor"]
        item.shape = ft.RoundedRectangleBorder(radius=SHEET_RADIUS, side=edge)
        item.elevation = 0
        item.barrier_color = colors["AlertOverlayColor"]
    elif isinstance(item, (ft.Checkbox, ft.Switch)):
        item.adaptive = False
        if isinstance(item, ft.Checkbox):
            item.border_side = {
                ft.ControlState.SELECTED: ft.BorderSide(2, colors["SuccessColor"]),
                ft.ControlState.DEFAULT: ft.BorderSide(2, colors["MutedColor"]),
            }
    elif isinstance(item, ft.ProgressBar):
        item.border_radius = 3
    object.__setattr__(item, "_nd_planner_styled", signature)


class PlannerHost(SurfaceHost):
    """Style newly inserted controls at the same update boundary as glass."""

    def __init__(self, theme, colors, **kwargs):
        super().__init__(**kwargs)
        self._nd_planner_theme = theme
        self._nd_planner_colors = colors

    def before_update(self):
        super().before_update()
        if not self.is_isolated():
            from .glass import apply_glass
            apply_glass(self, self._nd_planner_theme, self._nd_planner_colors, recursive_hosts=False)


def configure_widget_theme(result, colors):
    """Cover Material controls that render their own menus, pickers and overlays."""
    accent, text, muted = (colors[k] for k in ("ProgressColor", "TxtColor", "MutedColor"))
    edge = ft.BorderSide(1, colors["SoftBorderColor"])
    pill = ft.RoundedRectangleBorder(radius=PILL_RADIUS)
    sheet = ft.RoundedRectangleBorder(radius=SHEET_RADIUS, side=edge)
    button = ft.ButtonStyle(
        shape=pill, elevation=0, bgcolor=colors["BtnColor"], color=colors["ButtonTextColor"],
        side=edge, overlay_color=colors["HoverColor"],
        padding=ft.Padding.symmetric(horizontal=18, vertical=10),
        text_style=ft.TextStyle(weight=ft.FontWeight.W_500),
    )
    result.button_theme = ft.ButtonTheme(style=button)
    result.outlined_button_theme = ft.OutlinedButtonTheme(style=button)
    result.text_button_theme = ft.TextButtonTheme(style=ft.ButtonStyle(
        shape=pill, color=accent, overlay_color=colors["HoverColor"], elevation=0,
    ))
    result.filled_button_theme = ft.FilledButtonTheme(style=ft.ButtonStyle(
        shape=pill, bgcolor=colors["PrimaryColor"],
        color=contrast_color(colors["PrimaryColor"]), elevation=0,
    ))
    result.icon_button_theme = ft.IconButtonTheme(style=ft.ButtonStyle(
        shape=pill, color=text, overlay_color=colors["HoverColor"], elevation=0,
    ))
    result.dropdown_theme.menu_style = menu_style(colors)
    result.checkbox_theme = ft.CheckboxTheme(
        shape=ft.CircleBorder(), check_color="#FFFFFF",
        fill_color={ft.ControlState.SELECTED: colors["SuccessColor"],
                    ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT},
        border_side=ft.BorderSide(2, muted),
        overlay_color=colors["HoverColor"],
    )
    result.switch_theme = ft.SwitchTheme(
        thumb_color={ft.ControlState.SELECTED: contrast_color(accent), ft.ControlState.DEFAULT: muted},
        track_color={ft.ControlState.SELECTED: accent, ft.ControlState.DEFAULT: colors["BtnColor"]},
        track_outline_color={ft.ControlState.SELECTED: accent, ft.ControlState.DEFAULT: muted},
    )
    result.slider_theme = ft.SliderTheme(
        active_track_color=accent, inactive_track_color=colors["ProgressBgColor"],
        thumb_color=accent, overlay_color=colors["HoverColor"], track_height=6,
        value_indicator_color=accent,
        value_indicator_text_style=ft.TextStyle(color=contrast_color(accent)),
    )
    result.radio_theme = ft.RadioTheme(fill_color={
        ft.ControlState.SELECTED: accent, ft.ControlState.DEFAULT: muted,
    }, overlay_color=colors["HoverColor"])
    result.progress_indicator_theme = ft.ProgressIndicatorTheme(
        color=accent, circular_track_color=colors["ProgressBgColor"],
        linear_track_color=colors["ProgressBgColor"], linear_min_height=6, border_radius=3,
    )
    result.scrollbar_theme = ft.ScrollbarTheme(
        thumb_color=ft.Colors.with_opacity(0.35, text),
        track_color=ft.Colors.TRANSPARENT, radius=8, thickness=4,
    )
    result.popup_menu_theme = ft.PopupMenuTheme(
        color=colors["ContBgColor"], elevation=0,
        shape=ft.RoundedRectangleBorder(radius=FIELD_RADIUS, side=edge), icon_color=text,
    )
    result.dialog_theme = ft.DialogTheme(
        bgcolor=colors["ContBgColor"], shape=sheet, elevation=0,
        barrier_color=colors["AlertOverlayColor"],
        title_text_style=ft.TextStyle(size=19, weight=ft.FontWeight.W_600, color=text),
        content_text_style=ft.TextStyle(size=16, color=text),
    )
    result.date_picker_theme = ft.DatePickerTheme(
        bgcolor=colors["ContBgColor"], header_bgcolor=colors["InputBgColor"],
        header_foreground_color=text, shape=sheet, elevation=0,
        cancel_button_style=button, confirm_button_style=button,
    )
    result.time_picker_theme = ft.TimePickerTheme(
        bgcolor=colors["ContBgColor"], dial_bgcolor=colors["InputBgColor"], dial_hand_color=accent,
        dial_text_color=text, hour_minute_color=colors["InputBgColor"], hour_minute_text_color=text,
        shape=sheet, elevation=0, cancel_button_style=button, confirm_button_style=button,
    )
    result.chip_theme = ft.ChipTheme(
        shape=pill, border_side=edge, bgcolor=colors["ContBgColor"],
        selected_color=accent, check_color=contrast_color(accent), elevation=0,
        label_text_style=ft.TextStyle(size=14, color=text),
    )
    result.snackbar_theme = ft.SnackBarTheme(
        bgcolor=text, shape=pill, elevation=0,
        content_text_style=ft.TextStyle(color=colors["BgColor"], size=14),
        action_text_color=colors["BgColor"],
    )
    result.tooltip_theme = ft.TooltipTheme(
        decoration=ft.BoxDecoration(bgcolor=text, border_radius=FIELD_RADIUS),
        text_style=ft.TextStyle(color=colors["BgColor"], size=12),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
    )
    return result
