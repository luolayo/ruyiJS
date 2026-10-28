"""Add the product FFI to Mozilla's one Rust static library using recorded source edits."""
import json
import hashlib
from pathlib import Path
import sys

from build_spidermonkey import environment, run_logged
from spidermonkey_source import ROOT, SOURCE, OBJECTS, OUTPUT, digest


def build():
    config = json.loads((ROOT / "config/rust-runtime-overlay.json").read_text())
    additions = {
        "js/src/rust/Cargo.toml": '\nruyijs_urlpattern = { path = ' + json.dumps(str(ROOT / config["dependency"])) + ' }\n',
        "js/src/rust/lib.rs": '\nextern crate ruyijs_urlpattern;\n',
    }
    records = []
    for name, addition in additions.items():
        path = SOURCE / name
        current = path.read_text()
        if digest(path) == config["base_files"][name]:
            path.write_text(current + addition)
        elif (not current.endswith(addition) or
              hashlib.sha256(current[:-len(addition)].encode()).hexdigest() != config["base_files"][name]):
            raise ValueError("Unexpected donor edit: " + name)
        records.append({"path": name, "base_sha256": config["base_files"][name], "prepared_sha256": digest(path)})
    env = environment(Path("/opt/homebrew/opt/llvm"), Path("/opt/homebrew/opt/lld"))
    run_logged(["cargo", "metadata", "--offline", "--format-version", "1", "--no-deps",
                "--manifest-path", str(SOURCE / "js/src/rust/Cargo.toml")], OBJECTS, env, "runtime-rust-lock")
    run_logged([sys.executable, str(SOURCE / "mach"), "build", "js/src/rust", "--allow-subdirectory-build", "-j4"],
               SOURCE, env, "runtime-rust-build")
    library = OBJECTS / "aarch64-apple-darwin/release/libjsrust.a"
    report = {"overlay": records, "cargo_lock_sha256": digest(SOURCE / "Cargo.lock"),
              "library": str(library), "library_sha256": digest(library),
              "rust_runtime_owners": 1}
    (OUTPUT / "runtime-rust.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    build()
