#!/usr/bin/env python3
"""asterix2pack: turn ASTERIX category definitions into goat-transformers packs.

Reads   sources/asterix-specs/manifest.json and cat<NNN>-<edition>.json: the JSON form of the
        category definitions of zoranbosnjak/asterix-specs (BSD-3-Clause) at a pinned commit
Writes  sources/PROVENANCE.md                       (only with --commit)
        model/cat<NNN>.def                          raw keys and lists of the category
        packs/asterix-cat<NNN>/pack.def             wire bits, layout sequential, bit_order msb
        packs/asterix-cat<NNN>/pack.md              what is mapped, what is not, and why
        packs/asterix-cat<NNN>/PROVENANCE.md
        packs/asterix-cat<NNN>/vectors/*.json
        packs/canonical-track-v2/vectors/gen-to-asterix-cat<NNN>.json   (position-bearing categories)
        tools/gen/names/asterix-cat<NNN>.json       item path -> key name, read and rewritten

Category 062 is written as the pack `asterix-cat062-full` with the module `cat062full`, because
the library holds a hand-written pack `asterix-cat062` and module `cat062`.

Python 3 standard library only. Re-runnable: every output is rewritten from the sources, and a
generated vectors directory is emptied of *.json first.

Usage:
  asterix2pack.py --out <dir> [--commit <sha> [--fetch]] [--cats 048,062,...|all]
                  [--lib <goat-transformers checkout>]

--commit <sha>  commit of the gh-pages branch of zoranbosnjak/asterix-specs (the published JSON);
                recorded in sources/PROVENANCE.md. With --fetch, or when a source file is
                missing, the files are downloaded from raw.githubusercontent.com at that commit
                with curl. Without --commit the commit is read back from sources/PROVENANCE.md.
--lib <dir>     checks the built-in tables of `core`, `track`, `geojson` and
                `canonical-track-v2` against the files of that checkout.

One record per data block; the first UAP of a category that has several. A category is
written when every check passes; one that fails is reported with the reason and leaves no
files. After writing, the generator re-reads its own output from disk with an independent
loader and replays every vector through a sequential codec written from spec/engine-spec.md
(Version 0.8). Any failed check exits non-zero.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import OrderedDict
from decimal import Decimal
from fractions import Fraction

REPO = "zoranbosnjak/asterix-specs"
PACK_VERSION = "0.1.0"
MODULE_VERSION = "0.1.0"
PRIORITY = [48, 62, 21, 34, 10]
# the library holds a hand-written pack and module of these names
RENAME = {62: ("asterix-cat062-full", "cat062full")}

# model/core.def and model/track.def of goat-transformers (checked against --lib when given)
CORE_KEYS = OrderedDict([
    ("uid", "string"), ("type", "string"), ("time_ms", "int"), ("lat", "float"),
    ("lon", "float"), ("hae", "float"), ("ce", "float"), ("le", "float"),
    ("callsign", "string"), ("course", "float"), ("speed_ms", "float"), ("how", "string"),
    ("stale_ms", "int"),
])
TRACK_KEYS = OrderedDict([
    ("source_id", "string"), ("generation", "string"), ("vel_east_ms", "float"),
    ("vel_north_ms", "float"), ("vel_up_ms", "float"), ("class", "string"),
    ("confidence", "float"), ("sigma_east_m", "float"), ("sigma_north_m", "float"),
    ("sigma_up_m", "float"), ("confirmed", "int"), ("coasting", "int"), ("simulated", "int"),
    ("header_simulated", "int"), ("test_data", "int"), ("final_update", "int"),
    ("id_scheme", "string"), ("id_value", "string"),
])
TRACK_DERIVES = [
    ("course", "bearing", ["track.vel_east_ms", "track.vel_north_ms"]),
    ("speed_ms", "hypot", ["track.vel_east_ms", "track.vel_north_ms"]),
    ("ce", "hypot", ["track.sigma_east_m", "track.sigma_north_m"]),
    ("le", "copy", ["track.sigma_up_m"]),
    ("track.vel_east_ms", "east_of", ["speed_ms", "course"]),
    ("track.vel_north_ms", "north_of", ["speed_ms", "course"]),
]
# packs/geojson/pack.def: (key, locator) in line order
GEOJSON_FIELDS = [
    ("uid", "id"), ("type", "properties.type"), ("time_ms", "properties.time_ms"),
    ("how", "properties.how"), ("lat", "geometry.lat"), ("lon", "geometry.lon"),
    ("hae", "geometry.alt"), ("ce", "properties.ce"), ("le", "properties.le"),
    ("callsign", "properties.callsign"), ("course", "properties.course"),
    ("speed_ms", "properties.speed_ms"),
]
# packs/canonical-track-v2/pack.def: the members the generated vector uses
TRACK_JSON_FIELDS = [
    ("uid", "trackId", "string"), ("track.source_id", "sourceId", "string"),
    ("track.generation", "trackGeneration", "string"), ("time_ms", "observedAt", "iso8601_ms"),
    ("lat", "position.latitudeDeg", "float"), ("lon", "position.longitudeDeg", "float"),
    ("hae", "position.altitudeM", "float"), ("track.vel_east_ms", "velocity.eastMps", "float"),
    ("track.vel_north_ms", "velocity.northMps", "float"),
]

# Published sample blocks with the values their publisher states: the README of the Python
# library of zoranbosnjak/asterix-libs (BSD-3-Clause). `stated` is item path -> value; the
# generator refuses to write a vector whose decode does not give these values.
SAMPLES_REPO = "zoranbosnjak/asterix-libs"
SAMPLES_COMMIT = "24be3c4593a24001d10e04338b46f6d85df6660f"
SAMPLES_PATH = "libs/python/README.md"
SAMPLES = [
    dict(cat=34, name="sample-north-marker", hex="220007c0010201",
         stated={"000": 1, "010/SAC": 1, "010/SIC": 2},
         note="the North marker message of the README's first example: item 000 = 1, SAC 1, SIC 2"),
    dict(cat=34, name="sample-sector-crossing-0-degrees", hex="220008d001020200",
         stated={"000": 2, "010/SAC": 1, "010/SIC": 2, "020": 0.0},
         note="the sector crossing message at azimuth 0 degrees of the README's first example"),
    dict(cat=34, name="sample-sector-crossing-45-degrees", hex="220008d001020220",
         stated={"000": 2, "010/SAC": 1, "010/SIC": 2, "020": 45.0},
         note="the sector crossing message at azimuth 45 degrees of the README's first example"),
    dict(cat=48, name="sample-plot", hex="30000c9801020a0020000fff",
         stated={"010/SAC": 1, "010/SIC": 2, "040/RHO": 10.0, "040/THETA": 45.0,
                 "070/V": 0, "070/G": 0, "070/L": 0, "070/MODE3A": 0o7777},
         note="the plot of the README's first example: rho 10 NM, theta 45 degrees, Mode 3/A code 7777 (octal)"),
    dict(cat=48, name="sample-first-record-of-a-block-of-two",
         hex="3000119001020000000090010200000000", expect="30000a90010200000000",
         stated={"010/SAC": 1, "010/SIC": 2, "040/RHO": 0.0, "040/THETA": 0.0},
         note="the first data block of the README's SAC/SIC rewriting example (written there with edition 1.31): "
              "two records, each SAC 1, SIC 2 and item 040 zero. The pack reads the first record and writes it alone"),
    dict(cat=62, name="sample-record-with-reserved-expansion",
         hex="3e001b8101010104010211c8010000000000020000010000028000", expect="3e0006800102",
         stated={"010/SAC": 1, "010/SIC": 2},
         note="the block of the README's reserved expansion example (written there with edition 1.20): SAC 1, SIC 2 "
              "and an RE item of 17 octets. The RE item is read over and not written"),
    dict(cat=62, name="sample-first-record-of-a-block-of-four",
         hex="3e0017011010000101101000010110104ccd0110108320", expect="3e00080110100001",
         stated={"380/IAS/IM": 0, "380/IAS/IAS": 1},
         note="the block of the README's dependent content example (written there with edition 1.20): four records, "
              "the first with I062/380 subfield IAS holding IM 0 and the raw value 1. The pack reads the first "
              "record and writes it alone"),
]

FT = Fraction(381, 1250)            # one foot in metres, exactly
SPEED_TO_MS = {"m/s": Fraction(1), "kt": Fraction(1852, 3600), "NM/s": Fraction(1852)}
UNIT_TOKEN = {"": "-", "°": "deg", "m/s²": "m/s2", "°/s": "deg/s", "°C": "degC", "dBµV": "dBuV"}
ASCII_FOLD = {"’": "'", "‘": "'", "“": "'", "”": "'", '"': "'", "°": " deg", "µ": "u", "²": "2",
              "–": "-", "—": "-", "≤": "<=", "≥": ">=", "×": "x", "±": "+/-", "…": "...",
              " ": " ", "é": "e", "è": "e", "ü": "u", "ö": "o", "ä": "a"}


class GenError(Exception):
    pass


class Unmappable(Exception):
    """A UAP item the pack language cannot describe; the item is left without an `if` block."""


class WireError(Exception):
    def __init__(self, kind, msg=""):
        Exception.__init__(self, "%s: %s" % (kind, msg))
        self.kind = kind


def die(msg):
    raise GenError(msg)


# ---------------------------------------------------------------- small helpers

def plain(x):
    """Decimal text of a number in plain notation (no exponent), shortest round trip."""
    if isinstance(x, int):
        return str(x)
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 1e17:
        return str(int(x))
    t = format(Decimal(repr(x)), "f")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


def round_half_away(q):
    f = math.floor(abs(q) + 0.5)
    return int(-f if q < 0 else f)


def frac_text(fr):
    return str(fr.numerator) if fr.denominator == 1 else "%d/%d" % (fr.numerator, fr.denominator)


def fold(text):
    """One line of ASCII: what a quoted value of a .def file may hold."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r":math:`([^`]*)`", r"\1", t)
    out = []
    for ch in t:
        if ch in ASCII_FOLD:
            out.append(ASCII_FOLD[ch])
        elif 0x20 <= ord(ch) < 0x7F:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


def edition_key(text):
    return tuple(int(x) for x in text.split("."))


# ---------------------------------------------------------------- sources

def src_dir_of(out):
    return os.path.join(out, "sources", "asterix-specs")


def curl(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    subprocess.run(["curl", "-fsSL", "-o", dest, url], check=True)


def fetch_sources(out, sha, force):
    """-> (list of (local name, repository path, commit), master commit)"""
    sd = src_dir_of(out)
    raw = "https://raw.githubusercontent.com/%s/%s/%s"
    got = []
    for name in ("manifest.json", "gitrev.txt"):
        dest = os.path.join(sd, name)
        if force or not os.path.exists(dest):
            curl(raw % (REPO, sha, name), dest)
        got.append((name, name, sha))
    master = open(os.path.join(sd, "gitrev.txt"), encoding="utf-8").read().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", master):
        die("gitrev.txt does not hold a commit: %r" % master)
    dest = os.path.join(sd, "LICENSE")
    if force or not os.path.exists(dest):
        curl(raw % (REPO, master, "LICENSE"), dest)
    got.append(("LICENSE", "LICENSE", master))
    manifest = json.load(open(os.path.join(sd, "manifest.json"), encoding="utf-8"))
    for e in manifest:
        ed = max(e["cats"], key=edition_key)
        name = "cat%s-%s.json" % (e["category"], ed)
        rel = "specs/cat%s/cats/cat%s/definition.json" % (e["category"], ed)
        dest = os.path.join(sd, name)
        if force or not os.path.exists(dest):
            curl(raw % (REPO, sha, rel), dest)
        got.append((name, rel, sha))
    return got, master


def write_provenance(out, sha, got, master):
    sd = src_dir_of(out)
    lic = open(os.path.join(sd, "LICENSE"), encoding="utf-8").read()
    L = ["# Provenance of the inputs in `sources/asterix-specs/`", "",
         "| Fact | Value |", "|---|---|",
         "| repository | https://github.com/%s |" % REPO,
         "| what it is | \"EUROCONTROL asterix specifications in structured format\" (the repository's description): "
         "each category edition as a `.ast` source file, and built from it a JSON file of the same content |",
         "| commit of the published JSON (branch `gh-pages`): | `%s` |" % sha,
         "| commit of the sources the JSON was built from (branch `master`, stated by `gitrev.txt` at the commit above) | `%s` |" % master,
         "| licence | BSD 3-Clause, copyright (c) 2019 KZPS: the file `LICENSE` at the root of the `master` commit, verbatim below |",
         "| edition taken | for each category the newest edition `manifest.json` lists |",
         "", "## Files", "",
         "Every file is downloaded from `https://raw.githubusercontent.com/%s/<commit>/<repository path>`." % REPO, "",
         "| File | Repository path | Commit | Bytes | SHA-256 |", "|---|---|---|---|---|"]
    for name, rel, commit in got:
        p = os.path.join(sd, name)
        L.append("| `%s` | `%s` | `%s` | %d | `%s` |" % (name, rel, commit[:12], os.path.getsize(p), sha256_file(p)))
    L += ["", "## The licence file, verbatim", "", "```", lic.rstrip("\n"), "```", "",
          "## Sample blocks", "",
          "The vectors named `sample-*` take their input from the README of the Python library of",
          "https://github.com/%s (BSD-3-Clause), file `%s` at commit" % (SAMPLES_REPO, SAMPLES_PATH),
          "`%s`: blocks that README prints together with the values they hold." % SAMPLES_COMMIT, "",
          "## Other definition sets looked at", "",
          "| Repository | Licence GitHub reports | Used |", "|---|---|---|",
          "| https://github.com/CroatiaControlLtd/asterix (XML category definitions) | GPL-2.0 | no |",
          "| https://github.com/hpuhr/jASTERIX (JSON category definitions) | GPL-3.0 | no |", ""]
    write(os.path.join(out, "sources", "PROVENANCE.md"), "\n".join(L))


