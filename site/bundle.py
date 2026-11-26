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
data-stat, and the conversion shown when JavaScript is off. A conversion the
page shows that the tree does not give is an error. A count (formats, packs,
message kinds, vectors) that the tree has moved past is a note, as for the
README: the counts are updated in the counts pull request after each merge
wave, never in a feature pull request (AGENTS.md). In that pull request,
`--counts-only --write` writes the tree's counts into the page, and
`--counts-only` fails when one differs; neither needs the module built.

Standard library only. Usage:
  python3 -I site/bundle.py --wasm <file> --goat-xf <file>
  python3 -I site/bundle.py --counts-only [--write]
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


# The README's figures the page shows, copied from docs/figures/ on every
# build so the page and the README show the same drawing. Not kept in git.
FIGURES = ["hub-light.svg", "hub-dark.svg"]
FIG_OUT = os.path.join(HERE, "assets", "figures")


def copy_readme_figures():
    if os.path.isdir(FIG_OUT):
        shutil.rmtree(FIG_OUT)
    os.makedirs(FIG_OUT)
    for name in FIGURES:
        shutil.copyfile(os.path.join(REPO, "docs", "figures", name), os.path.join(FIG_OUT, name))


def check_figures(html):
    """index.html shows each copied figure, and its alt text is the README's."""
    bad = 0
    for name in FIGURES:
        if "assets/figures/" + name not in html:
            print("bundle.py: check: index.html does not show assets/figures/%s" % name)
            bad += 1
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    m = re.search(r'<img src="docs/figures/hub-light.svg"[^>]*alt="([^"]*)"', readme)
    page = re.search(r'<img src="assets/figures/hub-light.svg"[^>]*alt="([^"]*)"', html)
    if not m or not page or m.group(1) != page.group(1):
        print("bundle.py: check: the alt text of the hub figure differs from README.md")
        bad += 1
    return bad


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


COUNTS = ("formats", "packs", "message_kinds", "conversion_vectors", "load_vectors", "engines", "pair_converters")


