"""Locate a source-built or bundled native runtime without downloading files."""

import os
from pathlib import Path
import platform
import sys


def shell_name():
    machine = platform.machine().lower()
    if os.name == "nt" and machine in ("amd64", "x86_64"):
        return "js.exe"
    if sys.platform == "darwin" and machine in ("arm64", "aarch64"):
        return "js"
    raise OSError("ruyijs requires Windows x64 or an experimental macOS ARM64 build")


def get_runtime_path():
    """Return the runtime root containing ``dist`` and ``vendor``.

    ``RUYIJS_SHELL`` selects an existing executable and its enclosing runtime
    root. Otherwise prefer a source checkout's ``dist/js[.exe]`` to the runtime
    bundled in the installed package. This function never downloads files.
    """
    executable = shell_name()

    override = os.environ.get("RUYIJS_SHELL")
    if override:
        shell = Path(override).resolve()
        if not shell.is_file():
            raise FileNotFoundError(f"RUYIJS_SHELL does not exist: {shell}")
        return shell.parent.parent

    package = Path(__file__).resolve().parent
    candidates = [package / "_runtime"]
    if package.parent.name == "python":
        candidates.insert(0, package.parent.parent)
    for root in candidates:
        if (root / "dist" / executable).is_file():
            return root

    searched = ", ".join(str(root / "dist" / executable) for root in candidates)
    installation = ("Install the Windows x64 wheel" if os.name == "nt" else
                    "Install the macOS 27+ ARM64 wheel or build the native runtime")
    raise FileNotFoundError(
        f"ruyijs runtime is missing. {installation}, or set RUYIJS_SHELL to an "
        "existing ruyijs executable. "
        f"Searched: {searched}"
    )
