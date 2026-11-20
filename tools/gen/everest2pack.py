#!/usr/bin/env python3
"""everest2pack: the EVerest bus messages as goat-transformers packs, one per published type.

Usage: python3 -I tools/gen/everest2pack.py [--check] <everest-core checkout> <goat-transformers checkout>

EVerest (everest-core) defines its data types in `types/<file>.yaml`: a `types` mapping of
JSON Schema objects in YAML, which refer to one another as `/<file>#/<Type>`. Its
interfaces (`interfaces/<interface>.yaml`) publish `vars`, each a value of one type; an
object-typed var is a JSON message on the EVerest bus. This program makes one pack per
object type that some interface publishes as a var (`everest-<file>-<type>`); the types
used only as command arguments, results or inside other types are not packs of their own.

It reads the types files with the generators' YAML reader, turns each into a JSON document
whose `$ref`s point at the converted files (`/<file>#/<Type>` becomes
`<file>.json#/types/<Type>`), writes them to a temporary directory and passes each pack's
message to tools/gen/jsonschema2pack.py in this process. From the interfaces it reads only
the `$ref` of each var. Bindings (evidence in this project's words) are listed in BIND.
Also writes packs/everest-*/PROVENANCE.md. Every file goes through tools/gen/genio.py:
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

REPO = "https://github.com/EVerest/everest-core"
TAG = "2026.02.2"
COMMIT = "45dba2c049223d05beb7611c75d59f6639c46ee0"
READ_ON = "2026-11-20"

# (file, type) -> [(path, key, evidence)]
BIND = {
    ("powermeter", "Powermeter"): [
        ("timestamp", "time_ms", "types/powermeter.yaml: the time of the measurement, a date-time"),
        ("meter_id", "uid", "types/powermeter.yaml: the meter's identifier (for example the id printed on its case)")],
    ("ocpp", "EventData"): [
        ("timestamp", "time_ms", "types/ocpp.yaml: the moment the report was generated, a date-time")],
    ("ocpp", "SecurityEvent"): [
        ("timestamp", "time_ms", "types/ocpp.yaml: the moment the security event was generated, a date-time")],
    ("evse_manager", "SessionEvent"): [
        ("uuid", "uid", "types/evse_manager.yaml: the UUID the EVSE generates for the charging session")],
    ("evse_manager", "Limits"): [
        ("uuid", "uid", "types/evse_manager.yaml: the module's UUID, which identifies it globally")],
    ("energy", "EnergyFlowRequest"): [
        ("uuid", "uid", "types/energy.yaml: the UUID of the node of the energy tree that makes the request")],
    ("energy", "EnforcedLimits"): [
        ("uuid", "uid", "types/energy.yaml: the UUID of the node the limits apply to")],
}


class EverestError(Exception):
    pass


def kebab(name):
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    return s.replace("_", "-").lower()


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        try:
            return jsonschema2pack.yaml_load(fh.read()) or {}
        except jsonschema2pack.GenError as e:
            raise EverestError("%s: %s" % (path, e))


def rewrite(x, here):
    """The same document with every `/<file>#/<Type>` (and `#/<Type>`) reference pointed at
    the converted files."""
    if isinstance(x, dict):
        out = collections.OrderedDict()
        for k, v in x.items():
            if k == "$ref" and isinstance(v, str):
                m = re.fullmatch(r"/([A-Za-z0-9_]+)#/([A-Za-z0-9_]+)", v) or \
                    re.fullmatch(r"()#/([A-Za-z0-9_]+)", v)
                if not m:
                    raise EverestError("%s: reference %r is not /<file>#/<Type>" % (here, v))
                out[k] = "%s.json#/types/%s" % (m.group(1) or here, m.group(2))
            else:
                out[k] = rewrite(v, here)
        return out
    if isinstance(x, list):
        return [rewrite(v, here) for v in x]
    return x


def published(src, types):
    """Sorted [(file, type)] of object types some interface publishes as a var, and the
    interface files read."""
    found, read = set(), []
    idir = os.path.join(src, "interfaces")
    for f in sorted(os.listdir(idir)):
        if not f.endswith(".yaml"):
            continue
        read.append("interfaces/" + f)
        d = load_yaml(os.path.join(idir, f))
        for name, var in (d.get("vars") or {}).items():
            ref = (var or {}).get("$ref") if isinstance(var, dict) else None
            if not ref:
                continue
            m = re.fullmatch(r"/([A-Za-z0-9_]+)#/([A-Za-z0-9_]+)", ref)
            if not m:
                raise EverestError("interfaces/%s: var %s refers to %r" % (f, name, ref))
            key = (m.group(1), m.group(2))
            if key not in types:
                raise EverestError("interfaces/%s: var %s refers to %s, which no types file defines" % (f, name, ref))
            if types[key].get("type") == "object":
                found.add(key)
    return sorted(found), read


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def provenance(src, fmt, file_, type_, tread, iread):
    lic = os.path.join(src, "LICENSE")
    w = ["SPDX licence: Apache-2.0\n", "# Provenance of the %s pack\n" % fmt,
         "`tools/gen/everest2pack.py` reads the types files below, turns their references into",
         "references between JSON documents and passes `%s` of `types/%s.yaml` to" % (type_, file_),
         "`tools/gen/jsonschema2pack.py`; from the interface files it reads only which types they",
         "publish as vars. The files are not kept in this repository. Read on %s.\n" % READ_ON,
         "| | |\n|---|---|",
         "| Document | EVerest everest-core %s, type `%s` of `types/%s.yaml` |" % (TAG, type_, file_),
         "| Publisher | EVerest project (LF Energy) |",
         "| Repository | %s at tag `%s`, commit `%s` |" % (REPO, TAG, COMMIT),
         "| Download | `https://raw.githubusercontent.com/EVerest/everest-core/%s/types/%s.yaml` |" % (COMMIT, file_),
         "", "| File | SHA-256 |\n|---|---|"]
    for f in tread + iread:
        w.append("| `%s` | `%s` |" % (f, sha256(os.path.join(src, f))))
    w += ["| `LICENSE` | `%s` |" % sha256(lic), "", "## License\n",
          "The repository's `LICENSE` is the Apache License, Version 2.0; it opens:\n",
          "> Apache License", "> Version 2.0, January 2004", "> http://www.apache.org/licenses/", "",
          "The pack restates the type's structure (member names, types, nesting) with keys of this",
          "project's naming and takes no description text. It is not endorsed by the EVerest project.", ""]
    return "\n".join(w)


def run(args):
    src, gt = os.path.abspath(args.source), os.path.abspath(args.checkout)
    gen = os.path.join(gt, "tools", "gen")
    if not args.no_commit_check:
        r = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True)
        got = r.stdout.strip() if r.returncode == 0 else "no git commit"
        if got != COMMIT:
            print("everest2pack: %s is at %s, not %s (tag %s)" % (src, got, COMMIT, TAG), file=sys.stderr)
            return 1
    tdir = os.path.join(src, "types")
    docs, types, tread = {}, {}, []
    for f in sorted(os.listdir(tdir)):
        if not f.endswith(".yaml"):
            continue
        base = f[:-5]
        tread.append("types/" + f)
        d = load_yaml(os.path.join(tdir, f))
        docs[base] = rewrite(d, base)
        for t, s in (d.get("types") or {}).items():
            types[(base, t)] = s
    todo, iread = published(src, types)
    for (f, t) in BIND:
        if (f, t) not in todo:
            raise EverestError("BIND names %s#/%s, which no interface publishes" % (f, t))
    out = genio.Output(gt, check=args.check)
    status = 0
    with tempfile.TemporaryDirectory(prefix="everest2pack-") as tmp:
        paths = []
        for base, d in sorted(docs.items()):
            p = os.path.join(tmp, base + ".json")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(d, indent=1) + "\n")
            paths.append(p)
        for f, t in todo:
            fmt = "everest-%s-%s" % (f.replace("_", "-").lower(), kebab(t))
            module = "everest" + re.sub(r"[^a-z0-9]", "", (f + t).lower())
            main = os.path.join(tmp, f + ".json")
            argv = ["--schema"] + paths + ["--message", "%s=%s#/types/%s" % (t, main, t),
                    "--format", fmt, "--module", module,
                    "--title", "EVerest %s message %s (types/%s.yaml, everest-core)" % (TAG, t, f),
                    "--license", "Apache-2.0, EVerest (everest-core)",
                    "--source", "%s at tag %s, commit %s, types/%s.yaml#/types/%s" % (REPO, TAG, COMMIT, f, t),
                    "--out", gt, "--model-dir", os.path.join(gt, "model"),
                    "--names-file", os.path.join(gen, "names", fmt + ".json"),
                    "--notes-file", os.path.join(gen, "notes", "everest.md")]
            for path, key, ev in BIND.get((f, t), []):
                argv += ["--map", "%s:%s=%s" % (t, path, key), "--evidence", "%s:%s=%s" % (t, path, ev)]
            if args.check:
                argv.append("--check")
            with open(os.devnull, "w") as null, contextlib.redirect_stdout(null):
                r = jsonschema2pack.main(argv)
            if r:
                status = 1
                if not args.check:
                    print("everest2pack: %s failed" % fmt, file=sys.stderr)
                    return 1
            out.write("packs/%s/PROVENANCE.md" % fmt, provenance(src, fmt, f, t, tread, iread))
            if not args.check:
                print(fmt)
    return max(status, out.report("everest2pack (PROVENANCE.md)"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="everest2pack", description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="checkout of EVerest/everest-core at tag %s" % TAG)
    ap.add_argument("checkout", help="the goat-transformers checkout to write into")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; compare every file with the checkout, exit 1 on a difference")
    ap.add_argument("--no-commit-check", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        return run(args)
    except EverestError as e:
        print("everest2pack: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
