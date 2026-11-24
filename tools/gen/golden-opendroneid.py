#!/usr/bin/env python3
"""golden-opendroneid: golden vectors for packs/remote-id from
opendroneid-core-c, the reference implementation of broadcast Remote ID
(shared-model hardening, item 2: meaning is tested against an implementation
outside this project, not only engine agreement).

It fetches opendroneid.c and opendroneid.h at the commit the pack names,
refuses them unless their SHA-256 is the one packs/remote-id/PROVENANCE.md
records, compiles them with tools/gen/golden-opendroneid.c, runs the program
and writes packs/remote-id/vectors/golden-<kind>-<n>.json:

  input, expect  the message as the library's encoder writes it: a round trip
  model          "@kind" and the values the library's decoder gives; the
                 wire-integer keys from the library's encoded struct
  source         the library, its commit; no engine is run

Usage (a C compiler, network on the first run; standard library otherwise):

  python3 -I tools/gen/golden-opendroneid.py            write the vectors
  python3 -I tools/gen/golden-opendroneid.py --check    exit 1 when a committed
                                                        vector differs (CI)
  --cache DIR   keep the fetched files there
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACK = os.path.join(ROOT, "packs", "remote-id")
OUT = os.path.join(PACK, "vectors")
HARNESS = os.path.join(ROOT, "tools", "gen", "golden-opendroneid.c")
COMMIT = "849c03adbe0cdd68997a462fafab397edcfe53f3"
URL = "https://raw.githubusercontent.com/opendroneid/opendroneid-core-c/%s/libopendroneid/%s"
FILES = ("opendroneid.c", "opendroneid.h")
RAW = {
    "location": " The integers direction_raw, ew_direction, speed_h_raw, speed_mult and timestamp_ds are the fields of its "
                "encoded struct.",
    "auth-page0": " Only the last data byte is set, the one the pack maps.",
    "auth-page": " Only the last data byte is set, the one the pack maps.",
}


def recorded(name):
    """The SHA-256 that PROVENANCE.md records for libopendroneid/<name>."""
    for line in open(os.path.join(PACK, "PROVENANCE.md"), encoding="utf-8"):
        if line.startswith("| `libopendroneid/%s` |" % name):
            return line.split("|")[2].strip().strip("`")
    raise SystemExit("golden-opendroneid: PROVENANCE.md records no SHA-256 for %s" % name)


def fetch(cache):
    os.makedirs(cache, exist_ok=True)
    for name in FILES:
        local = os.path.join(cache, name)
        if not os.path.exists(local):
            with urllib.request.urlopen(URL % (COMMIT, name), timeout=60) as r:
                data = r.read()
        else:
            data = open(local, "rb").read()
        if hashlib.sha256(data).hexdigest() != recorded(name):
            raise SystemExit("golden-opendroneid: %s does not have the SHA-256 PROVENANCE.md records" % name)
        with open(local, "wb") as fh:
            fh.write(data)


def run(cache):
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "golden")
        subprocess.run([os.environ.get("CC", "cc"), "-O1", "-I", cache, HARNESS,
                        os.path.join(cache, "opendroneid.c"), "-lm", "-o", exe], check=True)
        return subprocess.run([exe], check=True, stdout=subprocess.PIPE).stdout.decode("ascii")


def value(text):
    tag, v = text.split(":", 1)
    if tag == "f":
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return v


def build(output):
    out = {}
    for line in output.splitlines():
        name, kind, hexa, *pairs = line.split("\t")
        model = {"@kind": kind}
        for p in pairs:
            k, v = p.split("=", 1)
            model[k] = value(v)
        out[name + ".json"] = {
            "name": name,
            "from": "remote-id",
            "to": "remote-id",
            "input": hexa,
            "expect": hexa,
            "model": model,
            "source": "opendroneid-core-c commit %s, libopendroneid/opendroneid.c: encoded and then decoded by the library. "
                      "Written by tools/gen/golden-opendroneid.py; no engine is run." % COMMIT,
            "reference": "The bytes are the library's encoder's and the values its decoder's.%s" % RAW.get(kind, ""),
        }
    return out


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-opendroneid", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cache")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        cache = args.cache or tmp
        fetch(cache)
        vecs = build(run(cache))
    have = {n for n in os.listdir(OUT) if n.startswith("golden-") and n.endswith(".json")}
    if args.check:
        bad = sorted(n for n in set(vecs) | have
                     if n not in vecs or n not in have or open(os.path.join(OUT, n), encoding="utf-8").read() != text(vecs[n]))
        if bad:
            print("golden-opendroneid: %d vector(s) differ from what the library writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-opendroneid: --check: ok, %d vectors" % len(vecs))
        return 0
    for n in have - set(vecs):
        os.remove(os.path.join(OUT, n))
    for n, v in vecs.items():
        with open(os.path.join(OUT, n), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text(v))
    print("golden-opendroneid: wrote %d vectors" % len(vecs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
