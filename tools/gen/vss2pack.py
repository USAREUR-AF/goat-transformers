#!/usr/bin/env python3
"""vss2pack: the COVESA Vehicle Signal Specification tree as one goat-transformers pack, vss-vehicle.

Usage: python3 -I tools/gen/vss2pack.py [--check] <vehicle_signal_specification checkout> <goat-transformers checkout>

VSS is a tree of signals, not a set of messages. `spec/VehicleSignalSpecification.vspec`
of COVESA/vehicle_signal_specification is the root; it and the files it includes
(`#include <file> [<prefix>]`) define nodes by dotted name, each with a `type` (branch,
sensor, actuator, attribute), a `datatype` for a signal, and on a branch possibly
`instances` (the branch's children are repeated under each instance: `Row[1,2]` is Row1
and Row2, a list of lists is one level per list) and on a child `instantiate: false`.

This program reads those keys only (no description, comment, unit or allowed-value text),
expands instances, and builds a JSON Schema of the document a VSS tree gives as JSON when
each branch is an object and each signal its value (the shape of a vss-tools JSON export
of values): `{"Vehicle": {"Speed": 12.5, "CurrentLocation": {"Latitude": ...}}}`. The
`VehicleDataTypes` branch holds type definitions, not signals, and is left out. The
schema is written to a temporary directory as `vss-vehicle.schema.json` and passed to
tools/gen/jsonschema2pack.py in this process.

The vspec files are read with a reader for their regular layout (node names at column 0,
keys at column 2, longer values continued on deeper lines, list items `    - x`); a line it
does not expect stops the run.

Types: boolean is a boolean; int8 to int64 and uint8 to uint64 are integers; float and
double are numbers; string is a string; `<type>[]` is an array of it.

Bindings (evidence in this project's words, in tools/gen/notes/vss.md):
Vehicle.CurrentLocation.Latitude/Longitude = lat/lon, .Altitude = hae,
.Timestamp = time_ms (iso8601_ms, --date-time), Vehicle.Speed = speed_ms (scale:5/18).
Also writes packs/vss-vehicle/PROVENANCE.md. Every file goes through tools/gen/genio.py:
with --check nothing is written and the exit status is 1 when a file differs.
Python 3 standard library only.
"""
import argparse
import collections
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio              # noqa: E402
import jsonschema2pack    # noqa: E402

REPO = "https://github.com/COVESA/vehicle_signal_specification"
TAG = "v6.1"
COMMIT = "2817646d1808fc7c470c0432fc7f4ed685e5c9e3"
READ_ON = "2026-11-20"
ROOT_FILE = "spec/VehicleSignalSpecification.vspec"
FORMAT, MODULE = "vss-vehicle", "vssvehicle"
LEFT_OUT = ("VehicleDataTypes",)

INTEGER = {"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"}
NUMBER = {"float", "double"}

LOC = "Vehicle.CurrentLocation."
MAPS = [(LOC + "Latitude", "lat", None), (LOC + "Longitude", "lon", None), (LOC + "Altitude", "hae", None),
        (LOC + "Timestamp", "time_ms", None), ("Vehicle.Speed", "speed_ms", "scale:5/18")]
EVIDENCE = {
    LOC + "Latitude": "spec/Vehicle/Vehicle.vspec: latitude of the GNSS antenna in WGS 84 geodetic coordinates, degrees",
    LOC + "Longitude": "spec/Vehicle/Vehicle.vspec: longitude of the GNSS antenna in WGS 84 geodetic coordinates, degrees",
    LOC + "Altitude": "spec/Vehicle/Vehicle.vspec: altitude of the GNSS antenna above the WGS 84 reference ellipsoid, metres",
    LOC + "Timestamp": ("spec/Vehicle/Vehicle.vspec: the GNSS time of the current location, a string in ISO 8601 "
                        "with the UTC time zone"),
    "Vehicle.Speed": ("spec/Vehicle/Vehicle.vspec: the vehicle's speed in km/h; read as speed_ms with scale:5/18 "
                      "(1 km/h = 5/18 m/s)"),
}


class VssError(Exception):
    pass


# --------------------------------------------------------------------------
# Reading vspec files
# --------------------------------------------------------------------------

