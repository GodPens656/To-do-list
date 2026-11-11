"""Shared Liquid glass material, including controls added after navigation."""

from dataclasses import fields
from functools import lru_cache
from typing import Any, ForwardRef, get_args

import flet as ft

from .controls import SurfaceHost
from .dayplanner import PlannerHost, mix_color, style_widget


def is_glass(theme):
    return str(theme).startswith("liquid_glass_")


def is_toolbar_glass(theme):
    return str(theme).startswith("liquid_glass_half_")


@lru_cache(maxsize=64)
def _palette(theme):
    # Imported at call time because theme.py configures Material with this module.
    from .theme import get_theme_colors
    return get_theme_colors(theme)


def glass_background(theme):
    colors = _palette(theme)
    background, surface, accent = (colors[key] for key in ("BgColor", "ContBgColor", "ProgressColor"))
    return ft.LinearGradient(
        begin=ft.Alignment.TOP_LEFT,
        end=ft.Alignment.BOTTOM_RIGHT,
        colors=[background, mix_color(background, accent, 0.20),
                mix_color(background, surface, 0.65), mix_color(background, accent, 0.09)],
        stops=[0, 0.38, 0.72, 1],
    )


def glass_border(theme):
    # Flutter requires uniform border sides on rounded decorations.
    return ft.Border.all(1, _palette(theme)["GlassEdgeColor"])


def glass_gradient(theme, *, mobile=False, toolbar=False):
    dark = str(theme).endswith("dark")
    colors = _palette(theme)
    if mobile and toolbar and is_toolbar_glass(theme):
        # Narrow specular bands frame a clearer centre, like light refracting
        # through a curved lens. Keep this paint on the mobile capsule only.
        return ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=[
                ft.Colors.with_opacity(0.48 if dark else 0.98, "#FFFFFF"),
                ft.Colors.with_opacity(0.14 if dark else 0.46, "#FFFFFF"),
                ft.Colors.with_opacity(0.30 if dark else 0.72, "#FFFFFF"),
                ft.Colors.with_opacity(0.04 if dark else 0.16, "#FFFFFF"),
                ft.Colors.with_opacity(0.24, colors["ContBgColor"]),
                ft.Colors.with_opacity(0.18, colors["ProgressColor"]),
                ft.Colors.with_opacity(0.34 if dark else 0.76, "#FFFFFF"),
            ],
            stops=[0, 0.10, 0.18, 0.38, 0.62, 0.82, 1],
        )
    if mobile:
        return ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=[ft.Colors.with_opacity(0.14 if dark else 0.48, "#FFFFFF"),
                    ft.Colors.with_opacity(0.38, colors["ContBgColor"])],
        )
    return ft.LinearGradient(
        begin=ft.Alignment.TOP_LEFT,
        end=ft.Alignment.BOTTOM_RIGHT,
        colors=[
            ft.Colors.with_opacity(0.18 if dark else 0.68, "#FFFFFF"),
            ft.Colors.with_opacity(0.25, colors["ContBgColor"]),
            ft.Colors.with_opacity(0.10, colors["ProgressColor"]),
            ft.Colors.with_opacity(0.14 if dark else 0.45, colors["ContBgColor"]),
        ],
        stops=[0, 0.18, 0.72, 1],
    )


