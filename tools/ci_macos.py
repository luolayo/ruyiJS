"""Fresh-machine build stages and artifact export for the ARM64 wheel workflow."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from spidermonkey_source import ROOT, OUTPUT, digest


def preflight():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('CI requires native macOS ARM64')
    if int(platform.mac_ver()[0].split('.')[0]) < 27:
        raise RuntimeError('The wheel requires macOS 27; use the xcode-27 hosted image')
    if sys.version_info[:2] != (3, 13): raise RuntimeError('Use Python 3.13 for the build tools')
    tools = {
        'python':sys.version,
        'llvm':subprocess.check_output(['/opt/homebrew/opt/llvm/bin/clang', '--version'], text=True).strip(),
        'lld':subprocess.check_output(['/opt/homebrew/opt/lld/bin/ld64.lld', '--version'], text=True).strip(),
        'rust':subprocess.check_output(['rustc', '--version'], text=True).strip(),
        'sdk':subprocess.check_output(['xcrun', '--show-sdk-version'], text=True).strip(),
    }
    lock = json.loads((ROOT / 'config/macos-wheel.lock.json').read_text())
    crypto = Path('/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib')
    if digest(crypto) != lock['openssl']['library_sha256']:
        raise ValueError('Runner OpenSSL differs from the pinned wheel input; do not replace the hash without review')
    free = shutil.disk_usage(ROOT).free
    if free < 10 * 1024 ** 3: raise RuntimeError('At least 10 GiB of free disk space is required')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {'macos':platform.mac_ver()[0], 'architecture':platform.machine(), 'tools':tools,
              'free_disk_bytes':free, 'openssl_sha256':digest(crypto),
              'github':{key:os.environ.get(key) for key in ('GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_RUN_ID',
                      'GITHUB_RUN_ATTEMPT','GITHUB_JOB','RUNNER_ENVIRONMENT','ImageOS','ImageVersion')}}
    (OUTPUT / 'ci-preflight.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def build_stage(name, jobs):
    stages = {
        'engine':[
            ('build_spidermonkey.py', 'prepare'),
            ('build_spidermonkey.py', 'bootstrap'),
            ('build_spidermonkey.py', 'build', '--jobs', str(jobs)),
            ('build_spidermonkey.py', 'commands'),
            ('verify_spidermonkey.py',),
        ],
        'inputs':[
            ('generate_browser_inputs.py', 'configure'),
            ('generate_browser_inputs.py', 'export', '--jobs', str(jobs)),
            ('generate_browser_inputs.py', 'generate'),
            ('prepare_firefox_reference.py',),
            ('capture_firefox_baseline.py',),
        ],
        'product':[
            ('build_macos_dependencies.py',),
            ('build_macos_runtime.py', '--jobs', str(jobs)),
            ('link_macos_runtime.py',),
            ('build_macos_network.py',),
        ],
        'verify':[
            ('verify_macos_network.py',),
            ('verify_macos_runtime.py',),
        ],
        'wheel':[
            ('build_macos_wheel.py',),
        ],
    }
    for command in stages[name]:
        subprocess.run([sys.executable, '-B', ROOT / 'tools' / command[0], *command[1:]], cwd=ROOT, check=True)


def export():
    report_path = OUTPUT / 'wheel-build.json'
    report = json.loads(report_path.read_text())
    wheel = Path(report['wheel'])
    if digest(wheel) != report['sha256']: raise ValueError('Wheel differs from its build report')
    peer = OUTPUT / 'quic/target/release/examples/peer'
    network = json.loads((OUTPUT / 'network-build.json').read_text())
    if digest(peer) != network['quic']['test_peer_sha256']: raise ValueError('QUIC peer differs from its build report')
    output = ROOT / 'artifacts/macos-arm64'
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for source, name in ((wheel, wheel.name), (peer, 'neqo-test-peer'), (report_path, 'wheel-build.json')):
        shutil.copy2(source, output / name)
        files[name] = digest(output / name)
    manifest = {'format':1, 'revision':subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'files':files, 'build_run_id':os.environ.get('GITHUB_RUN_ID'),
                'build_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT')}
    (output / 'ci-artifact.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('preflight','engine','inputs','product','verify','wheel','export'))
    parser.add_argument('--jobs', type=int, choices=range(1,5), default=2)
    args = parser.parse_args()
    if args.stage == 'preflight': preflight()
    elif args.stage == 'export': export()
    else: build_stage(args.stage, args.jobs)


if __name__ == '__main__': main()
