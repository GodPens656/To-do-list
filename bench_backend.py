"""Замеры слоя данных на синтетических данных без сети и пользовательских файлов.

Запуск после этапа 1: python -B bench_backend.py --output bench_after.txt
Для диагностической печати вложенных вызовов добавьте --trace.
"""

import argparse
import math
import os
import platform
import sys
import tempfile
from collections import Counter
from contextlib import ExitStack, contextmanager
from importlib.metadata import version
from pathlib import Path
from statistics import median
from time import perf_counter
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent
OPERATIONS = (
    "read_tasks", "saveB", "redact_statusB", "kill_taskB", "get_task", "alg_for_redact",
)


@contextmanager
def isolated_environment(trace=False):
    """Изолирует cwd, Android-путь и секрет; исходный secret.py не читается."""
    previous_cwd = Path.cwd()
    previous_path = sys.path[:]
    previous_bytecode = sys.dont_write_bytecode
    # Скрипт предназначен для отдельного процесса: уже импортированный backend
    # мог бы удерживать ключ шифрования от настоящего secret.py.
    if "Backend.crypto" in sys.modules or "secret" in sys.modules:
        raise RuntimeError("Запустите бенчмарк отдельным процессом Python.")
    temporary_parent = (PROJECT_ROOT / "artifacts" / "stage0" / "tmp").resolve()
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nd-bench-", dir=temporary_parent) as temporary:
        root = Path(temporary).resolve()
        if not root.is_relative_to(temporary_parent):
            raise RuntimeError("Временная папка находится вне каталога бенчмарка.")
        secret_dir = root / "configuration"
        secret_dir.mkdir()
        example = (PROJECT_ROOT / "secret.example.py").read_text(encoding="utf-8")
        marker = 'ENCRYPTION_KEYWORD = ""'
        if example.count(marker) != 1:
            raise RuntimeError("Проверьте шаблон ENCRYPTION_KEYWORD в secret.example.py.")
        (secret_dir / "secret.py").write_text(
            example.replace(marker, 'ENCRYPTION_KEYWORD = "only-synthetic-benchmark-data"'),
            encoding="utf-8",
        )
        sys.path[:0] = [str(secret_dir), str(PROJECT_ROOT)]
        sys.dont_write_bytecode = True
        try:
            with patch.dict(os.environ):
                os.environ.pop("FLET_APP_STORAGE_DATA", None)
                os.environ["ND_PERF_TIMING"] = "1" if trace else "0"
                os.chdir(root)
                yield root
        finally:
            os.chdir(previous_cwd)
            sys.path[:] = previous_path
            sys.dont_write_bytecode = previous_bytecode


@contextmanager
def count_io(crypto):
    """Считает открытия файлов и расшифровки отдельно от замера времени."""
    counters = Counter()
    original_open = Path.open
    original_stat = Path.stat
    original_decrypt = crypto.decrypt_bytes
    from Backend.storage import SECTION_FILENAMES

    section_names = set(SECTION_FILENAMES.values())

    def counted_open(path, mode="r", *args, **kwargs):
        result = original_open(path, mode, *args, **kwargs)
        if "r" in mode or "+" in mode:
            counters["reads"] += 1
            if path.name in section_names:
                counters["section_reads"] += 1
            elif path.name == "security.json":
                counters["security_reads"] += 1
            elif path.name == "user_data.txt":
                counters["user_reads"] += 1
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            counters["writes"] += 1
        return result

    def counted_stat(path, *args, **kwargs):
        counters["path_stats"] += 1
        return original_stat(path, *args, **kwargs)

    def counted_decrypt(raw, *args, **kwargs):
        counters["decrypt_calls"] += 1
        if crypto.is_encrypted(raw):
            counters["aes_decryptions"] += 1
        return original_decrypt(raw, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, "open", counted_open))
        stack.enter_context(patch.object(Path, "stat", counted_stat))
        # Учитываем и прямые импорты функции в storage/cloud/shared_groups.
        for name, module in tuple(sys.modules.items()):
            if name.startswith("Backend.") and getattr(module, "decrypt_bytes", None) is original_decrypt:
                stack.enter_context(patch.object(module, "decrypt_bytes", counted_decrypt))
        yield counters


