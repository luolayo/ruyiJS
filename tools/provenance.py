"""Input identity, including external members of LLVM thin archives."""

import hashlib
import json
import os
from pathlib import Path


# SHA256 by (path, size, mtime_ns): an unchanged file is not read again across
# builds. A file whose size or mtime differs is always rehashed.
_CACHE_FILE = Path(__file__).resolve().parents[1] / "build" / "hash-cache.json"
_cache = None


def _hash_cache():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def write_if_changed(path, text, encoding="utf-8", newline=None):
    """Write a generated file only when its bytes change, keeping mtime stable."""
    path = Path(path)
    # Same newline translation as Path.write_text(text, newline=newline).
    if newline is None:
        text = text.replace("\n", os.linesep)
    elif newline:
        text = text.replace("\n", newline)
    data = text.encode(encoding)
    try:
        if path.read_bytes() == data:
            return
    except OSError:
        pass
    path.write_bytes(data)


def save_hash_cache():
    if _cache is not None:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(_cache), encoding="utf-8")


def digest(path):
    path = Path(path)
    stat = path.stat()
    key, stamp = str(path.resolve()), [stat.st_size, stat.st_mtime_ns]
    entry = _hash_cache().get(key)
    if entry and entry[:2] == stamp:
        return entry[2]
    with path.open("rb") as stream:
        value = hashlib.file_digest(stream, "sha256").hexdigest()
    _hash_cache()[key] = [*stamp, value]
    return value


def thin_members(path):
    path = Path(path)
    with path.open("rb") as stream:
        if stream.read(8) != b"!<thin>\n":
            return []
        names = b""
        members = []
        while header := stream.read(60):
            if len(header) != 60 or header[58:] != b"`\n":
                raise ValueError(f"invalid thin archive: {path}")
            name = header[:16].decode("ascii").strip()
            size = int(header[48:58])
            if name in ("/", "//", "/SYM64/"):
                data = stream.read(size)
                if name == "//":
                    names = data
                if size % 2:
                    stream.read(1)
                continue
            if name.startswith("/") and name[1:].isdigit():
                start = int(name[1:])
                end = names.find(b"/\n", start)
                if end < 0:
                    raise ValueError(f"invalid thin member name: {path}")
                name = names[start:end].decode("utf-8")
            else:
                name = name.rstrip("/")
            members.append((path.parent / name).resolve())
        return members


def inventory(paths):
    expanded = set(Path(path).resolve() for path in paths)
    for path in list(expanded):
        if path.suffix.lower() == ".lib":
            expanded.update(thin_members(path))
    result = []
    for path in sorted(expanded):
        stat = path.stat()
        result.append({"path": str(path), "size": stat.st_size,
                       "mtime_ns": stat.st_mtime_ns, "sha256": digest(path)})
    return result


def verify_unchanged(records, rehash=False):
    for record in records:
        path = Path(record["path"])
        stat = path.stat()
        if stat.st_size != record["size"] or stat.st_mtime_ns != record["mtime_ns"]:
            raise RuntimeError(f"build input changed during build: {path}")
        if rehash and digest(path) != record["sha256"]:
            raise RuntimeError(f"build input SHA changed during build: {path}")
