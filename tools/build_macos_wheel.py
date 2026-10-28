"""Prepare the self-contained ARM64 runtime and build a platform wheel with PEP 517."""
import argparse
import json
import platform
from pathlib import Path
import tomllib
import shutil
import subprocess
import tempfile

from spidermonkey_source import ROOT, OUTPUT, digest
from prepare_macos_bundle import prepare, standalone_python, clean_environment, IGNORE
from wheel_runtime_macos import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-runtime', action='store_true', help='Reuse the existing validated bundle')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Build on an ARM64 Mac')
    runtime = OUTPUT / 'wheel-runtime' if args.reuse_runtime else prepare()
    validate(runtime)
    builder = OUTPUT / 'wheel-builder'
    base_python = standalone_python()
    if not (builder / 'bin/python3').is_file():
        subprocess.run([base_python / 'bin/python3', '-I', '-B', '-m', 'venv', builder], check=True)
    requirements = ROOT / 'config/macos-wheel-build-requirements.txt'
    env = clean_environment()
    subprocess.run([builder / 'bin/python3', '-I', '-B', '-m', 'pip', 'install', '--only-binary=:all:',
                    '--require-hashes', '--disable-pip-version-check', '-r', requirements], env=env, check=True)
    wheelhouse = ROOT / 'wheelhouse'
    wheelhouse.mkdir(exist_ok=True)
    # Fresh packaging tree avoids stale build_py caches while preserving the
    # developer checkout and all earlier porting work.
    with tempfile.TemporaryDirectory(prefix='wheel-source-', dir=OUTPUT) as temporary:
        source = Path(temporary)
        for name in ('setup.py','pyproject.toml','MANIFEST.in','README.md','LICENSE','NOTICE','runtime.json'):
            shutil.copy2(ROOT / name, source / name)
        (source / 'tools').mkdir()
        for name in ('wheel_runtime.py', 'wheel_runtime_macos.py'):
            shutil.copy2(ROOT / 'tools' / name, source / 'tools' / name)
        shutil.copytree(ROOT / 'python/ruyijs', source / 'python/ruyijs',
                        ignore=shutil.ignore_patterns('_runtime', '__pycache__', '*.pyc'))
        shutil.copytree(ROOT / 'examples', source / 'examples', ignore=IGNORE)
        env['RUYIJS_BUILD_MACOS_RUNTIME'] = str(runtime)
        env['SOURCE_DATE_EPOCH'] = '1792972800'
        subprocess.run([builder / 'bin/python3', '-I', '-B', '-m', 'build', '--wheel', '--no-isolation',
                        '--outdir', wheelhouse], cwd=source, env=env, check=True)
        version = tomllib.loads((source / 'pyproject.toml').read_text())['project']['version']
    wheel = wheelhouse / f'ruyijs-{version}-py3-none-macosx_27_0_arm64.whl'
    report = {'wheel':str(wheel), 'sha256':digest(wheel), 'bytes':wheel.stat().st_size,
              'platform':'macosx_27_0_arm64', 'runtime_inventory_sha256':digest(runtime / 'SHA256SUMS'),
              'build_requirements_sha256':digest(requirements), 'embedded_python':'3.13.18',
              'notarized':False, 'published':False}
    (OUTPUT / 'wheel-build.json').write_text(json.dumps(report, indent=2) + '\n')
    wheel.with_suffix('.whl.sha256').write_text(report['sha256'] + '  ' + wheel.name + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
