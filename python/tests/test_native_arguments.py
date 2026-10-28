"""Check UTF-8 argv/files and process-specific trace paths on macOS."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "darwin", "macOS native arguments")
class NativeArgumentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="ruyijs-arguments-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.executable = Path(cls.directory.name) / "arguments"
        subprocess.run(["xcrun", "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I" + str(ROOT / "src"), str(ROOT / "src/runtime/arguments.cpp"),
                        str(Path(__file__).with_name("native_arguments_probe.cpp")),
                        "-o", str(cls.executable)], check=True, capture_output=True, timeout=30)
        cls.script = Path(cls.directory.name) / "中文 空格.js"
        cls.script.write_text("const value = '中文🦊';", encoding="utf-8")

    def run_probe(self, *args):
        env = dict(os.environ, RUYIJS_TRACE_FILE="/tmp/env-{pid}.json")
        env.pop("MOZ_JS_STANDALONE_TRACE_FILE", None)
        return subprocess.check_output([self.executable, *args], env=env, text=True, timeout=5).splitlines()

    def test_utf8_file_and_environment_trace_pid(self):
        lines = self.run_probe("--ruyijs-runtime", self.script)
        self.assertEqual(lines[1:3], ["--ruyijs-runtime", str(self.script)])
        self.assertEqual(lines[3], "--trace-file=/tmp/env-" + lines[0] + ".json")
        self.assertEqual(lines[4], "const value = '中文🦊';")

    def test_explicit_trace_path_takes_precedence(self):
        lines = self.run_probe("--ruyijs-runtime", self.script, "--trace-file", "/tmp/显式-{pid}.json")
        self.assertEqual(lines[3:5], ["--trace-file", "/tmp/显式-" + lines[0] + ".json"])
        self.assertEqual(len(lines), 6)

    def test_plain_shell_arguments_remain_unchanged(self):
        lines = self.run_probe("--version")
        self.assertEqual(lines[1:], ["--version"])
