#!/usr/bin/env python3
"""Cross-check the UTM OpenAPI files against InterUSS's api.py modules.

The astm-f3411-* and astm-f3548-v21-* packs are generated from the OpenAPI files
(tools/gen/utm-run.sh), but their source of record is InterUSS's Apache-2.0 restatement of
the same interfaces in interuss/uas_standards (src/uas_standards/astm/<std>/<ver>/api.py).
This script compares, for every object schema of an OpenAPI file that api.py also defines
as a class, the member names and the JSON kind of each member (string, number, integer,
boolean, array, object), and prints every difference. Exit status 0 when the two agree on
every class, 1 otherwise.

Usage: python3 -I tools/gen/utm-crosscheck.py <openapi.yaml> <api.py> [<openapi.yaml> <api.py> ...]
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jsonschema2pack as j  # noqa: E402  (its YAML reader)

PRIM = {"str": "string", "float": "number", "int": "integer", "bool": "boolean", "dict": "object",
        "StringBasedDateTime": "string", "StringBasedTimeDelta": "string"}


def py_model(path):
    """({class: {member: annotation node}}, {alias: annotation node}, {enum classes})"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    classes, aliases, enums = {}, {}, set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = {ast.unparse(b) for b in node.bases}
            if "Enum" in bases or "str" in bases and any("Enum" in b for b in bases):
                enums.add(node.name)
                continue
            members = {}
            for st in node.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    members[st.target.id] = st.annotation
            classes[node.name] = members
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            aliases[node.targets[0].id] = node.value
    return classes, aliases, enums


def py_kind(ann, classes, aliases, enums, seen=()):
    s = ast.unparse(ann)
    if isinstance(ann, ast.BinOp):          # X | None
        parts = [p for p in (ann.left, ann.right) if ast.unparse(p) != "None"]
        return py_kind(parts[0], classes, aliases, enums, seen) if parts else None
    if isinstance(ann, ast.Subscript):
        head = ast.unparse(ann.value)
        if head in ("List", "list"):
            return "array"
        if head in ("Optional",):
            return py_kind(ann.slice, classes, aliases, enums, seen)
        if head in ("Dict", "dict"):
            return "object"
    if s in PRIM:
        return PRIM[s]
    if s in enums:
        return "string"
    if s in classes:
        return "object"
    if s in aliases and s not in seen:
        return py_kind(aliases[s], classes, aliases, enums, seen + (s,))
    return "?" + s


def yaml_kind(sch, comps, seen=()):
    if not isinstance(sch, dict):
        return None
    if "$ref" in sch:
        name = sch["$ref"].rsplit("/", 1)[1]
        if name in seen:
            return "object"
        return yaml_kind(comps.get(name, {}), comps, seen + (name,))
    for k in ("allOf", "anyOf", "oneOf"):
        if k in sch:
            kinds = {yaml_kind(x, comps, seen) for x in sch[k]} - {None}
            return kinds.pop() if len(kinds) == 1 else "/".join(sorted(kinds))
    t = sch.get("type")
    if t:
        return t
    if "properties" in sch:
        return "object"
    if "enum" in sch:
        return "string"
    return None


def yaml_props(sch, comps):
    """Members of an object schema, allOf merged."""
    out = {}
    if "$ref" in sch:
        return yaml_props(comps[sch["$ref"].rsplit("/", 1)[1]], comps)
    for part in sch.get("allOf", []):
        out.update(yaml_props(part, comps))
    out.update(sch.get("properties", {}))
    return out


def check(yaml_path, py_path):
    doc = j.load_doc(yaml_path)
    doc = doc[0] if isinstance(doc, tuple) else doc
    comps = doc["components"]["schemas"]
    classes, aliases, enums = py_model(py_path)
    diffs, compared = [], 0
    for name, sch in comps.items():
        if name not in classes or yaml_kind(sch, comps) != "object":
            continue
        compared += 1
        yp, pp = yaml_props(sch, comps), classes[name]
        for m in sorted(set(yp) - set(pp)):
            diffs.append("%s.%s: only in the OpenAPI file" % (name, m))
        for m in sorted(set(pp) - set(yp)):
            diffs.append("%s.%s: only in api.py" % (name, m))
        for m in sorted(set(yp) & set(pp)):
            yk, pk = yaml_kind(yp[m], comps), py_kind(pp[m], classes, aliases, enums)
            if yk != pk and not (yk == "number" and pk == "integer"):
                diffs.append("%s.%s: OpenAPI %s, api.py %s" % (name, m, yk, pk))
    missing = sorted(n for n, s in comps.items() if yaml_kind(s, comps) == "object" and n not in classes)
    # an object member that api.py types as a bare dict (or an alias of dict): the members of
    # its object are only in the OpenAPI file
    for name, sch in comps.items():
        if name not in classes:
            continue
        for m, ann in classes[name].items():
            a = ast.unparse(ann).replace(" | None", "")
            target = ast.unparse(aliases[a]) if a in aliases else a
            y = yaml_props(sch, comps).get(m)
            refs = [x for x in [y or {}] + (y or {}).get("anyOf", []) + (y or {}).get("allOf", []) if "$ref" in x]
            if target == "dict" and refs and any(yaml_props(r, comps) for r in refs):
                diffs.append("%s.%s: api.py types it as an untyped dict; its members are only in the OpenAPI file"
                             % (name, m))
    return compared, diffs, missing


def main(argv):
    if len(argv) < 2 or len(argv) % 2:
        print(__doc__, file=sys.stderr)
        return 2
    bad = 0
    for yaml_path, py_path in zip(argv[0::2], argv[1::2]):
        compared, diffs, missing = check(yaml_path, py_path)
        print("%s vs %s: %d classes compared, %d differences" % (
            os.path.basename(os.path.dirname(yaml_path)) or yaml_path, os.path.basename(py_path), compared, len(diffs)))
        for d in diffs:
            print("  " + d)
        if missing:
            print("  object schemas with no class of the same name in api.py: " + ", ".join(missing))
        bad += len(diffs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
