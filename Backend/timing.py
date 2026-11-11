"""Временные замеры этапа 0; включаются переменной ND_PERF_TIMING=1."""

import os
from functools import wraps
from inspect import iscoroutinefunction
from time import perf_counter


def timed(function):
    """Печатает длительность вызова, включая ожидание асинхронной функции."""
    if os.getenv("ND_PERF_TIMING") != "1":
        return function

    def report(started):
        elapsed = (perf_counter() - started) * 1000
        print(f"[timed] {function.__qualname__}: {elapsed:.3f} ms", flush=True)

    if iscoroutinefunction(function):
        @wraps(function)
        async def async_wrapper(*args, **kwargs):
            started = perf_counter()
            try:
                return await function(*args, **kwargs)
            finally:
                report(started)

        return async_wrapper

    @wraps(function)
    def wrapper(*args, **kwargs):
        started = perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            report(started)

    return wrapper