def parse_list(text, where):
    """The value of `instances` as written: a range `Name[a,b]`, a quoted or bare name,
    or a `[...]` list of these and of lists."""
    tok = re.compile(r'\s*(?:([A-Za-z_][A-Za-z0-9_]*\[\d+\s*,\s*\d+\])|"([^"]*)"|\'([^\']*)\'|(\[)|(\])|(,)|([A-Za-z_][A-Za-z0-9_]*))')
    pos, stack, cur, out = 0, [], None, None
    text = text.strip()
    while pos < len(text):
        m = tok.match(text, pos)
        if not m or m.end() == pos:
            raise VssError("%s: instances %r: not a list this reader takes" % (where, text))
        pos = m.end()
        rng, dq, sq, op, cl, comma, bare = m.groups()
        if op:
            new = []
            if cur is not None:
                cur.append(new)
                stack.append(cur)
            cur = new
            if out is None:
                out = new
        elif cl:
            if cur is None:
                raise VssError("%s: instances %r: unbalanced ]" % (where, text))
            cur = stack.pop() if stack else None
        elif comma:
            continue
        else:
            v = rng or (dq if dq is not None else sq if sq is not None else bare)
            if cur is None:
                if out is not None:
                    raise VssError("%s: instances %r: text after the list" % (where, text))
                out = v
            else:
                cur.append(v)
    if stack or (isinstance(out, list) and cur is not None):
        raise VssError("%s: instances %r: unbalanced [" % (where, text))
    return out


def read_vspec(path):
    """([(name, {key: value})] in file order, [(include file, prefix or "")])."""
    nodes, includes = [], []
    cur, key, pending, depth = None, None, None, 0
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    for n, line in enumerate(lines, 1):
        where = "%s:%d" % (path, n)
        if not line.strip():
            continue
        if line.startswith("#include"):
            m = re.fullmatch(r"#include\s+(\S+)(?:\s+(\S+))?\s*", line)
            if not m:
                raise VssError("%s: not an include line" % where)
            includes.append((m.group(1), m.group(2) or ""))
            continue
        if line.startswith("#"):
            continue
        if not line.startswith(" "):
            m = re.fullmatch(r"([A-Za-z0-9_.]+):\s*", line)
            if not m:
                raise VssError("%s: not a node name line" % where)
            cur = {}
            nodes.append((m.group(1), cur))
            key, pending = None, None
            continue
        if cur is None:
            raise VssError("%s: a key before the first node" % where)
        m = re.fullmatch(r"  ([A-Za-z_]+):(?:\s+(.*?))?\s*", line)
        if line.startswith("  ") and not line.startswith("   ") and not line.lstrip().startswith("#") \
                and not (depth > 0 and not m):
            if not m:
                raise VssError("%s: not a key line" % where)
            depth = (m.group(2) or "").count("[") - (m.group(2) or "").count("]")
            key, val = m.group(1), (m.group(2) or "")
            pending = None
            if key in ("type", "datatype"):
                cur[key] = val.strip("'\"")
            elif key == "instantiate":
                if val not in ("true", "false"):
                    raise VssError("%s: instantiate %r" % (where, val))
                cur[key] = val == "true"
            elif key == "instances":
                if val == "":
                    cur[key] = []
                    pending = "items"
                else:
                    pending = val
                    if val.count("[") == val.count("]"):
                        cur[key] = parse_list(val, where)
                        pending = None
            continue
        # deeper lines: list items of `instances`, the rest of an `instances` value, or
        # the continuation of a value this program does not read
        s = line.strip()
        depth += s.count("[") - s.count("]")
        if key == "instances" and pending == "items" and s.startswith("- "):
            cur["instances"].append(parse_list(s[2:], where))
        elif key == "instances" and pending not in (None, "items"):
            pending += " " + s
            if pending.count("[") == pending.count("]"):
                cur["instances"] = parse_list(pending, where)
                pending = None
    if pending not in (None, "items"):
        raise VssError("%s: instances value does not end" % path)
    return nodes, includes


def load_tree(spec_root, rel, prefix="", seen=None, read=None):
    """OrderedDict full name -> merged keys, following includes."""
    seen = seen if seen is not None else set()
    path = os.path.join(spec_root, rel)
    if rel in seen:
        raise VssError("include cycle at %s" % rel)
    read.add(os.path.relpath(path, os.path.dirname(spec_root)))
    out = collections.OrderedDict()
    nodes, includes = read_vspec(path)
    for name, keys in nodes:
        full = prefix + "." + name if prefix else name
        out.setdefault(full, {}).update(keys)
    for inc, inc_prefix in includes:
        cand = os.path.normpath(os.path.join(os.path.dirname(rel), inc))
        if not os.path.exists(os.path.join(spec_root, cand)):
            cand = os.path.normpath(inc)
        if not os.path.exists(os.path.join(spec_root, cand)):
            raise VssError("%s includes %s, which is not found" % (rel, inc))
        p = ".".join(x for x in (prefix, inc_prefix) if x)
        for full, keys in load_tree(spec_root, cand, p, seen | {rel}, read).items():
            out.setdefault(full, {}).update(keys)
    return out


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------

