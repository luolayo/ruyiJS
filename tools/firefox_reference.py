"""An owned Firefox process with a fresh profile and minimal Marionette transport."""
import json
import os
from pathlib import Path
import socket
import subprocess
from time import monotonic, sleep


class Firefox:
    def __init__(self, executable, profile, timeout=40, extra_args=(), prefs=None,
                 extra_environment=None):
        self.socket = self.process = self.log = None
        self.sequence = 0
        self.timeout = timeout
        profile = Path(profile).resolve()
        profile.mkdir(parents=True, exist_ok=False)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        prefs = {"marionette.port": port, "marionette.enabled": True,
                 "network.dns.localDomains": "parity.test", "network.proxy.type": 0,
                 "browser.shell.checkDefaultBrowser": False,
                 "browser.startup.homepage_override.mstone": "ignore",
                 "datareporting.policy.dataSubmissionEnabled": False, **(prefs or {})}
        (profile / "user.js").write_text("\n".join(
            f"user_pref({json.dumps(k)}, {json.dumps(v)});" for k, v in prefs.items()), "utf-8")
        environment = {k: v for k, v in os.environ.items() if not k.startswith("MOZ_DOM_")}
        environment.update(extra_environment or {})
        environment["MOZ_HEADLESS"] = "1"
        self.log = (profile.parent / "firefox.log").open("wb")
        try:
            self.process = subprocess.Popen(
                [str(executable), "--headless", "--no-remote", "--new-instance",
                 "--profile", str(profile), "--marionette", *extra_args, "about:blank"],
                stdout=self.log, stderr=self.log, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, env=environment)
            deadline = monotonic() + timeout
            while monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(f"Firefox exited: {self.process.returncode}")
                try:
                    self.socket = socket.create_connection(("127.0.0.1", port), timeout=1)
                    break
                except OSError:
                    sleep(.1)
            else:
                raise TimeoutError("Firefox Marionette startup deadline exceeded")
            self.socket.settimeout(timeout)
            self.handshake = self.receive()
            self.capabilities = self.command("WebDriver:NewSession", {
                "capabilities": {"alwaysMatch": {"acceptInsecureCerts": False}}})
            self.command("WebDriver:SetTimeouts", {"script": 120000, "pageLoad": 40000})
        except BaseException:
            self.close()
            raise

    def receive(self):
        prefix = b""
        while not prefix.endswith(b":"):
            part = self.socket.recv(1)
            if not part or len(prefix) > 12:
                raise RuntimeError("Invalid Marionette frame header")
            prefix += part
        length = int(prefix[:-1])
        if not 0 <= length <= 64 * 1024 * 1024:
            raise ValueError("Marionette frame exceeds bound")
        payload = bytearray()
        while len(payload) < length:
            part = self.socket.recv(min(65536, length - len(payload)))
            if not part:
                raise EOFError("Marionette disconnected")
            payload.extend(part)
        return json.loads(payload)

    def command(self, name, arguments):
        self.sequence += 1
        payload = json.dumps([0, self.sequence, name, arguments], ensure_ascii=True).encode()
        self.socket.sendall(str(len(payload)).encode() + b":" + payload)
        reply = self.receive()
        if reply[:2] != [1, self.sequence]:
            raise RuntimeError("Marionette response identity mismatch")
        if reply[2]:
            raise RuntimeError(json.dumps(reply[2], ensure_ascii=False))
        return reply[3]

    def navigate(self, url):
        return self.command("WebDriver:Navigate", {"url": url})

    def evaluate(self, expression):
        # No sandbox: inspect the actual content global, avoiding Xray wrappers.
        response = self.command("WebDriver:ExecuteScript", {
            "script": "return " + expression + ";", "args": [], "sandbox": None,
            "newSandbox": True, "filename": "firefox_parity", "line": 1})
        return response["value"]

    def close(self):
        if self.socket:
            try:
                self.command("Marionette:Quit", {"flags": ["eForceQuit"]})
            except Exception:
                pass
            self.socket.close()
            self.socket = None
        if self.process and self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