def counts_only(write):
    """Compare (or with `write`, set) the page's counts with the tree's."""
    path = os.path.join(HERE, "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    stats = count_stats()
    differ = []

    def fix(m):
        key, text = m.group(1), m.group(3)
        if key in COUNTS and text.strip().replace(",", "") != str(stats[key]):
            differ.append((key, text.strip(), format(stats[key], ",")))
            return 'data-stat="%s"%s>%s<' % (key, m.group(2), format(stats[key], ","))
        return m.group(0)

    new = re.sub(r'data-stat="([a-z_]+)"([^>]*)>([^<]*)<', fix, html)
    for key, was, now in differ:
        print("bundle.py: %s: index.html states %s, the tree has %s" % (key, was, now))
    if write:
        if new != html:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
        print("bundle.py: wrote %d count(s) into index.html" % len(differ))
        return 0
    if differ:
        print("bundle.py: FAIL, %d count(s) differ: run python3 -I site/bundle.py --counts-only --write" % len(differ))
        return 1
    print("bundle.py: every count of index.html is the tree's")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wasm")
    ap.add_argument("--goat-xf")
    ap.add_argument("--no-check", action="store_true", help="do not compare index.html with the tree")
    ap.add_argument("--counts-only", action="store_true",
                    help="only compare the page's counts with the tree (the counts pull request); no module needed")
    ap.add_argument("--write", action="store_true", help="with --counts-only: write the tree's counts into the page")
    a = ap.parse_args()
    if a.counts_only:
        return counts_only(a.write)
    if a.write:
        die("--write goes with --counts-only")
    if not (a.wasm and a.goat_xf):
        die("--wasm and --goat-xf are required")
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
    copy_readme_figures()

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

    # What carries between each pair: `goat-xf matrix`, one tab-separated line
    # per ordered pair after a header (spec 0.23): from, to, grade, carried,
    # dropped, each list joined by spaces.
    code, out, err = xf("matrix")
    if code != 0:
        die("goat-xf matrix failed: " + err)
    capability = {}
    for line in out.split("\n")[1:]:
        if not line:
            continue
        src, dst, grade, carried, dropped = line.split("\t")
        if src == dst:
            continue
        carried = carried.split(" ") if carried else []
        uniq = list(dict.fromkeys(dropped.split(" "))) if dropped else []
        entry = {"grade": grade, "carried": carried, "dropped_count": len(uniq)}
        if len(uniq) <= MAX_DROPPED:
            entry["dropped"] = uniq
        capability["%s>%s" % (src, dst)] = entry
    want = len(names) * (len(names) - 1)
    if len(capability) != want:
        die("read %d pairs from `goat-xf matrix`, expected %d" % (len(capability), want))

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
            # Counts move with every pack; the counts pull request updates them.
            if key in COUNTS:
                print("bundle.py: note: index.html states %s = %s, the tree has %s (the counts pull request "
                      "updates it: --counts-only --write)" % (key, text.strip(), format(stats[key], ",")))
                continue
            print("bundle.py: check: index.html states %s = %s, the tree has %s" % (key, text.strip(), format(stats[key], ",")))
            bad += 1
    plain = html.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    for s, t in STATIC:
        expect = pairs["%s>%s" % (s, t)]["expect"]
        if expect not in plain:
            print("bundle.py: check: index.html does not show the goat-xf output of %s to %s: %s" % (s, t, expect))
            bad += 1
    bad += check_hero(html, pairs)
    bad += check_figures(html)
    if bad:
        print("bundle.py: FAIL, index.html differs from the tree in %d place(s)" % bad)
        return 1
    print("bundle.py: index.html agrees with the tree (%d numbers, %d conversions)" % (len(found), len(STATIC)))
    return 0


def check_hero(html, pairs):
    """The drawing in the first screen must be the tree's: the bytes of the
    vector, the pack lines it quotes, the integer each line reads, the model
    value the vector states, the faint pack text behind it, and the output."""
    bad = 0

    def fail(msg):
        nonlocal bad
        print("bundle.py: check: hero: " + msg)
        bad += 1

    def unescape(t):
        return re.sub(r"<[^>]+>", "", t).replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")

    with open(os.path.join(REPO, "packs/remote-id/vectors/02-location-roundtrip.json"), encoding="utf-8") as f:
        vec = json.load(f)
    data = bytes.fromhex(vec["input"])
    lines = {}
    for name in ("remote-id", "cot-xml"):
        with open(os.path.join(REPO, "packs/%s/pack.def" % name), encoding="utf-8") as f:
            lines[name] = [l.rstrip("\n") for l in f]

    shown = re.findall(r'<span class="hb" data-i="(\d+)">([0-9a-f]{2})</span>', html)
    if [int(i) for i, _ in shown] != list(range(len(data))) or bytes.fromhex("".join(h for _, h in shown)) != data:
        fail("the bytes drawn are not the input of 02-location-roundtrip.json")

    steps = re.findall(r"<li (data-step=[^>]*)>", html)
    if len(steps) < 2:
        fail("no steps found")
    for attrs in steps:
        a = dict(re.findall(r'data-([a-z]+)="([^"]*)"', attrs))
        if a["line"] not in lines[a["pack"]]:
            fail("the line `%s` is not in packs/%s/pack.def" % (a["line"], a["pack"]))
        if "loc" not in a:
            continue
        _, first, length = (int(x) for x in a["loc"].split(":"))
        if a["loc"] not in a["line"]:
            fail("step %s: locator %s is not the one of its line" % (a["step"], a["loc"]))
        lo, hi = first // 8, (first + length - 1) // 8
        raw = (int.from_bytes(data[lo:hi + 1], "little") >> (first % 8)) & ((1 << length) - 1)
        if "sscale" in a["line"] and raw >= 1 << (length - 1):
            raw -= 1 << length
        if str(raw) != a["raw"]:
            fail("step %s: bytes %d-%d hold %d, the page states %s" % (a["step"], lo, hi, raw, a["raw"]))
        if vec["model"].get(a["key"]) != a["value"]:
            fail("step %s: the vector's model has %s = %s, the page states %s" % (
                a["step"], a["key"], vec["model"].get(a["key"]), a["value"]))

    m = re.search(r'<pre class="hero-code"[^>]*>(.*?)</pre>', html, re.S)
    if not m:
        fail("no hero-code block")
    else:
        every = set(lines["remote-id"]) | set(lines["cot-xml"])
        for line in unescape(m.group(1)).split("\n"):
            if line.strip() and line not in every:
                fail("the background line `%s` is not in the remote-id or cot-xml pack" % line)

    m = re.search(r'<pre class="sig-xml"[^>]*>(.*?)</pre>', html, re.S)
    out = re.sub(r"\n\s+", " ", unescape(m.group(1))) if m else ""
    if out != pairs["remote-id>cot-xml"]["expect"]:
        fail("the output drawn is not what goat-xf prints: %s" % out)
    return bad


if __name__ == "__main__":
    sys.exit(main())