def expand_range(v):
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\s*,\s*(\d+)\]", v)
    if not m:
        return [v]
    a, b = int(m.group(2)), int(m.group(3))
    if b < a:
        raise VssError("instance range %s runs backwards" % v)
    return ["%s%d" % (m.group(1), i) for i in range(a, b + 1)]


def instance_levels(spec):
    """[[names of level 1], [names of level 2], ...]"""
    if isinstance(spec, str):
        return [expand_range(spec)]
    if not isinstance(spec, list) or not spec:
        raise VssError("instances %r" % (spec,))
    if any(isinstance(x, list) or re.search(r"\[\d", x) for x in spec):
        levels = []
        for x in spec:
            if isinstance(x, list):
                names = []
                for y in x:
                    if not isinstance(y, str):
                        raise VssError("instances %r: a list inside a level" % (spec,))
                    names += expand_range(y)
                levels.append(names)
            else:
                levels.append(expand_range(x))
        return levels
    return [list(spec)]


def leaf_schema(name, keys):
    dt = keys.get("datatype")
    if dt is None:
        raise VssError("signal %s has no datatype" % name)
    arr = dt.endswith("[]")
    base = dt[:-2] if arr else dt
    if base == "boolean":
        s = {"type": "boolean"}
    elif base in INTEGER:
        s = {"type": "integer"}
    elif base in NUMBER:
        s = {"type": "number"}
    elif base == "string":
        s = {"type": "string"}
    else:
        raise VssError("signal %s has datatype %s, which this program does not take" % (name, dt))
    return {"type": "array", "items": s} if arr else s


def build_schema(tree):
    children = collections.defaultdict(list)
    for name in tree:
        if "." in name:
            children[name.rsplit(".", 1)[0]].append(name)
    for name, keys in tree.items():
        if "." in name and name.rsplit(".", 1)[0] not in tree:
            raise VssError("%s has no parent node %s" % (name, name.rsplit(".", 1)[0]))
        if "type" not in keys:
            raise VssError("node %s has no type" % name)

    def render(name):
        keys = tree[name]
        if keys["type"] != "branch":
            return leaf_schema(name, keys)
        own = collections.OrderedDict()
        inst = collections.OrderedDict()
        for c in children[name]:
            short = c.rsplit(".", 1)[1]
            if "instances" in keys and tree[c].get("instantiate", True):
                inst[short] = render(c)
            else:
                own[short] = render(c)
        if "instances" in keys:
            levels = instance_levels(keys["instances"])

            def nest(i):
                if i == len(levels):
                    return {"type": "object", "properties": json.loads(json.dumps(inst))}
                return {"type": "object", "properties": collections.OrderedDict((n, nest(i + 1)) for n in levels[i])}
            for n, s in nest(0)["properties"].items():
                if n in own:
                    raise VssError("%s: instance %s is also a child" % (name, n))
                own[n] = s
        return {"type": "object", "properties": own}

    roots = [n for n in tree if "." not in n and n not in LEFT_OUT]
    doc = collections.OrderedDict([("$schema", "https://json-schema.org/draft/2020-12/schema"),
                                   ("type", "object"),
                                   ("properties", collections.OrderedDict((r, render(r)) for r in roots))])
    return doc


def count_leaves(s):
    if s.get("type") == "object":
        return sum(count_leaves(v) for v in s["properties"].values())
    return 1


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def provenance(src, read, n_signals):
    lic = os.path.join(src, "LICENSE")
    w = ["# Provenance of the %s pack\n" % FORMAT,
         "`tools/gen/vss2pack.py` reads the files below (the `type`, `datatype`, `instances` and",
         "`instantiate` keys of their nodes, no text), expands the instances into %d signals, builds a" % n_signals,
         "JSON Schema of the tree as a document and passes it to `tools/gen/jsonschema2pack.py`. The",
         "files are not kept in this repository. Read on %s.\n" % READ_ON,
         "| | |\n|---|---|",
         "| Document | COVESA Vehicle Signal Specification (VSS) %s, the signal tree |" % TAG,
         "| Publisher | COVESA (Connected Vehicle Systems Alliance) |",
         "| Repository | %s at tag `%s`, commit `%s` |" % (REPO, TAG, COMMIT),
         "| Download | `https://raw.githubusercontent.com/COVESA/vehicle_signal_specification/%s/%s` and the files it includes |"
         % (COMMIT, ROOT_FILE), "",
         "| File | SHA-256 |\n|---|---|"]
    for f in sorted(read):
        w.append("| `%s` | `%s` |" % (f, sha256(os.path.join(src, f))))
    w += ["| `LICENSE` | `%s` |" % sha256(lic), "",
          "## License\n",
          "`LICENSE` is the Mozilla Public License, Version 2.0. Its title, and the notice each vspec",
          "file carries in its header (in full, the file's own words):\n",
          "> Mozilla Public License Version 2.0", ">",
          "> Copyright (c) 2016 Contributors to COVESA",
          ">",
          "> This program and the accompanying materials are made available under the",
          "> terms of the Mozilla Public License 2.0 which is available at",
          "> https://www.mozilla.org/en-US/MPL/2.0/",
          ">", "> SPDX-License-Identifier: MPL-2.0", "",
          "The pack is not a copy or a modification of the vspec files: it restates the tree's",
          "structure (node names, data types, the expansion of instances) with keys of this",
          "project's naming and takes no description, comment or allowed-value text. It is not",
          "endorsed by COVESA.", ""]
    return "\n".join(w)


