"""Audit a wheel and install/run it outside the checkout without Homebrew access."""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
import platform
from pathlib import Path
import re
import select
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

from spidermonkey_source import ROOT, OUTPUT, digest
from prepare_macos_bundle import download
from wheel_runtime_macos import validate
from macos_macho import audit


def wheel_inventory(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)): raise ValueError('Duplicate wheel entries')
        info = next(n.split('/')[0] for n in names if n.endswith('.dist-info/WHEEL') and '/' not in n.split('.dist-info/')[0])
        metadata = archive.read(info + '/WHEEL').decode()
        if 'Root-Is-Purelib: false' not in metadata or 'Tag: py3-none-macosx_27_0_arm64' not in metadata:
            raise ValueError('Incorrect wheel platform metadata')
        rows = list(csv.reader(io.StringIO(archive.read(info + '/RECORD').decode())))
        recorded = set()
        for name, checksum, size in rows:
            if name in recorded: raise ValueError('Duplicate RECORD entry')
            recorded.add(name)
            if name == info + '/RECORD': continue
            value = archive.read(name)
            expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b'=').decode()
            if checksum != expected or int(size) != len(value): raise ValueError('Bad wheel RECORD: ' + name)
        if recorded != set(names): raise ValueError('Incomplete wheel RECORD')
        for name in ('ruyijs/_runtime/dist/js', 'ruyijs/_runtime/vendor/necko-derived/bin/python3'):
            if not archive.getinfo(name).external_attr >> 16 & 0o111:
                raise ValueError('Executable permission missing from wheel: ' + name)
        return {'files':len(names), 'record_verified':True, 'executable_permissions':True}


