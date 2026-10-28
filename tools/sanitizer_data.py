"""Firefox's HTML Sanitizer data for the Document Model's Sanitizer, read from the donor:
the safe default configuration (dom/security/sanitizer/safe-default-configuration.json)
and the event handler content attribute names removeUnsafe() removes
(dom/events/EventNameList.inc: EVENT, WINDOW_ONLY_EVENT, DOCUMENT_ONLY_EVENT and
NON_IDL_EVENT entries, as nsContentUtils::InitializeEventTable registers them, whose
EventNameType has a bit outside EventNameType_XUL). Output: build/<mode>/firefox_sanitizer_data.h."""
import json
import re
from pathlib import Path

from provenance import write_if_changed

ENTRY = re.compile(r"^(EVENT|WINDOW_ONLY_EVENT|WINDOW_EVENT|DOCUMENT_ONLY_EVENT|NON_IDL_EVENT|FORWARDED_EVENT|"
                   r"TOUCH_EVENT|ERROR_EVENT|BEFOREUNLOAD_EVENT)\((\w+),\s*\w+,\s*([^,]+?),", re.M | re.S)
# Every entry reaches the table nsContentUtils builds (Firefox 158 removes the four
# touch handler attributes too, so TOUCH_EVENT is registered in this build).
REGISTERED = {"EVENT", "WINDOW_ONLY_EVENT", "WINDOW_EVENT", "DOCUMENT_ONLY_EVENT", "NON_IDL_EVENT",
              "FORWARDED_EVENT", "ERROR_EVENT", "BEFOREUNLOAD_EVENT", "TOUCH_EVENT"}
# nsContentUtils.h EventNameType; removeUnsafe() takes EventNameType_All & ~EventNameType_XUL.
TYPES = {"None": 0x0, "HTML": 0x1, "XUL": 0x2, "SVGGraphic": 0x4, "SVGSVG": 0x8, "SMIL": 0x10,
         "HTMLBodyOrFramesetOnly": 0x20, "HTMLMedia": 0x40, "HTMLXUL": 0x3, "All": 0xFFFF}


def _mask(expression):
    return sum(TYPES[name] for name in re.findall(r"EventNameType_(\w+)", expression))


def _events(text):
    names = []
    # Android-only entries are compiled out of desktop builds.
    text = re.sub(r"#if defined\(MOZ_WIDGET_ANDROID\).*?#endif", "", text, flags=re.S)
    for kind, name, types in ENTRY.findall(text):
        if kind not in REGISTERED or not (_mask(types) & (0xFFFF & ~TYPES["XUL"])):
            continue
        if ("on" + name) not in names:
            names.append("on" + name)
    return names


def prepare(source, directory):
    source = Path(source)
    config_path = source / "dom/security/sanitizer/safe-default-configuration.json"
    events_path = source / "dom/events/EventNameList.inc"
    config = json.loads(config_path.read_text("utf-8"))
    events = _events(events_path.read_text("utf-8"))
    if len(config.get("elements", [])) < 100 or len(events) < 100:
        raise ValueError("Firefox sanitizer source is incomplete")
    lines = ["// Generated from the donor's sanitizer configuration and EventNameList.inc; do not edit.",
             "#pragma once", "namespace ruyijs {",
             "struct SanitizerDefaultElement { const char* name; const char* ns; const char* const* attributes; };"]
    for index, element in enumerate(config["elements"]):
        attrs = ", ".join(json.dumps(a["name"]) for a in element["attributes"])
        lines.append("inline constexpr const char* kSanitizerElementAttributes%d[] = {%s};" %
                     (index, (attrs + ", " if attrs else "") + "nullptr"))
    lines.append("inline constexpr SanitizerDefaultElement kSanitizerDefaultElements[] = {")
    for index, element in enumerate(config["elements"]):
        lines.append("  {%s, %s, kSanitizerElementAttributes%d}," % (json.dumps(element["name"]),
                                                                    json.dumps(element["namespace"]), index))
    lines.append("};")
    lines.append("inline constexpr const char* kSanitizerDefaultAttributes[] = {%s};" %
                 ", ".join(json.dumps(a["name"]) for a in config["attributes"]))
    lines.append("inline constexpr const char* kSanitizerEventAttributes[] = {%s};" %
                 ", ".join(json.dumps(name) for name in events))
    lines += ["}", ""]
    header = Path(directory) / "firefox_sanitizer_data.h"
    write_if_changed(header, "\n".join(lines), "utf-8")
    return [header, config_path, events_path]
