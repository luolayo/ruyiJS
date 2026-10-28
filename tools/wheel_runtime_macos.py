"""Consume a prepared Mac runtime; wheel metadata queries never build/download it."""
import json
import os
from pathlib import Path

from wheel_runtime import digest

PLATFORM = "macosx_27_0_arm64"


def validate(root, *, installed=False):
    root = Path(root).resolve()
    manifest = json.loads((root / "runtime-manifest.json").read_text())
    if manifest.get("platform") != PLATFORM or manifest.get("format") != 1:
        raise ValueError("Not a macOS ARM64 runtime bundle")
    expected = set()
    for line in (root / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ", 1)
        path = root / name
        if not path.resolve().is_relative_to(root) or name in expected or path.is_symlink():
            raise ValueError("Invalid runtime checksum path: " + name)
        if digest(path) != checksum:
            raise ValueError("Runtime checksum mismatch: " + name)
        expected.add(name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
              if p.is_file() and p.name != "SHA256SUMS"
              and not (installed and p.suffix == ".pyc" and p.parent.name == "__pycache__")}
    if actual != expected:
        raise ValueError("Runtime inventory differs from SHA256SUMS")
    required = {"dist/js", "vendor/necko-derived/bin/python3", "lib/libcrypto.3.dylib"}
    if not required <= expected:
        raise ValueError("Runtime is missing its engine, embedded Python or OpenSSL")
    for name in manifest["executable_files"]:
        if name not in expected or not os.access(root / name, os.X_OK):
            raise ValueError("Runtime executable permission missing: " + name)
    return manifest


def obtain_runtime(project):
    root = Path(os.environ.get("RUYIJS_BUILD_MACOS_RUNTIME", project / "build/macos-arm64/wheel-runtime")).resolve()
    if not (root / "SHA256SUMS").is_file():
        raise FileNotFoundError("Prepare the Mac bundle with python3.13 -B tools/build_macos_wheel.py first, "
                                "or set RUYIJS_BUILD_MACOS_RUNTIME to a validated bundle directory")
    validate(root)
    return root
