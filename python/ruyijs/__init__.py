"""Persistent SpiderMonkey contexts on Windows x64 and macOS ARM64."""

from ._context import Context
from ._values import JSError, UNDEFINED
from ._callbacks import ReentrantError
from ._jsvalue import JSObject, JSFunction
from ._runtime_paths import get_runtime_path
from ._version import __version__

__all__ = ["Context", "JSError", "UNDEFINED", "ReentrantError", "JSObject", "JSFunction",
           "get_runtime_path", "__version__"]