def glass_surface(container, theme, *, radius=None, compact=False, tint=None,
                  mobile=False, backdrop=False):
    """Apply the material in place, keeping layout, content and events intact."""
    dark = str(theme).endswith("dark")
    mobile_toolbar = (mobile and is_toolbar_glass(theme)
                      and getattr(container, "_nd_glass_toolbar", False))
    container.bgcolor = tint
    # A Flutter background gradient replaces the color shader. Keep semantic
    # tints as the background and paint the reflection in the foreground.
    container.gradient = (None if tint is not None else
                          glass_gradient(theme, mobile=mobile, toolbar=mobile_toolbar))
    container.border_radius = radius if radius is not None else (container.border_radius or 16)
    container.border = glass_border(theme)
    # Only outer panels sample the backdrop. Cards, badges and buttons reuse
    # that material with a gradient and border instead of another GPU filter.
    sigma = 5 if mobile else 6
    container.blur = ft.Blur(sigma, sigma) if backdrop else None
    # Rounded decorations already paint their own corners. Only filtered
    # panels need to clip their descendants; clipping every card/button adds
    # work while scrolling large lists.
    container.clip_behavior = ft.ClipBehavior.ANTI_ALIAS if backdrop else ft.ClipBehavior.NONE
    if mobile_toolbar:
        # Bevel and reflections give the half-glass capsule depth with paint
        # alone, keeping scrolling free of backdrop filters and extra controls.
        container.border = ft.Border.all(
            1.25, ft.Colors.with_opacity(0.66 if dark else 0.98, "#FFFFFF"))
        container.shadow = ft.BoxShadow(
            blur_radius=16, spread_radius=-3, offset=ft.Offset(0, 5),
            color="#40000000" if dark else "#22314D7B",
        )
        container.foreground_decoration = ft.BoxDecoration(
            border_radius=container.border_radius,
            border=ft.Border.all(0.75, "#70FFFFFF" if dark else "#E6FFFFFF"),
            gradient=ft.RadialGradient(
                center=ft.Alignment(-0.85, -0.95), radius=1.5,
                colors=[
                    "#34FFFFFF" if dark else "#4CFFFFFF",
                    "#06FFFFFF", "#00FFFFFF",
                    "#1AFFFFFF" if dark else "#2EFFFFFF",
                ],
                stops=[0, 0.30, 0.72, 1],
            ),
        )
        return container
    if mobile or not backdrop:
        container.shadow = None
        container.foreground_decoration = None
        return container
    container.shadow = ft.BoxShadow(
        blur_radius=8 if compact else 12, spread_radius=-3 if compact else -5,
        offset=ft.Offset(0, 2 if compact else 7),
        color="#38030918" if dark else "#18314D7B",
    )
    # An inner highlight gives rounded panels the bright lip of polished glass.
    container.foreground_decoration = ft.BoxDecoration(
        border_radius=container.border_radius,
        border=ft.Border.all(0.5, "#30FFFFFF" if dark else "#80FFFFFF"),
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
            colors=["#18FFFFFF", "#00FFFFFF", "#00FFFFFF", "#0CFFFFFF"],
            stops=[0, 0.16, 0.8, 1],
        ),
    )
    return container


def _light_glass_colors(colors):
    """Nearly opaque widget fills; the toolbar keeps its original material."""
    return {
        **colors,
        "GlassEdgeColor": colors["SoftBorderColor"],
        "GlassInputColor": mix_color(colors["ContBgColor"], "#FFFFFF", 0.025),
        "GlassPopupColor": mix_color(colors["ContBgColor"], colors["BgColor"], 0.08),
        "GlassHoverColor": colors["HoverColor"],
        "GlassPressedColor": ft.Colors.with_opacity(0.12, colors["ProgressColor"]),
    }


def _light_glass_surface(container, theme):
    """Paint a faint reflection without filters or extra controls."""
    if (container.bgcolor in (None, ft.Colors.TRANSPARENT)
            or not (container.border_radius or container.border)
            or container.foreground_decoration is not None):
        return
    # Foreground paint preserves alpha and semantic colors of badges, previews
    # and warning panels, including later changes to their background/border.
    container.foreground_decoration = ft.BoxDecoration(
        border_radius=container.border_radius,
        border=ft.Border.all(0.5, "#14FFFFFF" if str(theme).endswith("dark") else "#28FFFFFF"),
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
            colors=["#0AFFFFFF", "#00FFFFFF"],
        ),
    )


