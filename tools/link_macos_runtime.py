"""Link the product runtime with its original shell hooks and all browser owners."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

from build_spidermonkey import environment, run_logged
import product_sources
from spidermonkey_source import ROOT, OBJECTS, OUTPUT, digest


def main():
    report = json.loads((OUTPUT / "runtime-compile.json").read_text())
    expected = {"shell0", *(name for _, name in product_sources.sources(ROOT))}
    if report["failed"] or {r["name"] for r in report["sources"]} != expected:
        raise ValueError("A successful complete product compilation is required")
    product = []
    for row in report["sources"]:
        path = Path(row["object"])
        stamp = json.loads(path.with_suffix(".json").read_text())
        if not path.is_file() or any(not Path(p).exists() or Path(p).stat().st_mtime_ns != m
                                    for p, m in stamp["dependencies"].items()):
            raise ValueError("Recompile changed inputs before linking: " + row["name"])
        product.append(str(path))
    shell = OBJECTS / "js/src/shell"
    donor = [(shell / line.strip()).resolve() for line in (shell / "js.list").read_text().splitlines() if line.strip()]
    donor = [p for p in donor if p.name != "Unified_cpp_js_src_shell0.o"]
    libraries = [OUTPUT / "dependencies/libbrotli.a",
                 OBJECTS / "js/src/build/libjs_static.a", OBJECTS / "build/pure_virtual/libpure_virtual.a",
                 OBJECTS / "aarch64-apple-darwin/release/libjsrust.a"]
    for path in donor + libraries:
        if not path.is_file(): raise FileNotFoundError(path)
    env = environment(Path("/opt/homebrew/opt/llvm"), Path("/opt/homebrew/opt/lld"))
    target = json.loads((ROOT / "config/macos-runtime.json").read_text())["link_deployment_target"]
    output = ROOT / "dist/js"
    output.parent.mkdir(exist_ok=True)
    candidate = output.with_name("js.candidate")
    sdk = subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip()
    command = [env["CXX"], "-isysroot", sdk, "-mmacosx-version-min=" + target,
               "-stdlib=libc++", "-fuse-ld=lld", "-Wl,-dead_strip", "-o", str(candidate),
               *product, *map(str, donor + libraries), "-lm", "-lresolv", "-lz",
               "/opt/homebrew/opt/openssl@3/lib/libcrypto.dylib",
               "-framework", "CoreFoundation", "-framework", "CoreGraphics",
               "-framework", "CoreText", "-framework", "ImageIO"]
    response = OUTPUT / "runtime-link.rsp"
    response.write_text("\n".join(shlex.quote(a) for a in command[1:]) + "\n")
    result = run_logged([command[0], "@" + str(response)], ROOT, env, "runtime-link")
    architecture = subprocess.check_output(["lipo", "-archs", candidate], text=True).strip()
    if architecture != "arm64": raise ValueError("Product binary is not ARM64")
    candidate.replace(output)
    result.update(executable=str(output), sha256=digest(output), architecture=architecture,
                  product_units=len(product), deployment_target=target,
                  dependencies=subprocess.check_output(["otool", "-L", output], text=True).splitlines())
    (OUTPUT / "runtime-link.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k:result[k] for k in ("executable", "sha256", "architecture", "product_units")}, indent=2))


if __name__ == "__main__":
    main()