def make_data(count, storage):
    """Создаёт воспроизводимый набор обычных дел без вложений."""
    data = storage.empty_data()
    data["tasks"] = [{
        "id": f"bench-{index:04d}",
        "name": f"Тестовое дело {index}: подготовить документы к рабочей встрече",
        "status": False,
        "group": "default",
        "is_repeat": False,
        "created_date": "10-11-2026",
        "deadline": "",
        "priority": "Неважно",
        "info_type": "created_date",
        "attachments": [],
    } for index in range(count)]
    return data


def run_operation(name, backend, cloud, target):
    """Вызывает настоящую операцию без подмены чтения, шифрования и undo."""
    if name == "read_tasks":
        return backend.read_tasks()
    if name == "saveB":
        return backend.saveB("Новое тестовое дело", created_date="10-11-2026")
    if name == "redact_statusB":
        return backend.redact_statusB(target, True)
    if name == "kill_taskB":
        return backend.kill_taskB(target)
    if name == "get_task":
        return backend.get_task(target)
    return cloud.alg_for_redact()


def verify_result(name, result, backend, cloud, data, target, authenticated):
    """Проверяет результат операции и восстановление изменённых данных через undo."""
    tasks = backend.read_tasks()
    if name == "read_tasks":
        assert result == tasks
    elif name == "get_task":
        assert result == data["tasks"][-1]
    elif name == "saveB":
        assert len(tasks) == len(data["tasks"]) + 1
        assert tasks[-1]["id"] == result
    elif name == "redact_statusB":
        assert backend.get_task(target)["status"] is True
        assert any(item["task_id"] == target for item in backend._load()["achievements"])
    elif name == "kill_taskB":
        assert len(tasks) == len(data["tasks"]) - 1
        assert backend.get_task(target) is None
    else:
        assert cloud._pending_login_password == ("bench_account" if authenticated else None)
    if name in ("saveB", "redact_statusB", "kill_taskB"):
        assert backend.undo_last_action()
        assert backend._load() == data


def benchmark_case(root, count, encrypted, authenticated, repeats, warmup):
    """Измеряет тёплые операции; подготовка и счётчики не входят во время."""
    from Backend import crypto, storage
    from Backend.cloud import Cloud
    from Backend.core import Backend

    case_dir = root / f"n{count}-encryption{int(encrypted)}-account{int(authenticated)}"
    case_dir.mkdir()
    os.chdir(case_dir)
    # Настоящий Cloud сохраняет проверку user_data и очередь синхронизации.
    # Воркер завершается сразу; конструктор не проверяет сеть и не создаёт Dropbox-клиент.
    with patch.object(Cloud, "_connect", False), \
            patch.object(Cloud, "_disk", object()), \
            patch.object(Cloud, "_upload_worker", lambda self: None):
        cloud = Cloud()
    backend = Backend(cloud=cloud)
    assert backend.data_dir.resolve().is_relative_to(root)
    assert backend.setting_dir.resolve().is_relative_to(root)
    assert cloud.user_data.resolve().is_relative_to(root)
    # В обоих режимах существует security.json: его чтения тоже входят в счётчики.
    storage.set_data_encryption(backend.data_dir, not encrypted)
    storage.set_data_encryption(backend.data_dir, encrypted)
    cloud.write_user_data_text("bench_account~~bench~~local" if authenticated else "")
    cloud.connect = True
    storage.save_all_sections(backend.data_dir, make_data(count, storage), force=True)
    data = backend._load()
    target = data["tasks"][-1]["id"]
    rows = []

    def prepare():
        # Сброс всегда вне измерения; затем прогреваем будущий кэш backend/cloud.
        storage.save_all_sections(backend.data_dir, data, force=True)
        backend.clear_undo()
        cloud._pending_login_password = None
        backend._load()
        cloud.check_user_data()

    for operation in OPERATIONS:
        samples = []
        for index in range(warmup + repeats):
            prepare()
            started = perf_counter()
            result = run_operation(operation, backend, cloud, target)
            elapsed = (perf_counter() - started) * 1000
            if index >= warmup:
                samples.append(elapsed)
            verify_result(operation, result, backend, cloud, data, target, authenticated)
        prepare()
        with count_io(crypto) as counters:
            result = run_operation(operation, backend, cloud, target)
        verify_result(operation, result, backend, cloud, data, target, authenticated)
        rows.append({
            "tasks": count, "encryption": "on" if encrypted else "off",
            "account": "account" if authenticated else "guest", "operation": operation,
            "p50_ms": median(samples),
            "p95_ms": sorted(samples)[math.ceil(len(samples) * 0.95) - 1],
            **{key: counters[key] for key in (
                "reads", "section_reads", "security_reads", "user_reads",
                "decrypt_calls", "aes_decryptions", "writes", "path_stats",
            )},
        })
    # Windows не позволит удалить временную папку, пока она является cwd.
    os.chdir(root)
    return rows


