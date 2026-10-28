"""Compile the complete product source inventory against the ARM64 donor."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time
from types import SimpleNamespace

from build_spidermonkey import environment
from generate import generate
import product_sources
from spidermonkey_source import OBJECTS, OUTPUT, ROOT, SOURCE, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, choices=range(1, 17), default=4)
    parser.add_argument("--match", default="")
    args = parser.parse_args()
    env = environment(Path("/opt/homebrew/opt/llvm"), Path("/opt/homebrew/opt/lld"))
    generated = OUTPUT / "generated"
    unit, _ = generate(SimpleNamespace(src=SOURCE, shell=OBJECTS / "js/src/shell"), ROOT, generated)
    entry, = [x for x in json.loads((OBJECTS / "compile_commands.json").read_text())
              if x["file"] == str(OBJECTS / "js/src/shell" / unit.name)]
    base = shlex.split(entry["command"])
    base.pop()
    target = json.loads((ROOT / "config/macos-runtime.json").read_text())["deployment_target"]
    base = ["-mmacosx-version-min=" + target if a.startswith("-mmacosx-version-min=") else a for a in base]
    base += ["-I" + str(ROOT / "src"), "-I" + str(generated),
             "-I" + str(SOURCE / "js/src/shell"), "-I" + str(SOURCE / "gfx/harfbuzz/src"),
             "-I/opt/homebrew/opt/openssl@3/include", "-ferror-limit=3"]
    directory = OUTPUT / "runtime-objects"
    directory.mkdir(parents=True, exist_ok=True)
    sources = [(unit, "shell0"), *product_sources.sources(ROOT)]
    sources = [(p, n) for p, n in sources if args.match in n]

    def compile_one(item):
        source, name = item
        output = directory / (name + ".o")
        log = directory / (name + ".log")
        stamp = directory / (name + ".json")
        dependency = directory / (name + ".d")
        command = list(base)
        if source.name == "compression_brotli.cpp":
            command += ["-I" + str(SOURCE / "modules/brotli/include")]
        command[command.index("-o") + 1] = str(output)
        if product_sources.needs_exceptions(source):
            command = [a for a in command if a != "-fno-exceptions"] + ["-fexceptions"]
        command += ["-MMD", "-MF", str(dependency), str(source)]
        signature = hashlib.sha256(json.dumps([command, digest(source)]).encode()).hexdigest()
        if output.exists() and stamp.exists():
            old = json.loads(stamp.read_text())
            if old["signature"] == signature and all(Path(p).exists() and Path(p).stat().st_mtime_ns == m
                                                      for p, m in old["dependencies"].items()):
                return {"source": str(source), "name": name, "status": "cached", "object": str(output)}
        with log.open("w") as stream:
            result = subprocess.run(command, cwd=entry["directory"], env=env, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            return {"source": str(source), "name": name, "status": "failed", "log": str(log)}
        deps = shlex.split(dependency.read_text().replace("\\\n", " ").split(": ", 1)[1])
        paths = [(Path(entry["directory"]) / p).resolve() for p in deps]
        stamp.write_text(json.dumps({"signature": signature,
                                    "dependencies": {str(p): p.stat().st_mtime_ns for p in paths}}))
        return {"source": str(source), "name": name, "status": "compiled", "object": str(output)}

    records = []
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(compile_one, item) for item in sources]
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            if record["status"] == "failed":
                print("FAILED " + record["name"], flush=True)
            elif len(records) % 100 == 0:
                print(f"Processed {len(records)}/{len(sources)} units", flush=True)
    report = {"seconds": time.monotonic() - start, "sources": sorted(records, key=lambda x: x["name"]),
              "failed": sum(x["status"] == "failed" for x in records), "linked": False}
    (OUTPUT / "runtime-compile.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"units": len(records), "failed": report["failed"], "seconds": report["seconds"]}), flush=True)
    return bool(report["failed"])


if __name__ == "__main__":
    raise SystemExit(main())
