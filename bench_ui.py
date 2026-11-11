"""Сравнение сборки карточек и патчей Flet на изолированных данных.

Запуск: python -B bench_ui.py --output bench_ui_before.txt
Время Flutter/GPU и задержка сети в эти замеры не входят.
"""

import argparse
import platform
import sys
from importlib.metadata import version
from pathlib import Path
from statistics import median
from time import perf_counter
from unittest.mock import Mock, patch

from bench_backend import isolated_environment, positive_integer, PROJECT_ROOT


def serialized_patch(control, *, initial=False):
    """Повторяет построение и упаковку патча, отправляемого клиенту Flet."""
    import flet as ft
    import msgpack
    from flet.controls.object_patch import ObjectPatch
    from flet.messaging.protocol import configure_encode_object_for_msgpack

    result, _, _ = ObjectPatch.from_diff(None if initial else control, control,
                                       control_cls=ft.BaseControl)
    return msgpack.packb(result.to_message(),
                         default=configure_encode_object_for_msgpack(ft.BaseControl))


def control_counts(root):
    """Считает сериализуемые контролы, не обходя ссылки на родителей."""
    import flet as ft
    from Frontend.glass import _child_fields

    pending = [root]
    seen = set()
    counts = {"controls": 0, "menu_items": 0}
    while pending:
        control = pending.pop()
        if not isinstance(control, ft.BaseControl) or id(control) in seen:
            continue
        seen.add(id(control))
        counts["controls"] += 1
        counts["menu_items"] += isinstance(control, ft.PopupMenuItem)
        for name in _child_fields(type(control)):
            value = getattr(control, name, None)
            if isinstance(value, (list, tuple)):
                pending.extend(value)
            else:
                pending.append(value)
    return counts


