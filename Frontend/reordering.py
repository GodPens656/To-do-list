"""Long-press reordering shared by cards, group management and group tabs."""
from time import monotonic

import flet as ft


MOUSE_HOLD_SECONDS = 0.2


class ReorderGesture(ft.GestureDetector):
    async def _trigger_event(self, event_name, event_data, e=None):
        # Flet 0.82's client omits `of` from long-press move payloads, while
        # its Python event requires it. Reordering uses global positions.
        if event_name == "long_press_move_update" and isinstance(event_data, dict):
            event_data = {"of": {"x": 0, "y": 0}, **event_data}
        return await super()._trigger_event(event_name, event_data, e)


class LongPressReorder:
    """Keep normal taps/scrolls intact; commit one undoable move on release.

    Measuring mounted items supports multiline cards and lazy lists. Gesture
    callbacks use global deltas so moving the feedback never shifts the origin.
    """

    def __init__(self, items, commit, update, *, horizontal=False, spacing=8, mouse_hold=True):
        self.items = items
        self.commit = commit
        self.update = update
        self.horizontal = horizontal
        self.spacing = spacing
        self.mouse_hold = mouse_hold
        self.active = None

    def wrap(self, control, content, *, extra_extent=0):
        # Keep transform/opacity wrappers mounted throughout the pointer gesture.
        # Adding one after long-press recognition would replace the Flutter
        # recognizer's subtree and lose subsequent move/up events.
        control.offset = ft.Offset(0, 0)
        control.scale = 1
        if control.animate_opacity is None:
            control.animate_opacity = 0
        gesture = ReorderGesture(
            content=self._mouse_gesture(control, content) if self.mouse_hold else content,
            drag_interval=35, mouse_cursor=ft.MouseCursor.GRAB,
            on_long_press_start=lambda e: self.start(control, e),
            on_long_press_move_update=self.move,
            on_long_press_end=self.end,
            on_long_press_cancel=self.cancel,
        )
        control._nd_reorder_extra_extent = extra_extent

        def measured(e):
            control._nd_reorder_extent = e.width if self.horizontal else e.height
            ft.context.disable_auto_update()

        control.on_size_change = measured
        return gesture

    def _mouse_gesture(self, control, content):
        # Flet's native long-press timeout is fixed at 500 ms. Mouse pans let
        # us shorten desktop holds. Mobile lists keep their native recognizers.
        press = None

        def down(event):
            nonlocal press
            press = {"at": monotonic(), "event": event, "dragging": False}
            ft.context.disable_auto_update()

        def dragging():
            return (press is not None and press["dragging"]
                    and self.active is not None and self.active["control"] is control)

        def start(event):
            if press is not None and monotonic() - press["at"] >= MOUSE_HOLD_SECONDS:
                self.start(control, press["event"])
                press["dragging"] = self.active is not None
                if dragging():
                    self.move(event)
            ft.context.disable_auto_update()

        def move(event):
            if dragging():
                self.move(event)
            ft.context.disable_auto_update()

        def finish(event=None):
            nonlocal press
            if dragging():
                if event is None:
                    self.cancel()
                else:
                    self.end(event)
            press = None
            ft.context.disable_auto_update()

        return ft.GestureDetector(
            content=content,
            drag_interval=35, mouse_cursor=ft.MouseCursor.GRAB,
            on_pan_down=down, on_pan_start=start, on_pan_update=move,
            on_pan_end=finish, on_pan_cancel=lambda _: finish(),
        )

    def _extent(self, control):
        fallback = 100 if self.horizontal else 80
        return (getattr(control, "_nd_reorder_extent", fallback)
                + getattr(control, "_nd_reorder_extra_extent", 0))

    def _axis(self, offset):
        return offset.x if self.horizontal else offset.y

    def start(self, control, event):
        self.cancel()
        items = list(self.items())
        if not any(item is control for item in items) or len(items) < 2:
            return
        old_index = next(i for i, item in enumerate(items) if item is control)
        self.active = dict(
            control=control, items=items, old_index=old_index, new_index=old_index,
            origin=self._axis(event.global_position),
            opacity=control.opacity, offset=control.offset, scale=control.scale,
            target=None,
        )
        control.opacity = 0.85
        control.scale = 1.025
        self.update(control)

    def _move(self, delta):
        state = self.active
        if state is None:
            return
        # Ignore gestures belonging to a screen replaced during a cloud refresh.
        items = list(self.items())
        if len(items) != len(state["items"]) or any(a is not b for a, b in zip(items, state["items"])):
            self.cancel(update=False)
            return
        source = state["control"]
        extent = self._extent(source)
        source.offset = ft.Offset(delta / extent, 0) if self.horizontal else ft.Offset(0, delta / extent)
        centers = []
        position = 0
        for item in items:
            size = self._extent(item)
            centers.append(position + size / 2)
            # Include date dividers in the measured gap when supplied by a list.
            position += size + getattr(item, "_nd_reorder_gap", self.spacing)
        center = centers[state["old_index"]] + delta
        new_index = sum(center > value for i, value in enumerate(centers) if i != state["old_index"])
        target = items[new_index] if new_index != state["old_index"] else None
        if target is not state["target"]:
            self._restore_target()
            if target is not None:
                state["target"] = target
                state["target_opacity"] = target.opacity
                target.opacity = 0.45
                self.update(target)
        state["new_index"] = new_index
        self.update(source)

    def move(self, event):
        if self.active is not None:
            self._move(self._axis(event.global_position) - self.active["origin"])

    def _restore_target(self, *, update=True):
        state = self.active
        if state and state["target"] is not None:
            target = state["target"]
            target.opacity = state["target_opacity"]
            state["target"] = None
            if update:
                self.update(target)

    def cancel(self, event=None, *, update=True):
        state = self.active
        if state is None:
            return
        self._restore_target(update=update)
        source = state["control"]
        source.opacity, source.offset, source.scale = state["opacity"], state["offset"], state["scale"]
        self.active = None
        if update:
            self.update(source)

    def end(self, event):
        if self.active is None:
            return
        self.move(event)
        state = self.active
        if state is None:
            return
        self.cancel()
        if state["old_index"] == state["new_index"]:
            return
        ordered = list(state["items"])
        ordered.insert(state["new_index"], ordered.pop(state["old_index"]))
        self.commit([item.key for item in ordered])


