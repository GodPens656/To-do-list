import asyncio
from copy import deepcopy
from io import BytesIO
import unittest
from unittest.mock import AsyncMock, patch

import flet as ft
from PIL import Image

from Backend.attachments import make_attachment
from Frontend.attachments import attachment_controls
from test_ui_state import make_front


class AttachmentZoomTests(unittest.TestCase):
    def test_preview_buttons_zoom_and_reset_on_desktop_and_phone(self):
        for phone in (False, True):
            with self.subTest(phone=phone):
                front = make_front(phone=phone)
                content = BytesIO()
                Image.new("RGB", (120, 80), "blue").save(content, "PNG")
                attachment = make_attachment("Фото.png", content.getvalue())
                original = deepcopy(attachment)
                controls = attachment_controls(front.libs, [attachment])
                open_preview = controls.controls[0].controls[-1].controls[0].on_click
                open_preview(None)
                dialog = front.page.show_dialog.call_args.args[0]
                viewer = dialog.content.content.controls[0]
                if phone:
                    _, clipboard_row, toolbar, _ = dialog.actions[0].content.controls
                    close_button = clipboard_row.controls[1]
                else:
                    toolbar = dialog.content.content.controls[2]
                    close_button = dialog.actions[-1]
                preview_src = viewer.content.src

                self.assertIsInstance(viewer, ft.InteractiveViewer)
                self.assertTrue(viewer.pan_enabled)
                self.assertTrue(viewer.scale_enabled)
                self.assertTrue(viewer.trackpad_scroll_causes_scale)
                self.assertLess(viewer.min_scale, 1)
                self.assertGreater(viewer.max_scale, 1)
                self.assertGreater(viewer.boundary_margin, 0)

                # Exercise Flet's method dispatch, including zoom after a reset.
                with patch.object(ft.InteractiveViewer, "_invoke_method", new=AsyncMock()) as invoke:
                    for button in (toolbar.controls[2], toolbar.controls[0],
                                   toolbar.controls[1], toolbar.controls[2]):
                        asyncio.run(button.on_click(None))
                    self.assertEqual([call.args[0] for call in invoke.await_args_list],
                                     ["zoom", "zoom", "reset", "zoom"])
                    self.assertEqual(invoke.await_args_list[0].kwargs["arguments"], {"factor": 1.25})
                    self.assertEqual(invoke.await_args_list[1].kwargs["arguments"], {"factor": 0.8})

                self.assertEqual(viewer.content.src, preview_src)
                self.assertEqual(attachment, original)
                close_button.on_click(None)
                front.page.pop_dialog.assert_called_once()
                open_preview(None)
                reopened = front.page.show_dialog.call_args.args[0]
                self.assertIsNot(reopened.content.content.controls[0], viewer)
