"""Update boundaries and bounded diagnostics for large control trees."""
import flet as ft


class SurfaceHost(ft.Container):
    """A panel whose covered native screen can defer parent-driven updates."""

    def __repr__(self):
        # Flet 0.82 eagerly formats controls in diff debug messages, including
        # when debug logging is disabled. Do not recursively format a task list.
        return f"{type(self).__name__}({self._i})"

    def is_isolated(self):
        # Native navigation keeps previous Views mounted. Retain their pending
        # changes until Back reveals them, instead of diffing every task card
        # for each event in the dialog above them.
        parent = self.parent
        while parent is not None:
            if isinstance(parent, ft.View):
                try:
                    return parent.page.views[-1] is not parent
                except (RuntimeError, IndexError):
                    return False
            parent = parent.parent
        return super().is_isolated()


class LazyListView(ft.ListView):
    """Flet's lazy list with a diagnostic repr independent of its item count."""

    def __repr__(self):
        return f"{type(self).__name__}({self._i}, items={len(self.controls)})"


class _StableButtonStyle:
    """Keep equal normalized styles from being retransmitted by Flet 0.82."""

    def __repr__(self):
        return f"{type(self).__name__}({self._i})"

    def before_update(self):
        previous = self._internals.get("style")
        super().before_update()
        # Button/IconButton create a copy on every update. Flet diffs style
        # replacements by identity, so even an unchanged button sends a patch.
        current = self._internals.get("style")
        if previous is not None and current == previous:
            self._internals["style"] = previous


class ActionButton(_StableButtonStyle, ft.Button):
    pass


class ActionIconButton(_StableButtonStyle, ft.IconButton):
    pass
