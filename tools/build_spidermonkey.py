"""Build the pinned upstream ARM64 engine; never install it as the ruyiJS runtime."""

import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from spidermonkey_source import LOCK, OBJECTS, OUTPUT, ROOT, SOURCE, digest, prepare


def environment(llvm, lld):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("This build entry requires native ARM64 macOS")
    if sys.version_info[:2] != tuple(map(int, LOCK["python_minor"].split("."))):
        raise RuntimeError("Run this entry with Python " + LOCK["python_minor"])
    compiler = llvm / "bin/clang"
    linker = lld / "bin/ld64.lld"
    if not compiler.is_file() or not linker.is_file():
        raise FileNotFoundError("LLVM clang and LLD are required; see docs/macos-arm64-port.md")
    env = dict(os.environ)
    env.update(MOZCONFIG=str(ROOT / "config/mozconfig.macos-arm64"),
               RUYIJS_OBJDIR=str(OBJECTS), MOZBUILD_STATE_PATH=str(ROOT / "build/mozilla-state"),
               CC=str(compiler), CXX=str(llvm / "bin/clang++"), MACH_TELEMETRY_NO_SUBMIT="1")
    env["PATH"] = os.pathsep.join((str(lld / "bin"), str(llvm / "bin"), env.get("PATH", "")))
    cbindgen = ROOT / "build/mozilla-state/cbindgen/cbindgen"
    if cbindgen.is_file():
        env["CBINDGEN"] = str(cbindgen)
    return env


def run_logged(command, cwd, env, name):
    logs = OUTPUT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = logs / f"{stamp}-{name}.log"
    print(f"{name}: {path}", flush=True)
    with path.open("w") as stream:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
    record = {"command": list(map(str, command)), "cwd": str(cwd),
              "exit_code": result.returncode, "log": str(path), "log_sha256": digest(path)}
    path.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
    if result.returncode:
        print(path.read_text(errors="replace")[-6000:])
        raise subprocess.CalledProcessError(result.returncode, command)
    return record


def toolchain(env):
    commands = {"clang": [env["CC"], "--version"], "lld": ["ld64.lld", "--version"],
                "rustc": ["rustc", "--version"], "sdk": ["xcrun", "--show-sdk-version"]}
    versions = {name: subprocess.check_output(command, env=env, text=True).strip()
                for name, command in commands.items()}
    versions["python"] = sys.version
    if env.get("CBINDGEN"):
        versions["cbindgen"] = subprocess.check_output([env["CBINDGEN"], "--version"], text=True).strip()
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "bootstrap", "configure", "build", "commands"))
    parser.add_argument("--jobs", type=int, choices=range(1, 17), default=4)
    parser.add_argument("--llvm", type=Path, default=Path("/opt/homebrew/opt/llvm"))
    parser.add_argument("--lld", type=Path, default=Path("/opt/homebrew/opt/lld"))
    args = parser.parse_args()
    source = prepare()
    if args.action == "prepare":
        print(source)
        return
    env = environment(args.llvm, args.lld)
    command = [sys.executable, str(SOURCE / "mach")]
    if args.action == "bootstrap":
        command += ["--no-interactive", "bootstrap", "--application-choice", "js",
                    "--no-system-changes", "--exclude", "clang", "rust"]
    elif args.action == "commands":
        command += ["build-backend", "-b", "CompileDB"]
    elif args.action == "build":
        command += ["build", f"-j{args.jobs}"]
    else:
        command += ["configure"]
    record = run_logged(command, source, env, "engine-" + args.action)
    report = {"source": LOCK, "toolchain": toolchain(env),
              "mozconfig_sha256": digest(ROOT / "config/mozconfig.macos-arm64"),
              "result": record, "product_runtime_built": False}
    config = OBJECTS / "config.status.json"
    if config.is_file():
        substs = json.loads(config.read_text())["substs"]
        report["target"] = {key: substs.get(key) for key in
                            ("target", "TARGET_CPU", "OS_ARCH", "JS_STANDALONE")}
    shell = OBJECTS / "dist/bin/js"
    if args.action == "build" and shell.is_file():
        report["upstream_shell"] = {"path": str(shell), "sha256": digest(shell),
                                    "version": subprocess.check_output([shell, "--version"], text=True).strip(),
                                    "architecture": subprocess.check_output(["file", shell], text=True).strip()}
    (OUTPUT / ("engine-" + args.action + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report.get("upstream_shell", report.get("target", {})), indent=2))


if __name__ == "__main__":
    main()
