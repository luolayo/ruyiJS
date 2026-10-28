"""Executed with only the wheel installed, in a filesystem sandbox."""
import errno
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import ruyijs

configuration = json.loads(Path(sys.argv[1]).read_text())
for name in ('requests', 'cryptography', 'h2', 'necko'):
    assert importlib.util.find_spec(name) is None, name + ' leaked into the host environment'
for path in configuration['blocked_probes']:
    try:
        with open(path, 'rb') as stream: stream.read(1)
    except PermissionError: pass
    else: raise AssertionError('Sandbox did not block ' + path)
root = ruyijs.get_runtime_path()
assert str(root).startswith(configuration['installation']), root
helper = root / 'vendor/necko-derived/bin/python3'
embedded = json.loads(subprocess.check_output([helper, '-I', '-B', '-c',
    'import json,sys,ssl,necko,h2,cryptography;print(json.dumps({"version":sys.version.split()[0],"prefix":sys.prefix,"openssl":ssl.OPENSSL_VERSION}))'], text=True))
assert Path(embedded['prefix']).resolve() == helper.parent.parent.resolve(), embedded
assert embedded['version'] == '3.13.18', embedded
assert sys.version_info[:2] != (3,13), 'Use a different host minor version to verify interpreter independence'
with ruyijs.Context() as context:
    assert context.eval('1+2') == 3
    assert context.eval("document.createElement('span').tagName") == 'SPAN'
print(json.dumps({'host_python':sys.version.split()[0], 'package':ruyijs.__file__,
                  'version':importlib.metadata.version('ruyijs'), 'embedded':embedded,
                  'blocked_probes_confirmed':configuration['blocked_probes'], 'eval':3}))
