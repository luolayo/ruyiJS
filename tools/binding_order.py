"""Prototype member order of every Firefox WebIDL interface, read from the donor's generated
bindings (obj/dom/bindings/*Binding.cpp): regular operations, then attributes, then constants,
exactly as CreateInterfaceObjects defines them. Chrome-only and unforgeable specs are skipped
(unforgeable members live on instances). The runtime reorders each installed prototype by it
(src/runtime/binding_order_table.cpp)."""
import json
import re
from pathlib import Path

from provenance import write_if_changed

NAMESPACE = re.compile(r'^namespace (\w+)_Binding \{', re.M)
SECTIONS = (("sMethods_specs", "method"), ("sAttributes_specs", "attribute"), ("sConstants_specs", "constant"))


def _block(text, name):
    match = re.search(r'static const \w+(?:<[^>]*>)? ' + name + r'\[\] = \{(.*?)\n\};', text, re.S)
    return match.group(1) if match else ""


def _names(block, kind):
    names = []
    for line in block.splitlines():
        line = line.strip()
        if kind == "constant":
            found = re.match(r'\{ "([^"]+)",', line)
        else:
            found = re.match(r'(?:JS_FNSPEC|JS_FNINFO|JS_FN|JSPropertySpec::\w+|JS_PSGS|JS_PSG)\("([^"]+)"', line)
            symbol = re.match(r'JS_SYM_FNSPEC\((\w+),', line)
            if symbol:
                names.append("@@" + symbol.group(1))
                continue
        if found:
            names.append(found.group(1))
    return names


def collect(bindings):
    orders = {}
    for path in sorted(bindings.glob("*Binding.cpp")):
        text = path.read_text("utf-8", errors="replace")
        starts = [(m.start(), m.group(1)) for m in NAMESPACE.finditer(text)]
        for index, (start, name) in enumerate(starts):
            # A namespace ends at its own closing comment; another interface's
            # namespace may be nested inside it (Document_Binding holds
            # AdoptedStyleSheets_Binding), so its text is cut out of the body.
            close = text.find("} // namespace %s_Binding" % name, start)
            end = close if close >= 0 else (starts[index + 1][0] if index + 1 < len(starts) else len(text))
            body = text[start:end]
            for inner_start, inner in starts:
                if start < inner_start < end:
                    inner_end = text.find("} // namespace %s_Binding" % inner, inner_start)
                    if inner_end > 0:
                        body = body.replace(text[inner_start:inner_end], "")
            members, constants = [], 0
            for spec, kind in SECTIONS:
                if kind == "constant":
                    constants = len(members)
                for member in _names(_block(body, spec), kind):
                    if member not in members:
                        members.append(member)
            if members:
                orders[name] = (members, constants)
    return orders


def prepare(bindings, directory):
    bindings = Path(bindings)
    orders = collect(bindings)
    if len(orders) < 500 or "Node" not in orders or "Event" not in orders:
        raise ValueError("Firefox binding order source is incomplete")
    lines = ["// Generated from the donor's dom/bindings/*Binding.cpp; do not edit.",
             "#pragma once", "#include <cstddef>", "namespace ruyijs {",
             "struct BindingOrderEntry { const char* name; const char* const* members; size_t count; size_t constants; };"]
    for index, (name, (members, constants)) in enumerate(sorted(orders.items())):
        lines.append("inline constexpr const char* kBindingOrder%d[] = {%s};" %
                     (index, ", ".join(json.dumps(m) for m in members)))
    lines.append("inline constexpr BindingOrderEntry kBindingOrders[] = {")
    for index, (name, (members, constants)) in enumerate(sorted(orders.items())):
        lines.append("  {%s, kBindingOrder%d, %d, %d}," % (json.dumps(name), index, len(members), constants))
    lines += ["};", "}"]
    header = directory / "firefox_binding_order.h"
    write_if_changed(header, "\n".join(lines) + "\n", "utf-8")
    return [header] + sorted(bindings.glob("*Binding.cpp"))
