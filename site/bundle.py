#!/usr/bin/env python3
"""bundle.py: write site/assets/engine/ from the tree. Run by site/build.sh.

Reads the tree it sits in and writes, under site/assets/engine/:

  goat_transformers_wasm.wasm   the small build of bindings/wasm (copied)
  goat_transformers.mjs         the wrapper of bindings/wasm (copied)
  model/<module>.def            the model modules the demo packs use (copied)
  packs/<format>.def            the pack.def of each demo pack (copied)
  bundle.json                   samples, the modules each pack uses, what
                                carries between each pair, and the output
                                goat-xf gives for each sample
  manifest.json                 the library commit and the size and SHA-256
                                of every file above

Then it checks site/index.html against the tree: every number marked
data-stat, and the conversion shown when JavaScript is off. A difference is an
error, so the page cannot drift from the tree without the build failing.

Standard library only. Usage: python3 -I site/bundle.py --wasm <file> --goat-xf <file>
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "assets", "engine")

# The demo's formats, in the order the page lists them: pack, label, the
# vector whose `input` is the sample message, and a one-line description.
DEMO = [
    ("remote-id", "Remote ID (ASTM F3411)", "02-location-roundtrip.json",
     "Location message, the 25 bytes a drone broadcasts"),
    ("mavlink2", "MAVLink 2", "rt-00033-global_position_int.json",
     "GLOBAL_POSITION_INT, the position message of a drone autopilot"),
    ("nmea2000", "NMEA 2000", "rt-pgn129025.json",
     "parameter group 129025, position, from a ship's instrument network"),
    ("cot-xml", "Cursor on Target XML", "01-track-to-geojson.json",
     "an event, the XML that tactical map software reads"),
    ("cot-protobuf", "Cursor on Target protobuf", "03-full-message-roundtrip.json",
     "TAK protocol version 1 message"),
    ("geojson", "GeoJSON", "01-geojson-to-cot.json",
     "a Feature (IETF RFC 7946)"),
    ("nvg", "NATO Vector Graphics", "01-nvg-to-geojson.json",
     "a point"),
    ("canonical-track-v2", "Canonical Track v2", "24-to-asterix-cat062-open-billie-sample.json",
     "a radar track as JSON, the contract of open-billie"),
    ("asterix-cat062", "ASTERIX Category 062", "01-open-billie-sample-roundtrip.json",
     "a system track record, 31 bytes"),
]
# Values only the caller knows, offered by the page when the target is this
# format. The same values as the pack's own vectors use.
CONTEXT = {"asterix-cat062": {"cat062.sac": "1", "cat062.sic": "7"}}
# A dropped-key list longer than this is given as a count only.
MAX_DROPPED = 40
# The conversion index.html shows when JavaScript is off.
STATIC = [("remote-id", "cot-xml"), ("remote-id", "nmea2000")]


def die(msg):
    print("bundle.py: " + msg, file=sys.stderr)
    sys.exit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def pack_uses(path):
    """The model modules a pack.def names with `uses`, in order."""
    uses = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            tok = line.split()
            if tok and tok[0] == "uses" and line[0] not in " \t#" and len(tok) > 1:
                uses.append(tok[1])
    return uses


def pack_wire(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            tok = line.split()
            if tok and tok[0] == "wire" and line[0] not in " \t#" and len(tok) > 1:
                return tok[1]
    return ""


def count_stats():
    """The numbers the page quotes, from tools/repo-stats, the counter that
    README.md is tested against, so the page and the README count alike."""
    r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools", "repo-stats"), "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die("tools/repo-stats failed: " + r.stderr.strip())
    t = json.loads(r.stdout)
    n = t["formats"]
    return {
        "formats": n,
        "packs": t["packs"],
        "message_kinds": t["message_kinds"],
        "conversion_vectors": t["conversion_vectors"],
        "load_vectors": t["load_vectors"],
        "engines": len(t["engines"]),
        "pair_converters": n * (n - 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wasm", required=True)
    ap.add_argument("--goat-xf", required=True)
    ap.add_argument("--no-check", action="store_true", help="do not compare index.html with the tree")
    a = ap.parse_args()
    for p in (a.wasm, a.goat_xf):
        if not os.path.isfile(p):
            die("not found: " + p)

    names = [d[0] for d in DEMO]
    only = ",".join(names)

    def xf(*args, stdin=None):
        # --models: only the modules the demo packs use, which were copied above
        r = subprocess.run([a.goat_xf, *args, "--packs", os.path.join(REPO, "packs"), "--packs-only", only,
                            "--models", os.path.join(OUT, "model")],
                           input=stdin, capture_output=True, text=True)
        return r.returncode, r.stdout.rstrip("\n"), r.stderr.strip()

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "model"))
    os.makedirs(os.path.join(OUT, "packs"))

    files = {}  # path under engine/ -> where it came from in the tree

    def put(src_rel, dst_rel):
        shutil.copyfile(os.path.join(REPO, src_rel), os.path.join(OUT, dst_rel))
        files[dst_rel] = src_rel

    shutil.copyfile(a.wasm, os.path.join(OUT, "goat_transformers_wasm.wasm"))
    files["goat_transformers_wasm.wasm"] = "bindings/wasm, `cargo build --profile small --target wasm32-unknown-unknown`"
    put("bindings/wasm/goat_transformers.mjs", "goat_transformers.mjs")

    formats = []
    modules = ["core"]
    for name, label, vector, what in DEMO:
        pdef = "packs/%s/pack.def" % name
        uses = pack_uses(os.path.join(REPO, pdef))
        for m in uses:
            if m not in modules:
                modules.append(m)
        put(pdef, "packs/%s.def" % name)
        vpath = "packs/%s/vectors/%s" % (name, vector)
        with open(os.path.join(REPO, vpath), encoding="utf-8") as f:
            sample = json.load(f)["input"]
        formats.append({
            "name": name, "label": label, "what": what,
            "wire": pack_wire(os.path.join(REPO, pdef)),
            "uses": ["core"] + [m for m in uses if m != "core"],
            "sample": sample, "sample_from": vpath,
        })
    for m in modules:
        put("model/%s.def" % m, "model/%s.def" % m)

    # What carries between each pair: `goat-xf matrix --detail`.
    code, out, err = xf("matrix", "--detail")
    if code != 0:
        die("goat-xf matrix failed: " + err)
    line_rx = re.compile(r"^\s*(\S+) -> (\S+)\s+(FULL|PARTIAL|NONE)\s+carries: \[(.*?)\](?:\s+dropped: (.*?) \(target .*\))?\s*$")
    capability = {}
    for line in out.split("\n"):
        m = line_rx.match(line)
        if not m:
            continue
        src, dst, grade, carried, dropped = m.groups()
        carried = [k for k in carried.split(", ") if k]
        dropped = [k for k in (dropped or "").split(", ") if k]
        seen, uniq = set(), []
        for k in dropped:
            if k not in seen:
                seen.add(k)
                uniq.append(k)
        entry = {"grade": grade.lower(), "carried": carried, "dropped_count": len(uniq)}
        if len(uniq) <= MAX_DROPPED:
            entry["dropped"] = uniq
        capability["%s>%s" % (src, dst)] = entry
    want = len(names) * (len(names) - 1)
    if len(capability) != want:
        die("read %d pairs from `goat-xf matrix --detail`, expected %d" % (len(capability), want))

    # The output goat-xf gives for each sample and each target. A pair is
    # offered by the page when this conversion succeeds.
    pairs = {}
    for f in formats:
        for t in names:
            if t == f["name"]:
                continue
            ctx = CONTEXT.get(t, {})
            sets = []
            for k, v in ctx.items():
                sets += ["--set", "%s=%s" % (k, v)]
            code, out, err = xf("convert", "--from", f["name"], "--to", t, *sets, stdin=f["sample"])
            if code == 0:
                pairs["%s>%s" % (f["name"], t)] = {"expect": out, "context": ctx}
    for s, t in STATIC:
        if "%s>%s" % (s, t) not in pairs:
            die("the static conversion %s to %s no longer succeeds" % (s, t))

    commit = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    stats = count_stats()
    stats["wasm_bytes"] = os.path.getsize(os.path.join(OUT, "goat_transformers_wasm.wasm"))

    bundle = {"commit": commit, "formats": formats, "capability": capability, "pairs": pairs, "stats": stats}
    with open(os.path.join(OUT, "bundle.json"), "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    files["bundle.json"] = "site/bundle.py"

    manifest = {
        "library": "https://github.com/USAREUR-AF/goat-transformers",
        "commit": commit,
        "built_by": "site/build.sh",
        "files": [
            {"path": p, "from": files[p], "bytes": os.path.getsize(os.path.join(OUT, p)),
             "sha256": sha256(os.path.join(OUT, p))}
            for p in sorted(files)
        ],
    }
    manifest["total_bytes"] = sum(e["bytes"] for e in manifest["files"])
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print("bundle.py: %d files, %s bytes, commit %s" % (len(files), format(manifest["total_bytes"], ","), commit[:7]))
    for k in sorted(stats):
        print("  %-20s %s" % (k, format(stats[k], ",")))
    print("  pairs offered        %d of %d" % (len(pairs), want))

    if a.no_check:
        return 0
    return check_page(stats, pairs)


def check_page(stats, pairs):
    """index.html must state the tree's numbers and goat-xf's output."""
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
        html = f.read()
    bad = 0
    found = re.findall(r'data-stat="([a-z_]+)"[^>]*>([^<]*)<', html)
    if not found:
        print("bundle.py: check: index.html has no data-stat elements")
        bad += 1
    for key, text in found:
        if key not in stats:
            print("bundle.py: check: index.html names an unknown number `%s`" % key)
            bad += 1
            continue
        if text.strip().replace(",", "") != str(stats[key]):
            # The module's size depends on the compiler version; the page
            # corrects it from the manifest when it loads.
            if key == "wasm_bytes":
                print("bundle.py: note: index.html states %s bytes for the module, this build is %s" % (
                    text.strip(), format(stats[key], ",")))
                continue
            print("bundle.py: check: index.html states %s = %s, the tree has %s" % (key, text.strip(), format(stats[key], ",")))
            bad += 1
    plain = html.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    for s, t in STATIC:
        expect = pairs["%s>%s" % (s, t)]["expect"]
        if expect not in plain:
            print("bundle.py: check: index.html does not show the goat-xf output of %s to %s: %s" % (s, t, expect))
            bad += 1
    if bad:
        print("bundle.py: FAIL, index.html differs from the tree in %d place(s)" % bad)
        return 1
    print("bundle.py: index.html agrees with the tree (%d numbers, %d conversions)" % (len(found), len(STATIC)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
