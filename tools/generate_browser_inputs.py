"""Generate ruyiJS tables from the pinned Firefox browser build configuration."""

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import binding_order
import geometry_fonts
import sanitizer_data
from build_spidermonkey import environment, run_logged
from spidermonkey_source import LOCK, OUTPUT, ROOT, SOURCE, digest, prepare

OBJECTS = ROOT / "build/firefox-inputs-arm64"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "export", "generate"))
    parser.add_argument("--jobs", type=int, choices=range(1, 9), default=2)
    parser.add_argument("--llvm", type=Path, default=Path("/opt/homebrew/opt/llvm"))
    parser.add_argument("--lld", type=Path, default=Path("/opt/homebrew/opt/lld"))
    args = parser.parse_args()
    prepare()
    env = environment(args.llvm, args.lld)
    env.update(MOZCONFIG=str(ROOT / "config/mozconfig.browser-inputs.macos-arm64"),
               RUYIJS_OBJDIR=str(OBJECTS))
    if args.action != "generate":
        command = [sys.executable, str(SOURCE / "mach")]
        command += ["configure"] if args.action == "configure" else ["build", "export", f"-j{args.jobs}"]
        run_logged(command, SOURCE, env, "browser-inputs-" + args.action)
        if args.action == "export":
            run_logged([sys.executable, str(SOURCE / "mach"), "build", "modules/libpref/misc",
                        f"-j{args.jobs}"], SOURCE, env, "browser-font-inputs")
        return
    generated = OUTPUT / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    inputs = binding_order.prepare(OBJECTS / "dom/bindings", generated)
    _, font_inputs = geometry_fonts.prepare(SimpleNamespace(src=SOURCE), generated,
                                             OBJECTS / "dist/bin/greprefs.js")
    inputs += font_inputs + sanitizer_data.prepare(SOURCE, generated)
    report = {"source": LOCK, "inputs": [{"path": str(p), "sha256": digest(p)} for p in inputs],
              "outputs": [{"path": str(p), "sha256": digest(p)} for p in sorted(generated.glob("firefox_*.h"))]}
    (OUTPUT / "browser-inputs.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["outputs"], indent=2))


if __name__ == "__main__":
    main()