def glass_button_style(theme, colors, style=None, *, material=False):
    lightweight = is_toolbar_glass(theme)
    style = style or ft.ButtonStyle()
    style.bgcolor = {
        ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT if material else colors["BtnColor"],
        ft.ControlState.HOVERED: colors["GlassHoverColor"],
        ft.ControlState.FOCUSED: colors["GlassHoverColor"],
        ft.ControlState.PRESSED: colors["GlassPressedColor"],
        ft.ControlState.DISABLED: colors["GlassDisabledColor"],
    }
    style.side = ft.BorderSide(0 if material else (0.5 if lightweight else 1),
                               ft.Colors.TRANSPARENT if material else colors["GlassEdgeColor"])
    style.shadow_color = ft.Colors.TRANSPARENT if lightweight else "#22081832"
    style.elevation = 0 if lightweight else {ft.ControlState.DEFAULT: 0, ft.ControlState.HOVERED: 2}
    style.overlay_color = colors["HoverColor"]
    style.shape = style.shape or ft.RoundedRectangleBorder(radius=14)
    return style


def _compact_text_button_padding(padding):
    if padding is None:
        return ft.Padding.symmetric(horizontal=12, vertical=6)
    if isinstance(padding, (int, float)):
        padding = ft.Padding.all(padding)
    if isinstance(padding, ft.Padding):
        return ft.Padding(
            left=min(padding.left, 12), right=min(padding.right, 12),
            top=min(padding.top, 6), bottom=min(padding.bottom, 6),
        )
    return padding


def _button_material(button, theme, colors, *, mobile=False):
    """Put lightweight glass inside the button, preserving its identity/state.

    Keeping the original button in the tree matters: callers change its visible,
    disabled, content and width properties and keep references to its handlers.
    """
    icon_button = isinstance(button, ft.IconButton)
    slot = "icon" if icon_button else "content"
    content = getattr(button, slot)
    skin = getattr(button, "_nd_glass_skin", None)
    state = (button.width, button.height, button.disabled,
             button.icon_size if icon_button else None)
    if (skin is not None and content is skin
            and getattr(button, "_nd_glass_button_state", None) == state):
        return
    if content is not skin or skin is None:
        style = button.style or ft.ButtonStyle()
        text_button = (not icon_button and content is not None
                       and not isinstance(content, (ft.Icon, ft.Image)))
        if text_button:
            style.visual_density = ft.VisualDensity.COMPACT
        padding = getattr(button, "_nd_glass_padding", None)
        if padding is None:
            padding = button.padding if icon_button and button.padding is not None else style.padding
            if text_button:
                padding = _compact_text_button_padding(padding)
            if padding is None:
                padding = 8 if icon_button else ft.Padding.symmetric(horizontal=16, vertical=10)
            object.__setattr__(button, "_nd_glass_padding", padding)
        shape = style.shape
        radius = 100 if isinstance(shape, ft.CircleBorder) else getattr(shape, "radius", 14)
        if icon_button:
            content = content if isinstance(content, ft.Control) else ft.Icon(
                content, size=button.icon_size or 24,
                color=button.icon_color or colors["TxtColor"],
            )
            button.padding = 0
        else:
            if isinstance(content, str):
                content = ft.Text(content, style=style.text_style, color=style.color or colors["TxtColor"])
            if button.icon is not None:
                icon = button.icon if isinstance(button.icon, ft.Control) else ft.Icon(
                    button.icon, color=button.icon_color or colors["TxtColor"],
                    size=style.icon_size or 18,
                )
                content = ft.Row([icon, *([content] if content is not None else [])],
                                 spacing=8, tight=True, alignment=ft.MainAxisAlignment.CENTER)
                button.icon = None
        skin = ft.Container(content=content, padding=padding)
        object.__setattr__(skin, "_nd_glass_material", True)
        object.__setattr__(button, "_nd_glass_skin", skin)
        tint = getattr(button, "bgcolor", None)
        if tint in (None, ft.Colors.TRANSPARENT, colors["BtnColor"]):
            tint = colors.get("GlassButtonTint")
        glass_surface(skin, theme, radius=radius, compact=True, tint=tint, mobile=mobile)
        if isinstance(shape, ft.CircleBorder) and style.side is not None:
            skin.border = ft.Border.all(style.side.width, style.side.color)
        setattr(button, slot, skin)
        style.padding = 0
        button.style = glass_button_style(theme, colors, style, material=True)
        button.bgcolor = ft.Colors.TRANSPARENT
        if hasattr(button, "elevation"):
            button.elevation = 0
    # Explicit dimensions still belong to the button, including later changes.
    skin.width, skin.height = button.width, button.height
    if icon_button:
        skin.width = button.width or max(36, (button.icon_size or 24) + 16)
        skin.height = button.height or skin.width
    # Alignment on a width-less Container expands it to the Wrap's full width.
    skin.alignment = ft.Alignment.CENTER if skin.width is not None else None
    skin.opacity = 0.45 if button.disabled else 1
    object.__setattr__(button, "_nd_glass_button_state", state)


