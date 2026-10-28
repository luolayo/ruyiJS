"""Prepare read-only Firefox font configuration and HarfBuzz production inputs."""
import json
from pathlib import Path
import re
from provenance import write_if_changed

FLAGS = ['-DHB_NO_PAINT', '-DHB_NO_DRAW', '-DHB_NO_BUFFER_SERIALIZE',
         '-DHB_NO_BUFFER_VERIFY', '-DHB_NO_AAT', '-DHB_NO_SUBSET']


def prepare(donor, directory, prefs):
    folder = donor.src / 'gfx/harfbuzz/src'
    source = folder / 'harfbuzz.cc'
    includes = re.findall(r'^#include "([^"]+)"', source.read_text('utf-8'), re.M)
    unity = directory / 'harfbuzz.cpp'
    write_if_changed(unity, '// Generated donor unity; original files retain their licenses.\n' +
        '\n'.join('#include "' + (folder / name).as_posix() + '"'
                  for name in includes if (folder / name).is_file()) + '\n', 'utf-8')
    prefs = Path(prefs)
    values = {}
    for key, value in re.findall(r'pref\("(font\.(?:name-list|name|default)[^"\n]*)",\s*("(?:[^"\\]|\\.)*")\);',
                                 prefs.read_text('utf-8')):
        values[key] = json.loads(value)
    if not values.get('font.name-list.serif.x-western') or not values.get('font.name-list.emoji'):
        raise ValueError('Firefox font preference source is incomplete')
    header = directory / 'firefox_font_prefs.h'
    rows = ',\n'.join('  {' + json.dumps(k) + ', ' + json.dumps(v) + '}' for k, v in sorted(values.items()))
    write_if_changed(header, '// Generated from the recorded Firefox greprefs.js; do not edit.\n'
        '#pragma once\nnamespace ruyijs::web_geometry {\n'
        'struct FontPreference { const char* key; const char* value; };\n'
        'inline constexpr FontPreference kFontPreferences[] = {\n' + rows + '\n};\n}\n', 'utf-8')
    inputs = [unity, header, prefs, source]
    inputs += [p for p in folder.iterdir() if p.suffix in ('.hh', '.h', '.cc')]
    licenses = [p for p in folder.parent.glob('COPYING*') if p.is_file()]
    if not licenses:
        raise ValueError('HarfBuzz license missing')
    return (unity, 'geometry_harfbuzz'), inputs + licenses