def read_commit(out):
    p = os.path.join(out, "sources", "PROVENANCE.md")
    if not os.path.exists(p):
        die("no --commit given and %s does not exist" % p)
    text = open(p, encoding="utf-8").read()
    m = re.search(r"commit of the published JSON[^|]*\| `([0-9a-f]{40})`", text)
    m2 = re.search(r"commit of the sources the JSON was built from[^|]*\| `([0-9a-f]{40})`", text)
    if not m or not m2:
        die("sources/PROVENANCE.md does not state the commits")
    return m.group(1), m2.group(1)


# ---------------------------------------------------------------- reading a definition

def num(n):
    t, c = n["tag"], n["contents"]
    if t == "NumInt":
        return Fraction(c)
    if t == "NumDiv":
        return num(c["numerator"]) / num(c["denominator"])
    if t == "NumPow":
        return Fraction(c["base"]) ** c["exponent"]
    die("unknown number tag %s" % t)


def fixed_bits(v):
    """Bit size of an Element or Group variation; None for anything else."""
    t, c = v["tag"], v["contents"]
    if t == "Element":
        return c["bitSize"]
    if t == "Group":
        total = 0
        for it in c:
            if it["tag"] == "Spare":
                total += it["contents"]
            else:
                b = rule_bits(it["contents"]["rule"])
                if b is None:
                    return None
                total += b
        return total
    return None


def rule_bits(rule):
    if rule["tag"] == "ContextFree":
        return fixed_bits(rule["contents"])
    d = rule["contents"]
    sizes = {fixed_bits(d["default"])} | {fixed_bits(c[1]) for c in d["cases"]}
    return sizes.pop() if len(sizes) == 1 else None


class Cat:
    """One category: the definition, and what the generator made of it."""

    def __init__(self, d, src_name, rel):
        c = d["contents"]
        if d["tag"] != "AsterixBasic":
            die("%s: not a category definition (%s)" % (src_name, d["tag"]))
        self.num = c["category"]
        self.nnn = "%03d" % self.num
        self.edition = "%d.%d" % (c["edition"]["major"], c["edition"]["minor"])
        self.date = "%04d-%02d-%02d" % (c["date"]["year"], c["date"]["month"], c["date"]["day"])
        self.title = fold(c["title"])
        self.catalogue = OrderedDict((it["name"], it) for it in c["catalogue"])
        self.src_name, self.rel = src_name, rel
        self.format, self.module = RENAME.get(self.num, ("asterix-cat" + self.nnn, "cat" + self.nnn))
        u = c["uap"]
        self.uap_note = None
        if u["tag"] == "Uap":
            self.uap = u["contents"]
        elif u["tag"] == "Uaps":
            cases = u["contents"]["cases"]
            self.uap = cases[0][1]
            sel = u["contents"]["selector"]
            self.uap_note = ("The category has %d UAPs (%s)%s. The pack holds the first, `%s`; a record of "
                             "another UAP is read wrongly or fails."
                             % (len(cases), ", ".join("`%s`" % n for n, _ in cases),
                                ", selected by the value of item %s" % "/".join(sel["item"]) if sel else "",
                                cases[0][0]))
        else:
            die("unknown uap tag %s" % u["tag"])
        self.entries = []       # one per FRN: dict(frn, name, title, kind, nodes, reason)
        self.keys = OrderedDict()   # name -> (type, unit, meaning)
        self.lists = OrderedDict()  # name -> meaning
        self.derives = []           # (target, function, [arguments])
        self.bindings = []          # dict(key, ident, how, evidence)
        self.names = {}
        self.pinned = {}
        self.uses = []


# ---------------------------------------------------------------- definition -> lines (IR)

