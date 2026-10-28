"""Build Brotli and the URLPattern bridge using the pinned Mozilla source tree."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess

from build_spidermonkey import environment
import integrate_runtime_rust
from spidermonkey_source import SOURCE, OUTPUT, digest


def main():
    directory = OUTPUT / "dependencies"
    directory.mkdir(parents=True, exist_ok=True)
    llvm = Path("/opt/homebrew/opt/llvm")
    env = environment(llvm, Path("/opt/homebrew/opt/lld"))
    brotli = SOURCE / "modules/brotli"
    units = re.findall(r"'((?:common|dec|enc)/[^']+\.c)'", (brotli / "moz.build").read_text())
    def compile_one(unit):
        output = directory / (unit.replace("/", "_") + ".o")
        source = brotli / unit
        command = [str(llvm / "bin/clang"), "-std=c11", "-O2", "-mmacosx-version-min=26.0",
                   "-DBROTLI_BUILD_PORTABLE", "-I" + str(brotli / "include"), "-c", str(source), "-o", str(output)]
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        if result.returncode: raise RuntimeError(result.stderr)
        return output
    with ThreadPoolExecutor(max_workers=4) as pool:
        objects = list(pool.map(compile_one, units))
    subprocess.run([llvm / "bin/llvm-ar", "rcs", directory / "libbrotli.a", *objects], check=True)
    integrate_runtime_rust.build()
    rust = json.loads((OUTPUT / "runtime-rust.json").read_text())
    libraries = [directory / "libbrotli.a", Path(rust["library"]),
                 Path("/opt/homebrew/opt/openssl@3/lib/libcrypto.dylib")]
    report = {"brotli_units": len(units), "libraries": [{"path": str(p), "sha256": digest(p)}
              for p in libraries]}
    (OUTPUT / "native-dependencies.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
