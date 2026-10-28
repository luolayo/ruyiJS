"""Extract a checksum-pinned Firefox reference inside build/, without installing it."""

import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request

from spidermonkey_source import LOCK, ROOT, digest


def main():
    reference = LOCK["reference_browser"]
    archive = ROOT / "build/downloads" / ("Firefox-" + LOCK["version"] + ".dmg")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.is_file():
        partial = archive.with_suffix(".dmg.part")
        with urllib.request.urlopen(reference["url"], timeout=60) as response, partial.open("wb") as stream:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 512 * 1024 * 1024:
                    raise ValueError("Reference DMG exceeds 512 MiB")
                stream.write(block)
        if digest(partial) != reference["sha256"]:
            raise ValueError("Reference DMG checksum mismatch")
        partial.rename(archive)
    if digest(archive) != reference["sha256"]:
        raise ValueError("Cached reference DMG checksum mismatch")
    directory = ROOT / "build/reference"
    application = directory / "Firefox.app"
    executable = application / "Contents/MacOS/firefox"
    receipt = directory / "source.json"
    if application.exists():
        if not receipt.is_file():
            raise ValueError("Existing reference has no extraction receipt; it was not overwritten")
        previous = json.loads(receipt.read_text())
        if previous["archive_sha256"] != reference["sha256"] or previous["executable_sha256"] != digest(executable):
            raise ValueError("Existing reference identity differs from its receipt")
        print(executable)
        return
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="extract-", dir=directory) as temporary:
        mount = Path(temporary) / "volume"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount),
                        str(archive)], check=True, capture_output=True)
        try:
            staged = Path(temporary) / "Firefox.app"
            subprocess.run(["ditto", str(mount / "Firefox.app"), str(staged)], check=True)
            staged.rename(application)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True, capture_output=True)
    version = subprocess.check_output([executable, "--version"], text=True).strip()
    if version != "Mozilla Firefox " + LOCK["version"]:
        raise ValueError("Extracted reference version mismatch")
    receipt.write_text(json.dumps({"url": reference["url"], "archive_sha256": reference["sha256"],
                                   "executable_sha256": digest(executable), "version": version}, indent=2) + "\n")
    print(executable)


if __name__ == "__main__":
    main()
