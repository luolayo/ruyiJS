"""Shared fixture for tests that require the real macOS product executable."""
from pathlib import Path
import sys
import time
import unittest
from ruyijs import Context, get_runtime_path

ROOT = Path(__file__).resolve().parents[2]

def runtime_available():
    if sys.platform != "darwin": return False
    try: return (get_runtime_path() / "dist/js").is_file()
    except (OSError, FileNotFoundError): return False


@unittest.skipUnless(runtime_available(), "built or installed macOS product required")
class MacRuntimeCase(unittest.TestCase):
    def setUp(self):
        self.context = Context(timeout=10)
        self.addCleanup(self.context.close)


    def await_value(self, name="result"):
        for _ in range(100):
            value = self.context.eval(name)
            if value is not None:
                return value
            self.context.advance(5)
            time.sleep(0.005)
        self.fail("Asynchronous product operation did not complete")
