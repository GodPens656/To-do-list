"""CPU/transport benchmark with isolated demo data; no user files or cloud.

Run from the repository root: python tests/benchmark_ui.py
Times cover Python/Flet patch generation, not GPU rendering.
"""
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flet as ft
import msgpack
from flet.controls.object_patch import ObjectPatch
from flet.messaging.protocol import configure_encode_object_for_msgpack

from test_ui_state import make_front


ENCODE = configure_encode_object_for_msgpack(ft.BaseControl)


def patch_tree(root, *, initial=False):
    patch, _, _ = ObjectPatch.from_diff(None if initial else root, root,
                                       control_cls=ft.BaseControl)
    return msgpack.packb(patch.to_message(), default=ENCODE)


def measure(callback):
    samples = []
    for _ in range(7):
        start = perf_counter()
        callback()
        samples.append((perf_counter() - start) * 1000)
    return median(samples)


def benchmark(effect, count):
    front = make_front(effect=effect)
    data = front.back._load()
    data["tasks"] = [dict(id=str(i), name=f"Task {i}", group="default", status=False,
                          info_type="priority", priority="Важно") for i in range(count)]
    front.back.store.save_all_sections(data)
    front.render_daily_repeat_tasks()
    front.show_groups()
    root = ft.Column([front.main_cont])
    patch_tree(root, initial=True)
    update_ms = measure(lambda: patch_tree(root))

    # A real Page/View tree is needed to identify covered native screens.
    page = ft.Page(sess=front.page.session, web=False)
    page.views[0].controls = [front.main_cont]
    page.views.append(ft.View(controls=[front.libs.create_style_cont([ft.Text("Dialog")])]))
    patch_tree(page, initial=True)
    covered_ms = measure(lambda: patch_tree(page))

    def build_settings():
        front._settings_screens.clear()
        front.open_settings()

    settings_ms = measure(build_settings)
    return_ms = measure(front.render_daily_repeat_tasks)
    return dict(effect=effect, tasks=count, active_patch_ms=round(update_ms, 2),
                covered_page_patch_ms=round(covered_ms, 2), settings_build_ms=round(settings_ms, 2),
                unchanged_list_ms=round(return_ms, 2))


if __name__ == "__main__":
    import json
    for effect in ("none", "liquid_glass_half", "liquid_glass"):
        for count in (100, 500):
            print(json.dumps(benchmark(effect, count)), flush=True)
