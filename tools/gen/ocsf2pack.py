#!/usr/bin/env python3
"""ocsf2pack: one goat-transformers pack per OCSF event class, from ocsf/ocsf-schema.

Usage: python3 -I tools/gen/ocsf2pack.py [--check] [--only NAME,...] <ocsf-schema checkout> <goat-transformers checkout>

The Open Cybersecurity Schema Framework states its event classes in its own JSON form, not
as JSON Schema: `dictionary.json` (every attribute's type and whether it is an array),
`categories.json`, `objects/*.json` and `events/**/*.json`, where a class or an object
names its parent with `extends` and takes profile attributes with `$include`. This
program resolves that form for one class at a time:

  - `extends` is followed to the root (`base_event` for classes); a child's attribute
    entry is merged over the parent's, member by member;
  - `$include` of `profiles/<name>.json` adds that profile's attributes marked with the
    profile; an attribute keeps a profile mark until a later entry sets `profile` to null;
    an attribute marked with a profile, inline or by include, is left out (profiles are
    not part of the class unless a producer applies them);
  - each attribute's type is the entry's `type` or the dictionary's; a type of the
    dictionary's `types` resolves to its base (`string_t`, `integer_t`, `long_t`,
    `float_t`, `boolean_t`; `json_t` has no JSON type); any other type names an object,
    which is resolved the same way; `is_array` makes it an array.

The result is a JSON Schema document (draft 2020-12, the objects under `$defs`) that
holds structure only: no description, caption or enum text of the source. It is written
to a temporary directory as `<class>.schema.json` and given to tools/gen/jsonschema2pack.py
in this process, with:

  --message <class>, --when class_uid=<category uid * 1000 + class uid>,
  --map time=time_ms, metadata.uid=uid, and device.location.lat/long=lat/lon where the
  class has `device` as an attribute of its own (not through the host profile),
  --evidence for each binding in this project's words, --max-depth MAX_DEPTH.

It also writes packs/ocsf-<class>/PROVENANCE.md (every source file read, with its
SHA-256, and the license) and adds to the notes of each pack the profile attributes it
left out. Every file goes through tools/gen/genio.py: with --check nothing is written,
every run is made, and the exit status is 1 when any file differs.
Python 3 standard library only.
"""
import argparse
import collections
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio              # noqa: E402
import jsonschema2pack    # noqa: E402

REPO = "https://github.com/ocsf/ocsf-schema"
TAG = "1.9.0"
COMMIT = "856d462bd20dc46cc1ffed2dfffe3b91ef0fbeba"
READ_ON = "2026-11-20"
MAX_DEPTH = 3

BASES = {"string_t": "string", "integer_t": "integer", "long_t": "integer", "float_t": "number",
         "boolean_t": "boolean", "json_t": None}

EV_TIME = ("dictionary.json: time is a timestamp_t, which the dictionary gives as milliseconds "
           "since 1970-01-01 00:00:00 UTC; base_event makes it the time the event occurred")
EV_UID = ("objects/metadata.json: uid is the identifier the OCSF event carries, its own and "
          "not the source system's")
EV_LAT = ("objects/location.json and dictionary.json: lat is the latitude in decimal degrees "
          "(the datum is not stated)")
EV_LON = ("objects/location.json and dictionary.json: long is the longitude in decimal degrees "
          "(the datum is not stated)")


class OcsfError(Exception):
    pass


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh, object_pairs_hook=collections.OrderedDict)


