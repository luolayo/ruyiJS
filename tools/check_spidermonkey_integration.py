"""Compile the real ruyiJS shell hooks and adapters against the pinned engine."""

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
from types import SimpleNamespace

from build_spidermonkey import environment, run_logged
from generate import generate
import product_sources
from spidermonkey_source import LOCK, OBJECTS, OUTPUT, ROOT, SOURCE, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm", type=Path, default=Path("/opt/homebrew/opt/llvm"))
    parser.add_argument("--lld", type=Path, default=Path("/opt/homebrew/opt/lld"))
    args = parser.parse_args()
    env = environment(args.llvm, args.lld)
    generated = OUTPUT / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    donor = SimpleNamespace(src=SOURCE, shell=OBJECTS / "js/src/shell")
    unit, inputs = generate(donor, ROOT, generated)
    entries = json.loads((OBJECTS / "compile_commands.json").read_text())
    entry, = [item for item in entries if item["file"] == str(donor.shell / unit.name)]
    base = shlex.split(entry["command"])
    if (Path(entry["directory"]) / base[-1]).resolve() != Path(entry["file"]):
        raise ValueError("Unexpected shell compile command source argument")
    base.pop()
    base += ["-I" + str(ROOT / "src"), "-I" + str(generated),
             "-I" + str(SOURCE / "js/src/shell")]
    output_index = base.index("-o") + 1
    directory = OUTPUT / "integration"
    directory.mkdir(parents=True, exist_ok=True)
    targets = [(unit, "shell0"), (ROOT / "src/runtime/arguments.cpp", "arguments"),
               (ROOT / "src/runtime/protocol.cpp", "protocol"),
               (ROOT / "src/browser_environment/schema.cpp", "environment_schema"),
               (ROOT / "src/browser_environment/snapshot.cpp", "environment_snapshot"),
               (ROOT / "src/runtime/binding_order_table.cpp", "binding_order"),
               (ROOT / "src/document_model/sanitizer_config.cpp", "sanitizer_config")]
    records = []
    for source, name in targets:
        command = list(base)
        output = directory / (name + ".o")
        command[output_index] = str(output)
        command.append(str(source))
        record = run_logged(command, Path(entry["directory"]), env, "integration-" + name)
        record.update(source=str(source), source_sha256=digest(source),
                      object=str(output), object_sha256=digest(output))
        records.append(record)
    undefined = subprocess.check_output([args.llvm / "bin/llvm-nm", "-u", "-C",
                                          directory / "shell0.o"], text=True)
    windows = re.compile(r'#\s*include\s*[<"](?:windows|bcrypt|dwrite(?:_\d+)?|d2d1|wincodec)\.h', re.I)
    platform_files = [p.relative_to(ROOT).as_posix() for domain in product_sources.domains(ROOT)
                      for p in (ROOT / "src" / domain).iterdir()
                      if p.suffix in (".cpp", ".h") and windows.search(p.read_text())]
    report = {"source": LOCK, "objects": records,
              "generator_inputs": [{"path": str(p), "sha256": digest(p)} for p in inputs],
              "shell_product_symbols": [line.strip() for line in undefined.splitlines() if "ruyijs::" in line],
              "production_units": len(product_sources.sources(ROOT)),
              "files_including_windows_sdk_headers": sorted(platform_files),
              "product_runtime_linked": False,
              "remaining": ["native platform backends and Worker lifecycle",
                            "Necko native bridge and helper runtime",
                            "compression/image dependency manifests and URLPattern Rust bridge"]}
    (OUTPUT / "integration.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"compiled": [name for _, name in targets],
                      "product_runtime_linked": False,
                      "windows_sdk_files": len(platform_files)}, indent=2))


if __name__ == "__main__":
    main()