def _contains_controls(annotation):
    # Forward references and Any can contain custom controls. Concrete scalar
    # and style fields cannot, and need not be read on every UI update.
    if annotation is Any or isinstance(annotation, (str, ForwardRef)):
        return True
    if isinstance(annotation, type) and issubclass(annotation, ft.BaseControl):
        return True
    return any(_contains_controls(arg) for arg in get_args(annotation))


@lru_cache(maxsize=None)
def _child_fields(control_type):
    return tuple(field.name for field in fields(control_type)
                 if not field.name.startswith("_") and field.name != "data"
                 and not field.metadata.get("skip") and _contains_controls(field.type))


def apply_glass(control, theme, colors, *, mobile=False, recursive_hosts=True):
    """Style descendants without replacing controls or resetting their state.

    Explicit preparation traverses the whole tree. At Flet's update boundary,
    each nested host handles its own children exactly once.
    """
    glass = is_glass(theme)
    lightweight = is_toolbar_glass(theme)
    if lightweight:
        colors = _light_glass_colors(colors)
    seen = set()
    surface_colors = {colors[key] for key in (
        "BgColor", "ContBgColor", "BtnColor", "LoadColor", "WarnBgColor",
    )}

    def visit(item, in_backdrop, dialog_action=False):
        if not isinstance(item, ft.BaseControl) or id(item) in seen:
            return
        seen.add(id(item))
        style_widget(item, theme, colors)
        # A nested GlassHost may be updated independently by Flet later. Keep
        # its inherited material context so new children do not add filters.
        object.__setattr__(item, "_nd_glass_in_backdrop", in_backdrop)
        dialog_action = dialog_action or getattr(item, "_nd_glass_dialog_action", False)
        if dialog_action:
            object.__setattr__(item, "_nd_glass_dialog_action", True)
        signature = (theme, mobile, dialog_action)
        if glass and getattr(item, "_nd_glass_styled", None) != signature:
            if isinstance(item, ft.Container):
                if (getattr(item, "_nd_glass_material", False)
                        or getattr(item, "_nd_glass_toolbar", False)):
                    pass
                elif item.bgcolor in surface_colors:
                    # Unadorned layout containers must remain transparent;
                    # otherwise several large panes hide the backdrop entirely.
                    if item.border is None and item.border_radius is None:
                        item.bgcolor = None
                    else:
                        warning = item.bgcolor == colors["WarnBgColor"]
                        # Both effects share the toolbar's transparency. Half
                        # glass paints the same surface without another filter.
                        # Individual task cards keep lightweight material even
                        # when their surrounding list has no background panel.
                        tint = colors["WarnBgColor"] if warning else getattr(item, "_nd_glass_tint", None)
                        glass_surface(item, theme, tint=tint,
                                      mobile=mobile, backdrop=not lightweight and not in_backdrop
                                      and not getattr(item, "_nd_glass_card", False))
                elif lightweight:
                    _light_glass_surface(item, theme)
                elif item.bgcolor not in (None, ft.Colors.TRANSPARENT) and item.border_radius:
                    # Priority/date badges and color previews retain their tint.
                    glass_surface(item, theme, compact=True, tint=item.bgcolor, mobile=mobile)
                elif item.gradient is not None and item.blur is not None:
                    glass_surface(item, theme, mobile=mobile, backdrop=not in_backdrop)
            elif isinstance(item, (ft.TextField, ft.Dropdown)):
                item.filled = True
                item.fill_color = colors["GlassInputColor"]
                item.border_radius = 12
                item.border_width = 1
                item.border_color = colors["GlassEdgeColor"]
                item.focused_border_color = colors["ProgressColor"]
                item.focused_border_width = 1.5
                item.hover_color = colors["HoverColor"]
                if isinstance(item, ft.TextField):
                    item.bgcolor = ft.Colors.TRANSPARENT
                    item.focused_bgcolor = colors["GlassHoverColor"]
                    item.selection_color = ft.Colors.with_opacity(0.25, colors["ProgressColor"])
                else:
                    item.bgcolor = colors["GlassPopupColor"]
                    item.menu_style = glass_menu_style(theme, colors)
            elif isinstance(item, ft.ExpansionTile):
                category = getattr(item, "_nd_planner_category", False)
                item.bgcolor = colors["BgColor"] if category and lightweight else ft.Colors.TRANSPARENT
                item.collapsed_bgcolor = colors["BtnColor"] if category and lightweight else ft.Colors.TRANSPARENT
                shape = ft.RoundedRectangleBorder(
                    radius=14,
                    side=item.shape.side if isinstance(item.shape, ft.RoundedRectangleBorder) else None,
                )
                item.shape = item.collapsed_shape = shape
                item.clip_behavior = ft.ClipBehavior.ANTI_ALIAS
            elif isinstance(item, ft.PopupMenuButton):
                item.bgcolor = colors["GlassPopupColor"]
                item.shape = ft.RoundedRectangleBorder(
                    radius=18, side=ft.BorderSide(1, colors["GlassEdgeColor"]),
                )
                item.shadow_color = ft.Colors.TRANSPARENT if lightweight else "#33081832"
                if lightweight:
                    item.elevation = 0
            elif isinstance(item, ft.AlertDialog):
                item.bgcolor = colors["GlassPopupColor"]
                item.shape = ft.RoundedRectangleBorder(
                    radius=24, side=ft.BorderSide(1, colors["GlassEdgeColor"]),
                )
                item.clip_behavior = ft.ClipBehavior.ANTI_ALIAS
                item.barrier_color = colors["AlertOverlayColor"]
                if lightweight:
                    item.elevation = 0
            elif dialog_action and not lightweight and isinstance(item, (ft.Button, ft.TextButton)):
                # Dialog actions need one Material surface: an intrinsic glass
                # child can be smaller than the button's minimum hit area,
                # leaving a second capsule around short labels such as "OK".
                style = glass_button_style(theme, colors, item.style)
                fill = getattr(item, "bgcolor", None)
                skin = getattr(item, "_nd_glass_skin", None)
                if skin is not None and item.content is skin:
                    # An action may already have been prepared before it was
                    # attached to the dialog. Reuse its label/icons and tint.
                    item.content, fill = skin.content, skin.bgcolor
                    object.__delattr__(item, "_nd_glass_skin")
                if fill in (None, ft.Colors.TRANSPARENT, colors["BtnColor"]):
                    fill = colors.get("GlassButtonTint") or colors["GlassInputColor"]
                style.bgcolor[ft.ControlState.DEFAULT] = fill
                style.shape = ft.RoundedRectangleBorder(radius=14)
                style.padding = ft.Padding.symmetric(horizontal=12, vertical=6)
                style.visual_density = ft.VisualDensity.COMPACT
                style.elevation = 0
                style.shadow_color = ft.Colors.TRANSPARENT
                item.style = style
                if isinstance(item, ft.Button):
                    item.bgcolor = None  # Let the state-aware style supply the fill.
                item.clip_behavior = ft.ClipBehavior.ANTI_ALIAS
            elif lightweight and isinstance(item, (ft.Button, ft.TextButton, ft.IconButton)):
                if not getattr(item, "_nd_glass_toolbar_action", False):
                    # Desktop text actions get a little more room around the
                    # label; icon actions keep their dedicated dimensions.
                    style = item.style or ft.ButtonStyle()
                    if (not mobile and not isinstance(item, ft.IconButton)
                            and item.content is not None
                            and not isinstance(item.content, (ft.Icon, ft.Image))):
                        padding = style.padding
                        if isinstance(padding, (int, float)):
                            padding = ft.Padding.all(padding)
                        if isinstance(padding, ft.Padding):
                            style.padding = ft.Padding(
                                left=padding.left + 4, right=padding.right + 4,
                                top=padding.top + 2, bottom=padding.bottom + 2,
                            )
                    if style.side is None:
                        style.side = ft.BorderSide(0.5, colors["GlassEdgeColor"])
                    style.overlay_color = colors["HoverColor"]
                    item.style = style
            elif isinstance(item, (ft.Checkbox, ft.Switch)):
                item.adaptive = False
            elif isinstance(item, ft.ProgressBar):
                item.bgcolor = colors["ProgressBgColor"]
                item.border_radius = 8
            elif isinstance(item, ft.Divider):
                item.color = colors["GlassEdgeColor"]
            object.__setattr__(item, "_nd_glass_styled", signature)

        if glass and not lightweight and isinstance(item, (ft.Button, ft.TextButton, ft.IconButton)):
            if (not getattr(item, "_nd_glass_toolbar_action", False)
                    and not (dialog_action and isinstance(item, (ft.Button, ft.TextButton)))):
                _button_material(item, theme, colors, mobile=mobile)

        if glass and not lightweight and isinstance(item, ft.Container) and item.blur is not None:
            if in_backdrop:
                # A panel can have been prepared before being attached to an
                # already filtered parent. Avoid nested filters in that case.
                item.blur = item.shadow = item.foreground_decoration = None
            else:
                in_backdrop = True
        if not recursive_hosts and item is not control and isinstance(item, (GlassHost, PlannerHost)):
            return
        for name in _child_fields(type(item)):
            child = getattr(item, name)
            child_action = name == "actions" if isinstance(item, ft.AlertDialog) else dialog_action
            if isinstance(child, (list, tuple)):
                for entry in child:
                    visit(entry, in_backdrop, child_action)
            elif isinstance(child, ft.BaseControl):
                visit(child, in_backdrop, child_action)

    visit(control, getattr(control, "_nd_glass_in_backdrop", False))
    return control


