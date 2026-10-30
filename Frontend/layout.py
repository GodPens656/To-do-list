"""Saved panel positions shared by settings and screen layout."""

ACTION_PANEL_OPTIONS = (
    ("top", "Сверху"), ("bottom", "Снизу"),
    ("left", "Слева"), ("right", "Справа"),
)
GROUP_PANEL_OPTIONS = ACTION_PANEL_OPTIONS[:2]


def normalize_action_panel_position(value, *, phone=False):
    return value if value in dict(ACTION_PANEL_OPTIONS) else ("bottom" if phone else "top")


def normalize_group_panel_position(value):
    return value if value in dict(GROUP_PANEL_OPTIONS) else "top"
