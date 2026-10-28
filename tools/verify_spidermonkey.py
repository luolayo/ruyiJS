"""Verify the freshly built ARM64 engine and the product's existing value codec."""

import json
import re
import subprocess

from spidermonkey_source import OBJECTS, OUTPUT, ROOT, digest


def main():
    shell = OBJECTS / "dist/bin/js"
    architecture = subprocess.check_output(["lipo", "-archs", shell], text=True).strip()
    if architecture != "arm64":
        raise ValueError("Expected a native ARM64 shell, got: " + architecture)
    probe = ROOT / "tools/probes/spidermonkey_smoke.js"
    codec = ROOT / "src/runtime/codec.js"
    command = [str(shell), "--ion-eager", "--no-threads", str(probe), str(codec)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
    checks = json.loads(result.stdout.strip())
    if not checks or not all(checks.values()):
        raise ValueError("Engine smoke checks failed")
    api_tests = OBJECTS / "dist/bin/jsapi-tests"
    api = subprocess.run([str(api_tests), "UTF8"], capture_output=True, text=True,
                         timeout=60, check=True)
    count = re.search(r"Passed: ran (\d+) tests\.", api.stdout)
    if not count or int(count[1]) == 0:
        raise ValueError("No upstream UTF8 embedding tests ran")
    api_log = OUTPUT / "logs/jsapi-utf8.log"
    api_log.parent.mkdir(parents=True, exist_ok=True)
    api_log.write_text(api.stdout + api.stderr)
    report = {"command": command, "architecture": architecture, "checks": checks,
              "shell_sha256": digest(shell), "probe_sha256": digest(probe),
              "product_codec_sha256": digest(codec), "stderr": result.stderr,
              "upstream_jsapi_utf8": {"passed": int(count[1]), "log": str(api_log),
                                      "binary_sha256": digest(api_tests)},
              "product_runtime_linked": False}
    (OUTPUT / "engine-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
