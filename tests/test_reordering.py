"""Long-press gestures, scoped persistence, sorting and undo regressions."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from Backend.core import Backend
from Backend.storage import load_all_sections, save_all_sections
from Backend.webstorage import WebSessionStore
from Frontend.main import ALL_TASKS_GROUP_ID
from Frontend.reordering import ReorderGesture
from test_ui_state import make_front, task_menu


def cards(front):
    return [c for c in front.tasks_cont.content.controls if isinstance(c.data, str)]


def drag(control, gesture, *, x=0, y=0):
    control.on_size_change(SimpleNamespace(width=100, height=80))
    gesture.on_long_press_start(SimpleNamespace(global_position=ft.Offset(0, 0)))
    event = SimpleNamespace(global_position=ft.Offset(x, y))
    gesture.on_long_press_move_update(event)
    gesture.on_long_press_end(event)


class ReorderStorageTests(unittest.TestCase):
    def setUp(self):
        self.store = WebSessionStore(SimpleNamespace())
        self.back = Backend(web_store=self.store, cloud=Mock())

    def test_scoped_task_order_preserves_other_groups_metadata_and_undo(self):
        work = self.back.create_group("Work")
        first = self.back.saveB("First", work, priority="Важно")
        other = self.back.saveB("Other", "default")
        last = self.back.saveB("Last", work)
        self.back.set_group_default_filter(work, "priority_desc", "incomplete_first")
        before = self.back._load()
        self.assertTrue(self.back.reorder_tasks([last, first], work))
        self.assertEqual([t["id"] for t in self.back.read_tasks()], [last, other, first])
        self.assertEqual(self.back.get_task(first), before["tasks"][0])
        self.assertEqual(self.back._load()["groups"], before["groups"])
        self.assertTrue(self.back.undo_last_action())
        self.assertEqual(self.back._load(), before)

    def test_unchanged_task_order_does_not_change_filters_or_undo(self):
        a, b = self.back.saveB("A"), self.back.saveB("B")
        self.back.set_group_default_filter("default", "deadline_asc", "complete_first")
        before = self.back._load()
        undo = self.back._undo_state
        for scope in ("default", None):
            with self.subTest(scope=scope):
                self.assertFalse(self.back.reorder_tasks([a, b], scope))
                self.assertEqual(self.back._load(), before)
                self.assertEqual(self.back._undo_state, undo)

    def test_stale_duplicate_and_cross_group_ids_do_not_change_data_or_undo(self):
        work = self.back.create_group("Work")
        a = self.back.saveB("A")
        b = self.back.saveB("B")
        other = self.back.saveB("Other", work)
        before = self.back._load()
        undo = self.back._undo_state
        for ids, scope in [([a, "missing"], None), ([a, a], None),
                           ([a, other], "default"), ([a], None)]:
            self.assertFalse(self.back.reorder_tasks(ids, scope))
            self.assertEqual(self.back._load(), before)
            self.assertEqual(self.back._undo_state, undo)
        self.assertTrue(self.back.reorder_tasks([b, a], "default"))

    def test_notes_groups_and_shared_metadata_round_trip_on_disk(self):
        group = self.back.create_group("Notes", group_type="notes")
        a = self.back.save_note(group, "A\nmultiline")
        b = self.back.save_note(group, "B")
        data = self.back._load()
        data["groups"][1]["shared_group"] = {"name": "Notes", "password": "test"}
        self.store.replace_from_cloud(data)
        self.assertTrue(self.back.reorder_notes(group, [b, a]))
        self.assertTrue(self.back.reorder_groups([group, "default"]))
        with tempfile.TemporaryDirectory() as directory:
            save_all_sections(Path(directory), self.back._load())
            restored = load_all_sections(Path(directory))
        self.assertEqual([g["id"] for g in restored["groups"]], [group, "default"])
        self.assertEqual(restored["groups"][0], self.back._load()["groups"][0])
        self.assertEqual([n["id"] for n in restored["groups"][0]["notes"]], [b, a])
        self.assertEqual(restored["groups"][0]["shared_group"], data["groups"][1]["shared_group"])
        self.assertFalse(self.back.reorder_notes("default", [b, a]))


class ReorderGestureTests(unittest.TestCase):
    def front(self, **kwargs):
        front = make_front(**kwargs)
        front._update_control = Mock()
        front.cloud.alg_for_redact.reset_mock()
        return front

    def test_mouse_drag_starts_after_200ms_and_saves_order(self):
        front = self.front()
        ids = [front.back.saveB(name) for name in ("A", "B")]
        front.render_daily_repeat_tasks()
        source = cards(front)[1]
        gesture = source._nd_reorder_area.content.content
        source.on_size_change(SimpleNamespace(width=100, height=80))
        down = SimpleNamespace(global_position=ft.Offset(0, 0))
        moved = SimpleNamespace(global_position=ft.Offset(0, -200))
        with patch("Frontend.reordering.monotonic", side_effect=[10, 10.21]):
            gesture.on_pan_down(down)
            gesture.on_pan_start(moved)
        self.assertIs(front._record_sorter.active["control"], source)
        gesture.on_pan_end(moved)
        self.assertEqual([c.key for c in cards(front)], ids[::-1])

    def test_short_mouse_drag_and_cancel_do_not_reorder(self):
        front = self.front()
        ids = [front.back.saveB(name) for name in ("A", "B")]
        front.render_daily_repeat_tasks()
        source = cards(front)[1]
        gesture = source._nd_reorder_area.content.content
        down = SimpleNamespace(global_position=ft.Offset(0, 0))
        moved = SimpleNamespace(global_position=ft.Offset(0, -200))
        with patch("Frontend.reordering.monotonic", side_effect=[10, 10.10]):
            gesture.on_pan_down(down)
            gesture.on_pan_start(moved)
        gesture.on_pan_update(moved)
        gesture.on_pan_end(moved)
        self.assertIsNone(front._record_sorter.active)
        self.assertEqual([c.key for c in cards(front)], ids)
        with patch("Frontend.reordering.monotonic", side_effect=[20, 20.21]):
            gesture.on_pan_down(down)
            gesture.on_pan_start(moved)
        gesture.on_pan_cancel(None)
        self.assertEqual(source.offset, ft.Offset(0, 0))
        self.assertEqual(source.scale, 1)
        self.assertEqual([c.key for c in cards(front)], ids)

    def test_tasks_move_both_directions_on_desktop_and_phone_and_survive_reopen(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = self.front(phone=phone)
                ids = [front.back.saveB(name) for name in ("A", "B", "C")]
                front.render_daily_repeat_tasks()
                last = cards(front)[-1]
                drag(last, last._nd_reorder_area.content, y=-250)
                self.assertEqual([c.key for c in cards(front)], [ids[2], ids[0], ids[1]])
                front.show_groups()
                first = cards(front)[0]
                drag(first, first._nd_reorder_area.content, y=250)
                self.assertEqual([c.key for c in cards(front)], ids)
                self.assertTrue(front.back.undo_last_action())
                front.render_daily_repeat_tasks()
                self.assertEqual([c.key for c in cards(front)], [ids[2], ids[0], ids[1]])

    def test_search_reorders_visible_slots_without_moving_hidden_tasks(self):
        front = self.front()
        ids = [front.back.saveB(name) for name in ("Visible A", "Hidden", "Visible B")]
        front.render_daily_repeat_tasks()
        front.apply_search_filter("visible")
        source = cards(front)[-1]
        drag(source, source._nd_reorder_area.content, y=-200)
        self.assertEqual([t["id"] for t in front.back.read_tasks()], [ids[2], ids[1], ids[0]])
        self.assertEqual(front.current_search, "visible")
        self.assertEqual([c.visible for c in cards(front)], [True, False, True])
        self.assertEqual(front.task_summary.value, "Найдено: 2 из 3")

    def test_drag_preserves_global_inherited_and_group_filters_after_reopening(self):
        for phone in (False, True):
            for scope in ("all", "inherited", "group"):
                with self.subTest(phone=phone, scope=scope):
                    front = self.front(phone=phone, settings={
                        "default_task_sort": "priority_desc",
                        "default_task_status_sort": "incomplete_first",
                    })
                    group = front.back.create_group("Work")
                    if scope == "group":
                        front.back.set_group_default_filter(
                            group, "priority_desc", "incomplete_first",
                        )
                        front.back2.redact_setting("default_task_sort", "priority_asc")
                        front.back2.redact_setting("default_task_status_sort", "complete_first")
                    low = front.back.saveB("Low", group)
                    a = front.back.saveB("High A", group, priority="Очень важно")
                    b = front.back.saveB("High B", group, priority="Очень важно")
                    done = front.back.saveB("Done", group, priority="Очень важно")
                    front.back.redact_statusB(done, True)
                    front.current_group_id = ALL_TASKS_GROUP_ID if scope == "all" else group
                    front.show_groups()
                    groups = front.back._load()["groups"]
                    settings = front.back2.read_settings()
                    self.assertEqual([c.key for c in cards(front)], [a, b, low, done])
                    # Equal sort keys still allow a meaningful manual move.
                    source = cards(front)[1]
                    drag(source, source._nd_reorder_area.content, y=-200)
                    self.assertEqual([c.key for c in cards(front)], [b, a, low, done])
                    # A drop across sort keys must keep both filters in force.
                    source = cards(front)[-1]
                    drag(source, source._nd_reorder_area.content, y=-1000)
                    self.assertEqual([c.key for c in cards(front)], [b, a, low, done])
                    self.assertEqual((front.current_sort, front.current_status_sort),
                                     ("priority_desc", "incomplete_first"))
                    self.assertEqual(front.back._load()["groups"], groups)
                    self.assertEqual(front.back2.read_settings(), settings)
                    selected = front.current_group_id
                    front.current_group_id = "default"
                    front.show_groups()
                    front.current_group_id = selected
                    front.show_groups()
                    self.assertEqual([c.key for c in cards(front)], [b, a, low, done])

    def test_drag_keeps_temporary_filter_and_group_inheritance(self):
        front = self.front()
        a = front.back.saveB("A", deadline="01-12-2026")
        b = front.back.saveB("B", deadline="01-12-2026")
        front.apply_task_sort("deadline_asc", "complete_first")
        source = cards(front)[1]
        drag(source, source._nd_reorder_area.content, y=-200)
        self.assertEqual([c.key for c in cards(front)], [b, a])
        self.assertEqual((front.current_sort, front.current_status_sort),
                         ("deadline_asc", "complete_first"))
        self.assertIsNone(front.back.get_group_default_filter("default"))

    def test_notes_keep_edit_delete_search_and_order(self):
        front = self.front(phone=True)
        group = front.back.create_group("Notes", group_type="notes")
        ids = [front.back.save_note(group, name) for name in ("A\nB", "C")]
        front.current_group_id = group
        front.render_daily_repeat_tasks()
        source = cards(front)[1]
        drag(source, source._nd_reorder_area.content, y=-200)
        self.assertEqual([n["id"] for n in front.back.read_notes(group)], ids[::-1])
        self.assertEqual([c.key for c in cards(front)], ids[::-1])
        actions = task_menu(cards(front)[0]).items
        self.assertTrue(callable(actions[0].on_click))
        self.assertTrue(callable(actions[-1].on_click))
        front.apply_search_filter("a")
        self.assertEqual([c.visible for c in cards(front)], [False, True])

    def test_management_and_tabs_share_group_order_and_keep_selection(self):
        front = self.front()
        work = front.back.create_group("Work")
        notes = front.back.create_group("Notes", group_type="notes")
        front.current_group_id = notes
        front.show_groups()
        front.open_group_management()
        source = front._groups_column.controls[-1]
        drag(source, source.controls[0].content, y=-300)
        self.assertEqual([g["id"] for g in front.back.get_groups()], [notes, "default", work])
        self.assertEqual([t.data for t in front.group_tab_bar.tabs],
                         [ALL_TASKS_GROUP_ID, notes, "default", work, None])
        self.assertEqual(front.group_tab_bar.tabs[front.group_tabs.selected_index].data, notes)
        front.close_page()
        source = front.group_tab_bar.tabs[1].label
        drag(source, source.content, x=400)
        self.assertEqual([g["id"] for g in front.back.get_groups()], ["default", work, notes])
        self.assertEqual(front.group_tab_bar.tabs[front.group_tabs.selected_index].data, notes)
        self.assertEqual([row.key for row in front._groups_column.controls], ["default", work, notes])

    def test_cancel_no_motion_and_replaced_screen_do_not_save(self):
        front = self.front()
        front.back.saveB("A")
        front.back.saveB("B")
        front.render_daily_repeat_tasks()
        source = cards(front)[0]
        gesture = source._nd_reorder_area.content
        before = front.back._load()
        drag(source, gesture)
        self.assertEqual(front.back._load(), before)
        gesture.on_long_press_start(SimpleNamespace(global_position=ft.Offset(0, 0)))
        gesture.on_long_press_cancel(None)
        self.assertEqual(source.opacity, 1)
        self.assertEqual(source.offset, ft.Offset(0, 0))
        gesture.on_long_press_start(SimpleNamespace(global_position=ft.Offset(0, 0)))
        front.back.saveB("New from cloud")
        front.render_daily_repeat_tasks()
        after_refresh = front.back._load()
        gesture.on_long_press_end(SimpleNamespace(global_position=ft.Offset(0, 400)))
        self.assertEqual(front.back._load(), after_refresh)
        front.cloud.alg_for_redact.assert_not_called()

    def test_flet_client_move_payload_without_origin_offset_decodes(self):
        gesture = ReorderGesture(content=ft.Text("Test"), on_long_press_move_update=Mock())
        decoded = []

        def inspect_event(event):
            decoded.append(event)
            return False  # No mounted client is needed to check payload decoding.

        gesture.before_event = inspect_event
        asyncio.run(gesture._trigger_event("long_press_move_update", {
            "l": {"x": 10, "y": -80}, "g": {"x": 200, "y": 100},
            "lofo": {"x": 0, "y": -100},
        }))
        self.assertEqual(decoded[0].global_position, ft.Offset(200, 100))

    def test_navigation_cancels_hold_and_restores_feedback_without_a_save(self):
        front = self.front()
        front.back.saveB("A")
        front.back.saveB("B")
        front.render_daily_repeat_tasks()
        source = cards(front)[0]
        gesture = source._nd_reorder_area.content
        before = front.back._load()
        gesture.on_long_press_start(SimpleNamespace(global_position=ft.Offset(0, 0)))
        front.open_group_management()
        gesture.on_long_press_end(SimpleNamespace(global_position=ft.Offset(0, 400)))
        self.assertEqual(front.back._load(), before)
        self.assertEqual(source.scale, 1)
        self.assertIsNone(front._record_sorter.active)


if __name__ == "__main__":
    unittest.main()
