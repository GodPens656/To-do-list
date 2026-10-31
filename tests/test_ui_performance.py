"""Regression coverage for native update boundaries and glass serialization."""
import unittest
from unittest.mock import Mock, patch

import flet as ft
import msgpack
from flet.controls.object_patch import ObjectPatch
from flet.messaging.protocol import configure_encode_object_for_msgpack

from Frontend.controls import ActionButton, ActionIconButton, LazyListView, SurfaceHost
from Frontend.glass import GlassHost
from Frontend.libs import Fr_Libs
from test_ui_state import make_front


def serialize(control, *, initial=False):
    result, _, _ = ObjectPatch.from_diff(None if initial else control, control,
                                        control_cls=ft.BaseControl)
    msgpack.packb(result.to_message(),
                  default=configure_encode_object_for_msgpack(ft.BaseControl))
    return list(result.patch)


class UiPerformanceTests(unittest.TestCase):
    def test_covered_native_screen_defers_children_and_sends_changes_on_return(self):
        for effect in ("none", "liquid_glass_half", "liquid_glass"):
            with self.subTest(effect=effect):
                front = make_front(effect=effect)
                label = ft.Text("Original")
                listing = front.libs.create_style_cont([label])
                page = ft.Page(sess=Mock(), web=False)
                page.views[0].controls = [listing]
                serialize(page, initial=True)
                self.assertFalse(listing.is_isolated())

                page.views.append(front.libs.view(controls=[front.libs.host(content=ft.Text("Dialog"))]))
                serialize(page)
                self.assertTrue(listing.is_isolated())
                label.value = "Changed while covered"
                with patch.object(ft.Text, "before_update", autospec=True) as update:
                    serialize(page)
                self.assertNotIn(id(label), [id(call.args[0]) for call in update.call_args_list])

                page.views.pop()
                changes = serialize(page)
                self.assertFalse(listing.is_isolated())
                self.assertTrue(any(op.get("value") == "Changed while covered" for op in changes))
                self.assertEqual(serialize(page), [])

    def test_nested_hosts_style_new_controls_once_at_serialization_boundary(self):
        for theme in ("liquid_glass_light", "liquid_glass_half_light"):
            with self.subTest(theme=theme):
                libs = Fr_Libs(theme, False)
                button = libs.create_style_button("Original")
                inner = libs.create_style_cont([button])
                outer = libs.create_style_cont([inner])
                page = ft.Page(sess=Mock(), web=False)
                page.views[0].controls = [outer]
                serialize(page, initial=True)
                later = ft.TextField(value="Keep value")
                inner.content.controls.append(later)
                serialize(page)
                self.assertTrue(later.filled)
                self.assertIsNotNone(later.fill_color)
                self.assertEqual(later.value, "Keep value")
                self.assertIsNone(inner.blur)
                self.assertEqual(serialize(page), [])
                if libs.glass:
                    button.content = "Changed label"
                    button.disabled = True
                    serialize(page)
                    self.assertEqual(button.content.content.value, "Changed label")
                    self.assertLess(button.content.opacity, 1)

    def test_host_hook_does_not_rewalk_a_nested_hosts_buttons(self):
        libs = Fr_Libs("liquid_glass_light", False)
        inner = libs.create_style_cont([ft.Button("Action")])
        outer = libs.create_style_cont([inner])
        libs.prepare(outer)
        with patch("Frontend.glass._button_material") as material:
            outer.before_update()
            material.assert_not_called()
            inner.before_update()
            material.assert_called_once()

    def test_settings_builds_separate_categories_only_when_opened_and_reads_fresh_values(self):
        front = make_front(effect="liquid_glass")
        with patch.object(front.utils2, "build_dialog_customization",
                          wraps=front.utils2.build_dialog_customization) as customization, \
             patch.object(front.utils2, "build_dialog_notifications",
                          wraps=front.utils2.build_dialog_notifications) as notifications:
            _, _, _, dialogs = front.utils2.build_widgets_for_settings(
                front.update_tasks, front.open_repeat_dialog, front.open_postponed_dialog, front.page,
            )
            customization.assert_not_called()
            notifications.assert_not_called()
            front.back2.redact_setting("dialog_animations", False)
            _, content, _ = dialogs["customization"]["build"]()
            customization.assert_called_once()
            controls = content.content.controls[0].content.controls
            row = next(c for c in controls if isinstance(c, ft.Row)
                       and isinstance(c.controls[0], ft.Text)
                       and c.controls[0].value == "Анимации от диалогов")
            self.assertFalse(row.controls[1].value)
            dialogs["notifications"]["build"]()
            notifications.assert_called_once()

    def test_native_update_patches_only_requested_control_and_suppresses_duplicate_auto_update(self):
        front = make_front(effect="liquid_glass")
        front.web = False
        with patch.object(GlassHost, "update") as update, \
             patch("Frontend.init_page.ft.context.disable_auto_update") as disable, \
             patch.object(front.libs, "prepare") as prepare:
            front.page.update.reset_mock()
            front._update_control(front.main_cont)
            update.assert_called_once()
            front.page.update.assert_not_called()
            prepare.assert_not_called()
            disable.assert_called_once()

    def test_diagnostic_representations_do_not_traverse_list_contents(self):
        listing = LazyListView([ft.Text("Private task content") for _ in range(500)])
        panel = SurfaceHost(content=listing)
        self.assertLess(len(repr(listing)), 70)
        self.assertLess(len(repr(panel)), 70)
        self.assertNotIn("Private task content", repr(panel))

    def test_unchanged_buttons_send_no_style_patch_but_later_style_changes_are_sent(self):
        for button in (ActionButton("Action"), ActionIconButton(ft.Icons.ADD)):
            with self.subTest(control=type(button).__name__):
                button.style = ft.ButtonStyle(color="#123456", padding=8)
                page = ft.Page(sess=Mock())
                page.views[0].controls = [button]
                serialize(page, initial=True)
                self.assertEqual(serialize(page), [])
                button.style.color = "#654321"
                self.assertTrue(serialize(page))
                self.assertEqual(serialize(page), [])
                button.style.shape = ft.RoundedRectangleBorder(radius=20)
                self.assertTrue(serialize(page))
                self.assertEqual(serialize(page), [])

    def test_unchanged_task_lists_reuse_cards_but_data_and_presentation_changes_rebuild(self):
        front = make_front(effect="liquid_glass")
        front.back.saveB("Original task", "default")
        front.render_daily_repeat_tasks()
        cards = list(front.tasks_cont.content.controls)
        front.current_search = "missing"
        with patch.object(front, "before_load", wraps=front.before_load) as build:
            front.render_daily_repeat_tasks()
            build.assert_not_called()
            self.assertEqual([id(c) for c in cards], [id(c) for c in front.tasks_cont.content.controls])
            self.assertTrue(front.empty_state.visible)
            front.back.saveB("New task", "default")
            front.render_daily_repeat_tasks()
            self.assertEqual(build.call_count, 1)
            front.back.update_group_settings("default", show_created_date=False)
            front.render_daily_repeat_tasks()
            self.assertEqual(build.call_count, 2)
            front.current_status_sort = "incomplete_first"
            front.render_daily_repeat_tasks()
            self.assertEqual(build.call_count, 3)
            front.back.rename_group("default", "Renamed group")
            front.render_daily_repeat_tasks()
            self.assertEqual(front.task_heading.value, "Renamed group")
            self.assertEqual(build.call_count, 4)
            front.tasks_cont.content.controls = []
            front.render_daily_repeat_tasks()
            self.assertEqual(build.call_count, 5)
            self.assertEqual(len([c for c in front.tasks_cont.content.controls
                                  if isinstance(c.data, str)]), 2)

    def test_notes_reuse_cards_and_detect_edits(self):
        front = make_front(effect="liquid_glass_half")
        group = front.back.create_group("Notes", group_type="notes")
        front.current_group_id = group
        note = front.back.save_note(group, "Original note")
        front.render_daily_repeat_tasks()
        with patch.object(front, "_render_notes", wraps=front._render_notes) as build:
            front.render_daily_repeat_tasks()
            build.assert_not_called()
            front.back.save_note(group, "Edited note", note)
            front.render_daily_repeat_tasks()
            build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
