#!/usr/bin/env python3
"""ecs2pack: the Elastic Common Schema event document as one goat-transformers pack, ecs-event.

Usage: python3 -I tools/gen/ecs2pack.py [--check] <elastic/ecs checkout> <goat-transformers checkout>

ECS defines one document, an event, made of field sets. `generated/ecs/ecs_flat.yml` of the
elastic/ecs repository lists every field of that document by its dotted name with, among
other things, its Elasticsearch type (`type`), whether it holds an array (`normalize`
contains `array`) and, for an `object`, the type of its free-form values (`object_type`).
This program reads those keys only (no description, example or other text), builds a JSON
Schema of the document's structure (dotted names as nested objects; `nested` as an array
of objects), writes it to a temporary directory as `ecs-event.schema.json` and passes it
to tools/gen/jsonschema2pack.py in this process. The file is read with a reader for the
regular layout PyYAML writes it in (field names at column 0, keys at column 2, values on
the same line, list items `  - x`); a line it does not expect stops the run.

Types: keyword, constant_keyword, wildcard, text, match_only_text, ip, version, binary
and date are strings; long, integer, short, byte and unsigned_long are integers; float,
half_float, scaled_float and double are numbers; boolean is a boolean; geo_point is the
object form {lat, lon}; an object or flattened field whose names are data is left free
(not mapped).

Bindings (--map, evidence in this project's words): `@timestamp`=time_ms (iso8601_ms,
by --date-time), `event.id`=uid, `host.geo.location.lat`/`lon`=lat/lon.
Also writes packs/ecs-event/PROVENANCE.md. Every file goes through tools/gen/genio.py:
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

REPO = "https://github.com/elastic/ecs"
TAG = "v9.5.0"
COMMIT = "401807e0547301525acd28c4fb667203fec66d59"
READ_ON = "2026-11-20"
FLAT = "generated/ecs/ecs_flat.yml"
FORMAT, MODULE = "ecs-event", "ecsevent"

STRING = {"keyword", "constant_keyword", "wildcard", "text", "match_only_text", "ip", "version",
          "binary", "date"}
INTEGER = {"long", "integer", "short", "byte", "unsigned_long"}
NUMBER = {"float", "half_float", "scaled_float", "double"}

EVIDENCE = {
    "@timestamp": ("schemas/base.yml and ecs_flat.yml: the date and time the event originated, a "
                   "date field; ECS examples write it as ISO 8601 in UTC with Z"),
    "event.id": "schemas/event.yml: an identifier unique to the event",
    "host.geo.location.lat": ("schemas/geo.yml: location is a geo_point, written as an object of "
                              "lat and lon in degrees; schemas/host.yml: the host the event happened on"),
    "host.geo.location.lon": ("schemas/geo.yml: location is a geo_point, written as an object of "
                              "lat and lon in degrees; schemas/host.yml: the host the event happened on"),
}
MAPS = [("@timestamp", "time_ms"), ("event.id", "uid"),
        ("host.geo.location.lat", "lat"), ("host.geo.location.lon", "lon")]


class EcsError(Exception):
    pass


def read_flat(path):
    """OrderedDict field name -> {type, normalize: [..], object_type}: the keys this program uses."""
    fields = collections.OrderedDict()
    cur, key, in_list = None, None, None
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if not line.startswith(" "):
                m = re.fullmatch(r"('([^']*)'|([^\s:]+)):", line)
                if not m:
                    raise EcsError("%s:%d: not a field name line" % (path, n))
                name = m.group(2) if m.group(2) is not None else m.group(3)
                cur = fields.setdefault(name, {"normalize": []})
                key, in_list = None, None
                continue
            if cur is None:
                raise EcsError("%s:%d: a key before the first field" % (path, n))
            if line.startswith("  ") and not line.startswith("   "):
                body = line[2:]
                if body.startswith("- "):
                    if in_list == "normalize":
                        cur["normalize"].append(body[2:].strip())
                    continue
                m = re.match(r"([A-Za-z_]+):(?: (.*))?$", body)
                if not m:
                    raise EcsError("%s:%d: not a key line" % (path, n))
                key, val = m.group(1), (m.group(2) or "").strip()
                in_list = key if val == "" else None
                if key in ("type", "object_type"):
                    cur[key] = val.strip("'")
                elif key == "normalize" and val not in ("", "[]"):
                    raise EcsError("%s:%d: normalize in a form this reader does not take" % (path, n))
            # deeper lines continue a value this program does not read
    for name, f in fields.items():
        if "type" not in f:
            raise EcsError("%s: field %s has no type" % (path, name))
    return fields


def leaf_schema(f):
    t = f["type"]
    if t in STRING:
        s = {"type": "string"}
    elif t in INTEGER:
        s = {"type": "integer"}
    elif t in NUMBER:
        s = {"type": "number"}
    elif t == "boolean":
        s = {"type": "boolean"}
    elif t == "geo_point":
        s = {"type": "object", "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}}}
    elif t in ("object", "flattened"):
        s = {"type": "object", "additionalProperties": {"anyOf": [{}]}}
    elif t == "nested":
        s = {"type": "array", "items": {"type": "object", "additionalProperties": {"anyOf": [{}]}}}
    else:
        raise EcsError("type %s is not one this program knows" % t)
    if "array" in f["normalize"] and t not in ("nested",):
        s = {"type": "array", "items": s}
    return s


def build_schema(fields):
    """A JSON Schema document: dotted names as nested objects. A field that also has
    children (an `object` or `nested` with fields under it) holds them."""
    root = collections.OrderedDict(type="object", properties=collections.OrderedDict())

    def container(node):
        if node.get("type") == "array":
            node = node["items"]
        node.pop("additionalProperties", None)
        return node.setdefault("properties", collections.OrderedDict())

    for name in sorted(fields):
        parts = name.split(".")
        props = root["properties"]
        for p in parts[:-1]:
            node = props.get(p)
            if node is None:
                node = props[p] = collections.OrderedDict(type="object", properties=collections.OrderedDict())
            props = container(node)
        last = parts[-1]
        s = leaf_schema(fields[name])
        if last in props:
            # children were placed first (sorting puts `a` before `a.b`, so this is rare): keep them
            kids = container(props[last])
            props[last] = s
            container(s).update(kids)
        else:
            props[last] = s
    return root


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def provenance(src, n_fields):
    lic, notice, flat = (os.path.join(src, f) for f in ("LICENSE.txt", "NOTICE.txt", FLAT))
    with open(notice, encoding="utf-8") as fh:
        ntext = fh.read().strip()
    w = ["# Provenance of the %s pack\n" % FORMAT,
         "`tools/gen/ecs2pack.py` reads `%s` (the type, array and object-type keys of its %d" % (FLAT, n_fields),
         "fields, no text), builds a JSON Schema of the document's structure and passes it to",
         "`tools/gen/jsonschema2pack.py`. The pack's notes cite `schemas/*.yml` for the bindings in",
         "this project's words. The files are not kept in this repository. Read on %s.\n" % READ_ON,
         "| | |\n|---|---|",
         "| Document | Elastic Common Schema (ECS) %s, the event document |" % TAG,
         "| Publisher | Elasticsearch B.V. |",
         "| Repository | %s at tag `%s`, commit `%s` |" % (REPO, TAG, COMMIT),
         "| Download | `https://raw.githubusercontent.com/elastic/ecs/%s/%s` |" % (COMMIT, FLAT), "",
         "| File | SHA-256 | Read by the generator |\n|---|---|---|",
         "| `%s` | `%s` | yes |" % (FLAT, sha256(flat))]
    for f in ("schemas/base.yml", "schemas/event.yml", "schemas/geo.yml", "schemas/host.yml"):
        w.append("| `%s` | `%s` | no (cited in the notes) |" % (f, sha256(os.path.join(src, f))))
    w += ["| `LICENSE.txt` | `%s` | no |" % sha256(lic), "| `NOTICE.txt` | `%s` | no |" % sha256(notice), "",
          "## License\n",
          "`LICENSE.txt` is the Apache License, Version 2.0; it opens:\n",
          "> Apache License", "> Version 2.0, January 2004", "> http://www.apache.org/licenses/", "",
          "`NOTICE.txt`, which the license asks to be carried with derivative works, in full:\n",
          "\n".join(("> " + l) if l.strip() else ">" for l in ntext.split("\n")), "",
          "The pack restates the document's structure (field names, types, nesting) with keys of",
          "this project's naming. It takes no description or example text of the schema. It is not",
          "endorsed by Elasticsearch B.V.", ""]
    return "\n".join(w)


def run(args):
    src, gt = os.path.abspath(args.source), os.path.abspath(args.checkout)
    gen = os.path.join(gt, "tools", "gen")
    if not args.no_commit_check:
        r = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True)
        got = r.stdout.strip() if r.returncode == 0 else "no git commit"
        if got != COMMIT:
            print("ecs2pack: %s is at %s, not %s (tag %s)" % (src, got, COMMIT, TAG), file=sys.stderr)
            return 1
    fields = read_flat(os.path.join(src, FLAT))
    doc = build_schema(fields)
    out = genio.Output(gt, check=args.check)
    with tempfile.TemporaryDirectory(prefix="ecs2pack-") as tmp:
        spath = os.path.join(tmp, "ecs-event.schema.json")
        with open(spath, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=1) + "\n")
        argv = ["--schema", spath, "--message", "event=" + spath, "--format", FORMAT, "--module", MODULE,
                "--title", "Elastic Common Schema (ECS) %s event document (structure from %s by tools/gen/ecs2pack.py)"
                % (TAG, FLAT),
                "--license", "Apache-2.0, Elasticsearch B.V. (elastic/ecs)",
                "--source", "%s at tag %s, commit %s, %s" % (REPO, TAG, COMMIT, FLAT),
                "--out", gt, "--model-dir", os.path.join(gt, "model"),
                "--names-file", os.path.join(gen, "names", FORMAT + ".json"),
                "--notes-file", os.path.join(gen, "notes", "ecs.md"),
                "--date-time", "event:@timestamp"]
        for path, key in MAPS:
            argv += ["--map", "event:%s=%s" % (path, key), "--evidence", "event:%s=%s" % (path, EVIDENCE[path])]
        if not args.no_cross:
            argv += ["--cross", "%s=%s:input" % (os.path.join(gt, "packs", "geojson", "pack.def"),
                                                os.path.join(gt, "packs", "geojson", "vectors",
                                                             "01-geojson-to-cot.json"))]
        if args.check:
            argv.append("--check")
        with open(os.devnull, "w") as null, contextlib.redirect_stdout(null):
            status = jsonschema2pack.main(argv)
    out.write("packs/%s/PROVENANCE.md" % FORMAT, provenance(src, len(fields)))
    if not args.check and not status:
        print(FORMAT)
    return max(status or 0, out.report("ecs2pack (PROVENANCE.md)"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ecs2pack", description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="checkout of elastic/ecs at tag %s" % TAG)
    ap.add_argument("checkout", help="the goat-transformers checkout to write into")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; compare every file with the checkout, exit 1 on a difference")
    ap.add_argument("--no-commit-check", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-cross", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        return run(args)
    except EcsError as e:
        print("ecs2pack: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
