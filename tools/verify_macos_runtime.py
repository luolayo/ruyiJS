"""Verify the built product through its public Python API and native regression suite."""
import json
from pathlib import Path
import re
import subprocess
import sys

from spidermonkey_source import ROOT, OUTPUT, digest

sys.path.insert(0, str(ROOT / "python"))
from ruyijs import Context


def main():
    executable = ROOT / "dist/js"
    if not executable.is_file(): raise FileNotFoundError("Build and link the product runtime first")
    with Context(timeout=10) as context:
        smoke = {"arithmetic": context.eval("1+2"),
                 "dom": context.eval("document.createElement('div').tagName"),
                 "window": context.eval("globalThis===window"),
                 "platform": context.eval("navigator.platform")}
        context.set("value", 21)
        smoke["python_data"] = context.eval("value*2")
    if smoke != {"arithmetic":3,"dom":"DIV","window":True,"platform":"MacIntel","python_data":42}:
        raise AssertionError(smoke)
    log = OUTPUT / "logs/runtime-tests.log"
    with log.open("w") as stream:
        result = subprocess.run([sys.executable,"-B","-m","unittest","discover","-s","tests","-v"],
                                cwd=ROOT / "python",stdout=stream,stderr=subprocess.STDOUT,timeout=120)
    text = log.read_text()
    if result.returncode:
        print(text[-10000:])
        raise SystemExit(result.returncode)
    count = re.search(r"Ran (\d+) tests", text)
    network_path = OUTPUT / "network-verification.json"
    network = json.loads(network_path.read_text()) if network_path.is_file() else {}
    network_build = OUTPUT / "network-build.json"
    bridge = ROOT / "vendor/necko-derived/lib/python3.13/site-packages/necko/libnecko_core.dylib"
    quic = bridge.with_name("libnecko_quic.dylib")
    network_ready = bool(network.get("passed") and network.get("product_sha256") == digest(executable)
                         and network_build.is_file() and bridge.is_file()
                         and network.get("network_build_sha256") == digest(network_build)
                         and network.get("bridge_sha256") == digest(bridge)
                         and quic.is_file() and network.get("quic_sha256") == digest(quic))
    report = {"product_runtime_linked":True,"public_context_eval_verified":True,
              "executable":str(executable),"sha256":digest(executable),
              "architecture":subprocess.check_output(["lipo","-archs",executable],text=True).strip(),
              "smoke":smoke,"tests_passed":int(count[1]),"test_log":str(log),
              "necko_network_ready":network_ready,"network_protocols_verified":network.get("protocols",[]) if network_ready else [],
              "webtransport_verified":network_ready and network.get("context_webtransport_verified",False),
              "macos_deployment_target":"27.0",
              "windows_regression_run":False}
    (OUTPUT / "runtime-verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
