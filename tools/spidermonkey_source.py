"""Acquire the official source archive pinned in config/spidermonkey.lock.json."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "config/spidermonkey.lock.json").read_text())
SOURCE = ROOT / "build/upstream" / LOCK["source_directory"]
OBJECTS = ROOT / "build/spidermonkey-arm64"
OUTPUT = ROOT / "build/macos-arm64"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare():
    archive = ROOT / "build/downloads" / LOCK["source_url"].rsplit("/", 1)[1]
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        partial = archive.with_suffix(".xz.part")
        with urllib.request.urlopen(LOCK["source_url"], timeout=60) as response, partial.open("wb") as output:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 1024 * 1024 * 1024:
                    raise ValueError("Source archive exceeds 1 GiB")
                output.write(block)
        if digest(partial) != LOCK["source_sha256"]:
            raise ValueError("Downloaded Mozilla source SHA256 mismatch")
        partial.rename(archive)
    if digest(archive) != LOCK["source_sha256"]:
        raise ValueError("Cached Mozilla source SHA256 mismatch")
    receipt = SOURCE.parent / (SOURCE.name + ".source.json")
    expected = {"url": LOCK["source_url"], "sha256": LOCK["source_sha256"]}
    if SOURCE.exists():
        if not receipt.is_file() or json.loads(receipt.read_text()) != expected:
            raise ValueError(f"Source directory has no matching extraction receipt: {SOURCE}")
        return SOURCE
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="extract-", dir=SOURCE.parent) as temporary:
        subprocess.run(["tar", "-xJf", str(archive), "-C", temporary], check=True)
        extracted = Path(temporary) / LOCK["source_directory"]
        if not (extracted / "mach").is_file():
            raise ValueError("Unexpected Mozilla source layout")
        extracted.rename(SOURCE)
    receipt.write_text(json.dumps(expected, indent=2) + "\n")
    return SOURCE
