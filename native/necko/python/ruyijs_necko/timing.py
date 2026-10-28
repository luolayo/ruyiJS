"""Optional monotonic observations; zero denotes an unavailable boundary."""
import time


def mark(control, boundary):
    if control is None:
        return
    observations = getattr(control, "_native_timing", None)
    if observations is None:
        observations = control._native_timing = {}
    observations.setdefault(boundary, time.monotonic() * 1000)


def snapshot(control):
    values = getattr(control, "_native_timing", {})
    return tuple(values.get(key, 0.0) for key in ("request", "response", "headers"))
