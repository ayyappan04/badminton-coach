"""Lightweight in-process background job runner for the MVP. Swappable for
Celery + Redis/SQS at scale without changing any pipeline code — callers only
depend on `submit(fn, *args)`.
"""
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=2)


def submit(fn, *args, **kwargs):
    return _executor.submit(fn, *args, **kwargs)