def run(args):
    src, gt = os.path.abspath(args.source), os.path.abspath(args.checkout)
    gen = os.path.join(gt, "tools", "gen")
    if not args.no_commit_check:
        r = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True)
        got = r.stdout.strip() if r.returncode == 0 else "no git commit"
        if got != COMMIT:
            print("vss2pack: %s is at %s, not %s (tag %s)" % (src, got, COMMIT, TAG), file=sys.stderr)
            return 1
    read = set()
    tree = load_tree(os.path.join(src, "spec"), os.path.relpath(ROOT_FILE, "spec"), "", None, read)
    doc = build_schema(tree)
    n = count_leaves(doc)
    out = genio.Output(gt, check=args.check)
    with tempfile.TemporaryDirectory(prefix="vss2pack-") as tmp:
        spath = os.path.join(tmp, "vss-vehicle.schema.json")
        with open(spath, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=1) + "\n")
        argv = ["--schema", spath, "--message", "vehicle=" + spath, "--format", FORMAT, "--module", MODULE,
                "--title", "COVESA Vehicle Signal Specification (VSS) %s signal tree as a JSON document "
                "(structure by tools/gen/vss2pack.py)" % TAG,
                "--license", "MPL-2.0, Contributors to COVESA (COVESA/vehicle_signal_specification)",
                "--source", "%s at tag %s, commit %s, %s and the files it includes" % (REPO, TAG, COMMIT, ROOT_FILE),
                "--out", gt, "--model-dir", os.path.join(gt, "model"),
                "--names-file", os.path.join(gen, "names", FORMAT + ".json"),
                "--notes-file", os.path.join(gen, "notes", "vss.md"),
                "--max-depth", str(args.max_depth),
                "--limit-reason", ("the deepest VSS signals sit below the instance levels; the limit "
                                   "keeps every signal of the tree and no more")]
        present = {p for p, _, _ in MAPS if _has(doc, p)}
        for path, key, scale in MAPS:
            if path not in present:
                continue
            if key == "time_ms":
                argv += ["--date-time", "vehicle:" + path]
            argv += ["--map", "vehicle:%s=%s" % (path, key), "--evidence", "vehicle:%s=%s" % (path, EVIDENCE[path])]
            if scale:
                argv += ["--scale", "vehicle:%s=%s" % (path, scale)]
        if not args.no_cross:
            argv += ["--cross", "%s=%s:input" % (os.path.join(gt, "packs", "geojson", "pack.def"),
                                                os.path.join(gt, "packs", "geojson", "vectors",
                                                             "01-geojson-to-cot.json"))]
        if args.check:
            argv.append("--check")
        with open(os.devnull, "w") as null, contextlib.redirect_stdout(null):
            status = jsonschema2pack.main(argv)
    out.write("packs/%s/PROVENANCE.md" % FORMAT, provenance(src, read, n))
    if not args.check and not status:
        print(FORMAT)
    return max(status or 0, out.report("vss2pack (PROVENANCE.md)"))


def _has(doc, path):
    node = doc
    for p in path.split("."):
        props = node.get("properties") or {}
        if p not in props:
            return False
        node = props[p]
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vss2pack", description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="checkout of COVESA/vehicle_signal_specification at tag %s" % TAG)
    ap.add_argument("checkout", help="the goat-transformers checkout to write into")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; compare every file with the checkout, exit 1 on a difference")
    ap.add_argument("--max-depth", type=int, default=10, help=argparse.SUPPRESS)
    ap.add_argument("--no-commit-check", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-cross", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        return run(args)
    except VssError as e:
        print("vss2pack: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
