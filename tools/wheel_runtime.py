"""Fetch and validate the pinned runtime only when building a wheel from source."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import urllib.parse
import urllib.request
import zipfile


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def validate(root):
    if not (root / "dist/js.exe").is_file():
        raise ValueError("Runtime archive has no dist/js.exe")
    if not (root / "vendor/necko-derived/python/python.exe").is_file():
        raise ValueError("Runtime archive has no embedded Python")
    expected = set()
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        sha, name = line.split("  ", 1)
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or name in expected:
            raise ValueError("Invalid runtime checksum path")
        if digest(path) != sha:
            raise ValueError(f"Runtime checksum mismatch: {name}")
        expected.add(name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
              if p.is_file() and p.name != "SHA256SUMS"}
    if expected != actual:
        raise ValueError("Runtime inventory differs from SHA256SUMS")


def download_url(manifest):
    if manifest.get("url"):
        if urllib.parse.urlparse(manifest["url"]).scheme != "https":
            raise ValueError("Runtime download must use HTTPS")
        return manifest["url"]
    request = urllib.request.Request(manifest["release_api"], headers={"User-Agent": "ruyijs-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    request = urllib.request.Request(
        manifest["releases_api"] + f'/{release["id"]}/attach_files',
        headers={"User-Agent": "ruyijs-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        attachments = json.load(response)
    for asset in attachments:
        if asset["name"] == manifest["archive"]:
            url = asset["browser_download_url"]
            if urllib.parse.urlparse(url).scheme != "https":
                raise ValueError("Runtime download must use HTTPS")
            return url
    raise FileNotFoundError(f'Runtime attachment missing: {manifest["archive"]}')


def obtain_runtime(project):
    manifest = json.loads((project / "runtime.json").read_text(encoding="utf-8"))
    supplied = os.environ.get("RUYIJS_BUILD_RUNTIME_ARCHIVE")
    cache = project / "build/pinned-runtime"
    if cache.exists():
        if digest(cache / "SHA256SUMS") != manifest["inventory_sha256"]:
            raise ValueError("Cached inventory differs from the pinned release")
        validate(cache)
        if digest(cache / "dist/js.exe") != manifest["shell_sha256"]:
            raise ValueError("Cached runtime shell differs from the pinned release")
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ruyijs-wheel-", dir=cache.parent) as temporary:
        temporary = Path(temporary).resolve()
        if not temporary.is_relative_to(cache.parent.resolve()):
            raise ValueError("Build temporary directory escaped the build root")
        archive = Path(supplied).resolve() if supplied else temporary / manifest["archive"]
        if not supplied:
            request = urllib.request.Request(download_url(manifest), headers={"User-Agent": "ruyijs-build"})
            with urllib.request.urlopen(request, timeout=180) as response, archive.open("wb") as output:
                size = 0
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > manifest["size"]:
                        raise ValueError("Runtime download exceeds its pinned size")
                    output.write(block)
        if archive.stat().st_size != manifest["size"] or digest(archive) != manifest["sha256"]:
            raise ValueError("Runtime archive size or SHA256 differs from the pinned release")
        unpacked = temporary / "unpacked"
        unpacked.mkdir()
        with zipfile.ZipFile(archive) as source:
            if sum(i.file_size for i in source.infolist()) > manifest["unpacked_limit"]:
                raise ValueError("Runtime archive exceeds the extraction limit")
            for entry in source.infolist():
                path = PurePosixPath(entry.filename)
                if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                        or ":" in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("Invalid runtime archive entry")
            source.extractall(unpacked)
        if digest(unpacked / "SHA256SUMS") != manifest["inventory_sha256"]:
            raise ValueError("Runtime inventory differs from the pinned release")
        validate(unpacked)
        if digest(unpacked / "dist/js.exe") != manifest["shell_sha256"]:
            raise ValueError("Runtime shell differs from the pinned release")
        unpacked.rename(cache)
    return cache