def run(command, directory, env, log, *, timeout=120):
    result = subprocess.run(list(map(str, command)), cwd=directory, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    log.write_text(result.stdout)
    if result.returncode:
        print(result.stdout[-12000:])
        raise RuntimeError('Wheel verification command failed; see ' + str(log))
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, help='Only use wheel/peer artifacts from a previous CI job')
    parser.add_argument('--require-clean-checkout', action='store_true')
    args = parser.parse_args()
    forbidden = ('dist/js', 'vendor/necko-derived', 'build/upstream', 'build/spidermonkey-arm64',
                 'build/firefox-inputs-arm64', 'build/macos-arm64/wheel-runtime')
    if args.require_clean_checkout and any((ROOT / path).exists() for path in forbidden):
        raise ValueError('Installation job must not contain a development runtime or native build tree')
    if args.artifact_dir:
        artifact = args.artifact_dir.resolve()
        manifest = json.loads((artifact / 'ci-artifact.json').read_text())
        if manifest.get('format') != 1: raise ValueError('Unknown CI artifact format')
        for name, expected in manifest['files'].items():
            if Path(name).name != name or digest(artifact / name) != expected:
                raise ValueError('CI artifact hash/path mismatch: ' + name)
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        if manifest['revision'] != revision: raise ValueError('Artifact and installation checkout commits differ')
        build = json.loads((artifact / 'wheel-build.json').read_text())
        wheel = artifact / Path(build['wheel']).name
        peer = artifact / 'neqo-test-peer'
        if set(manifest['files']) != {wheel.name, peer.name, 'wheel-build.json'}:
            raise ValueError('CI artifact inventory must include the wheel, peer and build report')
    else:
        build = json.loads((OUTPUT / 'wheel-build.json').read_text())
        wheel = Path(build['wheel'])
        peer = OUTPUT / 'quic/target/release/examples/peer'
    if digest(wheel) != build['sha256']: raise ValueError('Wheel differs from build report')
    inventory = wheel_inventory(wheel)
    host_lock = json.loads((ROOT / 'config/python-macos.lock.json').read_text())['verification_host']
    archive = download(host_lock)
    logs = OUTPUT / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ruyijs wheel ', dir='/tmp') as temporary:
        directory = Path(temporary).resolve()
        base = directory / 'host'
        with tarfile.open(archive) as source:
            if sum(p.size for p in source.getmembers()) > host_lock['unpacked_limit']:
                raise ValueError('Verification interpreter archive too large')
            source.extractall(base, filter='data')
        interpreter = base / 'python/bin/python3'
        env = {'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'TMPDIR':str(directory),
               'PIP_CONFIG_FILE':'/dev/null', 'PIP_DISABLE_PIP_VERSION_CHECK':'1',
               'PIP_NO_INDEX':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
        profile = directory / 'runtime.sb'
        blocked = [str(ROOT.resolve()), '/opt/homebrew', '/usr/local']
        rules = '(version 1)\n(allow default)\n(deny file-read* ' + ' '.join('(subpath ' + json.dumps(p) + ')' for p in blocked) + ')\n'
        profile.write_text(rules)
        offline = directory / 'offline.sb'
        offline.write_text(rules + '(deny network*)\n')
        sandbox = ['/usr/bin/sandbox-exec', '-f', profile]
        offline_sandbox = ['/usr/bin/sandbox-exec', '-f', offline]
        environment = directory / 'venv'
        run([*offline_sandbox, interpreter, '-I', '-B', '-m', 'venv', environment], directory, env, logs / 'wheel-create-venv.log')
        installed_python = environment / 'bin/python3'
        copied_wheel = directory / wheel.name
        shutil.copy2(wheel, copied_wheel)
        run([*offline_sandbox, installed_python, '-I', '-B', '-m', 'pip', 'install', '--no-index', '--no-deps',
             '--no-cache-dir', copied_wheel], directory, env, logs / 'wheel-offline-install.log')
        package = environment / f'lib/python{host_lock["version"].rsplit(".",1)[0]}/site-packages/ruyijs'
        manifest = validate(package / '_runtime', installed=True)
        binaries = audit(package / '_runtime')
        tests = directory / 'tests'
        tests.mkdir()
        for name in ('runtime_support.py', 'test_runtime_macos.py', 'test_runtime_backends.py'):
            shutil.copy2(ROOT / 'python/tests' / name, tests / name)
        for name in ('test_installed_network.py', 'inspect_install.py'):
            shutil.copy2(ROOT / 'native/wheel_tests' / name, tests / name)
        configuration = tests / 'installation.json'
        probes = [str(ROOT / 'README.md'), '/opt/homebrew/bin/brew']
        configuration.write_text(json.dumps({'installation':str(environment), 'blocked_probes':probes}))
        first = json.loads(run([*sandbox, installed_python, '-I', '-B', tests / 'inspect_install.py', configuration],
                               directory, env, logs / 'wheel-install-smoke.log'))
        server_root = directory / 'servers'
        server_root.mkdir()
        server_python = server_root / 'python'
        shutil.copytree(package / '_runtime/vendor/necko-derived', server_python)
        for name in ('wheel_peers.py', 'quic_fixture.py', 'fixtures.py'):
            shutil.copy2(ROOT / 'native/necko/tests' / name, server_root / name)
        server_peer = server_root / 'neqo-peer'
        shutil.copy2(peer, server_peer)
        server_peer.chmod(0o755)  # Actions artifacts do not preserve executable bits.
        server_log = (logs / 'wheel-network-peers.log').open('w')
        servers = subprocess.Popen([server_python / 'bin/python3', '-B', server_root / 'wheel_peers.py',
            '--peer', server_peer, '--native', server_python / 'lib/python3.13/site-packages/necko'],
            cwd=server_root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=server_log, text=True)
        try:
            if not select.select([servers.stdout], [], [], 20)[0]: raise TimeoutError('Network peers did not start')
            peers = json.loads(servers.stdout.readline())
            (tests / 'peers.json').write_text(json.dumps(peers))
            output = run([*sandbox, installed_python, '-I', '-B', '-m', 'unittest', 'discover', '-s', tests, '-v'],
                         directory, env, logs / 'wheel-installed-tests.log')
            count = re.search(r'Ran (\d+) tests', output)
            if not count or int(count[1]) != 17 or 'skipped=' in output:
                raise ValueError('Installed wheel suite incomplete')
            # Move the installed environment after pip has written RECORD and
            # scripts. Executing python -m keeps this independent of pip shebangs.
            moved = directory / 'relocated installation'
            environment.rename(moved)
            configuration.write_text(json.dumps({'installation':str(moved), 'blocked_probes':probes}))
            relocated = json.loads(run([*sandbox, moved / 'bin/python3', '-I', '-B', tests / 'inspect_install.py', configuration],
                                      directory, env, logs / 'wheel-relocated-smoke.log'))
            relocated_tests = run([*sandbox, moved / 'bin/python3', '-I', '-B', '-m', 'unittest', 'discover', '-s', tests,
                 '-p', 'test_installed_network.py', '-v'], directory, env, logs / 'wheel-relocated-network.log')
            if not re.search(r'Ran 5 tests', relocated_tests) or 'skipped=' in relocated_tests:
                raise ValueError('Relocated network suite incomplete')
            run([*offline_sandbox, moved / 'bin/python3', '-I', '-B', '-m', 'pip', 'uninstall', '-y', 'ruyijs'],
                directory, env, logs / 'wheel-uninstall.log')
            if (moved / package.relative_to(environment)).exists():
                raise ValueError('pip uninstall left bundled runtime files behind')
        finally:
            if servers.poll() is None:
                servers.stdin.close()
                try: servers.wait(timeout=10)
                except subprocess.TimeoutExpired: servers.kill(); servers.wait(timeout=5)
            servers.stdout.close(); server_log.close()
        hosted = (os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted')
        report = {'passed':True, 'wheel':str(wheel), 'sha256':digest(wheel), 'wheel_bytes':wheel.stat().st_size,
                  'inventory':inventory, 'mach_o_files':len(binaries), 'minimum_macos':manifest['minimum_macos'],
                  'installed_tests_passed':17, 'relocated_network_tests_passed':5,
                  'offline_install':True, 'pip_uninstall_removed_runtime':True,
                  'sandbox_denied_read_paths':blocked, 'host_python':host_lock['version'],
                  'embedded_python':manifest['embedded_python'], 'initial_smoke':first, 'relocated_smoke':relocated,
                  'runtime_overrides_used':False, 'public_network_used_by_tests':False,
                  'artifact_only':bool(args.artifact_dir), 'clean_checkout_checked':args.require_clean_checkout,
                  'new_machine_or_vm_tested':hosted and args.require_clean_checkout and bool(args.artifact_dir),
                  'machine':{'macos':platform.mac_ver()[0], 'architecture':platform.machine()},
                  'github_actions':{key:os.environ.get(key) for key in ('GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_RUN_ID',
                      'GITHUB_RUN_ATTEMPT','GITHUB_JOB','RUNNER_ENVIRONMENT','ImageOS','ImageVersion')},
                  'test_scope':'artifact installation with filesystem-denied development dependencies'}
        (OUTPUT / 'wheel-verification.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
