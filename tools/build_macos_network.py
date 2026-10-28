"""Build the native socket/HTTP/NSS bridge and install its isolated Python helper."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import venv

from spidermonkey_source import ROOT, SOURCE, OUTPUT, digest

RUNTIME = ROOT / "vendor/necko-derived"


def main():
    lock = json.loads((ROOT / "config/necko-macos.lock.json").read_text())
    target = RUNTIME / "lib/python3.13/site-packages"
    if sys.version_info[:2] != (3, 13): raise RuntimeError("Use Python 3.13")
    if not (RUNTIME / "bin/python3").is_file():
        venv.EnvBuilder(with_pip=True).create(RUNTIME)
    requirements = ROOT / "config/necko-macos-requirements.txt"
    if requirements.is_file():
        subprocess.run([RUNTIME / "bin/python3", "-m", "pip", "install", "--only-binary=:all:",
                        "--require-hashes", "-r", requirements], check=True)
    for name in ("necko", "ruyijs_necko"):
        shutil.copytree(ROOT / "native/necko/python" / name, target / name, dirs_exist_ok=True)
    shutil.copyfile(ROOT / "src/resource_network/necko_oneshot.py", target / "ruyijs_necko/oneshot.py")
    reference = ROOT / "build/reference/Firefox.app/Contents/MacOS"
    original = json.loads((ROOT / "build/reference/source.json").read_text())
    if digest(reference / "firefox") != original["executable_sha256"]:
        raise ValueError("Pinned Firefox reference changed")
    native = target / "necko"
    libraries = []
    for name in ("libmozglue.dylib", "libnss3.dylib", "libsoftokn3.dylib", "libfreebl3.dylib"):
        if digest(reference / name) != lock["mozilla_libraries_sha256"][name]:
            raise ValueError("Pinned Mozilla library changed: " + name)
        output = native / name
        shutil.copyfile(reference / name, output)
        libraries.append({"name":name,"sha256":digest(output)})
    include = OUTPUT / "network-include"
    include.mkdir(exist_ok=True)
    shutil.copyfile(SOURCE / "nsprpub/pr/include/md/_darwin.cfg", include / "prcpucfg.h")
    headers = [SOURCE / "nsprpub/pr/include", SOURCE / "nsprpub/lib/ds", SOURCE / "nsprpub/lib/libc/include", include]
    headers += [p for p in (SOURCE / "security/nss/lib").iterdir() if p.is_dir()]
    compiler = "/opt/homebrew/opt/llvm/bin/clang++"
    common = [compiler,"-std=c++20","-O2","-arch","arm64","-mmacosx-version-min=27.0","-dynamiclib",
              "-fvisibility=hidden","-Wall","-Wextra",*['-I'+str(p) for p in headers]]
    sources = [ROOT / "native/necko" / (n + ".cpp") for n in ("socket","exchange","exchange_read","tls_io","tls")]
    output = native / "libnecko_core.dylib"
    command = common + list(map(str,sources)) + ['-L'+str(native),'-lnss3','-lmozglue',
              '-Wl,-rpath,@loader_path','-Wl,-install_name,@rpath/libnecko_core.dylib','-o',str(output)]
    log = OUTPUT / "logs/network-build.log"
    with log.open('w') as stream:
        result = subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text()[-6000:]);raise SystemExit(result.returncode)
    brotli = target / "ruyijs_necko/libruyijs_brotli.dylib"
    subprocess.run(common + ['-I'+str(SOURCE/'modules/brotli/include'),
        str(ROOT/'native/necko/brotli.cpp'),str(OUTPUT/'dependencies/libbrotli.a'),'-o',str(brotli)],check=True)
    for binary in (output,brotli):
        subprocess.run(['codesign','--force','--sign','-',binary],check=True,capture_output=True)
    from build_macos_quic import build as build_quic
    quic = build_quic(native, headers)
    report = {"helper":str(RUNTIME/'bin/python3'),"nss_origin":original,
              "mozilla_libraries":libraries,"bridge_sha256":digest(output),"brotli_sha256":digest(brotli),
              "native_sources":{str(p.relative_to(ROOT)):digest(p) for p in sources},
              "python_sources":{str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'native/necko/python').rglob('*') if p.is_file()},
              "helper_entry_sha256":digest(ROOT/'src/resource_network/necko_oneshot.py'),
              "requirements_sha256":digest(requirements),
              "protocols":["http/1.0","http/1.1","h2","h3"],"http3":True,"webtransport":True,"quic":quic}
    (OUTPUT/'network-build.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