def glass_menu_style(theme, colors):
    return ft.MenuStyle(
        bgcolor=colors["GlassPopupColor"],
        side=ft.BorderSide(1, colors["GlassEdgeColor"]),
        shape=ft.RoundedRectangleBorder(radius=18),
        shadow_color=ft.Colors.TRANSPARENT if is_toolbar_glass(theme) else "#33081832",
        elevation=0 if is_toolbar_glass(theme) else 8,
    )


class GlassHost(SurfaceHost):
    """A normal Container that styles new children before they are serialized."""

    def __init__(self, theme, colors, *, mobile=False, **kwargs):
        super().__init__(**kwargs)
        self._nd_glass_theme = theme
        self._nd_glass_colors = colors
        self._nd_glass_mobile = mobile

    def before_update(self):
        super().before_update()
        if self.is_isolated():
            return
        apply_glass(self, self._nd_glass_theme, self._nd_glass_colors,
                    mobile=self._nd_glass_mobile, recursive_hosts=False)


def configure_glass_theme(result, theme, colors):
    """Material popups and small controls use the same translucent palette."""
    if not is_glass(theme):
        return result
    lightweight = is_toolbar_glass(theme)
    if lightweight:
        colors = _light_glass_colors(colors)
    shadow = ft.Colors.TRANSPARENT if lightweight else "#33081832"
    edge = ft.BorderSide(0.5 if lightweight else 1, colors["GlassEdgeColor"])
    shape = ft.RoundedRectangleBorder(radius=22, side=edge)
    style = glass_button_style(theme, colors)
    result.button_theme = ft.ButtonTheme(style=style)
    result.text_button_theme = ft.TextButtonTheme(style=style)
    result.icon_button_theme = ft.IconButtonTheme(style=style)
    result.filled_button_theme = ft.FilledButtonTheme(style=style)
    result.outlined_button_theme = ft.OutlinedButtonTheme(style=style)
    result.dropdown_theme.menu_style = glass_menu_style(theme, colors)
    result.popup_menu_theme = ft.PopupMenuTheme(
        color=colors["GlassPopupColor"], shape=shape,
        shadow_color=shadow, elevation=0 if lightweight else 8,
    )
    result.dialog_theme = ft.DialogTheme(
        bgcolor=colors["GlassPopupColor"], shape=shape,
        barrier_color=colors["AlertOverlayColor"],
        shadow_color=shadow, elevation=0 if lightweight else 12,
    )
    result.date_picker_theme = ft.DatePickerTheme(
        bgcolor=colors["GlassPopupColor"], shape=shape,
        header_bgcolor=colors["GlassInputColor"],
        cancel_button_style=style, confirm_button_style=style,
    )
    result.time_picker_theme = ft.TimePickerTheme(
        bgcolor=colors["GlassPopupColor"], shape=shape,
        dial_bgcolor=colors["GlassInputColor"],
        hour_minute_color=colors["BtnColor"],
        cancel_button_style=style, confirm_button_style=style,
    )
    result.switch_theme = ft.SwitchTheme(
        thumb_color={ft.ControlState.DEFAULT: colors["TxtColor"],
                     ft.ControlState.SELECTED: "#FFFFFF"},
        track_color={ft.ControlState.DEFAULT: colors["GlassInputColor"],
                     ft.ControlState.SELECTED: colors["ProgressColor"]},
        track_outline_color={ft.ControlState.DEFAULT: colors["GlassEdgeColor"],
                             ft.ControlState.SELECTED: colors["ProgressColor"]},
    )
    result.checkbox_theme = ft.CheckboxTheme(
        fill_color={ft.ControlState.DEFAULT: colors["GlassInputColor"],
                    ft.ControlState.SELECTED: colors["SuccessColor"]},
        check_color="#FFFFFF", border_side=edge, shape=ft.CircleBorder(),
    )
    result.scrollbar_theme = ft.ScrollbarTheme(
        thumb_color=ft.Colors.with_opacity(0.35, colors["ProgressColor"]),
        track_color=ft.Colors.TRANSPARENT, radius=8, thickness=4,
    )
    result.tooltip_theme = ft.TooltipTheme(
        decoration=ft.BoxDecoration(
            bgcolor="#F2F4F7",
            border=ft.Border.all(0.5, "#CCD3DD"), border_radius=8,
        ),
        text_style=ft.TextStyle(color="#202734"),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
    )
    result.slider_theme = ft.SliderTheme(
        active_track_color=colors["ProgressColor"],
        inactive_track_color=colors["GlassInputColor"],
        thumb_color=colors["ProgressColor"], overlay_color=colors["HoverColor"],
        value_indicator_color=colors["GlassPopupColor"],
        value_indicator_text_style=ft.TextStyle(color=colors["TxtColor"]),
        value_indicator_stroke_color=colors["GlassEdgeColor"],
    )
    result.radio_theme = ft.RadioTheme(
        fill_color={ft.ControlState.DEFAULT: colors["GlassEdgeColor"],
                    ft.ControlState.SELECTED: colors["ProgressColor"]},
        overlay_color=colors["HoverColor"],
    )
    result.progress_indicator_theme = ft.ProgressIndicatorTheme(
        color=colors["ProgressColor"],
        circular_track_color=colors["GlassInputColor"],
        linear_track_color=colors["ProgressBgColor"], border_radius=8,
    )
    result.snackbar_theme = ft.SnackBarTheme(
        bgcolor=colors["GlassPopupColor"], shape=shape,
        content_text_style=ft.TextStyle(color=colors["TxtColor"]),
    )
    return result