def benchmark(count, effect, phone, repeats):
    """Собирает карточки заново и отдельно измеряет полный неизменённый патч."""
    import flet as ft
    from test_ui_state import make_front

    front = make_front(effect=effect, phone=phone)
    data = front.back._load()
    data["tasks"] = [{
        "id": str(index), "name": f"Тестовое дело {index}", "group": "default",
        "status": False, "created_date": "10-11-2026", "priority": "Важно",
        "info_type": "priority", "attachments": [],
    } for index in range(count)]
    front.back.store.save_all_sections(data)
    builds, initial_patches, full_patches, returns, payloads = [], [], [], [], []
    checkbox_handlers, checkbox_patches = [], []
    for index in range(repeats + 1):
        front.back.store.save_all_sections(data)
        front._task_render_signature = None
        started = perf_counter()
        front.render_daily_repeat_tasks()
        build_ms = (perf_counter() - started) * 1000
        page = ft.Page(sess=Mock(), web=False)
        page.views[0].controls = [front.main_cont]
        started = perf_counter()
        payload = serialized_patch(page, initial=True)
        initial_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        serialized_patch(page)
        full_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        front.render_daily_repeat_tasks()
        return_ms = (perf_counter() - started) * 1000
        card = next(control for control in front.tasks_cont.content.controls
                    if isinstance(control.data, str))
        checkbox = next(control for control in card.content.controls if isinstance(control, ft.Checkbox))
        with patch.object(front, '_update_control') as updates, patch.object(ft.Control, 'update'):
            checkbox.value = True
            started = perf_counter()
            checkbox.on_change(Mock(control=checkbox))
            checkbox_handler_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        for call in updates.call_args_list:
            for subtree in call.args:
                serialized_patch(subtree)
        checkbox_patch_ms = (perf_counter() - started) * 1000
        if index:
            builds.append(build_ms)
            initial_patches.append(initial_ms)
            full_patches.append(full_ms)
            returns.append(return_ms)
            payloads.append(len(payload))
            checkbox_handlers.append(checkbox_handler_ms)
            checkbox_patches.append(checkbox_patch_ms)
    cards = [control for control in front.tasks_cont.content.controls
             if isinstance(control.data, str)]
    assert len(cards) == count
    counts = control_counts(front.main_cont)
    return dict(tasks=count, effect=effect, layout="phone" if phone else "desktop",
                build_ms=median(builds), initial_patch_ms=median(initial_patches),
                full_patch_ms=median(full_patches), unchanged_list_ms=median(returns),
                checkbox_handler_ms=median(checkbox_handlers), checkbox_patch_ms=median(checkbox_patches),
                payload_bytes=int(median(payloads)), **counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=positive_integer, default=[50, 300, 1000])
    parser.add_argument("--effects", nargs="+", default=["none", "liquid_glass_half", "liquid_glass"])
    parser.add_argument("--layouts", nargs="+", choices=("desktop", "phone"), default=["desktop", "phone"])
    parser.add_argument("--repeats", type=positive_integer, default=5)
    parser.add_argument("--label", default="Этап 2 — до изменений")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--frontend-root", type=Path)
    args = parser.parse_args()
    output = args.output.resolve() if args.output else None
    frontend_root = args.frontend_root.resolve() if args.frontend_root else None
    if frontend_root is not None and not (frontend_root / 'Frontend/init_page.py').is_file():
        parser.error('В --frontend-root должна находиться папка Frontend со снимком кода.')
    if output is not None and (output.name == "secret.py" or any(
        output.is_relative_to(PROJECT_ROOT / directory) for directory in ("saves", "settings")
    )):
        parser.error("Нельзя записывать результат поверх пользовательских данных.")
    rows = []
    with isolated_environment():
        if frontend_root:
            sys.path.insert(0, str(frontend_root))
        sys.path.insert(0, str(PROJECT_ROOT / "tests"))
        for effect in args.effects:
            for layout in args.layouts:
                for count in args.sizes:
                    rows.append(benchmark(count, effect, layout == "phone", args.repeats))
                    print(f"{args.label}: N={count}, {effect}, {layout} — готово", file=sys.stderr, flush=True)
    lines = [args.label,
             f"Python {platform.python_version()}, Flet {version('flet')}; Windows; повторы: {args.repeats}, прогрев: 1.",
             "Только синтетический web-store; сеть, облако и файлы пользователя не используются.",
             "Раскладки: desktop/phone; патч измеряется на реальном дереве Page/View без подключённого клиента.",
             "Числа — медианы, мс. Меню перед замером не открывались; перед full_patch_ms состояние не меняется вручную.",
             "Служебные повторные патчи стилей Flet учитываются во времени full_patch_ms.",
             "GPU, задержка сети, открытие нативного меню и физический отклик экрана не измеряются.",
             "build_ms — принудительная пересборка карточек; unchanged_list_ms — повторный рендер с прежней подписью.",
             "payload_bytes — размер начального msgpack-патча; controls — число контролов основного экрана.",
             "checkbox_handler_ms — обработчик с web-store без отправки; checkbox_patch_ms — упаковка запрошенных им поддеревьев.",
             "Сортировка статусов отключена; отдельное обновление кнопки undo не входит в checkbox_patch_ms.",
             "",
             "N | effect | layout | build_ms | initial_patch_ms | full_patch_ms | unchanged_list_ms | payload_bytes | controls | menu_items | checkbox_handler_ms | checkbox_patch_ms",
             "--- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---"]
    for row in rows:
        lines.append(f"{row['tasks']} | {row['effect']} | {row['layout']} | {row['build_ms']:.3f} | "
                     f"{row['initial_patch_ms']:.3f} | {row['full_patch_ms']:.3f} | "
                     f"{row['unchanged_list_ms']:.3f} | {row['payload_bytes']} | "
                     f"{row['controls']} | {row['menu_items']} | "
                     f"{row['checkbox_handler_ms']:.3f} | {row['checkbox_patch_ms']:.3f}")
    report = "\n".join(lines) + "\n"
    if output is not None:
        output.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
