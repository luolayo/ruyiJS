"""Build Neqo from the same vendored Firefox source as the ARM64 runtime."""
import json
import os
import platform
import shutil
import subprocess

from spidermonkey_source import ROOT, SOURCE, OUTPUT, digest


def build(native, headers, *, locked=True):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('The Neqo bridge currently requires a native ARM64 Mac')
    lock_path = ROOT / 'config/neqo-macos.lock.json'
    lock = json.loads(lock_path.read_text())
    engine = json.loads((ROOT / 'config/spidermonkey.lock.json').read_text())
    if lock['firefox_source_sha256'] != engine['source_sha256']:
        raise ValueError('Neqo and SpiderMonkey source locks do not match')
    for relative, expected in lock['vendor_manifests_sha256'].items():
        manifest = SOURCE / 'third_party/rust' / relative
        if digest(manifest) != expected:
            raise ValueError('Neqo vendor manifest changed: ' + relative)
        for name, checksum in json.loads(manifest.read_text())['files'].items():
            if digest(manifest.parent / name) != checksum:
                raise ValueError('Neqo source changed: ' + str(manifest.parent / name))
    headers = [*headers, SOURCE / 'security/nss/lib/freebl/ecl']
    work = OUTPUT / 'quic'
    work.mkdir(exist_ok=True)
    config = work / 'cargo-config.toml'
    config.write_text('[source.crates-io]\nreplace-with = "firefox"\n'
                      '[source.nss]\ngit = "https://github.com/mozilla/nss-rs"\nreplace-with = "firefox"\n'
                      '[source.firefox]\ndirectory = ' + json.dumps(str(SOURCE / 'third_party/rust')) + '\n')
    # Firefox folds NSS/SSL/NSPR into nss3 and mozglue. Describe that existing
    # pinned installation to nss-rs instead of downloading another NSS build.
    (work / 'nss.pc').write_text(
        'Name: nss\nDescription: Firefox 158 folded NSS\nVersion: 3.130\n'
        f'Libs: -L{native} -lnss3 -lmozglue\n'
        + 'Cflags: ' + ' '.join('-I' + str(path) for path in headers) + '\n')
    env = dict(os.environ, PKG_CONFIG_PATH=str(work), PKG_CONFIG_LIBDIR=str(work),
               MACOSX_DEPLOYMENT_TARGET='27.0', LIBCLANG_PATH='/opt/homebrew/opt/llvm/lib',
               BINDGEN_EXTRA_CLANG_ARGS='-isysroot ' + subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip(),
               RUSTFLAGS='-C link-arg=-Wl,-rpath,@loader_path -C link-arg=-Wl,-install_name,@rpath/libnecko_quic.dylib')
    env.pop('NSS_DIR', None)
    command = ['cargo', 'build', '--offline', '--release', '--manifest-path', str(ROOT / 'native/necko/quic/Cargo.toml'),
               '--examples', '--lib', '--target-dir', str(work / 'target'), '--config', str(config)]
    if locked:
        command.append('--locked')
    log = OUTPUT / 'logs/quic-build.log'
    with log.open('w') as stream:
        result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text()[-12000:])
        raise SystemExit(result.returncode)
    output = native / 'libnecko_quic.dylib'
    shutil.copyfile(work / 'target/release/libnecko_quic.dylib', output)
    architecture = subprocess.check_output(['lipo', '-archs', output], text=True).strip()
    if architecture != 'arm64':
        raise ValueError('Unexpected Neqo architecture: ' + architecture)
    subprocess.run(['codesign', '--force', '--sign', '-', output], check=True, capture_output=True)
    return {'sha256': digest(output), 'neqo_version': lock['neqo_version'],
            'architecture': architecture, 'source_lock_sha256': digest(lock_path),
            'test_peer_sha256': digest(work / 'target/release/examples/peer'),
            'nss_rs_version': lock['nss_rs_version'], 'nss_rs_revision': lock['nss_rs_revision'],
            'cargo_lock_sha256': digest(ROOT / 'native/necko/quic/Cargo.lock'),
            'sources': {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / 'native/necko/quic').rglob('*') if p.is_file()}}