class Schema:
    def __init__(self, src):
        self.src = src
        d = load_json(os.path.join(src, "dictionary.json"))
        self.dict_attrs = d["attributes"]
        self.types = d["types"]["attributes"]
        self.categories = load_json(os.path.join(src, "categories.json"))["attributes"]
        self.objects, self.object_file = {}, {}
        for f in sorted(os.listdir(os.path.join(src, "objects"))):
            if f.endswith(".json"):
                o = load_json(os.path.join(src, "objects", f))
                self.objects[o["name"]] = o
                self.object_file[o["name"]] = "objects/" + f
        self.classes, self.class_file = {}, {}
        for root, dirs, files in os.walk(os.path.join(src, "events")):
            dirs.sort()
            for f in sorted(files):
                if f.endswith(".json"):
                    c = load_json(os.path.join(root, f))
                    self.classes[c["name"]] = c
                    self.class_file[c["name"]] = os.path.relpath(os.path.join(root, f), src)
        self.read = set()      # relative paths of every file a resolution read

    def profile_attrs(self, rel):
        p = load_json(os.path.join(self.src, rel))
        self.read.add(rel)
        return p.get("name") or os.path.basename(rel)[:-5], p.get("attributes") or {}

    def resolve(self, item, table, files, stack=()):
        """OrderedDict attribute name -> merged entry (a dict, with "profile" when marked)."""
        name = item["name"]
        if name in stack:
            raise OcsfError("extends cycle at %s" % name)
        self.read.add(files[name])
        out = collections.OrderedDict()
        parent = item.get("extends")
        if parent:
            if parent not in table:
                raise OcsfError("%s extends %s, which is not defined" % (name, parent))
            for k, v in self.resolve(table[parent], table, files, stack + (name,)).items():
                out[k] = dict(v)
        attrs = item.get("attributes") or {}
        for rel in attrs.get("$include", []):
            if not rel.startswith("profiles/"):
                raise OcsfError("%s includes %s, which is not a profile" % (name, rel))
            pname, pattrs = self.profile_attrs(rel)
            for k, v in pattrs.items():
                e = dict(out.get(k, {}))
                e.update(v)
                e["profile"] = pname
                out[k] = e
        for k, v in attrs.items():
            if k == "$include":
                continue
            e = dict(out.get(k, {}))
            e.update(v)
            out[k] = e
        return out

    def json_type(self, t):
        seen = set()
        while t in self.types and t not in BASES:
            if t in seen:
                raise OcsfError("type cycle at %s" % t)
            seen.add(t)
            t = self.types[t].get("type") or t
        return t

    def to_schema(self, name, entry, defs, todo):
        d = self.dict_attrs.get(name)
        if d is None:
            raise OcsfError("attribute %s is not in dictionary.json" % name)
        t = entry.get("type") or d["type"]
        is_array = entry.get("is_array", d.get("is_array", False))
        base = self.json_type(t)
        if base in BASES:
            s = {"type": BASES[base]} if BASES[base] else {}
        elif t in self.objects:
            s = {"$ref": "#/$defs/" + t}
            if t not in defs and t not in todo:
                todo.append(t)
        else:
            raise OcsfError("attribute %s has type %s, which is neither a type nor an object" % (name, t))
        return {"type": "array", "items": s} if is_array else s


def class_schema(sch, cname):
    """(JSON Schema document, [(attribute, profile)] left out, object-level profile names left out)."""
    attrs = sch.resolve(sch.classes[cname], sch.classes, sch.class_file)
    defs, todo, left = collections.OrderedDict(), [], []
    props = collections.OrderedDict()
    for k, e in attrs.items():
        if e.get("profile"):
            left.append((k, e["profile"]))
            continue
        props[k] = sch.to_schema(k, e, defs, todo)
    obj_left = collections.OrderedDict()
    while todo:
        o = todo.pop(0)
        oattrs = sch.resolve(sch.objects[o], sch.objects, sch.object_file)
        op = collections.OrderedDict()
        for k, e in oattrs.items():
            if e.get("profile"):
                obj_left.setdefault(e["profile"], set()).add("%s.%s" % (o, k))
                continue
            op[k] = sch.to_schema(k, e, defs, todo)
        defs[o] = {"type": "object", "properties": op}
    doc = collections.OrderedDict([("$schema", "https://json-schema.org/draft/2020-12/schema"),
                                   ("type", "object"), ("properties", props),
                                   ("$defs", collections.OrderedDict(sorted(defs.items())))])
    return doc, left, obj_left