class ReorderingMixin:
    def _cancel_reordering(self):
        for name in ("_record_sorter", "_group_sorter", "_tab_sorter"):
            sorter = getattr(self, name, None)
            if sorter is not None:
                sorter.cancel(update=False)

    def _record_reorder_items(self):
        items = []
        for control in self.tasks_cont.content.controls:
            if not control.visible:
                continue
            if isinstance(control.data, str) and control.key:
                control._nd_reorder_gap = self.tasks_cont.content.spacing
                items.append(control)
            elif items and isinstance(control, ft.Divider):
                items[-1]._nd_reorder_gap += (control.height or 16) + self.tasks_cont.content.spacing
        return items

    def _bind_record_reordering(self, card):
        sorter = getattr(self, "_record_sorter", None)
        if sorter is None:
            sorter = self._record_sorter = LongPressReorder(
                self._record_reorder_items, self._save_record_order, lambda c: self._update_control(c),
                mouse_hold=not self.phone,
            )
        area = card._nd_reorder_area
        area.content = sorter.wrap(card, area.content)

    def _save_record_order(self, ordered_ids):
        if self._app_locked:
            return
        if self._notes_group:
            saved = self.back.reorder_notes(self.current_group_id, ordered_ids)
        else:
            group_id = None if self.current_group_id == "__all_tasks__" else self.current_group_id
            saved = self.back.reorder_tasks(ordered_ids, group_id)
        self.render_daily_repeat_tasks()
        if saved:
            self.cloud.alg_for_redact()
        self._update_control(self.main_cont)

    def _group_reorder_items(self):
        return [row for row in self._groups_column.controls if row.visible and row.key]

    def _save_group_order(self, ordered_ids):
        if self._app_locked:
            return
        saved = self.back.reorder_groups(ordered_ids)
        self._refresh_group_tabs()
        if self._groups_column is not None:
            self._refresh_group_management()
        if saved:
            self.cloud.alg_for_redact()
        self._update_control(self.main_cont)

    def _bind_group_reordering(self, row, button):
        sorter = getattr(self, "_group_sorter", None)
        if sorter is None:
            sorter = self._group_sorter = LongPressReorder(
                self._group_reorder_items, self._save_group_order, lambda c: self._update_control(c), spacing=10,
                mouse_hold=not self.phone,
            )
        button.content = sorter.wrap(row, button.content)

    def _wrap_group_tab(self, group_id, label):
        if group_id == "__all_tasks__":
            return label
        sorter = getattr(self, "_tab_sorter", None)
        if sorter is None:
            sorter = self._tab_sorter = LongPressReorder(
                lambda: [tab.label for tab in self.group_tab_bar.tabs
                         if tab.data not in (None, "__all_tasks__")],
                self._save_group_order, lambda c: self._update_control(c), horizontal=True, spacing=0,
                mouse_hold=not self.phone,
            )
        # The gesture also supplies the visual feedback and measured label size.
        host = ft.Container(content=label, key=group_id)
        host.content = sorter.wrap(host, label, extra_extent=20)
        return host
