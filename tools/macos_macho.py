"""Relocate and audit Mach-O dependencies inside a standalone runtime tree."""
import os
from pathlib import Path
import re
import subprocess

MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}
SYSTEM = ('/usr/lib/', '/System/Library/')


def machos(root):
    result = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:
                if stream.read(4) in MAGIC: result.append(path)
    return result


def command(*args):
    return subprocess.check_output([str(a) for a in args], text=True, stderr=subprocess.STDOUT)


def metadata(path):
    loads = command('otool', '-l', path)
    dependencies = []
    rpaths = []
    identifier = None
    minimum = None
    for block in loads.split('Load command ')[1:]:
        kind = re.search(r'\bcmd (LC_\w+)', block)
        if not kind: continue
        kind = kind[1]
        if kind in ('LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB', 'LC_LOAD_UPWARD_DYLIB', 'LC_ID_DYLIB'):
            value = re.search(r'\bname (.+) \(offset', block)[1]
            if kind == 'LC_ID_DYLIB': identifier = value
            else: dependencies.append(value)
        elif kind == 'LC_RPATH': rpaths.append(re.search(r'\bpath (.+) \(offset', block)[1])
        elif kind == 'LC_BUILD_VERSION': minimum = re.search(r'\bminos (\S+)', block)[1]
        elif kind == 'LC_VERSION_MIN_MACOSX': minimum = re.search(r'\bversion (\S+)', block)[1]
    return {'dependencies':dependencies, 'rpaths':rpaths, 'id':identifier, 'minimum':minimum}


def relocate(root):
    binaries = machos(root)
    index = {}
    for path in binaries: index.setdefault(path.name, []).append(path)
    for path in binaries:
        architectures = command('lipo', '-archs', path).split()
        if 'arm64' not in architectures:
            raise ValueError('Runtime contains a non-ARM64 binary: ' + str(path))
        if len(architectures) > 1:
            thin = path.with_name(path.name + '.arm64')
            command('lipo', path, '-thin', 'arm64', '-output', thin)
            thin.chmod(path.stat().st_mode); thin.replace(path)
        info = metadata(path)
        options = []
        for dep in info['dependencies']:
            if dep.startswith(SYSTEM): continue
            local = path.parent / dep.removeprefix('@loader_path/') if dep.startswith('@loader_path/') else None
            if local is not None and local.resolve().is_relative_to(root.resolve()) and local.is_file():
                destination = local.resolve()
            else:
                choices = index.get(Path(dep).name, [])
                if len(choices) != 1:
                    raise ValueError(f'Unresolved/ambiguous bundled dependency: {path}: {dep}')
                destination = choices[0]
            relative = '@loader_path/' + os.path.relpath(destination, path.parent)
            if dep != relative: options.extend(['-change', dep, relative])
        for rpath in info['rpaths']: options.extend(['-delete_rpath', rpath])
        if info['id']: options.extend(['-id', '@loader_path/' + path.name])
        if options: command('install_name_tool', *options, path)
        command('codesign', '--force', '--sign', '-', path)
    return audit(root)


def audit(root):
    rows = []
    for path in machos(root):
        info = metadata(path)
        if command('lipo', '-archs', path).strip() != 'arm64':
            raise ValueError('Unexpected binary architecture: ' + str(path))
        if info['minimum'] and tuple(map(int, info['minimum'].split('.'))) > (27, 0, 0):
            raise ValueError('Binary requires macOS newer than the wheel tag: ' + str(path))
        if info['rpaths']: raise ValueError('Unexpected runtime search path: ' + str(path))
        for dep in info['dependencies']:
            if dep.startswith(SYSTEM): continue
            if not dep.startswith('@loader_path/'):
                raise ValueError('External runtime dependency: ' + dep)
            destination = (path.parent / dep[len('@loader_path/'):]).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.is_file():
                raise ValueError('Missing/escaping runtime dependency: ' + dep)
        command('codesign', '--verify', path)
        rows.append({'path':path.relative_to(root).as_posix(), **info})
    return rows
