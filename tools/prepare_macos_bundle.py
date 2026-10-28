"""Assemble a relocatable Mac runtime from pinned build inputs."""
import base64
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request

from spidermonkey_source import ROOT, SOURCE, OUTPUT, digest
from macos_macho import relocate
from wheel_runtime_macos import validate

IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', '.DS_Store')


def download(lock):
    path = ROOT / 'build/downloads' / urllib.parse.unquote(lock['url'].rsplit('/', 1)[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        partial = path.with_name(path.name + '.part')
        with urllib.request.urlopen(lock['url'], timeout=60) as response, partial.open('wb') as stream:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > lock['size']: raise ValueError('Download exceeds pinned size')
                stream.write(block)
        if partial.stat().st_size != lock['size'] or digest(partial) != lock['sha256']:
            raise ValueError('Downloaded archive hash/size mismatch')
        partial.replace(path)
    if path.stat().st_size != lock['size'] or digest(path) != lock['sha256']:
        raise ValueError('Cached archive hash/size mismatch: ' + str(path))
    return path


def standalone_python():
    lock = json.loads((ROOT / 'config/python-macos.lock.json').read_text())
    archive = download(lock)
    output = ROOT / 'build/python-standalone'
    receipt = output / 'source.json'
    if not receipt.exists():
        # This is a generated cache. Recreate it only after the pinned archive
        # passes validation, so an interrupted extraction never becomes an input.
        if output.exists(): shutil.rmtree(output)
        output.mkdir()
        with tarfile.open(archive) as source:
            if sum(p.size for p in source.getmembers()) > lock['unpacked_limit']:
                raise ValueError('Python archive exceeds extraction limit')
            source.extractall(output, filter='data')
        receipt.write_text(json.dumps({'sha256':lock['sha256']}) + '\n')
    if json.loads(receipt.read_text())['sha256'] != lock['sha256']:
        raise ValueError('Standalone Python cache belongs to another release')
    return output / 'python'


def clean_environment():
    return {k:v for k,v in os.environ.items() if not k.startswith(('PYTHON', 'DYLD_', 'RUYIJS_', 'NECKO_'))
            and k not in ('VIRTUAL_ENV', 'OPENSSL_CONF', 'OPENSSL_MODULES')}


def prepare():
    python_lock = json.loads((ROOT / 'config/python-macos.lock.json').read_text())
    lock = json.loads((ROOT / 'config/macos-wheel.lock.json').read_text())
    link = json.loads((OUTPUT / 'runtime-link.json').read_text())
    network = json.loads((OUTPUT / 'network-build.json').read_text())
    if digest(ROOT / 'dist/js') != link['sha256']:
        raise ValueError('Product differs from the runtime link report')
    for inputs in (network['native_sources'], network['python_sources'], network['quic']['sources']):
        for name, expected in inputs.items():
            if digest(ROOT / name) != expected: raise ValueError('Rebuild changed network input: ' + name)
    base_python = standalone_python()
    full_archive = download(python_lock['full_archive'])
    with tempfile.TemporaryDirectory(prefix='bundle-', dir=OUTPUT) as temporary:
        root = Path(temporary) / 'runtime'
        (root / 'dist').mkdir(parents=True)
        shutil.copy2(ROOT / 'dist/js', root / 'dist/js')
        helper = root / 'vendor/necko-derived'
        shutil.copytree(base_python, helper, symlinks=False, ignore=IGNORE)
        for path in (helper / 'bin').iterdir():
            if path.name != 'python3': path.unlink()
        subprocess.run([helper / 'bin/python3', '-I', '-B', '-m', 'pip', 'install', '--only-binary=:all:',
                        '--require-hashes', '--no-compile', '--disable-pip-version-check',
                        '-r', ROOT / 'config/necko-macos-requirements.txt'], env=clean_environment(), check=True)
        target = helper / 'lib/python3.13/site-packages'
        built = ROOT / 'vendor/necko-derived/lib/python3.13/site-packages'
        for name in ('necko', 'ruyijs_necko'):
            shutil.copytree(ROOT / 'native/necko/python' / name, target / name, ignore=IGNORE)
        shutil.copy2(ROOT / 'src/resource_network/necko_oneshot.py', target / 'ruyijs_necko/oneshot.py')
        binaries = {'necko/libnecko_core.dylib':network['bridge_sha256'],
                    'necko/libnecko_quic.dylib':network['quic']['sha256'],
                    'ruyijs_necko/libruyijs_brotli.dylib':network['brotli_sha256']}
        binaries.update({'necko/' + row['name']:row['sha256'] for row in network['mozilla_libraries']})
        for name, checksum in binaries.items():
            if digest(built / name) != checksum: raise ValueError('Network binary changed: ' + name)
            shutil.copy2(built / name, target / name)
        openssl = Path('/opt/homebrew/opt/openssl@3')
        if digest(openssl / 'lib/libcrypto.3.dylib') != lock['openssl']['library_sha256']:
            raise ValueError('OpenSSL changed; update and review the wheel input lock')
        if digest(openssl / 'LICENSE.txt') != lock['openssl']['license_sha256']:
            raise ValueError('OpenSSL license changed')
        (root / 'lib').mkdir()
        shutil.copy2(openssl / 'lib/libcrypto.3.dylib', root / 'lib/libcrypto.3.dylib')
        licenses = root / 'licenses'
        licenses.mkdir()
        for name in ('LICENSE', 'NOTICE'): shutil.copy2(ROOT / name, licenses / name)
        shutil.copy2(openssl / 'LICENSE.txt', licenses / 'OpenSSL.txt')
        shutil.copy2(ROOT / 'native/necko/python/necko/licenses/firefox-license.html', licenses / 'Firefox.html')
        shutil.copytree(ROOT / 'src/web_platform/encoding_rs', licenses / 'encoding_rs',
                        ignore=lambda _, names: [n for n in names if not n.startswith('LICENSE')])
        # The full Python archive supplies all licenses for statically linked
        # third-party libraries; install_only intentionally omits this collection.
        members = subprocess.check_output(['tar', '-tf', full_archive], text=True).splitlines()
        notices = [n for n in members if n.startswith('python/licenses/') and not n.endswith('/')]
        if not notices: raise ValueError('Standalone Python license collection missing')
        (licenses / 'python').mkdir()
        for name in [*notices, 'python/PYTHON.json']:
            value = PurePosixPath(name)
            if '..' in value.parts: raise ValueError('Invalid Python license member')
            data = subprocess.check_output(['tar', '-xOf', full_archive, name])
            (licenses / 'python' / value.name).write_bytes(data)
        # Retain notices of the Rust code linked into SpiderMonkey and Neqo.
        rust_licenses = licenses / 'rust'
        for crate in (SOURCE / 'third_party/rust').iterdir():
            if not crate.is_dir(): continue
            for item in crate.iterdir():
                if item.is_file() and item.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                    destination = rust_licenses / crate.name / item.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, destination)
        # No compiler headers, package installer or absolute-shebang utilities
        # are required by the private network process.
        for path in [helper / 'include', helper / 'share', helper / 'lib/pkgconfig', target / 'pip',
                     *target.glob('pip-*.dist-info')]:
            if path.is_dir(): shutil.rmtree(path)
        for path in (helper / 'bin').iterdir():
            if path.name != 'python3': path.unlink()
        for path in helper.rglob('*.a'): path.unlink()
        for path in helper.rglob('__pycache__'): shutil.rmtree(path)
        for path in helper.rglob('*.pyc'): path.unlink()
        for path in root.rglob('*'):
            if path.is_symlink(): raise ValueError('Runtime must not contain symlinks: ' + str(path))
        rows = relocate(root)
        # Relocation/signing changes extension bytes, and private CLI scripts
        # were removed. Keep the embedded distributions' installed RECORD files
        # consistent with the actual bundle as well as the outer SHA256SUMS.
        for record in target.glob('*.dist-info/RECORD'):
            entries = []
            with record.open(newline='') as stream:
                for name, _, _ in csv.reader(stream):
                    path = (target / name).resolve()
                    if not path.is_relative_to(helper.resolve()):
                        raise ValueError('Embedded package RECORD escapes Python: ' + name)
                    if not path.is_file(): continue
                    if path == record.resolve(): entries.append([name, '', '']); continue
                    checksum = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b'=').decode()
                    entries.append([name, 'sha256=' + checksum, str(path.stat().st_size)])
            with record.open('w', newline='') as stream: csv.writer(stream).writerows(entries)
        requirements = ROOT / 'config/necko-macos-requirements.txt'
        packages = json.loads(subprocess.check_output([helper / 'bin/python3', '-I', '-B', '-c',
            'import importlib.metadata,json; print(json.dumps({d.metadata["Name"]:d.version for d in importlib.metadata.distributions()}))'],
            env=clean_environment(), text=True))
        manifest = {'format':1, 'platform':lock['platform'], 'minimum_macos':lock['minimum_macos'],
                    'embedded_python':python_lock['version'], 'python_archive_sha256':python_lock['sha256'],
                    'product_input_sha256':link['sha256'], 'network_build_sha256':digest(OUTPUT / 'network-build.json'),
                    'network_requirements_sha256':digest(requirements), 'packages':packages,
                    'openssl':lock['openssl'], 'neqo_version':network['quic']['neqo_version'],
                    'protocols':network['protocols'], 'webtransport':True,
                    'executable_files':[p.relative_to(root).as_posix() for p in sorted(root.rglob('*'))
                                        if p.is_file() and p.stat().st_mode & 0o111],
                    'mach_o':rows, 'signing':'ad-hoc', 'notarized':False}
        (root / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        inventory = ''.join(digest(p) + '  ' + p.relative_to(root).as_posix() + '\n'
                            for p in sorted(root.rglob('*')) if p.is_file())
        (root / 'SHA256SUMS').write_text(inventory)
        validate(root)
        output = OUTPUT / 'wheel-runtime'
        if output.exists(): shutil.rmtree(output)
        root.rename(output)
    return output