class Builder:
    def __init__(self, cat):
        self.cat = cat
        self.used = {}

    def name_of(self, ident, parts):
        cat = self.cat
        if ident in cat.pinned:
            name = cat.pinned[ident]
        else:
            head = parts[0].lower()
            name = "_".join((["i" + head] if head[:1].isdigit() else [head]) + [p.lower() for p in parts[1:]])
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            die("cat %s: %s gives the key name %r" % (cat.nnn, ident, name))
        if self.used.get(name, ident) != ident:
            die("cat %s: key name %s for both %s and %s" % (cat.nnn, name, self.used[name], ident))
        self.used[name] = ident
        cat.names[ident] = name
        return name

    def leaf(self, path, titles, bits, rule, bare=False):
        """An Element -> a field node."""
        cat = self.cat
        ident = "/".join(path) + ("/#" if bare else "")
        note, unit, vt = "", "-", "int"
        frac, signed = None, False
        if rule["tag"] == "Dependent":
            tr = "uint"
            note = "raw value; its content depends on the value of " + " and ".join(
                "/".join(p) for p in rule["contents"]["path"])
        else:
            ct = rule["contents"]
            t, c = ct["tag"], ct["contents"]
            if t == "ContentRaw":
                tr = "uint"
            elif t == "ContentTable":
                tr = "uint"
                note = ", ".join("%d = %s" % (v, fold(s)) for v, s in c)
            elif t == "ContentString":
                st = c["tag"]
                if st == "StringAscii":
                    if bits % 8 or bits > 2040:
                        raise Unmappable("an ASCII string of %d bits" % bits)
                    tr, vt = "ascii", "string"
                    note = "%d ASCII characters" % (bits // 8)
                elif st == "StringICAO":
                    tr = "uint"
                    note = "raw value: %d characters of 6 bits each in the ICAO character set (ICAO Annex 10)" % (bits // 6)
                elif st == "StringOctal":
                    tr = "uint"
                    note = "raw value: %d octal digits of 3 bits each" % (bits // 3)
                else:
                    die("unknown string type %s" % st)
            elif t == "ContentInteger":
                signed = c["signedness"]["tag"] == "Signed"
                tr = "twos" if signed else "uint"
            elif t == "ContentQuantity":
                signed = c["signedness"]["tag"] == "Signed"
                frac = num(c["lsb"])
                if frac <= 0:
                    die("%s: LSB %s" % (ident, frac))
                tr = ("sscale:" if signed else "uscale:") + frac_text(frac)
                vt = "float"
                unit = UNIT_TOKEN.get(c["unit"], c["unit"])
                if not re.fullmatch(r"[\x21-\x7e]+", unit):
                    die("%s: unit %r" % (ident, c["unit"]))
                note = "LSB %s %s" % (frac_text(frac), unit if unit != "-" else "")
            elif t == "ContentBds":
                tr = "uint"
                note = "raw value: a Mode S BDS register" + (" with its address" if c["tag"] == "BdsWithAddress" else "")
            else:
                die("unknown content tag %s" % t)
        if tr != "ascii" and not 1 <= bits <= 64:
            raise Unmappable("an element of %d bits (a field holds at most 64)" % bits)
        name = self.name_of(ident, path + (["val"] if bare else []))
        label = "I%s/%s" % (cat.nnn, "/".join(path))
        title = fold("; ".join(t for t in titles[1:] if t)) if len(titles) > 1 else fold(titles[0])
        meaning = label + (": " + title if title else "")
        if len(titles) > 1 and titles[0]:
            meaning += " (" + fold(titles[0]) + ")"
        if note:
            meaning += ". " + note.strip()
        if len(meaning) > 400:
            meaning = meaning[:397] + "..."
        return dict(t="field", ident=ident, sub=path[1:], key=cat.module + "." + name, also=[], bits=bits,
                    tr=tr, kind=tr.split(":")[0], frac=frac, signed=signed, vt=vt, unit=unit,
                    meaning=meaning, raw=cat.module + "." + name, declare=True,
                    src_unit=(rule["contents"]["contents"]["unit"]
                              if rule["tag"] == "ContextFree" and rule["contents"]["tag"] == "ContentQuantity" else None),
                    title=titles[-1] or "")

    def item(self, it, path, titles, bare_ok=False):
        return self.rule(it["rule"], path + [it["name"]], titles + [it["title"]])

    def rule(self, rule, path, titles, bare=False):
        if rule["tag"] == "ContextFree":
            return self.variation(rule["contents"], path, titles, bare)
        d = rule["contents"]
        if rule_bits(rule) is None:
            raise Unmappable("a structure that depends on the value of %s, with cases of different sizes"
                             % " and ".join("/".join(p) for p in d["path"]))
        # same size in every case: the default structure carries the bits
        nodes = self.variation(d["default"], path, titles, bare)
        for n in nodes:
            if n["t"] == "field":
                n["meaning"] += ". Raw value: the structure depends on the value of " + " and ".join(
                    "/".join(p) for p in d["path"])
        return nodes

    def variation(self, v, path, titles, bare=False):
        cat = self.cat
        t, c = v["tag"], v["contents"]
        if t == "Element":
            return [self.leaf(path, titles, c["bitSize"], c["rule"], bare)]
        if t == "Group":
            nodes = []
            for it in c:
                if it["tag"] == "Spare":
                    nodes.append(dict(t="pad", bits=it["contents"]))
                else:
                    nodes += self.item(it["contents"], path, titles)
            return nodes
        if t == "Extended":
            parts, cur = [], []
            for it in c:
                if it is None:
                    parts.append(cur)
                    cur = []
                elif it["tag"] == "Spare":
                    cur.append(dict(t="pad", bits=it["contents"]))
                else:
                    sub = self.item(it["contents"], path, titles)
                    if any(n["t"] not in ("field", "pad") for n in sub):
                        raise Unmappable("an extended item that holds a part that is not fixed")
                    cur += sub
            trailing = c[-1] is None
            if not trailing:
                parts.append(cur)
            return [dict(t="chain", parts=parts, trailing=trailing)]
        if t == "Repetitive":
            ident = "/".join(path) + "[]"
            lname = self.name_of(ident, path)
            body = self.variation(c["variation"], path, titles, bare=c["variation"]["tag"] == "Element")
            if any(n["t"] not in ("field", "pad") for n in body):
                raise Unmappable("a repetitive item whose repeated part is not fixed")
            ty = c["type"]
            label = "I%s/%s" % (cat.nnn, "/".join(path))
            cat.lists[lname] = "%s: %s, one item per repetition" % (label, fold(titles[-1] or titles[0]))
            if ty["tag"] == "RepetitiveRegular":
                return [dict(t="group", list=cat.module + "." + lname, mode="count",
                             cbits=8 * ty["contents"]["byteSize"], body=body, ident=ident)]
            if ty["tag"] == "RepetitiveFx":
                return [dict(t="group", list=cat.module + "." + lname, mode="fx", body=body, ident=ident)]
            die("unknown repetitive type %s" % ty["tag"])
        if t == "Compound":
            subs = []
            for i, it in enumerate(c):
                if it is not None:
                    subs.append((i + 1, it["name"], fold(it["title"]),
                                 self.rule(it["rule"], path + [it["name"]], titles + [it["title"]])))
            return [dict(t="compound", name="p" + "".join(p.lower() for p in path), subs=subs)]
        if t == "Explicit":
            return [dict(t="explicit")]
        die("unknown variation tag %s" % t)


VARIATION_KIND = {"Element": "fixed", "Group": "fixed", "Extended": "extended", "Repetitive": "repetitive",
                  "Compound": "compound", "Explicit": "explicit"}


def walk_fields(nodes, in_list=None):
    """Every field node, with the list it sits in (or None)."""
    for n in nodes:
        t = n["t"]
        if t == "field":
            yield n, in_list
        elif t == "chain":
            for p in n["parts"]:
                yield from walk_fields(p, in_list)
        elif t == "group":
            yield from walk_fields(n["body"], n["list"])
        elif t == "compound":
            for _, _, _, sub in n["subs"]:
                yield from walk_fields(sub, in_list)


def build(cat):
    b = Builder(cat)
    for i, u in enumerate(cat.uap):
        frn = i + 1
        e = dict(frn=frn, name=None, title="", kind=None, nodes=None, reason=None)
        if u["tag"] == "UapItemSpare":
            e["kind"], e["reason"] = "spare", "spare FRN"
        elif u["tag"] == "UapItemRFS":
            e["kind"], e["reason"] = "rfs", "random field sequencing: the items that follow name themselves by FRN, in any order"
        else:
            it = cat.catalogue.get(u["contents"])
            if it is None:
                die("cat %s: UAP names item %s, which the catalogue does not hold" % (cat.nnn, u["contents"]))
            e["name"], e["title"] = it["name"], fold(it["title"])
            rule = it["rule"]
            e["kind"] = VARIATION_KIND[rule["contents"]["tag"]] if rule["tag"] == "ContextFree" else "fixed"
            saved = (dict(b.used), dict(cat.names), OrderedDict(cat.lists))
            try:
                e["nodes"] = b.rule(rule, [it["name"]], [it["title"]])
            except Unmappable as x:
                b.used, cat.names, cat.lists = saved
                e["reason"] = str(x)
        cat.entries.append(e)
    bind(cat)
    for e in cat.entries:
        if e["nodes"]:
            for n, _ in walk_fields(e["nodes"]):
                if n["declare"]:
                    cat.keys[n["raw"].split(".", 1)[1]] = (n["vt"], n["unit"], n["meaning"])
    dup = set(cat.keys) & set(cat.lists)
    if dup:
        die("cat %s: a key and a list share the name %s" % (cat.nnn, sorted(dup)))


# ---------------------------------------------------------------- shared-model bindings

def doc_text(it):
    d = it["documentation"]
    return fold(d["definition"]), fold(d["remark"])


def bind(cat):
    """Bind shared-model keys where the definition text and the unit leave no doubt. Only items
    that stand directly in the UAP and are fixed (an Element or a Group) are looked at."""
    pos, tod = [], []
    for e in cat.entries:
        if not e["nodes"] or e["kind"] != "fixed":
            continue
        it = cat.catalogue[e["name"]]
        definition, remark = doc_text(it)
        title = fold(it["title"])
        label = "I%s/%s" % (cat.nnn, e["name"])
        fields = [n for n in e["nodes"] if n["t"] == "field"]
        by_sub = {"/".join(n["sub"]): n for n in fields}
        text = title + " " + definition

        # WGS-84 position of the reported target
        la, lo = by_sub.get("LAT"), by_sub.get("LON")
        if (la and lo and len(fields) == 2 and la["src_unit"] == "°" and lo["src_unit"] == "°"
                and la["signed"] and lo["signed"] and la["frac"] == lo["frac"]
                and re.match(r"(calculated |high-resolution )?position in wgs-?84 co-?ordinates", title, re.I)
                and not re.search(r"message type", remark, re.I)):      # what the item holds depends on the message
            pos.append((la["frac"], e["frn"], la, lo,
                        '%s "%s", definition: "%s"; subitems LAT and LON in degrees, two\'s complement%s'
                        % (label, title, definition,
                           '; note: "%s"' % remark if re.search(r"positive", remark, re.I) else "")))

        # height above the WGS-84 ellipsoid
        if (len(fields) == 1 and len(e["nodes"]) == 1 and fields[0]["src_unit"] in ("ft", "m") and fields[0]["signed"]
                and re.search(r"geometric (height|altitude)", title, re.I)
                and re.search(r"ellipsoid", definition, re.I) and re.search(r"wgs-? ?84", definition, re.I)):
            n = fields[0]
            mult = FT if n["src_unit"] == "ft" else Fraction(1)
            convert(cat, n, "hae", mult,
                    '%s "%s", definition: "%s"; LSB %s %s%s' % (label, title, definition, frac_text(n["frac"]), n["src_unit"],
                                                               '; note: "%s"' % remark if remark else ""))

        # ground speed, and track angle from true north
        for n in fields:
            if (n["src_unit"] in SPEED_TO_MS and not n["signed"]
                    and re.search(r"ground ?speed", n["title"], re.I)):
                convert(cat, n, "speed_ms", SPEED_TO_MS[n["src_unit"]],
                        '%s "%s", subitem %s "%s"; LSB %s %s' % (label, title, "/".join(n["sub"]), fold(n["title"]),
                                                                 frac_text(n["frac"]), n["src_unit"]))
            if (n["src_unit"] == "°" and not n["signed"] and re.search(r"track angle", n["title"], re.I)
                    and re.search(r"true north", n["title"], re.I)):
                convert(cat, n, "course", Fraction(1),
                        '%s "%s", subitem %s "%s"; LSB %s degrees' % (label, title, "/".join(n["sub"]), fold(n["title"]),
                                                                      frac_text(n["frac"])))

        # Cartesian velocity with the axes stated
        vx, vy = by_sub.get("VX"), by_sub.get("VY")
        if (vx and vy and len(fields) == 2 and vx["src_unit"] == "m/s" and vy["src_unit"] == "m/s"
                and vx["signed"] and vy["signed"] and re.search(r"cartesian", text, re.I)
                and re.search(r"y-axis points to the geographical north", remark, re.I)):
            ev = ('%s "%s", definition: "%s"; note: "%s"; subitems VX and VY in m/s, two\'s complement'
                  % (label, title, definition, remark))
            convert(cat, vx, "track.vel_east_ms", Fraction(1), ev + ". The x-axis of that system points east")
            convert(cat, vy, "track.vel_north_ms", Fraction(1), ev)
            if "track" not in cat.uses:
                cat.uses.append("track")

        # time of day
        if (len(fields) == 1 and len(e["nodes"]) == 1 and fields[0]["src_unit"] == "s" and fields[0]["bits"] == 24
                and fields[0]["frac"] == Fraction(1, 128) and not fields[0]["signed"]
                and re.search(r"absolute time stamping", definition, re.I) and re.search(r"UTC|universal", definition)):
            tod.append((fields[0], '%s "%s", definition: "%s"%s' % (label, title, definition,
                                                                   '; note: "%s"' % remark[:200] if remark else "")))

    if pos:
        # several items qualify: the finest resolution is bound, the others feed `lat` and `lon`
        # through derive lines of the module
        pos.sort(key=lambda p: (p[0], p[1]))
        _, _, la, lo, ev = pos[0]
        convert(cat, la, "lat", Fraction(1), ev)
        convert(cat, lo, "lon", Fraction(1), ev)
        for _, _, la2, lo2, ev2 in sorted(pos[1:], key=lambda p: p[1]):
            cat.derives.append(("lat", "copy", [la2["raw"]]))
            cat.derives.append(("lon", "copy", [lo2["raw"]]))
            cat.bindings.append(dict(key="lat, lon", ident=la2["ident"].rsplit("/", 1)[0], how="derive",
                                     evidence=ev2, raws=[la2["raw"], lo2["raw"]]))
    if len(tod) == 1:
        n, ev = tod[0]
        cat.derives.append((n["raw"], "day_seconds", ["time_ms"]))
        cat.bindings.append(dict(key=n["raw"], ident=n["ident"], how="day_seconds", evidence=ev))


def convert(cat, n, shared, mult, evidence):
    """Bind `shared` to the field. Same unit: the shared key is the field's key and the raw key
    follows on an `also` line. Another unit: the factor is folded into the scale and the field
    has the shared key only."""
    if n["key"] != n["raw"]:
        return
    if any(b["key"] == shared for b in cat.bindings):
        return
    if mult == 1:
        n["key"], n["also"] = shared, [n["raw"]]
        how = "same unit"
    else:
        f = n["frac"] * mult
        n["key"], n["frac"], n["declare"] = shared, f, False
        n["tr"] = ("sscale:" if n["signed"] else "uscale:") + frac_text(f)
        how = "factor %s folded into the scale" % frac_text(mult)
    n["meaning_shared"] = evidence
    cat.bindings.append(dict(key=shared, ident=n["ident"], how=how, evidence=evidence, tr=n["tr"],
                             raw=n["raw"] if mult == 1 else None))


# ---------------------------------------------------------------- emitting

def q(text):
    return '"' + text.replace('"', "'") + '"'


def source_line(cat, sha):
    return ("ASTERIX Category %s, %s, edition %s (%s), as transcribed in github.com/%s (BSD-3-Clause), "
            "commit %s, %s. The category is specified by EUROCONTROL"
            % (cat.nnn, cat.title, cat.edition, cat.date, REPO, sha, cat.rel))


def emit_module(cat, sha):
    L = ["# The %s module: the values of ASTERIX Category %s (%s), edition %s," % (cat.module, cat.nnn, cat.title, cat.edition),
         "# as the category holds them. Used by the pack `%s`. Generated by" % cat.format,
         "# tools/gen/asterix2pack.py; do not edit by hand. A key is named after its item",
         "# and subitems; a repetitive item is a list and its keys are the keys of one",
         "# repetition.",
         "module        " + cat.module, "version       " + MODULE_VERSION, "distribution  public",
         "source        " + q(source_line(cat, sha))]
    w = max([len(k) for k in cat.keys] + [len(k) for k in cat.lists] + [4])
    ents = [(name, ("key", v)) for name, v in cat.keys.items()] + [(name, ("list", m)) for name, m in cat.lists.items()]
    order = {name: i for i, name in enumerate(order_of_names(cat))}
    for name, (what, v) in sorted(ents, key=lambda x: order[x[0]]):
        if what == "key":
            L.append("key   %-*s  %-6s  %-6s  %s" % (w, name, v[0], v[1], q(v[2])))
        else:
            L.append("list  %-*s  %s" % (w, name, q(v)))
    if cat.derives:
        L.append("# Derived keys (engine-spec 0.6 and 0.8), applied by `convert` between decode and encode.")
        for target, fn, args in cat.derives:
            L.append("derive  %s  %s  %s" % (target, fn, "  ".join(args)))
    return "\n".join(L)


def order_of_names(cat):
    """Keys and lists in UAP order, a list before the keys of its items."""
    out = []

    def walk(nodes):
        for n in nodes:
            t = n["t"]
            if t == "field" and n["declare"]:
                out.append(n["raw"].split(".", 1)[1])
            elif t == "chain":
                for p in n["parts"]:
                    walk(p)
            elif t == "group":
                out.append(n["list"].split(".", 1)[1])
                walk(n["body"])
            elif t == "compound":
                for _, _, _, sub in n["subs"]:
                    walk(sub)
    for e in cat.entries:
        if e["nodes"]:
            walk(e["nodes"])
    return out


def emit_nodes(nodes, ind, L):
    pad = "  " * ind
    for n in nodes:
        t = n["t"]
        if t == "field":
            L.append("%sfield  %s  %d  %s" % (pad, n["key"], n["bits"], n["tr"]))
            for a in n["also"]:
                L.append("%salso   %s" % (pad, a))
        elif t == "pad":
            L.append("%spad    %d" % (pad, n["bits"]))
        elif t == "chain":
            L.append(pad + "chain")
            for i, p in enumerate(n["parts"]):
                emit_nodes(p, ind + 1, L)
                if i < len(n["parts"]) - 1 or n["trailing"]:
                    L.append(pad + "  fx")
            L.append(pad + "end")
        elif t == "group":
            L.append("%sgroup  %s  %s" % (pad, n["list"], "count %d" % n["cbits"] if n["mode"] == "count" else "fx"))
            emit_nodes(n["body"], ind + 1, L)
            L.append(pad + "end")
        elif t == "compound":
            L.append("%spresence %s fx" % (pad, n["name"]))
            for bit, name, title, sub in n["subs"]:
                L.append("%sif %s.%d%s# subfield %d, %s%s" % (pad, n["name"], bit, " " * max(1, 28 - len(n["name"]) - len(str(bit))),
                                                              bit, name, ": " + title if title else ""))
                emit_nodes(sub, ind + 1, L)
                L.append(pad + "end")
        elif t == "explicit":
            L.append(pad + "length 8 bytes plus 1                # the length octet counts itself; the content is not mapped")
            L.append(pad + "end")


def emit_pack(cat, sha):
    L = ["# ASTERIX Category %s, %s, edition %s: one data block holding one record." % (cat.nnn, cat.title, cat.edition),
         "# Public. Generated by tools/gen/asterix2pack.py from the category definition of",
         "# github.com/%s (BSD-3-Clause); do not edit by hand. I/O is hex text." % REPO,
         "# Needs engine version 0.8 (`layout sequential`). See pack.md.",
         "#",
         "#   octet 1       CAT = %d" % cat.num,
         "#   octets 2-3    LEN, the length of the data block in octets, CAT and LEN included",
         "#   FSPEC         octets of 7 presence bits and an extension bit; bit n is FRN n",
         "#   then          the items whose FSPEC bit is 1, in FRN order",
         "#",
         "# An FRN with no `if` block is not mapped: a record with that FSPEC bit set fails",
         "# with `malformed-wire` (ruling 1 of engine-spec 0.8), and encode never sets the bit.",
         "format     " + cat.format, "version    " + PACK_VERSION, "distribution public",
         "source  " + q(source_line(cat, sha))]
    for m in cat.uses:
        L.append("uses       " + m)
    L += ["uses       " + cat.module, "wire       bits", "layout     sequential", "bit_order  msb",
          "kind    record", "when    8  %d%s# CAT" % (cat.num, " " * 30), "length  16 whole" + " " * 25 + "# LEN",
          "presence f fx"]
    for e in cat.entries:
        if e["nodes"] is None:
            L.append("# FRN %d: %s" % (e["frn"], ("I%s/%s %s, not mapped: %s" % (cat.nnn, e["name"], e["title"], e["reason"]))
                                       if e["name"] else e["reason"]))
            continue
        L.append("if f.%d%s# FRN %d, I%s/%s %s" % (e["frn"], " " * max(1, 36 - len(str(e["frn"]))), e["frn"], cat.nnn, e["name"], e["title"]))
        emit_nodes(e["nodes"], 1, L)
        L.append("end")
    return "\n".join(L)


# ---------------------------------------------------------------- raw records (written from the definition)

def to_bits(v, n):
    return format(v & ((1 << n) - 1), "0%db" % n) if n else ""


def raw_has(nodes, rec):
    for n in nodes:
        t = n["t"]
        if t == "field" and n["key"] in rec:
            return True
        if t == "chain" and any(raw_has(p, rec) for p in n["parts"]):
            return True
        if t == "group" and rec.get(n["list"]):
            return True
        if t == "compound" and any(raw_has(sub, rec) for _, _, _, sub in n["subs"]):
            return True
    return False


def fx_octets(setbits):
    """FSPEC-style octets for a set of 1-based bit numbers."""
    n = max(1, (max(setbits) + 6) // 7) if setbits else 1
    out = ""
    for o in range(n):
        out += "".join("1" if o * 7 + i + 1 in setbits else "0" for i in range(7)) + ("1" if o < n - 1 else "0")
    return out


def raw_enc(nodes, rec):
    """Bits of the lines for a record of raw wire values, keyed by the field's first key."""
    out = ""
    for n in nodes:
        t = n["t"]
        if t == "field":
            v = rec.get(n["key"], "" if n["kind"] == "ascii" else 0)
            if n["kind"] == "ascii":
                b = v.encode("ascii").ljust(n["bits"] // 8, b"\0")
                out += "".join(to_bits(x, 8) for x in b)
            else:
                out += to_bits(v, n["bits"])
        elif t == "pad":
            out += "0" * n["bits"]
        elif t == "chain":
            parts = n["parts"]
            last = max([i for i, p in enumerate(parts) if raw_has(p, rec)] + [0])
            for i, p in enumerate(parts[:last + 1]):
                out += raw_enc(p, rec)
                if i < len(parts) - 1 or n["trailing"]:
                    out += "1" if i < last else "0"
        elif t == "group":
            items = rec.get(n["list"], [])
            if n["mode"] == "count":
                out += to_bits(len(items), n["cbits"])
                for it in items:
                    out += raw_enc(n["body"], it)
            else:
                for i, it in enumerate(items):
                    out += raw_enc(n["body"], it) + ("1" if i < len(items) - 1 else "0")
        elif t == "compound":
            setbits = {bit for bit, _, _, sub in n["subs"] if raw_has(sub, rec)}
            out += fx_octets(setbits)
            for bit, _, _, sub in n["subs"]:
                if bit in setbits:
                    out += raw_enc(sub, rec)
        elif t == "explicit":
            die("a raw record cannot hold an explicit item")
    return out


def raw_block(cat, rec, extra=None):
    """Hex of the data block for a raw record. `extra` is FRN -> bits of an item written as is."""
    extra = extra or {}
    setbits = {e["frn"] for e in cat.entries if e["nodes"] and raw_has(e["nodes"], rec)} | set(extra)
    body = fx_octets(setbits)
    for e in cat.entries:
        if e["frn"] in extra:
            body += extra[e["frn"]]
        elif e["frn"] in setbits:
            body += raw_enc(e["nodes"], rec)
    if len(body) % 8:
        die("cat %s: a record of %d bits" % (cat.nnn, len(body)))
    total = 3 + len(body) // 8
    bits = to_bits(cat.num, 8) + to_bits(total, 16) + body
    return "%0*x" % (len(bits) // 4, int(bits, 2))


def raw_value(n, v):
    """Model value of a raw wire value, by the definition."""
    if n["kind"] == "ascii":
        return v
    if n["frac"] is not None:
        return float(v) * float(n["frac"].numerator) / float(n["frac"].denominator) \
            if n["frac"].denominator != 1 else float(v) * float(n["frac"].numerator)
    return v


def raw_model(nodes, rec, prefix, model):
    for n in nodes:
        t = n["t"]
        if t == "field":
            if n["key"] in rec:
                x = raw_value(n, rec[n["key"]])
                for k in [n["key"]] + n["also"]:
                    model[prefix + k] = x
        elif t == "chain":
            for p in n["parts"]:
                raw_model(p, rec, prefix, model)
        elif t == "group":
            if rec.get(n["list"]):
                model[prefix + n["list"] + ".#"] = len(rec[n["list"]])
                for i, it in enumerate(rec[n["list"]]):
                    raw_model(n["body"], it, "%s%s[%d]." % (prefix, n["list"], i), model)
        elif t == "compound":
            for _, _, _, sub in n["subs"]:
                raw_model(sub, rec, prefix, model)


class Picker:
    """Deterministic raw values that set every bit pattern class: no zero, both signs."""

    def __init__(self):
        self.i = 0

    def value(self, n):
        self.i += 1
        bits = n["bits"]
        if n["kind"] == "ascii":
            alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            return "".join(alphabet[(self.i * 7 + j * 3) % len(alphabet)] for j in range(bits // 8))
        h = (self.i * 2654435761 + 0x9E3779B9) & 0xFFFFFFFFFFFF
        h ^= h >> 7
        if n["signed"]:
            lim = 1 << (bits - 1)
            v = h % lim if lim > 1 else 0
            if v == 0:
                v = 1 if lim > 1 else -1
            return -v if self.i % 2 else v
        lim = 1 << min(bits, 63)
        v = h % lim
        return v or 1

    def fill(self, nodes, rec, items=2):
        for n in nodes:
            t = n["t"]
            if t == "field":
                rec[n["key"]] = NICE[n["key"]](n) if n["key"] in NICE else self.value(n)
            elif t == "chain":
                for p in n["parts"]:
                    self.fill(p, rec, items)
            elif t == "group":
                rec[n["list"]] = []
                for _ in range(items):
                    it = {}
                    self.fill(n["body"], it, items)
                    rec[n["list"]].append(it)
            elif t == "compound":
                for _, _, _, sub in n["subs"]:
                    self.fill(sub, rec, items)


def nice(target):
    def f(n):
        t = target
        while True:         # a field too narrow for the value takes half of it, and so on
            try:
                return model_to_raw(n, t)
            except GenError:
                t = t / 2
    return f


def model_to_raw(n, x):
    """Raw wire value of a model value, by the definition (ruling 1 of 0.5: (x * den) / num)."""
    fr = n["frac"]
    qv = x * float(fr.denominator) / float(fr.numerator) if fr.denominator != 1 else x / float(fr.numerator)
    v = round_half_away(qv)
    lo, hi = (-(1 << (n["bits"] - 1)), (1 << (n["bits"] - 1)) - 1) if n["signed"] else (0, (1 << n["bits"]) - 1)
    if not lo <= v <= hi:
        die("%s: %r does not fit %d bits" % (n["ident"], x, n["bits"]))
    return v


# values of the bound keys in the generated vectors
NICE = {"lat": nice(47.5), "lon": nice(-122.25), "hae": nice(1524.0), "speed_ms": nice(57.875),
        "course": nice(90.0), "track.vel_east_ms": nice(0.0), "track.vel_north_ms": nice(4.0)}


# ---------------------------------------------------------------- derivations (engine-spec 0.6, 0.8)

def apply_derives(ent, derives):
    for _ in range(8):
        changed = False
        for target, fn, args in derives:
            if target in ent or any(a not in ent for a in args):
                continue
            a = [ent[x] for x in args]
            r = None
            if fn == "copy":
                r = a[0]
            elif fn == "hypot":
                r = math.sqrt(a[0] * a[0] + a[1] * a[1])
            elif fn == "bearing":
                if not (a[0] == 0 and a[1] == 0):
                    r = math.atan2(a[0], a[1]) * (180.0 / math.pi)
                    if r < 0:
                        r += 360.0
                    if r >= 360.0:
                        r -= 360.0
            elif fn == "east_of":
                r = a[0] * math.sin(a[1] * (math.pi / 180.0))
            elif fn == "north_of":
                r = a[0] * math.cos(a[1] * (math.pi / 180.0))
            elif fn == "day_seconds":
                r = (a[0] % 86400000) / 1000.0
            else:
                die("derive function %s is not in the self-check" % fn)
            if r is not None and not (isinstance(r, float) and not math.isfinite(r)):
                ent[target] = r
                changed = True
        if not changed:
            break
    return ent


def all_derives(modules):
    """Derive lines of the loaded modules in byte order of module name."""
    out = []
    for name in sorted(modules):
        out += modules[name]["derives"]
    return out


def geojson_text(ent):
    """Canonical GeoJSON Feature of the entity (packs/geojson, rulings 3 to 5 of 0.1.1)."""
    def js(v):
        return json.dumps(v, ensure_ascii=False) if isinstance(v, str) else plain(v)
    props, top = [], []
    for key, loc in GEOJSON_FIELDS:
        if key in ent and loc.startswith("properties."):
            props.append('"%s":%s' % (loc.split(".", 1)[1], js(ent[key])))
        elif key in ent and "." not in loc:
            top.append('"%s":%s' % (loc, js(ent[key])))
    if "lat" in ent and "lon" in ent:
        coords = [plain(ent["lon"]), plain(ent["lat"])] + ([plain(ent["hae"])] if "hae" in ent else [])
        geom = '{"type":"Point","coordinates":[%s]}' % ",".join(coords)
    else:
        geom = "null"
    return '{"type":"Feature","geometry":%s,"properties":{%s}%s}' % (geom, ",".join(props), "".join("," + t for t in top))


def iso8601_ms(text):
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?Z", text)
    if not m:
        die("time %r" % text)
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    frac = int((m.group(7) or "0")[:3].ljust(3, "0"))
    y2 = y - (mo <= 2)
    era = y2 // 400
    yoe = y2 - era * 400
    doy = (153 * (mo + (-3 if mo > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days = era * 146097 + doe - 719468
    return ((days * 24 + h) * 60 + mi) * 60000 + s * 1000 + frac


def track_json_decode(text):
    """The members of a Canonical Track v2 object the generated vector uses."""
    obj = json.loads(text)
    if obj.get("apiVersion") != "billie.dev/track-v2" or obj.get("kind") != "Track":
        raise WireError("no-kind", "not a track-v2 object")
    ent = {}
    for key, path, tr in TRACK_JSON_FIELDS:
        cur = obj
        for p in path.split("."):
            cur = cur.get(p) if isinstance(cur, dict) else None
        if cur is None:
            continue
        ent[key] = iso8601_ms(cur) if tr == "iso8601_ms" else float(cur) if tr == "float" else cur
    return ent


# ---------------------------------------------------------------- vectors

def model_strings(model):
    return OrderedDict((k, plain(v) if not isinstance(v, str) else v) for k, v in model.items())


def find_field(cat, key):
    for e in cat.entries:
        if e["nodes"]:
            for n, lst in walk_fields(e["nodes"]):
                if n["key"] == key and lst is None:
                    return e, n
    return None, None


def write_vectors(cat, out, pack, modules):
    """-> list of (file name, what it shows); also the vector for packs/canonical-track-v2."""
    vdir = os.path.join(out, "packs", cat.format, "vectors")
    os.makedirs(vdir, exist_ok=True)
    for old in glob.glob(os.path.join(vdir, "*.json")):
        os.remove(old)
    made = []
    src = "generated by tools/gen/asterix2pack.py from %s of github.com/%s" % (cat.rel, REPO)

    def put(name, what, **body):
        v = OrderedDict([("name", name), ("from", body.pop("frm", cat.format)), ("to", body.pop("to", cat.format))])
        v.update(body)
        v["source"] = body.get("source", src)
        v["reference"] = what
        fn = "%02d-%s.json" % (len(made) + 1, name)
        write(os.path.join(vdir, fn), json.dumps(v, indent=2, ensure_ascii=False))
        made.append((fn, what))

    mapped = [e for e in cat.entries if e["nodes"] and e["kind"] != "explicit"]
    # 1. every mapped item
    rec = {}
    pk = Picker()
    for e in mapped:
        pk.fill(e["nodes"], rec)
    model = OrderedDict([("@kind", "record")])
    for e in mapped:
        raw_model(e["nodes"], rec, "", model)
    hx = raw_block(cat, rec)
    put("every-mapped-item-roundtrip",
        "every mapped FRN present, every field of it set, two repetitions in every repetitive item, every extent "
        "of every extended item: %d octets" % (len(hx) // 2),
        input=hx, expect=hx, model=model_strings(model))
    # 2. one item
    first = mapped[0]
    rec = {}
    Picker().fill(first["nodes"], rec, items=1)
    model = OrderedDict([("@kind", "record")])
    raw_model(first["nodes"], rec, "", model)
    hx = raw_block(cat, rec)
    put("one-item-roundtrip",
        "a record holding only FRN %d, I%s/%s (the definition does not mark items as mandatory)" % (first["frn"], cat.nnn, first["name"]),
        input=hx, expect=hx, model=model_strings(model))
    # 3. extended items with their first part only
    chains = [e for e in mapped if e["kind"] == "extended"]
    if chains:
        rec = {}
        for e in chains:
            Picker().fill(e["nodes"][0]["parts"][0], rec)
        model = OrderedDict([("@kind", "record")])
        for e in chains:
            raw_model(e["nodes"], rec, "", model)
        if rec:
            hx = raw_block(cat, rec)
            put("extended-items-first-part-only-roundtrip",
                "each extended item with its first part and the extension bit 0; the keys of later parts are absent",
                input=hx, expect=hx, model=model_strings(model))
    # 4. explicit item: read over, not written
    expl = [e for e in cat.entries if e["nodes"] and e["kind"] == "explicit"]
    if expl:
        rec = {}
        Picker().fill(first["nodes"], rec, items=1)
        model = OrderedDict([("@kind", "record")])
        raw_model(first["nodes"], rec, "", model)
        extra = {e["frn"]: to_bits(4, 8) + to_bits(0xA1B2C3, 24) for e in expl}
        put("explicit-items-are-read-over-and-not-written",
            "the same record with %s present, each a length octet of 4 and three octets of content: decode passes "
            "over them, encode does not write them" % " and ".join("FRN %d (%s)" % (e["frn"], e["name"]) for e in expl),
            input=raw_block(cat, rec, extra), expect=raw_block(cat, rec), model=model_strings(model))
    # 5. an FRN the pack does not map
    unm = [e for e in cat.entries if e["nodes"] is None]
    if unm:
        e = unm[0]
        put("frn-the-pack-does-not-map",
            "FSPEC bit %d set (%s): ruling 1 of engine-spec 0.8" % (e["frn"], "I%s/%s" % (cat.nnn, e["name"]) if e["name"] else e["reason"]),
            input=raw_block(cat, {}, {e["frn"]: to_bits(0, 8)}), expect_error="malformed-wire")
    # 6. another category
    rec = {}
    Picker().fill(first["nodes"], rec, items=1)
    hx = raw_block(cat, rec)
    other = "%02x" % ((cat.num + 1) % 256)
    put("category-is-not-%d" % cat.num, "the first octet is %d" % ((cat.num + 1) % 256),
        input=other + hx[2:], expect_error="no-kind")
    # 7. a block shorter than LEN
    put("block-shorter-than-len", "LEN states %d octets and the input holds %d" % (len(hx) // 2, len(hx) // 2 - 1),
        input=hx[:-2], expect_error="malformed-wire")
    # 8. to geojson
    track_vec = None
    bound = [b["key"] for b in cat.bindings if b["how"] not in ("derive", "day_seconds")]
    if "lat" in bound and "lon" in bound:
        rec, items = {}, []
        for key in bound:
            e, n = find_field(cat, key)
            if e not in items:
                items.append(e)
        for e in sorted(items, key=lambda e: e["frn"]):
            for n in e["nodes"]:
                if n["t"] == "field":
                    rec[n["key"]] = NICE[n["key"]](n) if n["key"] in NICE else 0
        model = OrderedDict()
        for e in items:
            raw_model(e["nodes"], rec, "", model)
        ent = apply_derives(dict(model), all_derives(modules))
        hx = raw_block(cat, rec)
        put("to-geojson",
            "a record with %s: the shared keys %s reach the Feature" % (
                ", ".join("I%s/%s" % (cat.nnn, e["name"]) for e in sorted(items, key=lambda e: e["frn"])),
                ", ".join("`%s`" % k for k in bound)),
            to="geojson", input=hx, expect=geojson_text(ent),
            model=model_strings(OrderedDict((k, v) for k, v in model.items() if k in bound)))
        # 9. from canonical-track-v2 (the vector belongs to that pack: it owns the input)
        tj = ('{"apiVersion":"billie.dev/track-v2","kind":"Track","trackId":"311","sourceId":"sensor-a",'
              '"trackGeneration":"generation-1","observedAt":"2025-10-29T12:00:00.125Z",'
              '"position":{"latitudeDeg":47.5,"longitudeDeg":-122.25,"altitudeM":1524},'
              '"velocity":{"eastMps":3,"northMps":4}}')
        ent = apply_derives(track_json_decode(tj), all_derives(modules))
        fits = True
        for e in cat.entries:           # a field too narrow for the track's value: no vector
            for n, lst in walk_fields(e["nodes"] or []):
                if lst is None and n["key"] in ent and n["frac"] is not None:
                    try:
                        model_to_raw(n, ent[n["key"]])
                    except GenError:
                        fits = False
        rec = {}
        for e in cat.entries:
            if not e["nodes"] or not fits:
                continue
            for n, lst in walk_fields(e["nodes"]):
                if lst is None:
                    for k in [n["key"]] + n["also"]:
                        if k in ent and n["key"] not in rec:
                            rec[n["key"]] = model_to_raw(n, ent[k])
        written = [e for e in cat.entries if e["nodes"] and raw_has(e["nodes"], rec)]
        complete = OrderedDict([("@complete", True)])
        for d in cat.derives:
            if d[1] == "day_seconds":
                complete[d[0]] = plain(ent[d[0]])
        track_vec = None if not fits else OrderedDict([
            ("name", "gen-to-" + cat.format), ("from", "canonical-track-v2"), ("to", cat.format),
            ("input", tj), ("expect", raw_block(cat, rec))])
        if fits and len(complete) > 1:
            track_vec["model"] = complete
        if fits:
            track_vec["source"] = src
            track_vec["reference"] = ("a track at 47.5 N 122.25 W, 1524 m, velocity 3 m/s east and 4 m/s north, at "
                                      "12:00:00.125 UTC: the record holds %s; the fields of those items that no key "
                                      "fills are zero" % ", ".join("I%s/%s" % (cat.nnn, e["name"]) for e in written))
    # 10. published samples
    for s in SAMPLES:
        if s["cat"] != cat.num:
            continue
        ent, lists = seq_decode(pack, s["hex"])
        for path, want in s["stated"].items():
            ident = "%s" % path
            name = cat.names.get(ident)
            keys = [k for k in ent if name and k.endswith("." + name)] or \
                   [n["key"] for e in cat.entries if e["nodes"] for n, _ in walk_fields(e["nodes"]) if n["ident"] == ident]
            if not keys or keys[0] not in ent or abs(ent[keys[0]] - want) > 1e-9:
                die("cat %s sample %s: %s is %r, the publisher states %r" % (cat.nnn, s["name"], path, ent.get(keys[0]) if keys else None, want))
        expect = seq_encode(pack, ent, lists)
        if expect != s.get("expect", s["hex"]):
            die("cat %s sample %s: re-encoded %s" % (cat.nnn, s["name"], expect))
        model = OrderedDict([("@kind", "record")])
        for k, v in ent.items():
            model[k] = v
        put(s["name"], s["note"], input=s["hex"], expect=expect, model=model_strings(model),
            source="github.com/%s (BSD-3-Clause), %s, commit %s" % (SAMPLES_REPO, SAMPLES_PATH, SAMPLES_COMMIT))
    return made, track_vec


# ---------------------------------------------------------------- independent loader (spec 0.4 to 0.8)

def tokenize(line):
    out, i, n = [], 0, len(line)
    while i < n:
        ch = line[i]
        if ch in " \t\r\n":
            i += 1
        elif ch == "#":
            break
        elif ch == '"':
            j = line.find('"', i + 1)
            if j < 0:
                raise GenError("bad-directive: unterminated quote")
            out.append(line[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and line[j] not in " \t\r\n":
                j += 1
            out.append(line[i:j])
            i = j
    return out


def parse_module(text):
    m = dict(name=None, distribution=None, sources=[], keys=OrderedDict(), lists=OrderedDict(), derives=[], uses=[])
    for line in text.splitlines():
        a = tokenize(line)
        if not a:
            continue
        d = a[0]
        if d == "module" and len(a) == 2:
            m["name"] = a[1]
        elif d == "version" and len(a) == 2:
            pass
        elif d == "distribution" and len(a) == 2 and a[1] in ("public", "controlled"):
            m["distribution"] = a[1]
        elif d == "source" and len(a) == 2:
            m["sources"].append(a[1])
        elif d == "uses" and len(a) == 2:
            m["uses"].append(a[1])
        elif d == "key" and len(a) in (4, 5) and a[2] in ("string", "float", "int"):
            if "." in a[1] or a[1] in m["keys"] or a[1] in m["lists"]:
                raise GenError("duplicate-key: %s" % a[1])
            m["keys"][a[1]] = a[2]
        elif d == "list" and len(a) in (2, 3):
            if "." in a[1] or a[1] in m["keys"] or a[1] in m["lists"]:
                raise GenError("duplicate-key: %s" % a[1])
            m["lists"][a[1]] = True
        elif d == "derive" and len(a) >= 4:
            m["derives"].append((a[1], a[2], a[3:]))
        else:
            raise GenError("bad-directive: module line %r" % line)
    if not m["distribution"]:
        raise GenError("missing-distribution: module %s" % m["name"])
    if not m["sources"]:
        raise GenError("missing-source: module %s" % m["name"])
    return m


def key_type(modules, key):
    mod, name = key.split(".", 1) if "." in key else ("core", key)
    if mod not in modules:
        raise GenError("unknown-module: %s" % mod)
    if name in modules[mod]["lists"]:
        return "list"
    if name not in modules[mod]["keys"]:
        raise GenError("undeclared-key: %s" % key)
    return modules[mod]["keys"][name]


def check_module(m, modules):
    """`derive` lines: declared keys, types that fit (engine-spec 0.6 and 0.8)."""
    for target, fn, args in m["derives"]:
        tt = key_type(modules, target)
        at = [key_type(modules, a) for a in args]
        mod_t = target.split(".", 1)[0] if "." in target else "core"
        if mod_t not in ("core", m["name"]):
            raise GenError("bad-directive: derive target %s of another module" % target)
        for a in args:
            ma = a.split(".", 1)[0] if "." in a else "core"
            if ma not in ["core", m["name"]] + m["uses"]:
                raise GenError("bad-directive: derive argument %s of a module not used" % a)
        ok = {"copy": len(at) == 1 and at[0] == tt,
              "day_seconds": at == ["int"] and tt == "float"}.get(fn)
        if ok is None:
            raise GenError("bad-directive: derive function %s is not one the generator writes" % fn)
        if not ok:
            raise GenError("bad-directive: derive %s %s: types do not fit" % (target, fn))


YIELDS = {"uint": "int", "twos": "int", "uscale": "float", "sscale": "float", "ascii": "string"}


def parse_pack(text, modules):
    """-> dict(format, uses, kinds=[(name, lines)]); lines are nested dicts. Checks the load rules
    a sequential pack of this shape can break."""
    p = dict(format=None, distribution=None, sources=[], uses=[], wire=None, layout=None, bit_order="lsb", kind=None)
    root = []
    stack = [("root", root, None)]      # (block type, lines, node)
    last_field = None
    for ln_no, line in enumerate(text.splitlines(), 1):
        a = tokenize(line)
        if not a:
            continue
        d = a[0]
        cur = stack[-1][1]

        def bad(msg):
            raise GenError("bad-directive: line %d: %s" % (ln_no, msg))
        if d != "also":
            keep_last, last_field = last_field, None
        if d == "format":
            p["format"] = a[1]
        elif d == "version":
            pass
        elif d == "distribution":
            p["distribution"] = a[1]
        elif d == "source":
            p["sources"].append(a[1])
        elif d == "uses":
            p["uses"].append(a[1])
        elif d == "wire":
            p["wire"] = a[1]
        elif d == "layout":
            p["layout"] = a[1]
        elif d == "bit_order":
            p["bit_order"] = a[1]
        elif d == "kind":
            if p["kind"] or len(stack) != 1 or root:
                bad("the generator writes one kind, before every line")
            p["kind"] = a[1]
        elif d == "when":
            if len(stack) != 1 or any(x["t"] != "when" for x in root):
                bad("`when` after another line of its kind or inside a block")
            if not 1 <= int(a[1]) <= 64 or int(a[2]) >= 1 << int(a[1]):
                bad("`when` value does not fit")
            cur.append(dict(t="when", bits=int(a[1]), value=int(a[2])))
        elif d == "field":
            if len(a) != 4:
                bad("field with options")
            key, bits, tr = a[1], int(a[2]), a[3]
            name, _, arg = tr.partition(":")
            if name not in YIELDS:
                raise GenError("unknown-transform: %s" % tr)
            kt = key_type(modules, key)
            if kt == "list":
                raise GenError("key-type-mismatch: field names the list %s" % key)
            if kt != YIELDS[name]:
                raise GenError("key-type-mismatch: %s is %s, %s yields %s" % (key, kt, tr, YIELDS[name]))
            if name == "ascii":
                if bits % 8 or not 8 <= bits <= 2040:
                    bad("ascii of %d bits" % bits)
            elif not 1 <= bits <= 64:
                bad("field of %d bits" % bits)
            fac = None
            if name in ("uscale", "sscale"):
                if not re.fullmatch(r"\d+(/\d+)?", arg):
                    bad("scale %r" % arg)
                nd = arg.split("/")
                fac = (float(int(nd[0])), float(int(nd[1])) if len(nd) == 2 else None)
            elif arg:
                bad("transform argument %r" % arg)
            last_field = dict(t="field", keys=[key], bits=bits, tr=name, fac=fac)
            cur.append(last_field)
        elif d == "also":
            if last_field is None or len(a) != 2:
                bad("`also` not directly after a field")
            kt = key_type(modules, a[1])
            if kt != YIELDS[last_field["tr"]]:
                raise GenError("key-type-mismatch: also %s" % a[1])
            last_field["keys"].append(a[1])
        elif d == "pad":
            cur.append(dict(t="pad", bits=int(a[1])))
        elif d == "presence":
            if len(a) != 3 or a[2] != "fx":
                bad("presence form")
            if any(x["t"] == "presence" and x["name"] == a[1] for x in cur):
                bad("presence name declared twice in one block")
            cur.append(dict(t="presence", name=a[1]))
        elif d == "if":
            conds = []
            for c in a[1:]:
                m = re.fullmatch(r"(!?)([A-Za-z0-9_]+)\.(\d+)", c)
                if not m:
                    bad("if condition %r" % c)
                if not any(any(x["t"] == "presence" and x["name"] == m.group(2) for x in blk[1]) for blk in stack):
                    bad("`if` names the presence %s, which is not visible" % m.group(2))
                conds.append((m.group(1) == "!", m.group(2), int(m.group(3))))
            if not conds:
                bad("if with no condition")
            node = dict(t="if", conds=conds, body=[])
            cur.append(node)
            stack.append(("if", node["body"], node))
        elif d == "chain":
            node = dict(t="chain", body=[])
            cur.append(node)
            stack.append(("chain", node["body"], node))
        elif d == "fx":
            if stack[-1][0] != "chain":
                bad("`fx` outside a chain")
            cur.append(dict(t="fx"))
        elif d == "group":
            if key_type(modules, a[1]) != "list":
                raise GenError("key-type-mismatch: group names the scalar key %s" % a[1])
            if a[2:] == ["fx"]:
                node = dict(t="group", list=a[1], mode="fx", body=[])
            elif len(a) == 4 and a[2] == "count" and 1 <= int(a[3]) <= 64:
                node = dict(t="group", list=a[1], mode="count", cbits=int(a[3]), body=[])
            else:
                bad("group form")
            if any(x["t"] == "group" and x["list"] == a[1] for x in cur):
                bad("a list mapped by two groups of one scope")
            cur.append(node)
            stack.append(("group", node["body"], node))
        elif d == "length":
            bits, rest = int(a[1]), a[2:]
            node = dict(t="length", bits=bits, unit="bytes", plus=0, whole=False, body=[])
            i = 0
            while i < len(rest):
                if rest[i] in ("bytes", "bits"):
                    node["unit"] = rest[i]
                elif rest[i] == "plus":
                    i += 1
                    node["plus"] = int(rest[i])
                elif rest[i] == "whole":
                    node["whole"] = True
                else:
                    bad("length argument %r" % rest[i])
                i += 1
            if not 1 <= bits <= 64 or (node["whole"] and node["unit"] == "bits"):
                bad("length form")
            cur.append(node)
            if not node["whole"]:
                stack.append(("length", node["body"], node))
        elif d == "end":
            if len(stack) == 1:
                bad("`end` with no open block")
            stack.pop()
        else:
            bad("directive %r" % d)
    if len(stack) != 1:
        raise GenError("bad-directive: a block with no `end`")
    if not p["distribution"]:
        raise GenError("missing-distribution")
    if not p["sources"]:
        raise GenError("missing-source")
    if p["wire"] != "bits" or p["layout"] != "sequential" or p["bit_order"] != "msb" or not p["kind"]:
        raise GenError("bad-directive: not a sequential msb bits pack with one kind")
    for m in p["uses"]:
        if m not in modules:
            raise GenError("unknown-module: %s" % m)
        if p["distribution"] == "public" and modules[m]["distribution"] != "public":
            raise GenError("distribution-violation: %s" % m)

    def used(lines):
        for x in lines:
            if x["t"] == "field":
                for k in x["keys"]:
                    mod = k.split(".", 1)[0] if "." in k else "core"
                    if mod != "core" and mod not in p["uses"]:
                        raise GenError("module-not-used: %s" % k)
            if x["t"] == "group":
                mod = x["list"].split(".", 1)[0]
                if mod not in p["uses"]:
                    raise GenError("module-not-used: %s" % x["list"])
            if "body" in x:
                used(x["body"])
    used(root)
    p["lines"] = root
    return p


# ---------------------------------------------------------------- sequential codec (spec 0.8)

class Reader:
    def __init__(self, bits):
        self.bits, self.pos, self.end = bits, 0, len(bits)
        self.extents = []

    def take(self, n):
        """n bits as an int; None when the line starts at or after the end of a length extent."""
        if self.extents:
            ext = self.extents[-1]
            if self.pos >= ext:
                return None
            if self.pos + n > ext:
                raise WireError("malformed-wire", "a line straddles the end of a length extent")
        if self.pos + n > self.end:
            raise WireError("malformed-wire", "input ends inside a line")
        v = int(self.bits[self.pos:self.pos + n], 2) if n else 0
        self.pos += n
        return v


def named_bits(lines, name):
    """Bit numbers of presence `name` that an `if` of these lines names without `!`, with the blocks."""
    out = []
    for x in lines:
        if x["t"] == "if":
            for neg, nm, bit in x["conds"]:
                if nm == name and not neg:
                    out.append((bit, x))
        if "body" in x:
            out += named_bits(x["body"], name)
    return out


def all_named(lines, name):
    out = set()
    for x in lines:
        if x["t"] == "if":
            out |= {bit for _, nm, bit in x["conds"] if nm == name}
        if "body" in x:
            out |= all_named(x["body"], name)
    return out


def t_decode(x, v):
    tr, bits = x["tr"], x["bits"]
    if tr == "uint":
        return v - (1 << 64) if bits == 64 and v >> 63 else v
    signed = v - (1 << bits) if v >> (bits - 1) else v
    if tr == "twos":
        return signed
    if tr in ("uscale", "sscale"):
        num_, den = x["fac"]
        r = float(v if tr == "uscale" else signed) * num_
        return r / den if den is not None else r
    if tr == "ascii":
        b = v.to_bytes(bits // 8, "big").rstrip(b"\0")
        if any(c < 0x20 or c > 0x7E for c in b):
            raise WireError("transform-decode", "ascii byte out of range")
        return b.decode("ascii")
    raise GenError("transform %s" % tr)


def t_encode(x, val):
    tr, bits = x["tr"], x["bits"]
    if tr == "ascii":
        b = val.encode("utf-8")
        if len(b) > bits // 8 or any(c < 0x20 or c > 0x7E for c in b):
            raise WireError("transform-encode", "ascii text")
        return int.from_bytes(b.ljust(bits // 8, b"\0"), "big")
    if tr in ("uscale", "sscale"):
        num_, den = x["fac"]
        v = round_half_away(val * den / num_ if den is not None else val / num_)
    else:
        v = val
    if tr in ("uint", "uscale"):
        if tr == "uint" and bits == 64 and -(1 << 63) <= v < 0:
            v += 1 << 64
        if not 0 <= v < 1 << bits:
            raise WireError("transform-encode", "%r does not fit %d bits" % (val, bits))
        return v
    if not -(1 << (bits - 1)) <= v < 1 << (bits - 1):
        raise WireError("transform-encode", "%r does not fit %d bits" % (val, bits))
    return v & ((1 << bits) - 1)


def dec_lines(lines, rd, ent, lists, env):
    env = dict(env)
    for i, x in enumerate(lines):
        t = x["t"]
        if t == "when":
            v = rd.take(x["bits"])
            if v != x["value"]:
                raise WireError("no-kind", "when %d" % x["value"])
        elif t == "field":
            v = rd.take(x["bits"])
            if v is not None:
                val = t_decode(x, v)
                for k in x["keys"]:
                    ent.setdefault(k, val)
        elif t == "pad":
            rd.take(x["bits"])
        elif t == "presence":
            setbits, o = set(), 0
            while True:
                v = rd.take(8)
                if v is None:
                    break
                for b in range(7):
                    if v >> (7 - b) & 1:
                        setbits.add(o * 7 + b + 1)
                o += 1
                if not v & 1:
                    break
            stray = setbits - all_named(lines[i + 1:], x["name"])
            if stray:
                raise WireError("malformed-wire", "presence bit %s.%d is 1 and no `if` names it" % (x["name"], min(stray)))
            env[x["name"]] = setbits
        elif t == "if":
            if all((bit in env[nm]) != neg for neg, nm, bit in x["conds"]):
                dec_lines(x["body"], rd, ent, lists, env)
        elif t == "chain":
            for y_i, y in enumerate(x["body"]):
                if y["t"] == "fx":
                    v = rd.take(1)
                    if not v:
                        break
                    if y_i == len(x["body"]) - 1:
                        raise WireError("malformed-wire", "a chain that ends with an fx line whose bit is 1")
                else:
                    dec_lines([y], rd, ent, lists, env)
        elif t == "group":
            items = []
            if x["mode"] == "count":
                n = rd.take(x["cbits"])
                if n is None:
                    continue
                if n > rd.end - rd.pos:
                    raise WireError("malformed-wire", "count larger than the bits left")
                for _ in range(n):
                    it = ({}, {})
                    dec_lines(x["body"], rd, it[0], it[1], env)
                    items.append(it)
            else:
                if rd.extents and rd.pos >= rd.extents[-1]:
                    continue
                while True:
                    it = ({}, {})
                    dec_lines(x["body"], rd, it[0], it[1], env)
                    items.append(it)
                    if not rd.take(1):
                        break
            lists[x["list"]] = items
        elif t == "length":
            v = rd.take(x["bits"])
            if x["whole"]:
                total = v - x["plus"]
                if total * 8 < rd.pos or total * 8 > rd.end:
                    raise WireError("malformed-wire", "whole length %d, input %d octets" % (total, rd.end // 8))
                rd.end = total * 8
            elif v is not None:
                n = v - x["plus"]
                if n < 0:
                    raise WireError("malformed-wire", "stated length below `plus`")
                ext = rd.pos + n * (8 if x["unit"] == "bytes" else 1)
                if ext > rd.end or (rd.extents and ext > rd.extents[-1]):
                    raise WireError("malformed-wire", "length extent beyond the input")
                rd.extents.append(ext)
                dec_lines(x["body"], rd, ent, lists, env)
                rd.extents.pop()
                rd.pos = ext
        else:
            raise GenError("line %s" % t)


def seq_decode(pack, hx):
    hx = "".join(hx.split())
    if len(hx) % 2 or not re.fullmatch(r"[0-9a-fA-F]*", hx):
        raise WireError("malformed-wire", "hex")
    rd = Reader("".join(format(int(c, 16), "04b") for c in hx))
    ent, lists = {}, {}
    dec_lines(pack["lines"], rd, ent, lists, {})
    return ent, lists


def has_content(lines, ent, lists):
    """Would these lines write a present key, a non-empty list, or a nested presence that is not all zero?"""
    for i, x in enumerate(lines):
        t = x["t"]
        if t == "field" and any(k in ent for k in x["keys"]):
            return True
        if t == "group" and lists.get(x["list"]):
            return True
        if t in ("chain", "length") and has_content(x["body"], ent, lists):
            return True
        if t == "presence" and any(has_content(blk["body"], ent, lists) for _, blk in named_bits(lines[i + 1:], x["name"])):
            return True
    return False


def enc_lines(lines, ent, lists, env, st):
    env = dict(env)
    out = ""
    for i, x in enumerate(lines):
        t = x["t"]
        if t == "when":
            out += to_bits(x["value"], x["bits"])
        elif t == "field":
            val = next((ent[k] for k in x["keys"] if k in ent), None)
            out += to_bits(t_encode(x, val) if val is not None else 0, x["bits"])
        elif t == "pad":
            out += "0" * x["bits"]
        elif t == "presence":
            setbits = {bit for bit, blk in named_bits(lines[i + 1:], x["name"]) if has_content(blk["body"], ent, lists)}
            env[x["name"]] = setbits
            out += fx_octets(setbits)
        elif t == "if":
            if all((bit in env[nm]) != neg for neg, nm, bit in x["conds"]):
                out += enc_lines(x["body"], ent, lists, env, st)
        elif t == "chain":
            body = x["body"]
            for y_i, y in enumerate(body):
                if y["t"] == "fx":
                    more = has_content([z for z in body[y_i + 1:] if z["t"] != "fx"], ent, lists)
                    out += "1" if more else "0"
                    if not more:
                        break
                else:
                    out += enc_lines([y], ent, lists, env, st)
        elif t == "group":
            items = lists.get(x["list"], [])
            if x["mode"] == "count":
                if len(items) >= 1 << x["cbits"]:
                    raise WireError("transform-encode", "count does not fit")
                out += to_bits(len(items), x["cbits"])
                for it in items:
                    out += enc_lines(x["body"], it[0], it[1], env, st)
            else:
                if not items:
                    raise WireError("transform-encode", "an fx group with no item")
                for j, it in enumerate(items):
                    out += enc_lines(x["body"], it[0], it[1], env, st) + ("1" if j < len(items) - 1 else "0")
        elif t == "length":
            if x["whole"]:
                st["whole"] = (len(st["prefix"]) + len(out), x)
                out += "0" * x["bits"]
            else:
                body = enc_lines(x["body"], ent, lists, env, st)
                if x["unit"] == "bytes":
                    body += "0" * (-len(body) % 8)
                    n = len(body) // 8
                else:
                    n = len(body)
                out += to_bits(n + x["plus"], x["bits"]) + body
    return out


def seq_encode(pack, ent, lists):
    st = dict(prefix="", whole=None)
    bits = enc_lines(pack["lines"], ent, lists, {}, st)
    bits += "0" * (-len(bits) % 8)
    if st["whole"]:
        pos, x = st["whole"]
        v = len(bits) // 8 + x["plus"]
        if not 0 <= v < 1 << x["bits"]:
            raise WireError("transform-encode", "whole length does not fit")
        bits = bits[:pos] + to_bits(v, x["bits"]) + bits[pos + x["bits"]:]
    return "%0*x" % (len(bits) // 4, int(bits, 2)) if bits else ""


def lookup(ent, lists, key):
    """A `model` key of a vector: a key, `<list>.#`, or `<list>[<i>].<rest>` (spec/vector-format.md)."""
    m = re.match(r"([^\[\]]+)\[(\d+)\]\.(.*)$", key)
    if m:
        items = lists.get(m.group(1))
        if items is None or int(m.group(2)) >= len(items):
            raise GenError("list %s has no item %s" % (m.group(1), m.group(2)))
        it = items[int(m.group(2))]
        return lookup(it[0], it[1], m.group(3))
    if key.endswith(".#"):
        items = lists.get(key[:-2])
        return "absent" if items is None else len(items)
    if key not in ent:
        raise GenError("model key %s absent after decode" % key)
    return ent[key]


def replay(v, packs, modules):
    """One vector through the codec. Raises GenError when it does not hold."""
    frm, to = v["from"], v["to"]
    name = "%s/%s" % (frm, v["name"])
    try:
        if frm in packs:
            ent, lists = seq_decode(packs[frm], v["input"])
        elif frm == "canonical-track-v2":
            ent, lists = track_json_decode(v["input"]), {}
        else:
            raise GenError("%s: the self-check does not read %s" % (name, frm))
        decoded = (dict(ent), lists)
        if frm != to:
            ent = apply_derives(ent, all_derives(modules))
        if to in packs:
            got = seq_encode(packs[to], ent, lists)
        elif to == "geojson":
            got = geojson_text(ent)
        else:
            raise GenError("%s: the self-check does not write %s" % (name, to))
    except WireError as x:
        if v.get("expect_error") == x.kind:
            return
        raise GenError("%s: %s" % (name, x))
    if "expect_error" in v:
        raise GenError("%s: expected %s, the conversion succeeded" % (name, v["expect_error"]))
    if got != v["expect"]:
        raise GenError("%s: got %s, the vector expects %s" % (name, got, v["expect"]))
    model = v.get("model", {})
    base = (ent, lists) if model.get("@complete") else decoded
    for k, want in model.items():
        if k == "@complete":
            continue
        if k == "@kind":
            if want != packs[frm]["kind"]:
                raise GenError("%s: kind %s" % (name, want))
            continue
        got_v = lookup(base[0], base[1], k)
        if isinstance(got_v, float):
            ok = abs(got_v - float(want)) < 1e-9 * max(1.0, abs(got_v), abs(float(want)))
        else:
            ok = str(got_v) == want
        if not ok:
            raise GenError("%s: model key %s is %r, the vector expects %s" % (name, k, got_v, want))


# ---------------------------------------------------------------- pack.md

def count_nodes(nodes):
    """(fields, pad bits, lists) of an item."""
    f = p = g = 0
    for n in nodes:
        t = n["t"]
        if t == "field":
            f += 1
        elif t == "pad":
            p += n["bits"]
        elif t == "chain":
            for part in n["parts"]:
                a, b, c = count_nodes(part)
                f, p, g = f + a, p + b, g + c
        elif t == "group":
            a, b, c = count_nodes(n["body"])
            f, p, g = f + a, p + b, g + c + 1
        elif t == "compound":
            for _, _, _, sub in n["subs"]:
                a, b, c = count_nodes(sub)
                f, p, g = f + a, p + b, g + c
    return f, p, g


def mapped_as(e):
    n0 = e["nodes"][0]
    f, p, g = count_nodes(e["nodes"])
    if e["kind"] == "fixed":
        s = "%d field%s" % (f, "" if f == 1 else "s")
    elif e["kind"] == "extended":
        s = "`chain` of %d part%s, %d fields" % (len(n0["parts"]), "" if len(n0["parts"]) == 1 else "s", f)
    elif e["kind"] == "repetitive":
        s = "`group %s %s`, %d field%s per item" % (n0["list"], "count %d" % n0["cbits"] if n0["mode"] == "count" else "fx",
                                                   f, "" if f == 1 else "s")
    elif e["kind"] == "compound":
        s = "`presence %s fx` with %d subfields, %d fields" % (n0["name"], len(n0["subs"]), f)
        if g:
            s += ", %d list%s" % (g, "" if g == 1 else "s")
    else:
        return "`length 8 bytes plus 1` with an empty block: read over on decode, never written"
    if p:
        s += ", %d spare bit%s as `pad`" % (p, "" if p == 1 else "s")
    return s


def emit_pack_md(cat, sha, master, made, track_vec, stats):
    A = []
    a = A.append
    a("# Pack: %s" % cat.format)
    a("")
    a("ASTERIX Category %s, %s, edition %s (%s): one data block holding one record." % (cat.nnn, cat.title, cat.edition, cat.date))
    a("Public. Generated by `tools/gen/asterix2pack.py` from the machine-readable definition of the")
    a("category in `github.com/%s` (BSD-3-Clause), file `%s` at commit" % (REPO, cat.rel))
    a("`%s`. The category itself is specified by EUROCONTROL. I/O is hex text." % sha)
    a("Needs engine version 0.8 (`layout sequential`).")
    a("")
    a("Uses the modules `core`%s and `%s` (`model/%s.def`, generated with the pack)." % (
        "".join(", `%s`" % m for m in cat.uses), cat.module, cat.module))
    if cat.num in RENAME:
        a("")
        a("The pack and its module carry these names because the library also holds the hand-written pack")
        a("`asterix-cat%s` with the module `cat%s`. Section \"Beside the hand-written pack\" compares the two." % (cat.nnn, cat.nnn))
    a("")
    a("## Layout")
    a("")
    a("`layout sequential`, `bit_order msb`. One kind, `record`.")
    a("")
    a("| Part | Lines | Meaning |")
    a("|---|---|---|")
    a("| CAT, one octet | `when 8 %d` | selects the kind; another category is `no-kind` |" % cat.num)
    a("| LEN, two octets | `length 16 whole` | the block length in octets, CAT and LEN included; written on encode, and on decode input beyond it is not read |")
    a("| FSPEC | `presence f fx` | bit n is FRN n of the UAP |")
    a("| items | one `if f.<frn>` block per mapped FRN, in FRN order | below |")
    a("")
    a("A data block that holds more than one record: the first record is read and the rest of the block is not.")
    if cat.uap_note:
        a("")
        a(cat.uap_note)
    a("")
    a("How each item type of the definition is written:")
    a("")
    a("| Item type | Lines |")
    a("|---|---|")
    a("| fixed | one `field` per subitem, `pad` for spare bits |")
    a("| extended | `chain`: the fields of a part, then `fx` for its extension bit |")
    a("| repetitive with a count octet | `group <list> count 8`, the body being one repetition |")
    a("| repetitive with an extension bit per repetition | `group <list> fx` |")
    a("| compound | `presence <name> fx` for the primary subfield, then one `if <name>.<n>` block per subfield |")
    a("| explicit (SP, RE) | `length 8 bytes plus 1` with an empty block: the length octet counts itself, so the block is the stated length less one. The content is not mapped |")
    a("")
    a("How each content type is written:")
    a("")
    a("| Content | Transform | Key type |")
    a("|---|---|---|")
    a("| raw bits, a table of values (enumeration), a Mode S BDS register | `uint` | int |")
    a("| integer | `uint`, or `twos` when signed | int |")
    a("| quantity with an LSB and a unit | `uscale:<LSB>`, or `sscale:<LSB>` when signed, the LSB as an exact fraction | float, in the unit of the definition |")
    a("| ASCII string | `ascii` | string |")
    a("| string of 6-bit ICAO characters, octal digits | `uint` | int: the raw bits |")
    a("| content that depends on another subitem | `uint` | int: the raw bits |")
    a("")
    a("## Items")
    a("")
    a("| | Count |")
    a("|---|---|")
    a("| FRNs in the UAP | %d |" % len(cat.entries))
    for kind in ("fixed", "extended", "repetitive", "compound", "explicit"):
        n = sum(1 for e in cat.entries if e["nodes"] and e["kind"] == kind)
        if n:
            a("| mapped, %s | %d |" % (kind, n))
    a("| not mapped | %d |" % sum(1 for e in cat.entries if e["nodes"] is None))
    a("| keys of `%s` | %d |" % (cat.module, len(cat.keys)))
    a("| lists of `%s` | %d |" % (cat.module, len(cat.lists)))
    a("| `field` lines | %d |" % stats["fields"])
    a("")
    a("| FRN | Item | Title | Type | Written as |")
    a("|---|---|---|---|---|")
    for e in cat.entries:
        if e["nodes"]:
            a("| %d | I%s/%s | %s | %s | %s |" % (e["frn"], cat.nnn, e["name"], e["title"], e["kind"], mapped_as(e)))
    a("")
    ex = next((i, k) for i, k in sorted(cat.names.items()) if "/" in i and not i.endswith(("[]", "#")))
    a("A key is named after its item and subitems: `%s.%s` is I%s/%s. The meaning of" % (cat.module, ex[1], cat.nnn, ex[0]))
    a("every key, with its table of values or its LSB and unit, is in `model/%s.def`." % cat.module)
    a("")
    a("## Items not mapped")
    a("")
    unm = [e for e in cat.entries if e["nodes"] is None]
    if unm:
        a("No `if` block names these FSPEC bits. A record with one of them set fails to decode with")
        a("`malformed-wire`, and encode never sets them.")
        a("")
        a("| FRN | Item | Reason |")
        a("|---|---|---|")
        for e in unm:
            a("| %d | %s | %s |" % (e["frn"], "I%s/%s %s" % (cat.nnn, e["name"], e["title"]) if e["name"] else "-", e["reason"]))
    else:
        a("Every FRN of the UAP has an `if` block.")
    expl = [e for e in cat.entries if e["nodes"] and e["kind"] == "explicit"]
    if expl:
        a("")
        a("Mapped without content: %s. Decode reads the length octet and passes over the content; no key holds it," %
          ", ".join("FRN %d (%s, %s)" % (e["frn"], e["name"], e["title"]) for e in expl))
        a("so encode never writes the item, and a same-format round trip of a record that holds one returns the")
        a("record without it.")
    notin = [n for n in cat.catalogue if n not in [e["name"] for e in cat.entries]]
    if notin:
        a("")
        a("Items of the catalogue that the UAP read here does not name, and that the pack therefore does not hold: %s." %
          ", ".join("I%s/%s" % (cat.nnn, n) for n in notin))
    a("")
    a("## Shared-model keys")
    a("")
    binds = [b for b in cat.bindings]
    if binds:
        a("A shared key is bound only where the text of the definition and the unit leave no doubt, and only on an")
        a("item that stands directly in the UAP. The text quoted is the definition's.")
        a("")
        a("| Shared key | Bits | How | Text of the definition |")
        a("|---|---|---|---|")
        for b in binds:
            if b["how"] == "day_seconds":
                a("| `%s` (the module's own key) | I%s/%s | `derive %s day_seconds time_ms` in the module: on a conversion from another format the time of day follows from `time_ms` | %s |"
                  % (b["key"], cat.nnn, b["ident"], b["key"], b["evidence"]))
            elif b["how"] == "derive":
                a("| `lat`, `lon` | I%s/%s | not bound on the wire; `derive lat copy %s` and `derive lon copy %s` in the module fill the shared keys from the raw keys when the bound item is absent | %s |"
                  % (cat.nnn, b["ident"], b["raws"][0], b["raws"][1], b["evidence"]))
            elif b["raw"]:
                a("| `%s` | I%s/%s | `field %s … %s`, then `also %s`: same unit, both keys hold the value | %s |"
                  % (b["key"], cat.nnn, b["ident"], b["key"], b["tr"], b["raw"], b["evidence"]))
            else:
                a("| `%s` | I%s/%s | `field %s … %s`: %s; the field has no raw key | %s |"
                  % (b["key"], cat.nnn, b["ident"], b["key"], b["tr"], b["how"], b["evidence"]))
        a("")
        a("Where a field has a shared key and a raw key, the shared key is on the `field` line and the raw key on")
        a("the `also` line. Decode fills both. Encode writes the earliest key that is present (ruling 13 of 0.8), so")
        a("the shared key wins: a consumer that changes `lat` sees the change on the wire, and a change made only")
        a("to the raw key is not written (ruling 16 of 0.5 asks for this order).")
        a("")
        a("Where the unit of the definition is not the unit of the shared key, the conversion factor is part of")
        a("the scale (one foot is 381/1250 m, one NM/s is 1852 m/s, one knot is 1852/3600 m/s), the field holds")
        a("the shared key alone, and `model/%s.def` has no raw key for it: an `also` line shares the transform of" % cat.module)
        a("its field, so one field cannot hold feet in one key and metres in another.")
    else:
        a("None. No item of this category meets a rule of the generator: a position of the target in WGS-84")
        a("degrees, a height above the WGS-84 ellipsoid, a ground speed, a track angle from true north, a")
        a("Cartesian velocity with its axes stated, or a single item of absolute UTC time of day.")
    a("")
    a("Not bound, on purpose: a position, height or speed inside a compound or repetitive item (it describes")
    a("something other than the reported target's own state, or one of several); a flight level or barometric")
    a("altitude (`hae` is geometric); a heading, or a track angle whose reference the definition does not state")
    a("(`course` is degrees true); a Cartesian velocity or position in a local system whose axes the definition")
    a("does not state; a polar position relative to a sensor; a time item where the category has several.")
    a("")
    a("## Converting to this pack")
    a("")
    a("The kind has no `requires` line: the definition does not mark items as mandatory, so encode writes the")
    a("items whose keys the entity holds. A field of a written item whose key is absent is written as zero.")
    a("Keys of `%s` that another format does not carry (SAC and SIC, for example) are given as context." % cat.module)
    if cat.num in RENAME:
        a("")
        a("## Beside the hand-written pack")
        a("")
        a("| | `asterix-cat062` (hand-written) | `%s` (generated) |" % cat.format)
        a("|---|---|---|")
        a("| written from | the EUROCONTROL document, edition 1.21 | the transcription of edition %s in `%s` |" % (cat.edition, REPO))
        a("| FRNs mapped | 7: I062/010, 070, 105, 185, 040, 080, 130 | %d of %d; a record with any item of the UAP decodes |" % (
            sum(1 for e in cat.entries if e["nodes"]), sum(1 for e in cat.entries if e["name"])))
        a("| module | `cat062`: 9 keys named by meaning (`sac`, `time_of_day_s`, `track_number`, `mon`, `cnf`, `sim`, `tse`, `cst`) | `%s`: %d keys and %d lists named by item (`i010_sac`, `i070`, `i040`, `i080_mon`) |" % (cat.module, len(cat.keys), len(cat.lists)))
        a("| I062/105, 185, 130 | `lat`, `lon`, `track.vel_east_ms`, `track.vel_north_ms`, `hae` | the same shared keys with the same scales; `lat`, `lon` and the velocities also have raw keys |")
        a("| I062/080 Track Status | MON, CNF, SIM, TSE, CST mapped; CNF, SIM, TSE, CST also bound to the `track` flags (`confirmed` through a table that turns CNF over); the other bits are `pad` | every bit has a raw key; no `track` flag is bound, because a generator rule cannot tell from the table text which bit means what a flag means |")
        a("| defaults | MON 1, SIM, TSE, CST 0: the status item always has its first part and three extents | none: a key that is absent is not written, and an extent is written only when a key of it or of a later one is present |")
        a("| `requires` | SAC, SIC, time of day, track number, `track.confirmed`: an entity without them is `no-kind` | none |")
        a("| derived keys | time of day from `time_ms`, track number from `uid`, SIM from three `track` flags | time of day from `time_ms` |")
        a("| an item the pack does not map | 28 FRNs: `malformed-wire` | the spare FRNs only; RE and SP are read over |")
        a("")
        a("Both packs select CAT 62. A record that holds only the seven items of the hand-written pack decodes in")
        a("both to the same `lat`, `lon`, `hae` and velocity. The hand-written pack is the one to convert a track")
        a("into: it writes the mandatory items and the status flags. The generated pack is the one to read a")
        a("record of an operational system with: it holds every item.")
    a("")
    a("## Vectors")
    a("")
    a("Input and expected bytes are computed by the generator from the definition, with a codec of its own;")
    a("the generator then reloads the pack and replays every vector through a second codec written from")
    a("`spec/engine-spec.md`.")
    a("")
    a("| File | Shows |")
    a("|---|---|")
    for fn, what in made:
        a("| `%s` | %s |" % (fn, what))
    if track_vec:
        a("| `packs/canonical-track-v2/vectors/%s.json` | from `canonical-track-v2` to this pack: %s |" % (track_vec["name"], track_vec["reference"]))
    a("")
    return "\n".join(A)


def emit_pack_provenance(cat, sha, master, src_path):
    return "\n".join([
        "# Provenance: %s" % cat.format, "",
        "| Fact | Value |", "|---|---|",
        "| category | ASTERIX Category %s, %s |" % (cat.nnn, cat.title),
        "| edition | %s, dated %s in the definition |" % (cat.edition, cat.date),
        "| specified by | EUROCONTROL (https://www.eurocontrol.int/asterix) |",
        "| definition read | `%s` of https://github.com/%s |" % (cat.rel, REPO),
        "| commit (branch `gh-pages`, the published JSON) | `%s` |" % sha,
        "| built from commit (branch `master`) | `%s` |" % master,
        "| SHA-256 of the definition | `%s` |" % sha256_file(src_path),
        "| licence of the repository | BSD 3-Clause, copyright (c) 2019 KZPS (`LICENSE` at the `master` commit; verbatim in `sources/PROVENANCE.md`) |",
        "| generator | `tools/gen/asterix2pack.py`; key names pinned in `tools/gen/names/%s.json` |" % cat.format,
        ""])


# ---------------------------------------------------------------- one category

def generate(cat, out, sha, master, core_track):
    names_path = os.path.join(out, "tools", "gen", "names", cat.format + ".json")
    if os.path.exists(names_path):
        cat.pinned = json.load(open(names_path, encoding="utf-8"))
    build(cat)
    if not any(e["nodes"] and e["kind"] != "explicit" for e in cat.entries):
        die("no item of the UAP can be mapped")
    mod_text = emit_module(cat, sha)
    pack_text = emit_pack(cat, sha)
    # independent reload
    modules = dict(core_track)
    m = parse_module(mod_text)
    if m["name"] != cat.module:
        die("module name")
    modules[cat.module] = m
    check_module(m, modules)
    pack = parse_pack(pack_text, modules)
    fields = sum(1 for e in cat.entries if e["nodes"] for _ in walk_fields(e["nodes"]))
    declared = set(m["keys"])
    mapped_keys = {n["raw"].split(".", 1)[1] for e in cat.entries if e["nodes"] for n, _ in walk_fields(e["nodes"]) if n["declare"]}
    if declared != mapped_keys:
        die("module keys and mapped keys differ: %s" % sorted(declared ^ mapped_keys)[:5])
    made, track_vec = write_vectors(cat, out, pack, modules)
    pdir = os.path.join(out, "packs", cat.format)
    write(os.path.join(out, "model", cat.module + ".def"), mod_text)
    write(os.path.join(pdir, "pack.def"), pack_text)
    write(os.path.join(pdir, "pack.md"), emit_pack_md(cat, sha, master, made, track_vec, dict(fields=fields)))
    write(os.path.join(pdir, "PROVENANCE.md"), emit_pack_provenance(cat, sha, master, os.path.join(src_dir_of(out), cat.src_name)))
    names = dict(cat.pinned)
    names.update(cat.names)
    write(names_path, json.dumps(OrderedDict(sorted(names.items())), indent=1))
    tdir = os.path.join(out, "packs", "canonical-track-v2", "vectors")
    tpath = os.path.join(tdir, "gen-to-%s.json" % cat.format)
    if track_vec:
        write(tpath, json.dumps(track_vec, indent=2, ensure_ascii=False))
    elif os.path.exists(tpath):
        os.remove(tpath)
    return dict(made=made, track=bool(track_vec), fields=fields)


def remove_outputs(cat, out):
    pdir = os.path.join(out, "packs", cat.format)
    for p in glob.glob(os.path.join(pdir, "vectors", "*.json")) + [os.path.join(pdir, f) for f in ("pack.def", "pack.md", "PROVENANCE.md")] + \
            [os.path.join(out, "model", cat.module + ".def"),
             os.path.join(out, "packs", "canonical-track-v2", "vectors", "gen-to-%s.json" % cat.format)]:
        if os.path.exists(p):
            os.remove(p)
    for d in (os.path.join(pdir, "vectors"), pdir):
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)


def self_check(out, cats, core_track):
    """Re-read every output from disk and replay every vector."""
    modules = dict(core_track)
    packs = {}
    for cat in cats:
        m = parse_module(open(os.path.join(out, "model", cat.module + ".def"), encoding="utf-8").read())
        if m["name"] in modules:
            die("duplicate-module: %s" % m["name"])
        modules[m["name"]] = m
        check_module(m, modules)
    for cat in cats:
        text = open(os.path.join(out, "packs", cat.format, "pack.def"), encoding="utf-8").read()
        for needle in (os.path.abspath(out), os.path.expanduser("~")):
            for path in glob.glob(os.path.join(out, "packs", cat.format, "**", "*"), recursive=True) + \
                    [os.path.join(out, "model", cat.module + ".def")]:
                if os.path.isfile(path) and needle in open(path, encoding="utf-8").read():
                    die("%s holds a local path" % path)
        p = parse_pack(text, modules)
        if p["format"] != cat.format:
            die("format name of %s" % cat.format)
        packs[cat.format] = p
    n = 0
    for cat in cats:
        seen = set()
        files = sorted(glob.glob(os.path.join(out, "packs", cat.format, "vectors", "*.json")))
        tv = os.path.join(out, "packs", "canonical-track-v2", "vectors", "gen-to-%s.json" % cat.format)
        for path in files + ([tv] if os.path.exists(tv) else []):
            v = json.load(open(path, encoding="utf-8"))
            if path != tv:
                if v["name"] in seen or v["from"] != cat.format:
                    die("%s: vector name or owner" % path)
                seen.add(v["name"])
            replay(v, packs, modules)
            n += 1
    return n


def lib_tables(lib):
    """core and track as modules; checked against the checkout when one is given."""
    core = dict(name="core", distribution="public", sources=["built in"], keys=OrderedDict(CORE_KEYS),
                lists=OrderedDict(), derives=[], uses=[])
    track = dict(name="track", distribution="public", sources=["built in"], keys=OrderedDict(TRACK_KEYS),
                 lists=OrderedDict([("identifiers", True)]), derives=list(TRACK_DERIVES), uses=[])
    if lib:
        c = parse_module(open(os.path.join(lib, "model", "core.def"), encoding="utf-8").read())
        t = parse_module(open(os.path.join(lib, "model", "track.def"), encoding="utf-8").read())
        if dict(c["keys"]) != dict(CORE_KEYS):
            die("model/core.def of --lib differs from the built-in table")
        if dict(t["keys"]) != dict(TRACK_KEYS) or [(a, b, list(x)) for a, b, x in t["derives"]] != TRACK_DERIVES:
            die("model/track.def of --lib differs from the built-in table")
        gj = [tokenize(l) for l in open(os.path.join(lib, "packs", "geojson", "pack.def"), encoding="utf-8")]
        if [(a[1], a[2]) for a in gj if a and a[0] == "field"] != GEOJSON_FIELDS:
            die("packs/geojson/pack.def of --lib differs from the built-in table")
        tj = [tokenize(l) for l in open(os.path.join(lib, "packs", "canonical-track-v2", "pack.def"), encoding="utf-8")]
        have = {(a[1], a[2], a[3]) for a in tj if a and a[0] == "field" and len(a) == 4}
        if not set(TRACK_JSON_FIELDS) <= have:
            die("packs/canonical-track-v2/pack.def of --lib differs from the built-in table")
    return {"core": core, "track": track}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output root (holds sources/, model/, packs/, tools/gen/names/)")
    ap.add_argument("--commit", help="gh-pages commit of %s; writes sources/PROVENANCE.md" % REPO)
    ap.add_argument("--fetch", action="store_true", help="download the sources again even when present")
    ap.add_argument("--cats", default="all", help="comma-separated category numbers, or `all` (default)")
    ap.add_argument("--lib", help="goat-transformers checkout, to check the built-in tables")
    a = ap.parse_args()
    out = a.out
    try:
        if a.commit:
            if not re.fullmatch(r"[0-9a-f]{40}", a.commit):
                die("--commit takes a full 40-digit SHA")
            got, master = fetch_sources(out, a.commit, a.fetch)
            write_provenance(out, a.commit, got, master)
            sha = a.commit
        else:
            sha, master = read_commit(out)
        sd = src_dir_of(out)
        manifest = json.load(open(os.path.join(sd, "manifest.json"), encoding="utf-8"))
        avail = OrderedDict()
        for e in manifest:
            ed = max(e["cats"], key=edition_key)
            avail[int(e["category"])] = ("cat%s-%s.json" % (e["category"], ed),
                                         "specs/cat%s/cats/cat%s/definition.json" % (e["category"], ed))
        want = sorted(avail) if a.cats == "all" else [int(x) for x in a.cats.split(",")]
        order = [c for c in PRIORITY if c in want] + [c for c in want if c not in PRIORITY]
        core_track = lib_tables(a.lib)
        done, failed = [], []
        for n in order:
            if n not in avail:
                failed.append((n, "the source holds no category %03d" % n))
                continue
            name, rel = avail[n]
            cat = Cat(json.load(open(os.path.join(sd, name), encoding="utf-8")), name, rel)
            try:
                st = generate(cat, out, sha, master, core_track)
                done.append((cat, st))
            except (GenError, WireError) as x:
                remove_outputs(cat, out)
                failed.append((n, str(x)))
        n_vec = self_check(out, [c for c, _ in done], core_track)
    except GenError as x:
        print("asterix2pack: " + str(x), file=sys.stderr)
        return 1
    for cat, st in done:
        unm = [e for e in cat.entries if e["nodes"] is None]
        print("%s  edition %s  FRNs %d  mapped %d (%s)  not mapped %d  keys %d  lists %d  fields %d  vectors %d%s  shared: %s" % (
            cat.format, cat.edition, len(cat.entries), sum(1 for e in cat.entries if e["nodes"]),
            ", ".join("%s %d" % (k, sum(1 for e in cat.entries if e["nodes"] and e["kind"] == k))
                      for k in ("fixed", "extended", "repetitive", "compound", "explicit")
                      if any(e["nodes"] and e["kind"] == k for e in cat.entries)),
            len(unm), len(cat.keys), len(cat.lists), st["fields"], len(st["made"]), "+1 from track" if st["track"] else "",
            ", ".join(b["key"] for b in cat.bindings) or "none"))
        for e in unm:
            if e["kind"] not in ("spare",):
                print("    not mapped: FRN %d %s: %s" % (e["frn"], e["name"] or "", e["reason"]))
    for n, why in failed:
        print("cat%03d  NOT GENERATED: %s" % (n, why))
    print("self-check: %d vectors replayed, %d packs" % (n_vec, len(done)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