def format_report(rows, args):
    """Формирует таблицу, пригодную для сопоставления этапов 0 и 1."""
    lines = [
        f"{args.label} — замеры слоя данных.",
        f"Python {platform.python_version()}, Flet {version('flet')}, cryptography {version('cryptography')}",
        f"Платформа: {platform.system()} {platform.release()}, {platform.machine()}",
        f"Повторов: {args.repeats}; прогревов: {args.warmup}; p95: ближайший верхний ранг.",
        "Режим: native/ПК; синтетические данные; временные cwd, saves, settings и secret.py.",
        "Сеть отключена; облачный воркер не работает; connect=True проверяет постановку в очередь.",
        "account — синтетический вход с настоящей проверкой user_data и валидацией квот.",
        "Перед каждой операцией: восстановление ровно N дел и прогрев backend/cloud, вне таймера.",
        "Время измеряется без счётчиков; затем считаются обращения одной такой же операции.",
        "read — успешное открытие файла для чтения через Path.open, включая security/user_data.",
        "sections/security/user — подмножества read; dec — вызовы decrypt_bytes; aes — реальные AES-GCM.",
        "write — открытия для записи, включая временные файлы; stat — вызовы Path.stat, включая exists.",
        "Это обращения API файлов, а не физические чтения диска; кэш ОС не сбрасывается.",
        "Времена отдельных методов не включают последующий alg_for_redact, Flet/Flutter и GPU.",
        "После каждого изменения проверены результат, история выполнения и undo.",
        f"Консольные декораторы: {'включены; печать вложенных вызовов влияет на время' if args.trace else 'отключены, чтобы печать не искажала время'}.",
        "",
        "N | enc | profile | operation | p50_ms | p95_ms | read | sections | security | user | dec | aes | write | stat",
        "--- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---",
    ]
    for row in rows:
        lines.append(
            f"{row['tasks']} | {row['encryption']} | {row['account']} | {row['operation']} | "
            f"{row['p50_ms']:.3f} | {row['p95_ms']:.3f} | {row['reads']} | "
            f"{row['section_reads']} | {row['security_reads']} | {row['user_reads']} | "
            f"{row['decrypt_calls']} | {row['aes_decryptions']} | {row['writes']} | {row['path_stats']}"
        )
    return "\n".join(lines) + "\n"


def positive_integer(value):
    """Отклоняет пустые наборы данных и число повторов без измерений."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Ожидается положительное число.")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=positive_integer, default=[50, 300, 1000])
    parser.add_argument("--repeats", type=positive_integer, default=11)
    parser.add_argument("--warmup", type=positive_integer, default=2)
    parser.add_argument("--encryption", choices=("on", "off", "both"), default="both")
    parser.add_argument("--account", choices=("guest", "account", "both"), default="both")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--label", default="Этап 1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve() if args.output else None
    if output is not None:
        if (output.name == "secret.py" or any(
            output.is_relative_to(PROJECT_ROOT / directory) for directory in ("saves", "settings")
        )):
            parser.error("Результат нельзя записывать поверх настроек и пользовательских данных.")
    rows = []
    with isolated_environment(args.trace) as root:
        for count in args.sizes:
            for encrypted in (True, False) if args.encryption == "both" else (args.encryption == "on",):
                for authenticated in (False, True) if args.account == "both" else (args.account == "account",):
                    rows.extend(benchmark_case(root, count, encrypted, authenticated, args.repeats, args.warmup))
    report = format_report(rows, args)
    if output is not None:
        output.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
