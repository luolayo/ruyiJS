"""Measure the five required environment groups in an isolated Firefox 158 profile."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from firefox_reference import Firefox
import product_sources
from spidermonkey_source import LOCK, OUTPUT, ROOT, digest


class ReferencePage(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><meta charset=utf-8><title>ruyiJS reference</title>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firefox", type=Path,
                        default=ROOT / "build/reference/Firefox.app/Contents/MacOS/firefox")
    args = parser.parse_args()
    version = subprocess.check_output([args.firefox, "--version"], text=True).strip()
    if version != "Mozilla Firefox " + LOCK["version"]:
        raise ValueError("Reference Firefox version differs from source lock: " + version)
    schema = (ROOT / "src/browser_environment/model.h").read_text()
    fields = {}
    for name in ("Navigator", "Screen"):
        body = re.search(r"k" + name + r"Fields\[\] = \{(.*?)\n\};", schema, re.S)
        fields[name.lower()] = re.findall(r'\{"([^"]+)", ValueType::', body[1])
    expression = '''({
      navigator:Object.fromEntries(NAV.map(key=>[key,navigator[key]])),
      screen:Object.fromEntries(SCREEN.map(key=>[key,screen[key]])),
      viewport:{width:innerWidth,height:innerHeight,devicePixelRatio},
      location:{href:location.href},
      locale:{timezone:Intl.DateTimeFormat().resolvedOptions().timeZone}
    })'''.replace("NAV", json.dumps(fields["navigator"])).replace("SCREEN", json.dumps(fields["screen"]))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with ThreadingHTTPServer(("127.0.0.1", 0), ReferencePage) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="reference-profile-", dir=OUTPUT) as directory:
                with Firefox(args.firefox, Path(directory) / "profile", prefs={
                        "app.update.auto": False, "app.update.disabledForTesting": True}) as browser:
                    browser.navigate(f"http://127.0.0.1:{server.server_port}/")
                    profile = browser.evaluate(expression)
                    capabilities = browser.capabilities
        finally:
            server.shutdown()
            thread.join()
    for group, expected in fields.items():
        if set(profile[group]) != set(expected):
            raise ValueError("Reference is missing required fields: " + group)
    reference = OUTPUT / "reference"
    (reference / "profiles").mkdir(parents=True, exist_ok=True)
    path = reference / "profiles/firefox-environment.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
    generated = OUTPUT / "generated"
    generated.mkdir(exist_ok=True)
    product_sources.profile(reference, generated)
    report = {"reference_version": version, "executable_sha256": digest(args.firefox),
              "headless": True, "automation": "Marionette; webdriver is retained as observed",
              "capabilities": capabilities, "profile": str(path), "profile_sha256": digest(path),
              "generated_header": str(generated / "firefox_environment_profile.h"),
              "generated_header_sha256": digest(generated / "firefox_environment_profile.h"),
              "publishable_default_profile": False}
    (OUTPUT / "environment-baseline.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"version": version, "fields": {k: len(v) for k, v in profile.items()},
                      "observed_webdriver": profile["navigator"]["webdriver"]}, indent=2))


if __name__ == "__main__":
    main()