def class_uid(sch, c):
    # the category is stated by the class or by its nearest ancestor that states one
    cur, cat = c, None
    while cur is not None and cat is None:
        cat = cur.get("category")
        cur = sch.classes.get(cur.get("extends")) if cur.get("extends") else None
    if cat not in sch.categories:
        raise OcsfError("class %s: no category %s" % (c["name"], cat))
    return sch.categories[cat]["uid"] * 1000 + c["uid"]


def event_classes(sch):
    return sorted(n for n, c in sch.classes.items() if "uid" in c)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def notes_text(base_notes, cname, left, obj_left):
    w = [base_notes.rstrip(), "", "## Profile attributes left out of this class", ""]
    if left:
        w.append("| Attribute | Profile |\n|---|---|")
        for k, p in left:
            w.append("| `%s` | `%s` |" % (k, p))
    else:
        w.append("None at the class level.")
    if obj_left:
        w.append("")
        w.append("Inside objects the class uses, profile attributes are left out too:")
        w.append("")
        for p in sorted(obj_left):
            w.append("- `%s`: %s" % (p, ", ".join("`%s`" % x for x in sorted(obj_left[p]))))
    w.append("")
    return "\n".join(w)


def provenance(sch, fmt, cname, files):
    lic = os.path.join(sch.src, "LICENSE")
    notice = os.path.join(sch.src, "NOTICE")
    with open(notice, encoding="utf-8") as fh:
        ntext = fh.read().strip()
    w = ["# Provenance of the %s pack\n" % fmt,
         "`tools/gen/ocsf2pack.py` reads the files below, resolves the class `%s` into a JSON" % cname,
         "Schema of structure only and passes it to `tools/gen/jsonschema2pack.py`. The files are",
         "not kept in this repository. Read on %s.\n" % READ_ON,
         "| | |\n|---|---|",
         "| Document | Open Cybersecurity Schema Framework (OCSF) %s, event class `%s` |" % (TAG, cname),
         "| Publisher | OCSF, a Series of LF Projects, LLC |",
         "| Repository | %s at tag `%s`, commit `%s` |" % (REPO, TAG, COMMIT), "",
         "| File | SHA-256 |\n|---|---|"]
    for f in sorted(files):
        w.append("| `%s` | `%s` |" % (f, sha256(os.path.join(sch.src, f))))
    w += ["", "## License\n",
          "The repository's `LICENSE` (SHA-256 `%s`) is the Apache License, Version 2.0; it opens:\n"
          % sha256(lic),
          "> Apache License", "> Version 2.0, January 2004", "> http://www.apache.org/licenses/", "",
          "Its `NOTICE` (SHA-256 `%s`), which the license asks to be carried with derivative works, "
          "in full:\n" % sha256(notice),
          "\n".join(("> " + l) if l.strip() else ">" for l in ntext.split("\n")), "",
          "The pack restates the class's structure (attribute names, types, nesting) with keys of",
          "this project's naming. It takes no description, caption or enum text of the schema. It",
          "is not endorsed by the OCSF project.", ""]
    return "\n".join(w)


