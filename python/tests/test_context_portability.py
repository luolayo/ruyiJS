"""macOS process-start errors must preserve diagnostics and dispose resources."""

from pathlib import Path
import errno
import sys
import tempfile
import unittest

from ruyijs import Context
from ruyijs._runtime_paths import shell_name


@unittest.skipUnless(sys.platform == "darwin", "macOS client")
class ContextPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ruyijs-context-", dir="/tmp")
        self.addCleanup(self.directory.cleanup)

    def test_native_shell_name(self):
        self.assertEqual(shell_name(), "js")

    def test_exec_format_error_is_not_masked_by_winerror_attribute(self):
        executable = Path(self.directory.name) / "invalid-runtime"
        executable.write_text("not an executable")
        executable.chmod(0o700)
        context = Context.__new__(Context)
        with self.assertRaises(OSError) as raised:
            context.__init__(shell=executable)
        self.assertEqual(raised.exception.errno, errno.ENOEXEC)
        self.assertTrue(context.closed)
        self.assertFalse(Path(context._pipe.name).parent.exists())
        self.assertIsNone(context._stderr)

    def test_startup_timeout_kills_child_and_removes_endpoint(self):
        executable = Path(self.directory.name) / "never-connects"
        executable.write_text("#!/bin/sh\nexec /bin/sleep 30\n")
        executable.chmod(0o700)
        context = Context.__new__(Context)
        with self.assertRaises(TimeoutError):
            context.__init__(shell=executable, timeout=0.1)
        self.assertTrue(context.closed)
        self.assertIsNotNone(context._process.poll())
        self.assertFalse(Path(context._pipe.name).parent.exists())
        self.assertIsNone(context._stderr)

    def test_child_exit_reports_stderr_without_waiting_for_startup_timeout(self):
        executable = Path(self.directory.name) / "fails-before-connect"
        executable.write_text("#!/bin/sh\necho native-startup-failed >&2\nexit 23\n")
        executable.chmod(0o700)
        context = Context.__new__(Context)
        with self.assertRaisesRegex(BrokenPipeError, "code 23.*native-startup-failed"):
            context.__init__(shell=executable, timeout=5)
        self.assertTrue(context.closed)
        self.assertFalse(Path(context._pipe.name).parent.exists())