def run(args):
    src, gt = os.path.abspath(args.source), os.path.abspath(args.checkout)
    gen = os.path.join(gt, "tools", "gen")
    if not args.no_commit_check:
        r = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True)
        got = r.stdout.strip() if r.returncode == 0 else "no git commit"
        if got != COMMIT:
            print("ocsf2pack: %s is at %s, not %s (tag %s)" % (src, got, COMMIT, TAG), file=sys.stderr)
            return 1
    sch = Schema(src)
    names = event_classes(sch)
    if args.only:
        want = set(args.only.split(","))
        missing = want - set(names)
        if missing:
            print("ocsf2pack: no event class %s" % ", ".join(sorted(missing)), file=sys.stderr)
            return 2
        names = [n for n in names if n in want]
    with open(os.path.join(gen, "notes", "ocsf.md"), encoding="utf-8") as fh:
        base_notes = fh.read()
    out = genio.Output(gt, check=args.check)
    status = 0
    with tempfile.TemporaryDirectory(prefix="ocsf2pack-") as tmp:
        for cname in names:
            sch.read = {"dictionary.json", "categories.json"}
            doc, left, obj_left = class_schema(sch, cname)
            c = sch.classes[cname]
            fmt = "ocsf-" + cname.replace("_", "-")
            module = "ocsf" + cname.replace("_", "")
            spath = os.path.join(tmp, cname + ".schema.json")
            with open(spath, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(doc, indent=1) + "\n")
            npath = os.path.join(tmp, cname + ".notes.md")
            with open(npath, "w", encoding="utf-8") as fh:
                fh.write(notes_text(base_notes, cname, left, obj_left))
            argv = ["--schema", spath, "--message", "%s=%s" % (cname, spath),
                    "--when", "class_uid=%d" % class_uid(sch, c),
                    "--format", fmt, "--module", module,
                    "--title", "OCSF %s event class %s (structure resolved by tools/gen/ocsf2pack.py)" % (TAG, cname),
                    "--license", "Apache-2.0, OCSF a Series of LF Projects, LLC (ocsf/ocsf-schema)",
                    "--source", "%s at tag %s, commit %s: %s, its ancestors, the objects it uses and dictionary.json"
                    % (REPO, TAG, COMMIT, sch.class_file[cname]),
                    "--out", gt, "--model-dir", os.path.join(gt, "model"),
                    "--names-file", os.path.join(gen, "names", fmt + ".json"),
                    "--notes-file", npath, "--max-depth", str(MAX_DEPTH),
                    "--limit-reason", "OCSF objects nest deeply and refer to one another; three levels "
                    "keep a pack within a few hundred keys",
                    "--map", "%s:time=time_ms" % cname, "--evidence", "%s:time=%s" % (cname, EV_TIME),
                    "--map", "%s:metadata.uid=uid" % cname, "--evidence", "%s:metadata.uid=%s" % (cname, EV_UID)]
            if "device" in doc["properties"] and "location" in \
                    doc["$defs"].get("device", {}).get("properties", {}):
                argv += ["--map", "%s:device.location.lat=lat" % cname,
                         "--evidence", "%s:device.location.lat=%s" % (cname, EV_LAT),
                         "--map", "%s:device.location.long=lon" % cname,
                         "--evidence", "%s:device.location.long=%s" % (cname, EV_LON)]
            if cname in args.cross:
                argv += ["--cross", "%s=%s:input" % (os.path.join(gt, "packs", "geojson", "pack.def"),
                                                    os.path.join(gt, "packs", "geojson", "vectors",
                                                                 "01-geojson-to-cot.json"))]
            if args.check:
                argv.append("--check")
            with open(os.devnull, "w") as null, contextlib.redirect_stdout(null):
                r = jsonschema2pack.main(argv)
            if r:
                status = 1
                if not args.check:
                    print("ocsf2pack: %s failed" % fmt, file=sys.stderr)
                    return 1
            out.write("packs/%s/PROVENANCE.md" % fmt, provenance(sch, fmt, cname, sch.read | {"LICENSE", "NOTICE"}))
            if not args.check:
                print(fmt)
    return max(status, out.report("ocsf2pack (PROVENANCE.md)"))


CROSS = ("device_config_state_change",)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ocsf2pack", description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="checkout of ocsf/ocsf-schema at tag %s" % TAG)
    ap.add_argument("checkout", help="the goat-transformers checkout to write into")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; compare every file with the checkout, exit 1 on a difference")
    ap.add_argument("--only", metavar="NAME,...", help="only these event classes")
    ap.add_argument("--no-commit-check", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    args.cross = CROSS
    try:
        return run(args)
    except OcsfError as e:
        print("ocsf2pack: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
