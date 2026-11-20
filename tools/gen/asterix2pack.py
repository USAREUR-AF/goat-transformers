#!/usr/bin/env python3
"""asterix2pack: turn ASTERIX category definitions into goat-transformers packs.

Reads, under --out:
  sources/asterix-specs/manifest.json           the categories and their editions
  sources/asterix-specs/cat<NNN>-<edition>.json the JSON form of the category definitions of
                                                zoranbosnjak/asterix-specs (BSD-3-Clause) at a
                                                pinned commit; the newest edition of each category
  sources/PROVENANCE.md                         the two commits, when --commit is not given
  tools/gen/names/asterix-cat<NNN>.json         item path -> key name of an earlier run

Writes, under --out:
  sources/PROVENANCE.md                         (only with --commit)
  model/cat<NNN>.def                            raw keys and lists of the category
  packs/asterix-cat<NNN>/pack.def               wire bits, layout sequential, bit_order msb
  packs/asterix-cat<NNN>/pack.md                what is mapped, what is not, and why
  packs/asterix-cat<NNN>/PROVENANCE.md
  packs/asterix-cat<NNN>/vectors/*.json
  packs/canonical-track-v2/vectors/gen-to-asterix-cat<NNN>.json   (position-bearing categories)
  tools/gen/names/asterix-cat<NNN>.json         read and rewritten, sorted

Category 062 is written as the pack `asterix-cat062-full` with the module `cat062full`, because
the library holds a hand-written pack `asterix-cat062` and module `cat062`.

One record per data block; the first UAP of a category that has several, except the categories
of SWITCHED_UAPS, which hold every UAP behind a `switch` on the selecting item (engine-spec 0.20). Besides the newest
edition of each category, the editions in OTHER_EDITIONS are written as packs
asterix-cat<NNN>-ed<major><minor> with modules cat<NNN>ed<major><minor> (CAT021 0.23 and 0.26).

Guarantees:
  - The same input gives the same bytes. Every output is rewritten from the sources; a key keeps
    the name the names file pins; a vectors directory holds only the vectors of this run.
  - Every module and pack is loaded back through gtcheck (the load rules of spec/engine-spec.md)
    and checked to have the shape this generator writes. Every vector is replayed through a
    sequential codec written from spec/engine-spec.md (Versions 0.8 and 0.20) that reads the loaded pack.
  - A category that fails a check is reported with its definition file and the reason, and
    leaves no files; the other categories are still written.
  - The network is reached only with --fetch.

Exit status: 0 when every category asked for was written and every check passed (with --check:
and no file differs); 1 when an input was refused or a check failed; 2 for a usage error.

Usage:
  asterix2pack.py --out <dir> [--check] [--commit <sha> [--fetch]] [--cats 048,062,...|all]
                  [--lib <goat-transformers checkout>]

--check         writes nothing; reports every file under --out that differs from what the
                generator writes, is missing, or would be removed.
--commit <sha>  commit of the gh-pages branch of zoranbosnjak/asterix-specs (the published JSON);
                recorded in sources/PROVENANCE.md with the size and SHA-256 of every source file.
                Without --commit the commit is read back from sources/PROVENANCE.md.
--fetch         with --commit: download every source file from raw.githubusercontent.com at that
                commit with curl, then generate. Without --fetch a missing source file is an error.
--lib <dir>     checks the built-in tables of `core`, `track`, `geojson` and
                `canonical-track-v2` against the files of that checkout.

Python 3 standard library only.
"""
import argparse
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # under `python3 -I` the script directory is not on the path
import genio            # noqa: E402
import gtcheck          # noqa: E402

NAME = "asterix2pack"
REPO = "zoranbosnjak/asterix-specs"
PACK_VERSION = "0.1.0"
MODULE_VERSION = "0.1.0"
PRIORITY = [48, 62, 21, 34, 10]
# the library holds a hand-written pack and module of these names
RENAME = {62: ("asterix-cat062-full", "cat062full")}
# Editions written beside the newest one, as packs asterix-cat<NNN>-ed<major><minor>, because
# they are in operational use and their records differ in layout from the newest edition's.
# CAT021 0.23 and 0.26 (ADS-B ground stations of the DO-260 era): a different UAP from 2.x,
# and I021/130 of 24-bit angles in 0.23 against 32-bit in 0.26. A data block does not state
# its edition, so a reader chooses the pack by configuration.
OTHER_EDITIONS = {21: ["0.23", "0.26"]}
# Categories whose definition holds several UAPs, one chosen by the value of an item, that are
# written with all their UAPs: the items up to the selecting item as common lines, then a
# `switch` on the selecting key (engine-spec 0.20) with one `case` per further UAP and the first
# UAP under `else`, so a record without the selecting item reads the first UAP. Any other such
# category keeps its first UAP only (CAT007 qualifies; it is not switched yet, so that its pack
# stays as reviewed).
SWITCHED_UAPS = (1,)


def edition_tag(ed):
    """`ed` and the edition's digits, the minor number in two: 0.23 -> ed023, 1.2 -> ed102."""
    major, minor = ed.split(".")
    return "ed%s%s" % (major, minor.rjust(2, "0"))

# model/core.def and model/track.def of goat-transformers: the keys, lists and derive lines the
# generator needs to load its packs and to work out the cross-format vectors. --lib checks these
# tables against a checkout, and so does the test that reads the repository.
CORE_KEYS = OrderedDict([
    ("uid", "string"), ("type", "string"), ("time_ms", "int"),
    ("time_error_ms", "float"), ("time_state", "string"), ("lat", "float"),
    ("lon", "float"), ("hae", "float"), ("ce", "float"), ("le", "float"),
    ("callsign", "string"), ("course", "float"), ("speed_ms", "float"), ("how", "string"),
    ("stale_ms", "int"), ("time_text", "string"), ("stale_text", "string"),
    ("access", "string"), ("display_name", "string"),
])
TRACK_KEYS = OrderedDict([
    ("source_id", "string"), ("generation", "string"), ("scoped_id", "string"), ("vel_east_ms", "float"),
    ("vel_north_ms", "float"), ("vel_up_ms", "float"), ("class", "string"),
    ("confidence", "float"), ("sigma_east_m", "float"), ("sigma_north_m", "float"),
    ("sigma_up_m", "float"), ("confirmed", "int"), ("coasting", "int"), ("simulated", "int"),
    ("header_simulated", "int"), ("test_data", "int"), ("final_update", "int"),
    ("simulated_any", "int"), ("tentative", "int"), ("status_text", "string"), ("opex", "string"),
    ("id_scheme", "string"), ("id_value", "string"),
])
TRACK_LISTS = ("identifiers",)
TRACK_DERIVES = [
    ("course", "bearing", ["track.vel_east_ms", "track.vel_north_ms"]),
    ("speed_ms", "hypot", ["track.vel_east_ms", "track.vel_north_ms"]),
    ("ce", "hypot", ["track.sigma_east_m", "track.sigma_north_m"]),
    ("le", "copy", ["track.sigma_up_m"]),
    ("track.vel_east_ms", "east_of", ["speed_ms", "course"]),
    ("track.vel_north_ms", "north_of", ["speed_ms", "course"]),
    ("track.simulated_any", "any", ["track.simulated", "track.header_simulated", "track.test_data"]),
    ("track.tentative", "not", ["track.confirmed"]),
    ("track.status_text", "tokens:comma:test-data,simulated,tentative,coasting,final-update",
     ["track.test_data", "track.simulated_any", "track.tentative", "track.coasting", "track.final_update"]),
    ("track.opex", "text_if:s", ["track.simulated_any"]),
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
    """An input the generator refuses, or a check of its own output that failed. `file` is the
    source or output file the error belongs to and `line` a 1-based line of it, where one exists;
    `str()` is `<file>:<line>: <what>` with the parts that are known."""

    def __init__(self, message, file=None, line=None):
        Exception.__init__(self, message, file, line)
        self.message, self.file, self.line = message, file, line

    def __str__(self):
        where = "" if self.file is None else self.file + (":%d" % self.line if self.line is not None else "") + ": "
        return where + self.message


class Unmappable(Exception):
    """A UAP item the pack language cannot describe; the item is left without an `if` block."""


class WireError(Exception):
    """A decode or encode failure of the codec; `kind` is the error kind of the specification."""

    def __init__(self, kind, msg=""):
        Exception.__init__(self, "%s: %s" % (kind, msg))
        self.kind = kind


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
    """Round to the nearest integer, a half away from zero (engine-spec 0.5 "bits: more transforms")."""
    f = math.floor(abs(q) + 0.5)
    return int(-f if q < 0 else f)


def frac_text(fr):
    """A Fraction as a pack writes a scale: `<num>` or `<num>/<den>` (ruling 1 of 0.5)."""
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


def read_bytes(root, rel):
    """The bytes of an input file under the output root."""
    try:
        with open(os.path.join(root, *rel.split("/")), "rb") as fh:
            return fh.read()
    except OSError as x:
        raise GenError("cannot be read (%s)" % (x.strerror or x), file=rel)


def ending_in_newline(text):
    """Every output file ends with one line end."""
    return text if text.endswith("\n") else text + "\n"


def edition_key(text):
    """An edition `<major>.<minor>` as a tuple of numbers, so that 1.10 is newer than 1.9."""
    return tuple(int(x) for x in text.split("."))


# ---------------------------------------------------------------- sources

SOURCES_DIR = "sources/asterix-specs"           # under --out
SOURCES_PROVENANCE = "sources/PROVENANCE.md"
RAW_URL = "https://raw.githubusercontent.com/%s/%s/%s"


def read_text(root, rel):
    """The text of an input file under the output root; a missing file is a GenError naming it."""
    try:
        with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
            return fh.read()
    except OSError as x:
        raise GenError("cannot be read (%s)" % (x.strerror or x), file=rel)


def read_json(root, rel):
    """A JSON input file; text that is not JSON is a GenError with the file and the line."""
    try:
        return json.loads(read_text(root, rel))
    except json.JSONDecodeError as x:
        raise GenError("not JSON: %s" % x.msg, file=rel, line=x.lineno)


def definition_files(manifest):
    """[(category number, local file name, repository path)] in manifest order: for each
    category the newest edition the manifest lists, editions compared as numbers."""
    out = []
    try:
        for e in manifest:
            ed = max(e["cats"], key=edition_key)
            out.append((int(e["category"]), "cat%s-%s.json" % (e["category"], ed),
                        "specs/cat%s/cats/cat%s/definition.json" % (e["category"], ed)))
    except (KeyError, TypeError, ValueError) as x:
        raise GenError("not a manifest of categories and editions (%s: %s)" % (type(x).__name__, x),
                       file=SOURCES_DIR + "/manifest.json")
    return out


def other_edition_files(manifest):
    """{category number: [(local file name, repository path)]} of OTHER_EDITIONS; an edition the
    manifest does not list is a GenError."""
    out = {}
    try:
        listed = {int(e["category"]): (e["category"], e["cats"]) for e in manifest}
    except (KeyError, TypeError, ValueError) as x:
        raise GenError("not a manifest of categories and editions (%s: %s)" % (type(x).__name__, x),
                       file=SOURCES_DIR + "/manifest.json")
    for n, eds in sorted(OTHER_EDITIONS.items()):
        if n not in listed:
            continue
        cc, cats = listed[n]
        for ed in eds:
            if ed not in cats:
                raise GenError("lists no edition %s of category %s" % (ed, cc), file=SOURCES_DIR + "/manifest.json")
            out.setdefault(n, []).append(("cat%s-%s.json" % (cc, ed), "specs/cat%s/cats/cat%s/definition.json" % (cc, ed)))
    return out


def curl(url, dest):
    """Download one file. The only place the generator reaches the network."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        subprocess.run(["curl", "-fsSL", "-o", dest, url], check=True)
    except (OSError, subprocess.CalledProcessError) as x:
        raise GenError("download failed: %s" % x, file=url)


def master_commit(root):
    """The commit of the `master` branch that `gitrev.txt` states."""
    master = read_text(root, SOURCES_DIR + "/gitrev.txt").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", master):
        raise GenError("does not hold a commit: %r" % master, file=SOURCES_DIR + "/gitrev.txt")
    return master


def source_list(root, sha, download=None):
    """-> ([(local name, repository path, commit)], master commit): every file of the source
    directory with the place it comes from. With `download` (a function of URL and destination)
    each file is fetched first, in the order a later one needs an earlier one: `gitrev.txt` names
    the commit of `LICENSE`, and `manifest.json` names the definitions."""
    def get(name, rel, commit):
        path = os.path.join(root, *SOURCES_DIR.split("/"), name)
        if download:
            download(RAW_URL % (REPO, commit, rel), path)
        elif not os.path.isfile(path):
            raise GenError("is missing; --commit with --fetch downloads the sources", file=SOURCES_DIR + "/" + name)
        got.append((name, rel, commit))

    got = []
    get("manifest.json", "manifest.json", sha)
    get("gitrev.txt", "gitrev.txt", sha)
    master = master_commit(root)
    get("LICENSE", "LICENSE", master)
    manifest = read_json(root, SOURCES_DIR + "/manifest.json")
    others = other_edition_files(manifest)
    for n, name, rel in definition_files(manifest):
        get(name, rel, sha)
        for oname, orel in others.get(n, []):
            get(oname, orel, sha)
    return got, master


def emit_sources_provenance(root, sha, got, master):
    """The text of sources/PROVENANCE.md: both commits, every file with its size and SHA-256, and
    the license file verbatim."""
    lic = read_text(root, SOURCES_DIR + "/LICENSE")
    L = ["# Provenance of the inputs in `sources/asterix-specs/`", "",
         "| Fact | Value |", "|---|---|",
         "| repository | https://github.com/%s |" % REPO,
         "| what it is | \"EUROCONTROL asterix specifications in structured format\" (the repository's description): "
         "each category edition as a `.ast` source file, and built from it a JSON file of the same content |",
         "| commit of the published JSON (branch `gh-pages`): | `%s` |" % sha,
         "| commit of the sources the JSON was built from (branch `master`, stated by `gitrev.txt` at the commit above) | `%s` |" % master,
         "| licence | BSD 3-Clause, copyright (c) 2019 KZPS: the file `LICENSE` at the root of the `master` commit, verbatim below |",
         "| edition taken | for each category the newest edition `manifest.json` lists; also %s |" % "; ".join(
             "category %03d edition %s" % (c, ", ".join(eds)) for c, eds in sorted(OTHER_EDITIONS.items())),
         "", "## Files", "",
         "Every file is downloaded from `https://raw.githubusercontent.com/%s/<commit>/<repository path>`." % REPO, "",
         "| File | Repository path | Commit | Bytes | SHA-256 |", "|---|---|---|---|---|"]
    for name, rel, commit in got:
        data = read_bytes(root, SOURCES_DIR + "/" + name)
        L.append("| `%s` | `%s` | `%s` | %d | `%s` |" % (name, rel, commit[:12], len(data), hashlib.sha256(data).hexdigest()))
    L += ["", "## The licence file, verbatim", "", "```", lic.rstrip("\n"), "```", "",
          "## Sample blocks", "",
          "The vectors named `sample-*` take their input from the README of the Python library of",
          "https://github.com/%s (BSD-3-Clause), file `%s` at commit" % (SAMPLES_REPO, SAMPLES_PATH),
          "`%s`: blocks that README prints together with the values they hold." % SAMPLES_COMMIT, "",
          "## Other definition sets looked at", "",
          "| Repository | Licence GitHub reports | Used |", "|---|---|---|",
          "| https://github.com/CroatiaControlLtd/asterix (XML category definitions) | GPL-2.0 | no |",
          "| https://github.com/hpuhr/jASTERIX (JSON category definitions) | GPL-3.0 | no |", ""]
    return "\n".join(L)


def read_commits(text):
    """(commit of the published JSON, commit of its sources) as sources/PROVENANCE.md states them."""
    m = re.search(r"commit of the published JSON[^|]*\| `([0-9a-f]{40})`", text)
    m2 = re.search(r"commit of the sources the JSON was built from[^|]*\| `([0-9a-f]{40})`", text)
    if not m or not m2:
        raise GenError("does not state the two commits", file=SOURCES_PROVENANCE)
    return m.group(1), m2.group(1)


# ---------------------------------------------------------------- parse: definition JSON -> Cat
#
# The JSON form of asterix-specs, as far as the generator reads it. A tagged value is
# {"tag": <name>, "contents": <value>}.
#
#   category   AsterixBasic {category, edition {major, minor}, date {year, month, day}, title,
#              catalogue [item], uap}
#   uap        Uap [uap item] | Uaps {cases [[name, [uap item]]], selector {item [name]} | null}
#   uap item   UapItem <item name> | UapItemSpare | UapItemRFS
#   item       {name, title, rule, documentation {definition, remark}}
#   rule       ContextFree <x> | Dependent {path [[name]], default <x>, cases [[values, <x>]]}
#              where <x> is a variation (the rule of an item) or a content (the rule of an Element)
#   variation  Element {bitSize, rule} | Group [member] | Extended [member | null]
#              | Repetitive {type RepetitiveRegular {byteSize} | RepetitiveFx, variation}
#              | Compound [item | null] | Explicit
#   member     Item <item> | Spare <bits>; null in an Extended stands for the extension bit
#   content    ContentRaw | ContentTable [[value, text]] | ContentString {tag StringAscii |
#              StringICAO | StringOctal} | ContentInteger {signedness} | ContentQuantity
#              {signedness, lsb <number>, unit} | ContentBds {tag}
#   number     NumInt <int> | NumDiv {numerator <number>, denominator <number>} | NumPow {base, exponent}

def num(n):
    """A number of the definition as an exact Fraction."""
    t, c = n["tag"], n["contents"]
    if t == "NumInt":
        return Fraction(c)
    if t == "NumDiv":
        return num(c["numerator"]) / num(c["denominator"])
    if t == "NumPow":
        return Fraction(c["base"]) ** c["exponent"]
    raise GenError("unknown number tag %s" % t)


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
    """Bit size of the variation a rule gives: of a context-free rule its variation's, of a
    dependent rule the one size every case and the default share; None when they differ or the
    variation is not fixed."""
    if rule["tag"] == "ContextFree":
        return fixed_bits(rule["contents"])
    d = rule["contents"]
    sizes = {fixed_bits(d["default"])} | {fixed_bits(c[1]) for c in d["cases"]}
    return sizes.pop() if len(sizes) == 1 else None


def dependency_text(paths):
    """The item paths a dependent rule names, as text."""
    return " and ".join("/".join(p) for p in paths)


class Cat:
    """One category as its definition states it. Nothing here is decided by the generator but the
    pack and module names. `label` is the definition file as error messages name it."""

    def __init__(self, d, src_name, rel, other=False):
        self.src_name, self.rel = src_name, rel
        self.other = other              # an edition of OTHER_EDITIONS, not the newest
        self.label = SOURCES_DIR + "/" + src_name
        if not isinstance(d, dict) or d.get("tag") != "AsterixBasic":
            raise GenError("not a category definition (the tag is %s)"
                           % (d.get("tag") if isinstance(d, dict) else type(d).__name__), file=self.label)
        try:
            c = d["contents"]
            self.num = c["category"]
            self.nnn = "%03d" % self.num
            self.edition = "%d.%d" % (c["edition"]["major"], c["edition"]["minor"])
            self.date = "%04d-%02d-%02d" % (c["date"]["year"], c["date"]["month"], c["date"]["day"])
            self.title = fold(c["title"])
            self.catalogue = OrderedDict((it["name"], it) for it in c["catalogue"])
            self.uap, self.uap_note = self._first_uap(c["uap"])
            self.uaps, self.selector = self._all_uaps(c["uap"])
        except (KeyError, TypeError, IndexError) as x:
            raise GenError("the definition lacks a member the generator reads (%s: %s)" % (type(x).__name__, x),
                           file=self.label)
        self.format, self.module = RENAME.get(self.num, ("asterix-cat" + self.nnn, "cat" + self.nnn))
        if other:
            tag = edition_tag(self.edition)
            self.format, self.module = "asterix-cat%s-%s" % (self.nnn, tag), "cat%s%s" % (self.nnn, tag)

    def _first_uap(self, u):
        """(the UAP the pack holds, a note for pack.md when the category has several)."""
        if u["tag"] == "Uap":
            return u["contents"], None
        if u["tag"] != "Uaps":
            raise GenError("unknown uap tag %s" % u["tag"], file=self.label)
        cases = u["contents"]["cases"]
        sel = u["contents"]["selector"]
        note = ("The category has %d UAPs (%s)%s. The pack holds the first, `%s`; a record of "
                "another UAP is read wrongly or fails."
                % (len(cases), ", ".join("`%s`" % n for n, _ in cases),
                   ", selected by the value of item %s" % "/".join(sel["item"]) if sel else "",
                   cases[0][0]))
        return cases[0][1], note

    def _all_uaps(self, u):
        """([(UAP name, UAP items)], selector) of a category in SWITCHED_UAPS that has several UAPs
        chosen by an item; ([], None) for any other. The selector is dict(item=[path], cases=[(value,
        UAP name)])."""
        if self.num not in SWITCHED_UAPS or self.other or u["tag"] != "Uaps":
            return [], None
        sel = u["contents"]["selector"]
        if not sel:
            raise GenError("the category has several UAPs and no selecting item", file=self.label)
        cases = [(name, items) for name, items in u["contents"]["cases"]]
        return cases, dict(item=list(sel["item"]), cases=[(int(v), name) for v, name in sel["cases"]])


def load_category(root, src_name, rel, other=False):
    """Read one definition file of the source directory."""
    return Cat(read_json(root, SOURCES_DIR + "/" + src_name), src_name, rel, other)


# ---------------------------------------------------------------- plan: Cat -> what the pack holds
#
# The plan is a tree of nodes, one list per UAP item. A node is a dict whose `t` names its type:
#
#   field     one Element. ident (item path, the key of the names file), sub (path below the
#             item), key (the key on the `field` line), also (keys on `also` lines), raw (the
#             module's own key), declare (False when the field holds a shared key alone), bits,
#             tr (transform text), kind (transform name), frac (LSB as a Fraction, or None),
#             signed, vt (key type), unit, meaning, src_unit (the unit as the definition writes
#             it), title
#   pad       spare bits. bits
#   chain     an Extended item. parts (lists of field and pad nodes), trailing (True when the last
#             part ends with an extension bit)
#   group     a Repetitive item. list (the list key), mode (`count` or `fx`), cbits (bits of the
#             count), body (field and pad nodes), ident
#   compound  a Compound item. name (the presence name), subs ([(bit number, name, title, nodes)])
#   explicit  an Explicit item (RE, SP): a length octet and content the pack does not map

class Plan:
    """What the generator decided for one category: every FRN, key, list, derive line and shared
    key. `plan_category` fills it; the emit functions only read it."""

    def __init__(self, cat, pinned=None):
        self.cat = cat
        self.pinned = dict(pinned or {})    # item path -> key name, from the names file
        self.entries = []                   # one per FRN: dict(frn, name, title, kind, nodes, reason)
        self.keys = OrderedDict()           # name -> (type, unit, meaning)
        self.lists = OrderedDict()          # name -> meaning
        self.derives = []                   # (target, function, [arguments])
        self.bindings = []                  # dict(key, ident, how, evidence, ...): pack.md rows
        self.names = {}                     # item path -> key name, of this run
        self.uses = []                      # modules the pack uses beside `core` and its own
        # A category of SWITCHED_UAPS: `entries` are those of the first UAP (the `else` arm);
        # `arms` holds every UAP in the order of the definition as dict(name, values, default,
        # entries), and `sel` the selecting field as dict(frn, ident, key). Otherwise [] and None.
        self.arms = []
        self.sel = None

    def unique_entries(self):
        """Every entry once: those of `entries`, then the items only another UAP names."""
        out = list(self.entries)
        seen = {e["name"] for e in out if e["name"]}
        for arm in self.arms:
            for e in arm["entries"]:
                if e["name"] and e["name"] not in seen:
                    seen.add(e["name"])
                    out.append(e)
        return out

    def pack_entries(self):
        """The entries in the order the pack writes their lines: the common ones, then those of
        each arm after the selecting item."""
        if not self.sel:
            return list(self.entries)
        out = [e for e in self.entries if e["frn"] <= self.sel["frn"]]
        for arm in self.arms:
            out += [e for e in arm["entries"] if e["frn"] > self.sel["frn"]]
        return out

    def uap_of(self, rec):
        """The arm a raw record is written with: the one whose values hold the selecting field's
        value; the default arm when no arm lists it or the selecting item is absent."""
        if not self.sel:
            return None
        sel_entry = next(e for e in self.entries if e["frn"] == self.sel["frn"])
        default = next(a for a in self.arms if a["default"])
        if not raw_has(sel_entry["nodes"], rec):
            return default
        v = rec.get(self.sel["key"], 0)
        return next((a for a in self.arms if not a["default"] and v in a["values"]), default)

    def mapped(self):
        """The entries the pack has an `if` block for."""
        return [e for e in self.entries if e["nodes"]]

    def unmapped(self):
        """The entries with no `if` block: spare FRNs, RFS, and items that cannot be described."""
        return [e for e in self.entries if e["nodes"] is None]

    def field_count(self):
        """The number of `field` lines of the pack."""
        return sum(1 for e in self.pack_entries() if e["nodes"] for _ in walk_fields(e["nodes"]))

    def names_file(self):
        """The names to pin: those of earlier runs, overwritten by those of this run."""
        names = dict(self.pinned)
        names.update(self.names)
        return names


VARIATION_KIND = {"Element": "fixed", "Group": "fixed", "Extended": "extended", "Repetitive": "repetitive",
                  "Compound": "compound", "Explicit": "explicit"}


class Builder:
    """Turns the rules and variations of a definition into plan nodes, and names their keys."""

    def __init__(self, plan):
        self.plan = plan
        self.cat = plan.cat
        self.used = {}                      # key name -> the item path that has it

    def name_of(self, ident, parts):
        """The key name of an item path: the pinned name when the names file has one, otherwise
        the lowercase path joined with `_`, with `i` before a leading digit. Two paths never share
        a name: the second is refused."""
        plan = self.plan
        if ident in plan.pinned:
            name = plan.pinned[ident]
        else:
            head = parts[0].lower()
            name = "_".join((["i" + head] if head[:1].isdigit() else [head]) + [p.lower() for p in parts[1:]])
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise GenError("%s gives the key name %r" % (ident, name))
        if self.used.get(name, ident) != ident:
            raise GenError("key name %s for both %s and %s" % (name, self.used[name], ident))
        self.used[name] = ident
        plan.names[ident] = name
        return name

    def content(self, rule, bits, ident):
        """How the content of an Element is written -> dict(tr, vt, unit, note, frac, signed).
        Raw bits, tables, BDS registers, 6-bit and octal strings and dependent contents are `uint`;
        an integer is `uint` or `twos`; a quantity is `uscale` or `sscale` with its LSB as an exact
        fraction; an ASCII string is `ascii`."""
        r = dict(tr="uint", vt="int", unit="-", note="", frac=None, signed=False, icao=False)
        if rule["tag"] == "Dependent":
            r["note"] = "raw value; its content depends on the value of " + dependency_text(rule["contents"]["path"])
            return r
        ct = rule["contents"]
        t, c = ct["tag"], ct["contents"]
        if t == "ContentRaw":
            pass
        elif t == "ContentTable":
            r["note"] = ", ".join("%d = %s" % (v, fold(s)) for v, s in c)
        elif t == "ContentString":
            st = c["tag"]
            if st == "StringAscii":
                if bits % 8 or bits > 2040:
                    raise Unmappable("an ASCII string of %d bits" % bits)
                r["tr"], r["vt"] = "ascii", "string"
                r["note"] = "%d ASCII characters" % (bits // 8)
            elif st == "StringICAO":
                r["note"] = "raw value: %d characters of 6 bits each in the ICAO character set (ICAO Annex 10)" % (bits // 6)
                r["icao"] = True
            elif st == "StringOctal":
                r["note"] = "raw value: %d octal digits of 3 bits each" % (bits // 3)
            else:
                raise GenError("unknown string type %s" % st)
        elif t == "ContentInteger":
            r["signed"] = c["signedness"]["tag"] == "Signed"
            r["tr"] = "twos" if r["signed"] else "uint"
        elif t == "ContentQuantity":
            r["signed"] = c["signedness"]["tag"] == "Signed"
            frac = r["frac"] = num(c["lsb"])
            if frac <= 0:
                raise GenError("%s has the LSB %s; an LSB is above zero" % (ident, frac))
            r["tr"] = scale_text(r["signed"], frac)
            r["vt"] = "float"
            unit = r["unit"] = UNIT_TOKEN.get(c["unit"], c["unit"])
            if not re.fullmatch(r"[\x21-\x7e]+", unit):
                raise GenError("%s has the unit %r, which is not one token" % (ident, c["unit"]))
            r["note"] = "LSB %s %s" % (frac_text(frac), unit if unit != "-" else "")
        elif t == "ContentBds":
            r["note"] = "raw value: a Mode S BDS register" + (" with its address" if c["tag"] == "BdsWithAddress" else "")
        else:
            raise GenError("unknown content tag %s" % t)
        return r

    def meaning(self, path, titles, note):
        """The quoted meaning of a key in the module: item path, titles, then the note; 400
        characters at most."""
        label = "I%s/%s" % (self.cat.nnn, "/".join(path))
        title = fold("; ".join(t for t in titles[1:] if t)) if len(titles) > 1 else fold(titles[0])
        meaning = label + (": " + title if title else "")
        if len(titles) > 1 and titles[0]:
            meaning += " (" + fold(titles[0]) + ")"
        if note:
            meaning += ". " + note.strip()
        if len(meaning) > 400:
            meaning = meaning[:397] + "..."
        return meaning

    def leaf(self, path, titles, bits, rule, bare=False):
        """An Element -> a field node. `bare` marks the Element that is the whole repetition of a
        repetitive item: its key takes the suffix `_val`, the list has the item's name."""
        ident = "/".join(path) + ("/#" if bare else "")
        c = self.content(rule, bits, ident)
        if c["tr"] != "ascii" and not 1 <= bits <= 64:
            raise Unmappable("an element of %d bits (a field holds at most 64)" % bits)
        name = self.name_of(ident, path + (["val"] if bare else []))
        key = self.cat.module + "." + name
        quantity = rule["tag"] == "ContextFree" and rule["contents"]["tag"] == "ContentQuantity"
        return dict(t="field", ident=ident, sub=path[1:], key=key, also=[], bits=bits,
                    tr=c["tr"], kind=c["tr"].split(":")[0], frac=c["frac"], signed=c["signed"], vt=c["vt"],
                    unit=c["unit"], meaning=self.meaning(path, titles, c["note"]), raw=key, declare=True, icao=c["icao"],
                    src_unit=rule["contents"]["contents"]["unit"] if quantity else None,
                    title=titles[-1] or "")

    def item(self, it, path, titles):
        return self.rule(it["rule"], path + [it["name"]], titles + [it["title"]])

    def rule(self, rule, path, titles, bare=False):
        """The nodes of an item's rule. A dependent rule whose cases all have one size is written
        as its default structure; one whose cases differ in size cannot be described."""
        if rule["tag"] == "ContextFree":
            return self.variation(rule["contents"], path, titles, bare)
        d = rule["contents"]
        if rule_bits(rule) is None:
            raise Unmappable("a structure that depends on the value of %s, with cases of different sizes"
                             % dependency_text(d["path"]))
        nodes = self.variation(d["default"], path, titles, bare)
        for n in nodes:
            if n["t"] == "field":
                n["meaning"] += ". Raw value: the structure depends on the value of " + dependency_text(d["path"])
        return nodes

    def members(self, members, path, titles):
        """The nodes of Group members: a Spare is a pad, an Item its own nodes."""
        nodes = []
        for it in members:
            if it["tag"] == "Spare":
                nodes.append(dict(t="pad", bits=it["contents"]))
            else:
                nodes += self.item(it["contents"], path, titles)
        return nodes

    def extended(self, c, path, titles):
        """An Extended variation -> one chain node; a null member ends a part with its extension bit."""
        parts, cur = [], []
        for it in c:
            if it is None:
                parts.append(cur)
                cur = []
                continue
            sub = self.members([it], path, titles)
            if any(n["t"] not in ("field", "pad") for n in sub):
                raise Unmappable("an extended item that holds a part that is not fixed")
            cur += sub
        trailing = c[-1] is None
        if not trailing:
            parts.append(cur)
        return [dict(t="chain", parts=parts, trailing=trailing)]

    def repetitive(self, c, path, titles):
        """A Repetitive variation -> one group node and a list of the module."""
        ident = "/".join(path) + "[]"
        lname = self.name_of(ident, path)
        body = self.variation(c["variation"], path, titles, bare=c["variation"]["tag"] == "Element")
        if any(n["t"] not in ("field", "pad") for n in body):
            raise Unmappable("a repetitive item whose repeated part is not fixed")
        ty = c["type"]
        label = "I%s/%s" % (self.cat.nnn, "/".join(path))
        self.plan.lists[lname] = "%s: %s, one item per repetition" % (label, fold(titles[-1] or titles[0]))
        key = self.cat.module + "." + lname
        if ty["tag"] == "RepetitiveRegular":
            return [dict(t="group", list=key, mode="count", cbits=8 * ty["contents"]["byteSize"], body=body, ident=ident)]
        if ty["tag"] == "RepetitiveFx":
            return [dict(t="group", list=key, mode="fx", body=body, ident=ident)]
        raise GenError("unknown repetitive type %s" % ty["tag"])

    def compound(self, c, path, titles):
        """A Compound variation -> one compound node; subfield n has presence bit n, a null slot none."""
        subs = []
        for i, it in enumerate(c):
            if it is not None:
                subs.append((i + 1, it["name"], fold(it["title"]),
                             self.rule(it["rule"], path + [it["name"]], titles + [it["title"]])))
        return [dict(t="compound", name="p" + "".join(p.lower() for p in path), subs=subs)]

    def variation(self, v, path, titles, bare=False):
        t, c = v["tag"], v["contents"]
        if t == "Element":
            return [self.leaf(path, titles, c["bitSize"], c["rule"], bare)]
        if t == "Group":
            return self.members(c, path, titles)
        if t == "Extended":
            return self.extended(c, path, titles)
        if t == "Repetitive":
            return self.repetitive(c, path, titles)
        if t == "Compound":
            return self.compound(c, path, titles)
        if t == "Explicit":
            return [dict(t="explicit")]
        raise GenError("unknown variation tag %s" % t)


def scale_text(signed, frac):
    """The scale transform of a quantity: the LSB as an exact fraction, never a rounded decimal."""
    return ("sscale:" if signed else "uscale:") + frac_text(frac)


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


def stray_bits(nodes):
    """Bits by which a run of nodes misses a whole number of octets, or 0. An ASTERIX item is a
    whole number of octets, and so is each part of an extended item with its extension bit, each
    repetition (with its extension bit in the FX form) and each subfield of a compound item. The
    first run that is not is reported: (bits over, what)."""
    total = 0
    for n in nodes:
        t = n["t"]
        if t in ("field", "pad"):
            total += n["bits"]
        elif t == "chain":
            for i, part in enumerate(n["parts"]):
                has_fx = i < len(n["parts"]) - 1 or n["trailing"]
                size = sum(x["bits"] for x in part) + (1 if has_fx else 0)
                if size % 8:
                    return size, "part %d of the extended item, with its extension bit," % (i + 1)
        elif t == "group":
            size = sum(x["bits"] for x in n["body"]) + (1 if n["mode"] == "fx" else 0)
            if size % 8:
                return size, "one repetition" + (", with its extension bit," if n["mode"] == "fx" else "")
        elif t == "compound":
            for _, name, _, sub in n["subs"]:
                found = stray_bits(sub)
                if found:
                    return found[0], "subfield %s: %s" % (name, found[1])
    return (total, "the item") if total % 8 else None


def plan_entry(builder, frn, u):
    """One FRN of the UAP -> its entry. An item the pack language cannot describe keeps `nodes`
    None and the reason; the names and lists it had claimed are released."""
    plan, cat = builder.plan, builder.cat
    e = dict(frn=frn, name=None, title="", kind=None, nodes=None, reason=None)
    if u["tag"] == "UapItemSpare":
        e["kind"], e["reason"] = "spare", "spare FRN"
        return e
    if u["tag"] == "UapItemRFS":
        e["kind"], e["reason"] = "rfs", "random field sequencing: the items that follow name themselves by FRN, in any order"
        return e
    it = cat.catalogue.get(u["contents"])
    if it is None:
        raise GenError("the UAP names item %s, which the catalogue does not hold" % u["contents"], file=cat.label)
    try:
        e["name"], e["title"] = it["name"], fold(it["title"])
        rule = it["rule"]
        tag = rule["contents"]["tag"] if rule["tag"] == "ContextFree" else None
        if tag is not None and tag not in VARIATION_KIND:
            raise GenError("unknown variation tag %s" % tag)
        e["kind"] = VARIATION_KIND[tag] if tag else "fixed"
        saved = (dict(builder.used), dict(plan.names), OrderedDict(plan.lists))
        try:
            e["nodes"] = builder.rule(rule, [it["name"]], [it["title"]])
        except Unmappable as x:
            builder.used, plan.names, plan.lists = saved
            e["reason"] = str(x)
    except GenError as x:
        raise GenError("item %s: %s" % (it.get("name"), x.message), file=x.file or cat.label)
    except (KeyError, TypeError, IndexError) as x:
        raise GenError("item %s: the definition lacks a member the generator reads (%s: %s)"
                       % (it.get("name"), type(x).__name__, x), file=cat.label)
    if e["nodes"]:
        stray = stray_bits(e["nodes"])
        if stray:
            raise GenError("item %s: %s is %d bits, not a whole number of octets" % (e["name"], stray[1], stray[0]),
                           file=cat.label)
    return e


def plan_arms(plan, builder):
    """The entries of every UAP of a category of SWITCHED_UAPS. An item two UAPs name is planned
    once and its nodes shared, so it has one set of keys. Every UAP names the same items up to
    and including the selecting item, at the same FRNs; those are the common lines."""
    cat = plan.cat
    cache = {}
    for name, items in cat.uaps:
        entries = []
        for i, u in enumerate(items):
            key = u["contents"] if u["tag"] == "UapItem" else None
            if key in cache:
                e = dict(cache[key])
                e["frn"] = i + 1
            else:
                e = plan_entry(builder, i + 1, u)
                if key:
                    cache[key] = e
            entries.append(e)
        values = [v for v, n in cat.selector["cases"] if n == name]
        plan.arms.append(dict(name=name, values=values, default=not plan.arms, entries=entries))
    plan.entries = plan.arms[0]["entries"]
    item = cat.selector["item"]
    frns = {next((e["frn"] for e in a["entries"] if e["name"] == item[0]), None) for a in plan.arms}
    if len(frns) != 1 or None in frns:
        raise GenError("the selecting item %s does not stand at one FRN in every UAP" % item[0], file=cat.label)
    frn = frns.pop()
    if len({tuple(e["name"] for e in a["entries"][:frn]) for a in plan.arms}) != 1:
        raise GenError("the UAPs differ before the selecting item %s" % item[0], file=cat.label)
    entry = plan.entries[frn - 1]
    ident = "/".join(item)
    node = next((n for n, lst in walk_fields(entry["nodes"] or []) if n["ident"] == ident and lst is None), None)
    if node is None or node["kind"] != "uint":
        raise GenError("the selecting item %s is not a field of its own" % ident, file=cat.label)
    if any(not a["values"] for a in plan.arms[1:]):
        raise GenError("a UAP that no value of %s selects" % ident, file=cat.label)
    plan.sel = dict(frn=frn, ident=ident, key=node["key"])


def plan_category(cat, pinned=None):
    """Cat -> Plan: every decision the emit functions need. `pinned` is the names file of an
    earlier run (item path -> key name)."""
    plan = Plan(cat, pinned)
    builder = Builder(plan)
    if cat.selector:
        plan_arms(plan, builder)
    else:
        for i, u in enumerate(cat.uap):
            plan.entries.append(plan_entry(builder, i + 1, u))
    bind(plan)
    for e in plan.unique_entries():
        if not e["nodes"]:
            continue
        for n, _ in walk_fields(e["nodes"]):
            if n["declare"]:
                plan.keys[n["raw"].split(".", 1)[1]] = (n["vt"], n["unit"], n["meaning"])
    dup = set(plan.keys) & set(plan.lists)
    if dup:
        raise GenError("a key and a list share the name %s" % sorted(dup), file=cat.label)
    if not any(e["kind"] != "explicit" for e in plan.mapped()):
        raise GenError("no item of the UAP can be mapped", file=cat.label)
    return plan


# ---------------------------------------------------------------- plan: shared-model bindings

class Candidate:
    """A fixed item that stands directly in the UAP, with the text the binding rules read."""

    def __init__(self, cat, entry):
        it = cat.catalogue[entry["name"]]
        doc = it["documentation"]
        self.entry = entry
        self.nodes = entry["nodes"]
        self.title = fold(it["title"])
        self.definition, self.remark = fold(doc["definition"]), fold(doc["remark"])
        self.label = "I%s/%s" % (cat.nnn, entry["name"])
        self.fields = [n for n in self.nodes if n["t"] == "field"]
        self.by_sub = {"/".join(n["sub"]): n for n in self.fields}

    def single_field(self):
        """The field of an item that is one Element and nothing else, or None."""
        return self.fields[0] if len(self.fields) == 1 and len(self.nodes) == 1 else None


def position_of(c):
    """WGS-84 position of the reported target: subitems LAT and LON, signed degrees of one LSB,
    under a title that says so -> [(LSB, FRN, LAT field, LON field, evidence)], else []."""
    la, lo = c.by_sub.get("LAT"), c.by_sub.get("LON")
    if not (la and lo and len(c.fields) == 2 and la["src_unit"] == "°" and lo["src_unit"] == "°"
            and la["signed"] and lo["signed"] and la["frac"] == lo["frac"]
            and re.match(r"(calculated |high-resolution )?position in wgs-?84 co-?ordinates", c.title, re.I)
            and not re.search(r"message type", c.remark, re.I)):       # what the item holds depends on the message
        return []
    return [(la["frac"], c.entry["frn"], la, lo,
             '%s "%s", definition: "%s"; subitems LAT and LON in degrees, two\'s complement%s'
             % (c.label, c.title, c.definition,
                '; note: "%s"' % c.remark if re.search(r"positive", c.remark, re.I) else ""))]


def bind_height(plan, c):
    """Height above the WGS-84 ellipsoid, in feet or metres -> `hae` (metres)."""
    n = c.single_field()
    if (n and n["src_unit"] in ("ft", "m") and n["signed"]
            and re.search(r"geometric (height|altitude)", c.title, re.I)
            and re.search(r"ellipsoid", c.definition, re.I) and re.search(r"wgs-? ?84", c.definition, re.I)):
        mult = FT if n["src_unit"] == "ft" else Fraction(1)
        convert(plan, n, "hae", mult,
                '%s "%s", definition: "%s"; LSB %s %s%s' % (c.label, c.title, c.definition, frac_text(n["frac"]), n["src_unit"],
                                                           '; note: "%s"' % c.remark if c.remark else ""))


def bind_speed_and_course(plan, c):
    """Ground speed in m/s, kt or NM/s -> `speed_ms`; track angle from true north -> `course`."""
    for n in c.fields:
        if (n["src_unit"] in SPEED_TO_MS and not n["signed"]
                and re.search(r"ground ?speed", n["title"], re.I)):
            convert(plan, n, "speed_ms", SPEED_TO_MS[n["src_unit"]],
                    '%s "%s", subitem %s "%s"; LSB %s %s' % (c.label, c.title, "/".join(n["sub"]), fold(n["title"]),
                                                             frac_text(n["frac"]), n["src_unit"]))
        if (n["src_unit"] == "°" and not n["signed"] and re.search(r"track angle", n["title"], re.I)
                and re.search(r"true north", n["title"], re.I)):
            convert(plan, n, "course", Fraction(1),
                    '%s "%s", subitem %s "%s"; LSB %s degrees' % (c.label, c.title, "/".join(n["sub"]), fold(n["title"]),
                                                                  frac_text(n["frac"])))


def bind_velocity(plan, c):
    """Cartesian velocity VX, VY in m/s whose y-axis the definition states to point north ->
    `track.vel_east_ms`, `track.vel_north_ms`; the pack then uses the module `track`."""
    vx, vy = c.by_sub.get("VX"), c.by_sub.get("VY")
    if (vx and vy and len(c.fields) == 2 and vx["src_unit"] == "m/s" and vy["src_unit"] == "m/s"
            and vx["signed"] and vy["signed"] and re.search(r"cartesian", c.title + " " + c.definition, re.I)
            and re.search(r"y-axis points to the geographical north", c.remark, re.I)):
        ev = ('%s "%s", definition: "%s"; note: "%s"; subitems VX and VY in m/s, two\'s complement'
              % (c.label, c.title, c.definition, c.remark))
        convert(plan, vx, "track.vel_east_ms", Fraction(1), ev + ". The x-axis of that system points east")
        convert(plan, vy, "track.vel_north_ms", Fraction(1), ev)
        if "track" not in plan.uses:
            plan.uses.append("track")


def time_of_day_of(c):
    """Absolute UTC time of day: one unsigned Element of 24 bits in 1/128 s -> [(field, evidence)]."""
    n = c.single_field()
    if (n and n["src_unit"] == "s" and n["bits"] == 24 and n["frac"] == Fraction(1, 128) and not n["signed"]
            and re.search(r"absolute time stamping", c.definition, re.I) and re.search(r"UTC|universal", c.definition)):
        return [(n, '%s "%s", definition: "%s"%s' % (c.label, c.title, c.definition,
                                                    '; note: "%s"' % c.remark[:200] if c.remark else ""))]
    return []


def bind_position(plan, pos):
    """Of the items that hold a position the one of the finest resolution (the lowest FRN among
    equals) is bound on the wire; the others feed `lat` and `lon` through `derive ... copy` lines."""
    if not pos:
        return
    pos = sorted(pos, key=lambda p: (p[0], p[1]))
    _, _, la, lo, ev = pos[0]
    convert(plan, la, "lat", Fraction(1), ev)
    convert(plan, lo, "lon", Fraction(1), ev)
    for _, _, la2, lo2, ev2 in sorted(pos[1:], key=lambda p: p[1]):
        plan.derives.append(("lat", "copy", [la2["raw"]]))
        plan.derives.append(("lon", "copy", [lo2["raw"]]))
        plan.bindings.append(dict(key="lat, lon", ident=la2["ident"].rsplit("/", 1)[0], how="derive",
                                  evidence=ev2, raws=[la2["raw"], lo2["raw"]]))


def bind_callsign(plan, c):
    """The identification of the reported aircraft as 6-bit ICAO characters -> `callsign`, read
    with `chars:icao6` (engine-spec 0.15). Only the first such item of a category. The raw key
    stays declared in the module; the field line holds `callsign`, as `also` cannot change the
    transform."""
    for n in c.fields:
        if (n.get("icao") and n["bits"] % 6 == 0 and n["key"] == n["raw"]
                and re.search(r"(target|aircraft) identification", c.title + " " + n["title"], re.I)
                and not re.search(r"conflict", c.title + " " + c.definition, re.I)
                and not any(b["key"] == "callsign" for b in plan.bindings)):
            n["key"], n["tr"], n["kind"] = "callsign", "chars:icao6", "chars"
            plan.bindings.append(dict(
                key="callsign", ident=n["ident"], how="chars", tr=n["tr"], raw=None,
                evidence='%s "%s", definition: "%s"%s; %d characters of 6 bits in the ICAO character set (StringICAO)'
                % (c.label, c.title, c.definition,
                   (', subitem %s "%s"' % ("/".join(n["sub"]), fold(n["title"]))) if n["sub"] else "", n["bits"] // 6)))


def bind(plan):
    """Bind shared-model keys where the definition text and the unit leave no doubt. Only items
    that stand directly in the UAP and are fixed (an Element or a Group) are looked at. A time of
    day is bound, through `derive ... day_seconds time_ms`, only when the category has one."""
    pos, tod = [], []
    for e in plan.unique_entries():
        if not e["nodes"] or e["kind"] != "fixed":
            continue
        c = Candidate(plan.cat, e)
        pos += position_of(c)
        bind_height(plan, c)
        bind_speed_and_course(plan, c)
        bind_velocity(plan, c)
        bind_callsign(plan, c)
        tod += time_of_day_of(c)
    bind_position(plan, pos)
    if len(tod) == 1:
        n, ev = tod[0]
        plan.derives.append((n["raw"], "day_seconds", ["time_ms"]))
        plan.bindings.append(dict(key=n["raw"], ident=n["ident"], how="day_seconds", evidence=ev))


def convert(plan, n, shared, mult, evidence):
    """Bind `shared` to the field, unless the field or the shared key is bound already. Same
    unit: the shared key is the field's key and the raw key follows on an `also` line. Another
    unit: the factor is folded into the scale, exactly, and the field has the shared key only."""
    if n["key"] != n["raw"]:
        return
    if any(b["key"] == shared for b in plan.bindings):
        return
    if mult == 1:
        n["key"], n["also"] = shared, [n["raw"]]
        how = "same unit"
    else:
        f = n["frac"] * mult
        n["key"], n["frac"], n["declare"] = shared, f, False
        n["tr"] = scale_text(n["signed"], f)
        how = "factor %s folded into the scale" % frac_text(mult)
    plan.bindings.append(dict(key=shared, ident=n["ident"], how=how, evidence=evidence, tr=n["tr"],
                              raw=n["raw"] if mult == 1 else None))


# ---------------------------------------------------------------- emit: module and pack

def q(text):
    """A double-quoted value of a .def file; a quote inside it becomes `'` (ruling 6 of 0.5)."""
    return '"' + text.replace('"', "'") + '"'


def source_line(cat, sha):
    """The text of the `source` line of the module and of the pack."""
    return ("ASTERIX Category %s, %s, edition %s (%s), as transcribed in github.com/%s (BSD-3-Clause), "
            "commit %s, %s. The category is specified by EUROCONTROL"
            % (cat.nnn, cat.title, cat.edition, cat.date, REPO, sha, cat.rel))


def emit_module(plan, sha):
    """The text of model/<module>.def: keys and lists in UAP order, then the derive lines."""
    cat = plan.cat
    L = ["# The %s module: the values of ASTERIX Category %s (%s), edition %s," % (cat.module, cat.nnn, cat.title, cat.edition),
         "# as the category holds them. Used by the pack `%s`. Generated by" % cat.format,
         "# tools/gen/asterix2pack.py; do not edit by hand. A key is named after its item",
         "# and subitems; a repetitive item is a list and its keys are the keys of one",
         "# repetition.",
         "module        " + cat.module, "version       " + MODULE_VERSION, "distribution  public",
         "source        " + q(source_line(cat, sha))]
    w = max([len(k) for k in plan.keys] + [len(k) for k in plan.lists] + [4])
    ents = [(name, ("key", v)) for name, v in plan.keys.items()] + [(name, ("list", m)) for name, m in plan.lists.items()]
    order = {name: i for i, name in enumerate(order_of_names(plan))}
    for name, (what, v) in sorted(ents, key=lambda x: order[x[0]]):
        if what == "key":
            L.append("key   %-*s  %-6s  %-6s  %s" % (w, name, v[0], v[1], q(v[2])))
        else:
            L.append("list  %-*s  %s" % (w, name, q(v)))
    if plan.derives:
        L.append("# Derived keys (engine-spec 0.6 and 0.8), applied by `convert` between decode and encode.")
        for target, fn, args in plan.derives:
            L.append("derive  %s  %s  %s" % (target, fn, "  ".join(args)))
    return "\n".join(L)


def order_of_names(plan):
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
    for e in plan.unique_entries():
        if e["nodes"]:
            walk(e["nodes"])
    return out


def emit_nodes(nodes, ind, L):
    """Append the pack lines of plan nodes to `L`, indented by `ind` levels."""
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


def emit_pack(plan, sha):
    """The text of pack.def: the header, CAT, LEN, the FSPEC and one `if` block per mapped FRN."""
    cat = plan.cat
    L = ["# ASTERIX Category %s, %s, edition %s: one data block holding one record." % (cat.nnn, cat.title, cat.edition),
         "# Public. Generated by tools/gen/asterix2pack.py from the category definition of",
         "# github.com/%s (BSD-3-Clause); do not edit by hand. I/O is hex text." % REPO,
         "# Needs engine version %s. See pack.md." % ("0.20 (`switch`)" if plan.sel else "0.8 (`layout sequential`)"),
         "#",
         "#   octet 1       CAT = %d" % cat.num,
         "#   octets 2-3    LEN, the length of the data block in octets, CAT and LEN included",
         "#   FSPEC         octets of 7 presence bits and an extension bit; bit n is FRN n",
         "#   then          the items whose FSPEC bit is 1, in FRN order",
         "#",
         "# An FRN with no `if` block is not mapped: a record with that FSPEC bit set fails",
         "# with `malformed-wire` (ruling 1 of engine-spec 0.8), and encode never sets the bit.",
         ] + ([
         "# The category has %d UAPs. The items up to I%s/%s are the same in each; after them" % (len(plan.arms), cat.nnn, plan.sel["ident"].split("/")[0]),
         "# a `switch` on I%s/%s (engine-spec 0.20) reads the items of the UAP it selects, and" % (cat.nnn, plan.sel["ident"]),
         "# only the `if` lines of that case name FSPEC bits.",
         ] if plan.sel else []) + [
         "format     " + cat.format, "version    " + PACK_VERSION, "distribution public",
         "source  " + q(source_line(cat, sha))]
    for m in plan.uses:
        L.append("uses       " + m)
    L += ["uses       " + cat.module, "wire       bits", "layout     sequential", "bit_order  msb",
          "kind    record", "when    8  %d%s# CAT" % (cat.num, " " * 30), "length  16 whole" + " " * 25 + "# LEN",
          "presence f fx"]
    if not plan.sel:
        emit_entries(cat, plan.entries, 0, L)
        return "\n".join(L)
    sel = plan.sel
    emit_entries(cat, [e for e in plan.entries if e["frn"] <= sel["frn"]], 0, L)
    def col(text):
        return text + " " * max(1, 41 - len(text))
    L.append(col("switch " + sel["key"]) + "# the UAP, chosen by I%s/%s (engine-spec 0.20)" % (cat.nnn, sel["ident"]))
    for arm in plan.arms[1:] + plan.arms[:1]:
        vals = ",".join(str(v) for v in arm["values"])
        if arm["default"]:
            L.append(col("  else") + "# UAP `%s`: I%s/%s = %s, or I%s/%s absent" % (
                arm["name"], cat.nnn, sel["ident"], vals, cat.nnn, sel["ident"].split("/")[0]))
        else:
            L.append(col("  case " + vals) + "# UAP `%s`" % arm["name"])
        emit_entries(cat, [e for e in arm["entries"] if e["frn"] > sel["frn"]], 2, L)
    L.append("end")
    return "\n".join(L)


def emit_entries(cat, entries, ind, L):
    """Append one `if f.<frn>` block per mapped entry, and a comment per entry with none."""
    pad = "  " * ind
    for e in entries:
        if e["nodes"] is None:
            L.append("%s# FRN %d: %s" % (pad, e["frn"], ("I%s/%s %s, not mapped: %s" % (cat.nnn, e["name"], e["title"], e["reason"]))
                                         if e["name"] else e["reason"]))
            continue
        L.append("%sif f.%d%s# FRN %d, I%s/%s %s" % (pad, e["frn"], " " * max(1, 36 - len(str(e["frn"])) - len(pad)), e["frn"], cat.nnn,
                                                   e["name"], e["title"]))
        emit_nodes(e["nodes"], ind + 1, L)
        L.append(pad + "end")


# ---------------------------------------------------------------- raw records (written from the definition)

def to_bits(v, n):
    """The low `n` bits of `v` as text, most significant bit first (`bit_order msb`); a negative
    value is written in two's complement."""
    return format(v & ((1 << n) - 1), "0%db" % n) if n else ""


def raw_has(nodes, rec):
    """True when the raw record holds a value for a field or list of these nodes."""
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
    """The bits of an FX presence field (an FSPEC, or the primary subfield of a compound item) for
    a set of bit numbers counted from 1: octets of 7 presence bits and an extension bit that is 1
    when another octet follows. Octets after the last set bit are not written; one octet always is."""
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
            v = rec.get(n["key"], "" if n["kind"] in ("ascii", "chars") else 0)
            if n["kind"] == "ascii":
                b = v.encode("ascii").ljust(n["bits"] // 8, b"\0")
                out += "".join(to_bits(x, 8) for x in b)
            elif n["kind"] == "chars":
                out += "".join(to_bits(ICAO6.index(ch), 6) for ch in v.ljust(n["bits"] // 6))
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
            raise GenError("a raw record cannot hold an explicit item")
    return out


def raw_block(plan, rec, extra=None):
    """Hex of the data block for a raw record. `extra` is FRN -> bits of an item written as is."""
    cat = plan.cat
    extra = extra or {}
    entries = plan.uap_of(rec)["entries"] if plan.sel else plan.entries
    setbits = {e["frn"] for e in entries if e["nodes"] and raw_has(e["nodes"], rec)} | set(extra)
    body = fx_octets(setbits)
    by_frn = {e["frn"]: e for e in entries}
    for frn in sorted(setbits):
        if frn in extra:
            body += extra[frn]
        else:
            body += raw_enc(by_frn[frn]["nodes"], rec)
    if len(body) % 8:
        raise GenError("cat %s: a record of %d bits" % (cat.nnn, len(body)))
    total = 3 + len(body) // 8
    bits = to_bits(cat.num, 8) + to_bits(total, 16) + body
    return "%0*x" % (len(bits) // 4, int(bits, 2))


def raw_value(n, v):
    """Model value of a raw wire value, by the definition."""
    if n["kind"] == "ascii":
        return v
    if n["kind"] == "chars":
        return v.rstrip(" ")
    if n["frac"] is not None:
        return float(v) * float(n["frac"].numerator) / float(n["frac"].denominator) \
            if n["frac"].denominator != 1 else float(v) * float(n["frac"].numerator)
    return v


def raw_model(nodes, rec, prefix, model):
    """Fill `model` with the model values of a raw record, under the key names a vector's `model`
    member uses (`<list>.#`, `<list>[<i>].<key>`)."""
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
        if n["kind"] == "chars":
            alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            return "".join(alphabet[(self.i * 5 + j * 3) % len(alphabet)] for j in range(bits // 6))
        h = (self.i * 2654435761 + 0x9E3779B9) & 0xFFFFFFFFFFFF
        h ^= h >> 7
        if n["signed"]:
            lim = 1 << (bits - 1)
            if lim == 1:
                return -1               # a signed field of one bit holds 0 or -1
            v = h % lim or 1
            return -v if self.i % 2 else v
        lim = 1 << min(bits, 63)
        v = h % lim
        return v or 1

    def fill(self, nodes, rec, items=2):
        """Set every field of the nodes in the raw record: a bound key to its fixed value, any
        other to the next picked value; `items` repetitions in every list."""
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
    """A function of a field node that gives the raw value of `target`, halved until it fits."""
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
        raise GenError("%s: %r does not fit %d bits" % (n["ident"], x, n["bits"]))
    return v


# values of the bound keys in the generated vectors
NICE = {"lat": nice(47.5), "lon": nice(-122.25), "hae": nice(1524.0), "speed_ms": nice(57.875),
        "course": nice(90.0), "track.vel_east_ms": nice(0.0), "track.vel_north_ms": nice(4.0)}


# ---------------------------------------------------------------- derivations (engine-spec 0.6, 0.8)

def apply_derives(ent, derives):
    """Apply derive lines to an entity until nothing changes: a target that is absent is set when
    every argument is present (engine-spec 0.6 "Derived keys")."""
    for _ in range(8):
        changed = False
        for target, fn, args in derives:
            partial = fn == "any" or fn.startswith("tokens:")    # 0.8 and ruling 7 of 0.18
            if target in ent or (any(a not in ent for a in args) if not partial else
                                 not any(a in ent for a in args)):
                continue
            a = [ent.get(x) for x in args]
            r = None
            if fn == "any":
                r = 1 if any(v not in (None, 0) for v in a) else 0
            elif fn == "not":
                r = 1 if a[0] == 0 else 0
            elif fn.startswith("tokens:"):
                sep, toks = fn.split(":", 2)[1:]
                sep = {"space": " ", "comma": ",", "colon": ":"}.get(sep, sep)
                on = [t for t, v in zip(toks.split(","), a) if v not in (None, 0)]
                r = sep.join(on) if on else None
            elif fn.startswith("text_if:"):
                r = fn.split(":", 1)[1] if a[0] not in (None, 0) else None
            elif fn == "copy":
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
                raise GenError("derive function %s is not in the self-check" % fn)
            if r is not None and not (isinstance(r, float) and not math.isfinite(r)):
                ent[target] = r
                changed = True
        if not changed:
            break
    return ent


def all_derives(model):
    """The derive lines of every module of a gtcheck model as (target, function, arguments), the
    modules in byte order of name."""
    out = []
    for name in sorted(model.modules):
        out += [(d.target, d.function + (":" + d.parameter if d.parameter is not None else ""), d.arguments)
                for d in model.modules[name].derives]
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
    """Milliseconds since 1970-01-01T00:00:00Z of an ISO 8601 UTC time (days from the civil date)."""
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?Z", text)
    if not m:
        raise GenError("time %r" % text)
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


# ---------------------------------------------------------------- emit: vectors
#
# Input and expected bytes of every vector but the published samples come from `raw_block`,
# which writes a record from the plan; the pack that was loaded back is not consulted. The
# self-check then replays each vector through the sequential codec, which reads only the pack.

TRACK_INPUT = ('{"apiVersion":"billie.dev/track-v2","kind":"Track","trackId":"311","sourceId":"sensor-a",'
               '"trackGeneration":"generation-1","observedAt":"2025-10-29T12:00:00.125Z",'
               '"position":{"latitudeDeg":47.5,"longitudeDeg":-122.25,"altitudeM":1524},'
               '"velocity":{"eastMps":3,"northMps":4}}')


def model_strings(model):
    """The `model` member of a vector: every value as text (spec/vector-format.md)."""
    return OrderedDict((k, plain(v) if not isinstance(v, str) else v) for k, v in model.items())


def json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False)


def find_field(plan, key):
    """(entry, field node) of the field outside every list that has `key` as its first key."""
    for e in plan.mapped():
        for n, lst in walk_fields(e["nodes"]):
            if n["key"] == key and lst is None:
                return e, n
    return None, None


def filled(entries, items=2, part=None):
    """(raw record, model) with every field of the entries set by a Picker of their own; `part`
    selects one part of each extended item."""
    rec = {}
    pk = Picker()
    for e in entries:
        if part is None:
            pk.fill(e["nodes"], rec, items)
        else:
            Picker().fill(e["nodes"][0]["parts"][part], rec)
    model = OrderedDict([("@kind", "record")])
    for e in entries:
        raw_model(e["nodes"], rec, "", model)
    return rec, model


class VectorSet:
    """The vectors of one pack in the order made: (file name, text, what it shows)."""

    def __init__(self, plan):
        self.plan = plan
        self.source = "generated by tools/gen/asterix2pack.py from %s of github.com/%s" % (plan.cat.rel, REPO)
        self.made = []

    def put(self, name, what, **body):
        fmt = self.plan.cat.format
        v = OrderedDict([("name", name), ("from", body.pop("frm", fmt)), ("to", body.pop("to", fmt))])
        v.update(body)
        v["source"] = body.get("source", self.source)
        v["reference"] = what
        self.made.append(("%02d-%s.json" % (len(self.made) + 1, name), json_text(v), what))

    def roundtrips(self):
        """Every mapped item; one item; extended items cut after their first part."""
        plan, cat = self.plan, self.plan.cat
        if plan.sel:
            return self.uap_roundtrips()
        mapped = [e for e in plan.mapped() if e["kind"] != "explicit"]
        rec, model = filled(mapped)
        hx = raw_block(plan, rec)
        self.put("every-mapped-item-roundtrip",
                 "every mapped FRN present, every field of it set, two repetitions in every repetitive item, every extent "
                 "of every extended item: %d octets" % (len(hx) // 2),
                 input=hx, expect=hx, model=model_strings(model))
        first = mapped[0]
        rec, model = filled([first], items=1)
        hx = raw_block(plan, rec)
        self.put("one-item-roundtrip",
                 "a record holding only FRN %d, I%s/%s (the definition does not mark items as mandatory)" % (first["frn"], cat.nnn, first["name"]),
                 input=hx, expect=hx, model=model_strings(model))
        chains = [e for e in mapped if e["kind"] == "extended"]
        if chains:
            rec, model = filled(chains, part=0)
            if rec:
                hx = raw_block(plan, rec)
                self.put("extended-items-first-part-only-roundtrip",
                         "each extended item with its first part and the extension bit 0; the keys of later parts are absent",
                         input=hx, expect=hx, model=model_strings(model))
        return first

    def uap_roundtrips(self):
        """A category of SWITCHED_UAPS: every mapped item of each UAP with the selecting field set to
        the UAP's value; the first UAP's items without the selecting item; one item; extended
        items cut after their first part, for each UAP."""
        plan, cat = self.plan, self.plan.cat
        sel, key = plan.sel, plan.sel["key"]
        item = sel["ident"].split("/")[0]

        def put_uap(name, what, rec, model, arm):
            rec[key] = arm["values"][0]
            if key in model:
                model[key] = arm["values"][0]
            if plan.uap_of(rec) is not arm:
                raise GenError("vector %s: the record does not select UAP %s" % (name, arm["name"]))
            hx = raw_block(plan, rec)
            self.put(name, "UAP `%s`, I%s/%s = %d: %s" % (arm["name"], cat.nnn, sel["ident"], arm["values"][0], what)
                     + (" (%d octets)" % (len(hx) // 2) if "every" in name else ""),
                     input=hx, expect=hx, model=model_strings(model))

        for arm in plan.arms:
            mapped = [e for e in arm["entries"] if e["nodes"] and e["kind"] != "explicit"]
            rec, model = filled(mapped)
            put_uap("%s-every-mapped-item-roundtrip" % arm["name"],
                    "every mapped FRN of the UAP present, every field of it set, two repetitions in every repetitive "
                    "item, every extent of every extended item", rec, model, arm)
        default = plan.arms[0]
        rest = [e for e in default["entries"] if e["nodes"] and e["kind"] != "explicit" and e["frn"] != sel["frn"]]
        rec, model = filled(rest)
        hx = raw_block(plan, rec)
        if plan.uap_of(rec) is not default:
            raise GenError("a record without I%s/%s does not read UAP %s" % (cat.nnn, item, default["name"]))
        self.put("without-i%s-reads-uap-%s-roundtrip" % (item.lower(), default["name"]),
                 "a record without I%s/%s, every other mapped FRN of UAP `%s` present: the `switch` finds "
                 "`%s` absent and reads the `else` lines, the layout of UAP `%s` (%d octets)"
                 % (cat.nnn, item, default["name"], key, default["name"], len(hx) // 2),
                 input=hx, expect=hx, model=model_strings(model))
        first = plan.entries[0]
        rec, model = filled([first], items=1)
        hx = raw_block(plan, rec)
        self.put("one-item-roundtrip",
                 "a record holding only FRN %d, I%s/%s (the definition does not mark items as mandatory)" % (first["frn"], cat.nnn, first["name"]),
                 input=hx, expect=hx, model=model_strings(model))
        for arm in plan.arms:
            chains = [e for e in arm["entries"] if e["nodes"] and e["kind"] == "extended"]
            rec, model = filled(chains, part=0)
            put_uap("%s-extended-items-first-part-only-roundtrip" % arm["name"],
                    "each extended item of the UAP with its first part and the extension bit 0; the keys of later "
                    "parts are absent", rec, model, arm)
        return first

    def other_uap_bits(self):
        """A category of SWITCHED_UAPS: a record of one UAP with an FSPEC bit set that only another
        UAP maps is `malformed-wire`, because only the `if` lines of the case read count."""
        plan, cat = self.plan, self.plan.cat
        if not plan.sel:
            return
        for arm in plan.arms:
            own = {e["frn"] for e in arm["entries"] if e["nodes"]}
            other = sorted({e["frn"] for a in plan.arms if a is not arm for e in a["entries"] if e["nodes"]} - own)
            if not other:
                continue
            frn = other[0]
            by = next(a for a in plan.arms if a is not arm and any(e["frn"] == frn and e["nodes"] for e in a["entries"]))
            sel_entry = plan.entries[plan.sel["frn"] - 1]
            rec, _ = filled([sel_entry], part=0) if sel_entry["kind"] == "extended" else filled([sel_entry], items=1)
            rec[plan.sel["key"]] = arm["values"][0]
            self.put("uap-%s-record-with-an-frn-only-uap-%s-maps" % (arm["name"], by["name"]),
                     "I%s/%s = %d (UAP `%s`) and FSPEC bit %d set, which only UAP `%s` maps: only the `if` lines of "
                     "the case read name FSPEC bits (engine-spec 0.20), so the bit is `malformed-wire`"
                     % (cat.nnn, plan.sel["ident"], arm["values"][0], arm["name"], frn, by["name"]),
                     input=raw_block(plan, rec, {frn: to_bits(0, 8)}), expect_error="malformed-wire")

    def explicit_items(self, first):
        """Explicit items are read over on decode and not written on encode."""
        plan = self.plan
        expl = [e for e in plan.mapped() if e["kind"] == "explicit"]
        if not expl:
            return
        rec, model = filled([first], items=1)
        extra = {e["frn"]: to_bits(4, 8) + to_bits(0xA1B2C3, 24) for e in expl}
        self.put("explicit-items-are-read-over-and-not-written",
                 "the same record with %s present, each a length octet of 4 and three octets of content: decode passes "
                 "over them, encode does not write them" % " and ".join("FRN %d (%s)" % (e["frn"], e["name"]) for e in expl),
                 input=raw_block(plan, rec, extra), expect=raw_block(plan, rec), model=model_strings(model))

    def refusals(self, first):
        """An FRN with no `if` block, another category, and a block shorter than its LEN."""
        plan, cat = self.plan, self.plan.cat
        unm = [e for e in plan.unmapped()           # with several UAPs, an FRN that none maps
               if not any(x["frn"] == e["frn"] and x["nodes"] for a in plan.arms for x in a["entries"])]
        if unm:
            e = unm[0]
            self.put("frn-the-pack-does-not-map",
                     "FSPEC bit %d set (%s): ruling 1 of engine-spec 0.8" % (e["frn"], "I%s/%s" % (cat.nnn, e["name"]) if e["name"] else e["reason"]),
                     input=raw_block(plan, {}, {e["frn"]: to_bits(0, 8)}), expect_error="malformed-wire")
        rec, _ = filled([first], items=1)
        hx = raw_block(plan, rec)
        other = (cat.num + 1) % 256
        self.put("category-is-not-%d" % cat.num, "the first octet is %d" % other,
                 input="%02x" % other + hx[2:], expect_error="no-kind")
        self.put("block-shorter-than-len", "LEN states %d octets and the input holds %d" % (len(hx) // 2, len(hx) // 2 - 1),
                 input=hx[:-2], expect_error="malformed-wire")

    def to_geojson(self, bound, derives):
        """A record of the items that hold shared keys, converted to a GeoJSON Feature."""
        plan, cat = self.plan, self.plan.cat
        rec, items = {}, []
        for key in bound:
            e, _ = find_field(plan, key)
            if e not in items:
                items.append(e)
        in_frn_order = sorted(items, key=lambda e: e["frn"])
        for e in in_frn_order:
            for n in e["nodes"]:
                if n["t"] == "field":
                    rec[n["key"]] = NICE[n["key"]](n) if n["key"] in NICE else ("AFR2041" if n["kind"] == "chars" else 0)
        model = OrderedDict()
        for e in items:
            raw_model(e["nodes"], rec, "", model)
        ent = apply_derives(dict(model), derives)
        self.put("to-geojson",
                 "a record with %s: the shared keys %s reach the Feature" % (
                     ", ".join("I%s/%s" % (cat.nnn, e["name"]) for e in in_frn_order),
                     ", ".join("`%s`" % k for k in bound)),
                 to="geojson", input=raw_block(plan, rec), expect=geojson_text(ent),
                 model=model_strings(OrderedDict((k, v) for k, v in model.items() if k in bound)))

    def samples(self, pack):
        """Blocks a publisher prints with the values they hold. A sample whose decode does not give
        the stated values, or that does not encode back to the expected bytes, is refused."""
        plan, cat = self.plan, self.plan.cat
        for s in SAMPLES:
            if s["cat"] != cat.num or cat.other:          # the samples are of the newest edition
                continue
            ent, lists = seq_decode(pack, s["hex"])
            for path, want in s["stated"].items():
                name = plan.names.get(path)
                keys = [k for k in ent if name and k.endswith("." + name)] or \
                       [n["key"] for e in plan.mapped() for n, _ in walk_fields(e["nodes"]) if n["ident"] == path]
                if not keys or keys[0] not in ent or abs(ent[keys[0]] - want) > 1e-9:
                    raise GenError("sample %s: %s is %r, the publisher states %r"
                                   % (s["name"], path, ent.get(keys[0]) if keys else None, want))
            expect = seq_encode(pack, ent, lists)
            if expect != s.get("expect", s["hex"]):
                raise GenError("sample %s: re-encoded %s" % (s["name"], expect))
            model = OrderedDict([("@kind", "record")])
            model.update(ent)
            self.put(s["name"], s["note"], input=s["hex"], expect=expect, model=model_strings(model),
                     source="github.com/%s (BSD-3-Clause), %s, commit %s" % (SAMPLES_REPO, SAMPLES_PATH, SAMPLES_COMMIT))


def track_vector(plan, derives, source):
    """The vector of packs/canonical-track-v2 that converts one track to this pack, or None when
    a field is too narrow for the track's value."""
    cat = plan.cat
    ent = apply_derives(track_json_decode(TRACK_INPUT), derives)
    top = [n for e in plan.mapped() for n, lst in walk_fields(e["nodes"]) if lst is None]
    try:
        for n in top:
            if n["key"] in ent and n["frac"] is not None:
                model_to_raw(n, ent[n["key"]])
    except GenError:
        return None
    rec = {}
    for n in top:
        for k in [n["key"]] + n["also"]:
            if k in ent and n["key"] not in rec:
                rec[n["key"]] = model_to_raw(n, ent[k])
    written = [e for e in plan.mapped() if raw_has(e["nodes"], rec)]
    complete = OrderedDict([("@complete", True)])
    for target, function, _ in plan.derives:
        if function == "day_seconds":
            complete[target] = plain(ent[target])
    vec = OrderedDict([("name", "gen-to-" + cat.format), ("from", "canonical-track-v2"), ("to", cat.format),
                       ("input", TRACK_INPUT), ("expect", raw_block(plan, rec))])
    if len(complete) > 1:
        vec["model"] = complete
    vec["source"] = source
    vec["reference"] = ("a track at 47.5 N 122.25 W, 1524 m, velocity 3 m/s east and 4 m/s north, at "
                        "12:00:00.125 UTC: the record holds %s; the fields of those items that no key "
                        "fills are zero" % ", ".join("I%s/%s" % (cat.nnn, e["name"]) for e in written))
    return vec


def make_vectors(plan, pack, model):
    """-> ([(file name, text, what it shows)], the vector for packs/canonical-track-v2 or None).
    `pack` and `model` are the generated pack and modules as gtcheck loaded them."""
    vs = VectorSet(plan)
    derives = all_derives(model)
    first = vs.roundtrips()
    vs.explicit_items(first)
    vs.refusals(first)
    vs.other_uap_bits()
    track_vec = None
    bound = [b["key"] for b in plan.bindings if b["how"] not in ("derive", "day_seconds")]
    if "lat" in bound and "lon" in bound:
        vs.to_geojson(bound, derives)
        track_vec = track_vector(plan, derives, vs.source)
    vs.samples(pack)
    return vs.made, track_vec


# ---------------------------------------------------------------- loading what was written (gtcheck)

def builtin_module_text(name, keys, lists=(), derives=()):
    """The text of a model module made from a built-in table."""
    lines = ["module %s" % name, "version 0", "distribution public", 'source "built into asterix2pack.py"']
    lines += ["key %s %s -" % (key, key_type) for key, key_type in keys.items()]
    lines += ["list %s" % name_ for name_ in lists]
    lines += ["derive %s %s %s" % (target, function, " ".join(arguments)) for target, function, arguments in derives]
    return "\n".join(lines) + "\n"


def shared_model():
    """A gtcheck model that holds `core` and `track` as the built-in tables state them."""
    model = gtcheck.Model()
    model.add(builtin_module_text("core", CORE_KEYS), "core (built in)")
    model.add(builtin_module_text("track", TRACK_KEYS, TRACK_LISTS, TRACK_DERIVES), "track (built in)")
    return model


def load_module(model, text, label):
    """Add a generated module to the model; a gtcheck refusal becomes a GenError."""
    try:
        return model.add(text, label)
    except gtcheck.CheckError as e:
        raise GenError("%s: %s" % (e.kind, e.message), file=e.label, line=e.line)


def load_pack(model, text, label):
    """Load a generated pack through gtcheck; a refusal becomes a GenError."""
    try:
        return gtcheck.load_pack(text, model, label)
    except gtcheck.CheckError as e:
        raise GenError("%s: %s" % (e.kind, e.message), file=e.label, line=e.line)


# The transforms and derive functions the generator writes. The codec below implements these and
# no others, so `check_shape` refuses a pack or module that holds anything else.
SHAPE_TRANSFORMS = ("uint", "twos", "uscale", "sscale", "ascii", "chars")
SHAPE_DERIVES = ("copy", "day_seconds")
# `chars:icao6` (engine-spec 0.15): code 1-26 A-Z, 32 space, 48-57 0-9; any other code is an error.
ICAO6 = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######"
ICAO6_CODES = set(range(1, 27)) | {32} | set(range(48, 58))
ICAO6_SET = {ICAO6[c] for c in ICAO6_CODES}
_SHAPE_SCALE = re.compile(r"\d+(/\d+)?\Z")


def arm_paths(lines, path=()):
    """id(node) -> the `case` and `else` nodes it stands in, outermost first, as ids."""
    out = {}
    for node in lines:
        out[id(node)] = path
        if node.body:
            inner = path + (id(node),) if node.d in ("case", "else") else path
            out.update(arm_paths(node.body, inner))
    return out


def check_shape(pack, module):
    """The invariants of this generator's output that are narrower than the specification.

    gtcheck has already applied the load rules. A generated pack is, beyond them: the bits wire,
    `layout sequential`, `bit_order msb`; one kind that holds every line and has no `requires`; no
    value table; `field` lines with no option, one of five transforms and a scale that is an
    integer or a fraction with no offset; `also` lines with no table; `presence` in the `fx` form
    only; groups in the `count` and `fx` forms with no item kinds; each list mapped by one group,
    or by one group in each arm of a `switch` (ruling 10 of 0.20); a `switch` only among the
    kind's own lines, with `case` values that are unsigned integers; no `const`, `default`,
    `align` or `opt` line. A generated module derives with `copy` and
    `day_seconds` only. The sequential codec of this file relies on every one of these."""

    def bad(what, line=None):
        raise GenError("not a pack this generator writes: " + what, file=pack.label, line=line)

    if (pack.wire, pack.layout, pack.bit_order) != ("bits", "sequential", "msb"):
        bad("wire %s, layout %s, bit_order %s" % (pack.wire, pack.layout, pack.bit_order))
    if pack.common or len(pack.kinds) != 1:
        bad("%d lines before the first kind and %d kinds; one kind holds every line"
            % (len(pack.common), len(pack.kinds)))
    if pack.kinds[0].requires:
        bad("the kind has a `requires` line", pack.kinds[0].line)
    if pack.tables or pack.typemap:
        bad("a `map` or `typemap` line")
    lists = []                  # (list, the switch arms the group stands in)
    arms = arm_paths(pack.kinds[0].lines)
    for node in gtcheck.walk(pack.kinds[0].lines):
        d = node.d
        if d == "switch" and node not in pack.kinds[0].lines:
            bad("a `switch` inside a block", node.line)
        elif d == "case" and not all(re.fullmatch(r"\d+", v) for v in node.values):
            bad("a `case` value that is not an unsigned integer", node.line)
        if d in ("const", "default", "align", "opt"):
            bad("a `%s` line" % d, node.line)
        elif d == "field":
            if node.opts or node.via is not None:
                bad("a field with an option", node.line)
            if node.tr not in SHAPE_TRANSFORMS:
                bad("the transform `%s`" % node.tr, node.line)
            if node.tr in ("uscale", "sscale") and not (len(node.targs) == 1 and _SHAPE_SCALE.match(node.targs[0])):
                bad("the scale `%s`" % ":".join(node.targs), node.line)
            if any(via is not None for _, via in node.also):
                bad("an `also` line with a table", node.line)
        elif d == "presence" and node.bits != "fx":
            bad("a `presence` of a fixed number of bits", node.line)
        elif d == "group":
            if node.mode not in ("count", "fx") or node.kinds:
                bad("a group that is not `count` or `fx`, or that has item kinds", node.line)
            path = arms[id(node)]
            if any(k == node.key and (p[:len(path)] == path or path[:len(p)] == p) for k, p in lists):
                bad("the list %s is mapped by two groups" % node.key, node.line)
            lists.append((node.key, path))
    for derive in module.derives:
        if derive.function not in SHAPE_DERIVES:
            raise GenError("not a module this generator writes: the derive function `%s`" % derive.function,
                           file=module.label, line=derive.line)


# ---------------------------------------------------------------- sequential codec (spec 0.8 and 0.20)
#
# Decode and encode of a pack that passed `check_shape`, written from spec/engine-spec.md. It walks
# the tree gtcheck returns. An entity is a dict of key -> value and a dict of list -> items, an
# item being a pair of the same two dicts.

class Reader:
    """A cursor over the bits of a message, as a text of `0` and `1`, first bit first."""

    def __init__(self, bits):
        self.bits, self.pos, self.end = bits, 0, len(bits)
        self.extents = []
        self.chosen = set()         # ids of the `case` and `else` nodes read (spec 0.20)

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


def pack_lines(pack):
    """The lines of the one kind of a generated pack."""
    return pack.kinds[0].lines


def named_bits(lines, name, chosen=frozenset()):
    """Bit numbers of presence `name` that an `if` of these lines names without `!`, with the blocks.
    Of a `switch`, only the arms in `chosen` (ids) count (spec 0.20)."""
    out = []
    for x in lines:
        if x.d == "if":
            for neg, nm, bit in x.conds:
                if nm == name and not neg:
                    out.append((bit, x))
        if x.d in ("case", "else") and id(x) not in chosen:
            continue
        if x.body:
            out += named_bits(x.body, name, chosen)
    return out


def all_named(lines, name, chosen=frozenset()):
    """Every bit number of presence `name` that an `if` of these lines names (ruling 17 of 0.8);
    an `if` in a `switch` arm counts only when the arm was read (spec 0.20), its id in `chosen`."""
    out = set()
    for x in lines:
        if x.d == "if":
            out |= {bit for _, nm, bit in x.conds if nm == name}
        if x.d in ("case", "else") and id(x) not in chosen:
            continue
        if x.body:
            out |= all_named(x.body, name, chosen)
    return out


def has_switch(lines):
    """True when a `switch` stands among these lines or in a block of them."""
    return any(x.d == "switch" or (x.body and has_switch(x.body)) for x in lines)


def case_holds(arm, value):
    """True when a `case` lists the value (spec 0.20; the generator writes integer values only)."""
    return value is not None and not isinstance(value, str) and any(int(v) == value for v in arm.values)


def select_arm(x, value):
    """The arm of a `switch` the key's value selects: the first `case` that lists it, else the
    `else` arm; None when there is neither (`no-kind`)."""
    arm = next((a for a in x.body if a.d == "case" and case_holds(a, value)), None)
    return arm or next((a for a in x.body if a.d == "else"), None)


def scale_of(field):
    """(numerator, denominator or None) of a scale transform, as doubles (ruling 1 of 0.5)."""
    factor = gtcheck.parse_factor(field.targs[0])
    if isinstance(factor, tuple):
        return float(factor[0]), float(factor[1])
    return factor, None


def t_decode(x, v):
    """Model value of the unsigned wire value `v` of a field (engine-spec 0.2 and 0.5)."""
    tr, bits = x.tr, x.bits
    if tr == "uint":
        return v - (1 << 64) if bits == 64 and v >> 63 else v      # ruling 2 of 0.5
    signed = v - (1 << bits) if v >> (bits - 1) else v
    if tr == "twos":
        return signed
    if tr in ("uscale", "sscale"):
        num_, den = scale_of(x)
        r = float(v if tr == "uscale" else signed) * num_
        return r / den if den is not None else r
    if tr == "chars":
        out = ""
        for i in range(bits // 6):
            code = (v >> (bits - 6 * (i + 1))) & 63
            if code not in ICAO6_CODES:
                raise WireError("transform-decode", "icao6 code %d" % code)
            out += ICAO6[code]
        return out.rstrip(" ")
    if tr == "ascii":
        b = v.to_bytes(bits // 8, "big").rstrip(b"\0")
        if any(c < 0x20 or c > 0x7E for c in b):
            raise WireError("transform-decode", "ascii byte out of range")
        return b.decode("ascii")
    raise GenError("the codec has no transform %s" % tr)


def t_encode(x, val):
    """Unsigned wire value of a model value; out of range is `transform-encode`."""
    tr, bits = x.tr, x.bits
    if tr == "chars":
        if len(val) > bits // 6 or any(ch not in ICAO6_SET for ch in val):
            raise WireError("transform-encode", "icao6 text")
        v = 0
        for ch in val.ljust(bits // 6):
            v = (v << 6) | ICAO6.index(ch)
        return v
    if tr == "ascii":
        b = val.encode("utf-8")
        if len(b) > bits // 8 or any(c < 0x20 or c > 0x7E for c in b):
            raise WireError("transform-encode", "ascii text")
        return int.from_bytes(b.ljust(bits // 8, b"\0"), "big")
    if tr in ("uscale", "sscale"):
        num_, den = scale_of(x)
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


def holds(conds, env):
    """True when every condition of an `if` line holds for the presence bits read or computed."""
    return all((bit in env[name]) != negated for negated, name, bit in conds)


def dec_presence(x, rd, following, check=True):
    """The set bits of an `fx` presence: octets of 7 bits and an extension bit. A set bit that no
    `if` of the lines after it names is `malformed-wire` (ruling 1 of 0.8); with `check` False the
    caller tests that once the arms of a `switch` are read (`stray_presence`)."""
    setbits, octet = set(), 0
    while True:
        v = rd.take(8)
        if v is None:
            break
        for b in range(7):
            if v >> (7 - b) & 1:
                setbits.add(octet * 7 + b + 1)
        octet += 1
        if not v & 1:
            break
    if check:
        stray_presence(x.name, setbits, following, frozenset())
    return setbits


def stray_presence(name, setbits, following, chosen):
    """A set bit that no `if` of the lines after the presence names, of the arms read, is
    `malformed-wire` (ruling 1 of 0.8, and spec 0.20: only the selected case counts)."""
    stray = setbits - all_named(following, name, chosen)
    if stray:
        raise WireError("malformed-wire", "presence bit %s.%d is 1 and no `if` names it" % (name, min(stray)))


def dec_chain(x, rd, ent, lists, env):
    """A chain: at each `fx` line a 0 bit ends it; a 1 bit on a last `fx` line is refused (ruling 3)."""
    for i, y in enumerate(x.body):
        if y.d == "fx":
            if not rd.take(1):
                break
            if i == len(x.body) - 1:
                raise WireError("malformed-wire", "a chain that ends with an fx line whose bit is 1")
        else:
            dec_lines([y], rd, ent, lists, env)


def dec_group(x, rd, lists, env):
    """A `count` or `fx` group. Inside a length extent that has ended the list stays absent."""
    items = []
    if x.mode == "count":
        n = rd.take(x.count)
        if n is None:
            return
        if n > rd.end - rd.pos:         # rulings 14 and 25 of 0.8
            raise WireError("malformed-wire", "count larger than the bits left")
        for _ in range(n):
            it = ({}, {})
            dec_lines(x.body, rd, it[0], it[1], env)
            items.append(it)
    else:
        if rd.extents and rd.pos >= rd.extents[-1]:
            return
        while True:
            it = ({}, {})
            dec_lines(x.body, rd, it[0], it[1], env)
            items.append(it)
            if not rd.take(1):
                break
    lists[x.key] = items


def dec_length(x, rd, ent, lists, env):
    """`length ... whole` sets the end of the input; another `length` opens an extent for its block."""
    v = rd.take(x.bits)
    if x.whole:
        total = v - x.plus
        if total * 8 < rd.pos or total * 8 > rd.end:
            raise WireError("malformed-wire", "whole length %d, input %d octets" % (total, rd.end // 8))
        rd.end = total * 8
    elif v is not None:
        n = v - x.plus
        if n < 0:
            raise WireError("malformed-wire", "stated length below `plus`")
        ext = rd.pos + n * (8 if x.unit == "bytes" else 1)
        if ext > rd.end or (rd.extents and ext > rd.extents[-1]):
            raise WireError("malformed-wire", "length extent beyond the input")
        rd.extents.append(ext)
        dec_lines(x.body, rd, ent, lists, env)
        rd.extents.pop()
        rd.pos = ext


def dec_lines(lines, rd, ent, lists, env):
    """Read the lines of one block in file order. `env` maps a visible presence name to its set bits."""
    env = dict(env)
    deferred = []               # presences whose stray bits are checked once the switch arms are read
    for i, x in enumerate(lines):
        d = x.d
        if d == "when":
            if rd.take(x.bits) != int(x.value):
                raise WireError("no-kind", "when %s" % x.value)
        elif d == "field":
            v = rd.take(x.bits)
            if v is not None:
                val = t_decode(x, v)
                for k in gtcheck.keys_of(x):
                    ent.setdefault(k, val)
        elif d == "also":
            pass                        # its key is on the field node
        elif d == "pad":
            rd.take(x.bits)
        elif d == "presence":
            later = not has_switch(lines[i + 1:])
            env[x.name] = dec_presence(x, rd, lines[i + 1:], check=later)
            if not later:
                deferred.append((x.name, env[x.name], lines[i + 1:]))
        elif d == "switch":
            arm = select_arm(x, ent.get(x.key))
            if arm is None:
                raise WireError("no-kind", "no `case` of the switch on %s holds %r" % (x.key, ent.get(x.key)))
            rd.chosen.add(id(arm))
            dec_lines(arm.body, rd, ent, lists, env)
        elif d == "if":
            if holds(x.conds, env):
                dec_lines(x.body, rd, ent, lists, env)
        elif d == "chain":
            dec_chain(x, rd, ent, lists, env)
        elif d == "group":
            dec_group(x, rd, lists, env)
        elif d == "length":
            dec_length(x, rd, ent, lists, env)
        else:
            raise GenError("the codec has no line `%s`" % d)
    for name, setbits, following in deferred:
        stray_presence(name, setbits, following, rd.chosen)


def seq_decode(pack, hx):
    """Decode hex text through a generated pack -> (keys, lists)."""
    hx = "".join(hx.split())
    if len(hx) % 2 or not re.fullmatch(r"[0-9a-fA-F]*", hx):
        raise WireError("malformed-wire", "hex")
    rd = Reader("".join(format(int(c, 16), "04b") for c in hx))
    ent, lists = {}, {}
    dec_lines(pack_lines(pack), rd, ent, lists, {})
    return ent, lists


def has_content(lines, ent, lists):
    """Would these lines write a present key, a non-empty list, or a nested presence that is not
    all zero? Nested conditions are not evaluated (ruling 22 of 0.8)."""
    for i, x in enumerate(lines):
        d = x.d
        if d == "field" and any(k in ent for k in gtcheck.keys_of(x)):
            return True
        if d == "group" and lists.get(x.key):
            return True
        if d in ("chain", "length") and x.body and has_content(x.body, ent, lists):
            return True
        if d == "presence" and any(has_content(blk.body, ent, lists) for _, blk in named_bits(lines[i + 1:], x.name)):
            return True
    return False


def enc_chain(x, ent, lists, env, st):
    """A chain: an `fx` bit is 1 when a line after it would write a present key; the chain stops at
    the first 0."""
    out = ""
    for i, y in enumerate(x.body):
        if y.d == "fx":
            more = has_content([z for z in x.body[i + 1:] if z.d != "fx"], ent, lists)
            out += "1" if more else "0"
            if not more:
                break
        else:
            out += enc_lines([y], ent, lists, env, st)
    return out


def enc_group(x, lists, env, st):
    """A `count` group writes its count and items; an `fx` group needs one item (ruling 6 of 0.8)."""
    items = lists.get(x.key, [])
    if x.mode == "count":
        if len(items) >= 1 << x.count:
            raise WireError("transform-encode", "count does not fit")
        return to_bits(len(items), x.count) + "".join(enc_lines(x.body, it[0], it[1], env, st) for it in items)
    if not items:
        raise WireError("transform-encode", "an fx group with no item")
    return "".join(enc_lines(x.body, it[0], it[1], env, st) + ("1" if j < len(items) - 1 else "0")
                   for j, it in enumerate(items))


def enc_lines(lines, ent, lists, env, st):
    """Write the lines of one block. Presence bits are computed from the blocks that follow before
    they are written. `st` records where a `length ... whole` field stands, for `seq_encode`."""
    env = dict(env)
    out = ""
    for i, x in enumerate(lines):
        d = x.d
        if d == "when":
            out += to_bits(int(x.value), x.bits)
        elif d == "field":
            val = next((ent[k] for k in gtcheck.keys_of(x) if k in ent), None)     # ruling 13 of 0.8
            wire = t_encode(x, val) if val is not None else 0
            out += to_bits(wire, x.bits)
            if x.tr in ("uint", "twos"):            # what decode reads back, for a `switch` (0.20)
                for k in gtcheck.keys_of(x):
                    st["written"].setdefault(k, t_decode(x, wire))
        elif d == "pad":
            out += "0" * x.bits
        elif d == "presence":
            setbits = {bit for bit, blk in named_bits(lines[i + 1:], x.name, st["sel"]) if has_content(blk.body, ent, lists)}
            env[x.name] = setbits
            out += fx_octets(setbits)
        elif d == "switch":
            arm = select_arm(x, st["written"].get(x.key))
            if arm is None:
                raise WireError("no-kind", "no `case` of the switch on %s holds %r" % (x.key, st["written"].get(x.key)))
            st["chosen"].add(id(arm))
            out += enc_lines(arm.body, ent, lists, env, st)
        elif d == "if":
            if holds(x.conds, env):
                out += enc_lines(x.body, ent, lists, env, st)
        elif d == "chain":
            out += enc_chain(x, ent, lists, env, st)
        elif d == "group":
            out += enc_group(x, lists, env, st)
        elif d == "length":
            if x.whole:
                st["whole"] = (len(st["prefix"]) + len(out), x)
                out += "0" * x.bits
            else:
                body = enc_lines(x.body, ent, lists, env, st)
                if x.unit == "bytes":
                    body += "0" * (-len(body) % 8)
                    n = len(body) // 8
                else:
                    n = len(body)
                out += to_bits(n + x.plus, x.bits) + body
    return out


def seq_encode(pack, ent, lists):
    """Encode an entity through a generated pack -> hex text. The whole length is filled in last."""
    sel = frozenset()
    for _ in range(4):
        # The presence bits are computed before the switch is reached, from the arms in `sel`;
        # the arms the switches then chose are taken as `sel` and the record written again until
        # the two agree (an FSPEC bit the selecting key depends on stands before the switch).
        st = dict(prefix="", whole=None, written={}, sel=sel, chosen=set())
        bits = enc_lines(pack_lines(pack), ent, lists, {}, st)
        if st["chosen"] == sel:
            break
        sel = frozenset(st["chosen"])
    else:
        raise GenError("the arms of a switch do not settle on encode")
    bits += "0" * (-len(bits) % 8)
    if st["whole"]:
        pos, x = st["whole"]
        v = len(bits) // 8 + x.plus
        if not 0 <= v < 1 << x.bits:
            raise WireError("transform-encode", "whole length does not fit")
        bits = bits[:pos] + to_bits(v, x.bits) + bits[pos + x.bits:]
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


def replay(v, packs, derives):
    """One vector through the codec. `packs` maps a format to its loaded pack and `derives` holds
    the derive lines of every loaded module. Raises GenError when the vector does not hold."""
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
            ent = apply_derives(ent, derives)
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
            if want != packs[frm].kinds[0].name:
                raise GenError("%s: kind %s" % (name, want))
            continue
        got_v = lookup(base[0], base[1], k)
        if isinstance(got_v, float):
            ok = abs(got_v - float(want)) < 1e-9 * max(1.0, abs(got_v), abs(float(want)))
        else:
            ok = str(got_v) == want
        if not ok:
            raise GenError("%s: model key %s is %r, the vector expects %s" % (name, k, got_v, want))


# ---------------------------------------------------------------- emit: pack.md and PROVENANCE.md

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
    """The "Written as" cell of pack.md for one mapped FRN."""
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


def md_intro(a, plan, sha):
    """pack.md: what the pack is, where its definition comes from and which modules it uses."""
    cat = plan.cat
    a("# Pack: %s" % cat.format)
    a("")
    a("ASTERIX Category %s, %s, edition %s (%s): one data block holding one record." % (cat.nnn, cat.title, cat.edition, cat.date))
    a("Public. Generated by `tools/gen/asterix2pack.py` from the machine-readable definition of the")
    a("category in `github.com/%s` (BSD-3-Clause), file `%s` at commit" % (REPO, cat.rel))
    a("`%s`. The category itself is specified by EUROCONTROL. I/O is hex text." % sha)
    a("Needs engine version 0.20 (`switch`)." if plan.sel else "Needs engine version 0.8 (`layout sequential`).")
    a("")
    a("Uses the modules `core`%s and `%s` (`model/%s.def`, generated with the pack)." % (
        "".join(", `%s`" % m for m in plan.uses), cat.module, cat.module))
    if cat.other:
        a("")
        a("This is an older edition of the category, written beside the pack `asterix-cat%s` of the newest" % cat.nnn)
        a("edition because it is in operational use and its records are laid out differently. A data block")
        a("does not state its edition: both packs select CAT %d, and the reader chooses the pack by what the" % cat.num)
        a("sending system is configured to send. A record of one edition decoded with the other edition's pack")
        a("is read wrongly or fails.")
    if cat.num in RENAME:
        a("")
        a("The pack and its module carry these names because the library also holds the hand-written pack")
        a("`asterix-cat%s` with the module `cat%s`. Section \"Beside the hand-written pack\" compares the two." % (cat.nnn, cat.nnn))


def md_layout(a, plan):
    """pack.md: the block layout and how each item type and content type is written."""
    cat = plan.cat
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
    if plan.sel:
        sel = plan.sel
        item = sel["ident"].split("/")[0]
        a("| common items | one `if f.<frn>` block per FRN up to %d, I%s/%s | the same items in every UAP |" % (sel["frn"], cat.nnn, item))
        a("| `switch %s` | one `case` per UAP after the first, and `else` | the items of the UAP that I%s/%s selects, one `if f.<frn>` block per mapped FRN |"
          % (sel["key"], cat.nnn, sel["ident"]))
    else:
        a("| items | one `if f.<frn>` block per mapped FRN, in FRN order | below |")
    a("")
    a("A data block that holds more than one record: the first record is read and the rest of the block is not.")
    if plan.sel:
        md_uaps(a, plan)
    elif cat.uap_note:
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


def md_uaps(a, plan):
    """pack.md of a category of SWITCHED_UAPS: how the UAP is chosen, on decode and on encode."""
    cat, sel = plan.cat, plan.sel
    item = sel["ident"].split("/")[0]
    a("")
    a("### The UAPs")
    a("")
    a("The definition gives the category %d UAPs and names I%s/%s as the field whose value says which one" % (len(plan.arms), cat.nnn, sel["ident"]))
    a("a record follows. Every UAP holds the same items up to FRN %d, so those are written once, before a" % sel["frn"])
    a("`switch` on `%s` (engine-spec 0.20):" % sel["key"])
    a("")
    a("| UAP | Arm | I%s/%s | FRNs | mapped |" % (cat.nnn, sel["ident"]))
    a("|---|---|---|---|---|")
    for arm in plan.arms:
        a("| `%s` | `%s` | %s%s | %d | %d |" % (
            arm["name"], "else" if arm["default"] else "case " + ",".join(str(v) for v in arm["values"]),
            ", ".join(str(v) for v in arm["values"]), ", or the item absent" if arm["default"] else "",
            len(arm["entries"]), sum(1 for e in arm["entries"] if e["nodes"])))
    a("")
    a("- **Decode.** The value read from I%s/%s picks the case. A record without I%s/%s leaves the key absent," % (cat.nnn, sel["ident"], cat.nnn, item))
    a("  and the `else` lines are read: UAP `%s`, which is also the layout the earlier one-UAP pack read." % plan.arms[0]["name"])
    a("  The definition names no UAP for a record without the item; reading the first is this pack's choice.")
    a("- **FSPEC bits.** Only the `if` lines of the case read name FSPEC bits, so a bit that only another UAP")
    a("  maps is `malformed-wire` in a record of this UAP.")
    a("- **Encode.** The case is the one decode would pick from what was written: the value of `%s`," % sel["key"])
    a("  zero when the item is written without it, and `else` when the item is not written at all. Keys of")
    a("  items that only another UAP holds are not written.")
    a("- **One kind.** The UAP is not a kind: `@kind` is `record` for every UAP, and the decoded `%s`" % sel["key"])
    a("  tells them apart. An item two UAPs share has one set of keys, whichever FRN it has in each.")


def md_items(a, plan):
    """pack.md: the counts, and one row per mapped FRN."""
    cat = plan.cat
    if plan.sel:
        return md_items_uaps(a, plan)
    a("")
    a("## Items")
    a("")
    a("| | Count |")
    a("|---|---|")
    a("| FRNs in the UAP | %d |" % len(plan.entries))
    for kind in ("fixed", "extended", "repetitive", "compound", "explicit"):
        n = sum(1 for e in plan.entries if e["nodes"] and e["kind"] == kind)
        if n:
            a("| mapped, %s | %d |" % (kind, n))
    a("| not mapped | %d |" % sum(1 for e in plan.entries if e["nodes"] is None))
    a("| keys of `%s` | %d |" % (cat.module, len(plan.keys)))
    a("| lists of `%s` | %d |" % (cat.module, len(plan.lists)))
    a("| `field` lines | %d |" % plan.field_count())
    a("")
    a("| FRN | Item | Title | Type | Written as |")
    a("|---|---|---|---|---|")
    for e in plan.entries:
        if e["nodes"]:
            a("| %d | I%s/%s | %s | %s | %s |" % (e["frn"], cat.nnn, e["name"], e["title"], e["kind"], mapped_as(e)))
    a("")
    ex = next((i, k) for i, k in sorted(plan.names.items()) if "/" in i and not i.endswith(("[]", "#")))
    a("A key is named after its item and subitems: `%s.%s` is I%s/%s. The meaning of" % (cat.module, ex[1], cat.nnn, ex[0]))
    a("every key, with its table of values or its LSB and unit, is in `model/%s.def`." % cat.module)


def md_items_uaps(a, plan):
    """pack.md: md_items for a category of SWITCHED_UAPS, one row per item with its FRN in each UAP."""
    cat = plan.cat
    items = [e for e in plan.unique_entries() if e["nodes"]]
    a("")
    a("## Items")
    a("")
    a("| | Count |")
    a("|---|---|")
    for arm in plan.arms:
        a("| FRNs in UAP `%s` | %d |" % (arm["name"], len(arm["entries"])))
    for kind in ("fixed", "extended", "repetitive", "compound", "explicit"):
        n = sum(1 for e in items if e["kind"] == kind)
        if n:
            a("| items mapped, %s | %d |" % (kind, n))
    for arm in plan.arms:
        a("| not mapped in UAP `%s` | %d |" % (arm["name"], sum(1 for e in arm["entries"] if e["nodes"] is None)))
    a("| keys of `%s` | %d |" % (cat.module, len(plan.keys)))
    a("| lists of `%s` | %d |" % (cat.module, len(plan.lists)))
    a("| `field` lines (an item of two UAPs has its lines in each case) | %d |" % plan.field_count())
    a("")
    a("| Item | Title | Type | %s | Written as |" % " | ".join("FRN in `%s`" % arm["name"] for arm in plan.arms))
    a("|---|---|---|%s---|" % ("---|" * len(plan.arms)))
    for e in items:
        frns = [next((str(x["frn"]) for x in arm["entries"] if x["name"] == e["name"]), "-") for arm in plan.arms]
        a("| I%s/%s | %s | %s | %s | %s |" % (cat.nnn, e["name"], e["title"], e["kind"], " | ".join(frns), mapped_as(e)))
    a("")
    ex = next((i, k) for i, k in sorted(plan.names.items()) if "/" in i and not i.endswith(("[]", "#")))
    a("A key is named after its item and subitems: `%s.%s` is I%s/%s. The meaning of" % (cat.module, ex[1], cat.nnn, ex[0]))
    a("every key, with its table of values or its LSB and unit, is in `model/%s.def`." % cat.module)


def md_not_mapped(a, plan):
    """pack.md: the FRNs with no `if` block and why, explicit items, items no FRN names."""
    cat = plan.cat
    a("")
    a("## Items not mapped")
    a("")
    if plan.sel:
        return md_not_mapped_uaps(a, plan)
    unm = [e for e in plan.entries if e["nodes"] is None]
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
    expl = [e for e in plan.entries if e["nodes"] and e["kind"] == "explicit"]
    if expl:
        a("")
        a("Mapped without content: %s. Decode reads the length octet and passes over the content; no key holds it," %
          ", ".join("FRN %d (%s, %s)" % (e["frn"], e["name"], e["title"]) for e in expl))
        a("so encode never writes the item, and a same-format round trip of a record that holds one returns the")
        a("record without it.")
    notin = [n for n in cat.catalogue if n not in [e["name"] for e in plan.entries]]
    if notin:
        a("")
        a("Items of the catalogue that the UAP read here does not name, and that the pack therefore does not hold: %s." %
          ", ".join("I%s/%s" % (cat.nnn, n) for n in notin))


def md_not_mapped_uaps(a, plan):
    """pack.md: md_not_mapped for a category of SWITCHED_UAPS."""
    cat = plan.cat
    a("No `if` line of the case read names these FSPEC bits. A record of that UAP with one of them set fails")
    a("to decode with `malformed-wire`, and encode never sets them.")
    a("")
    a("| UAP | FRN | Item | Reason |")
    a("|---|---|---|---|")
    for arm in plan.arms:
        for e in arm["entries"]:
            if e["nodes"] is None:
                a("| `%s` | %d | %s | %s |" % (arm["name"], e["frn"], "I%s/%s %s" % (cat.nnn, e["name"], e["title"]) if e["name"] else "-",
                                             e["reason"]))
    expl = [e for e in plan.unique_entries() if e["nodes"] and e["kind"] == "explicit"]
    if expl:
        a("")
        a("Mapped without content: %s. Decode reads the length octet and passes over the content; no key holds it," %
          ", ".join("%s, %s (FRN %s)" % (e["name"], e["title"], " and ".join(
              "%d in `%s`" % (x["frn"], arm["name"]) for arm in plan.arms for x in arm["entries"] if x["name"] == e["name"]))
              for e in expl))
        a("so encode never writes the item, and a same-format round trip of a record that holds one returns the")
        a("record without it.")
    named = {e["name"] for e in plan.unique_entries()}
    notin = [n for n in cat.catalogue if n not in named]
    if notin:
        a("")
        a("Items of the catalogue that no UAP names, and that the pack therefore does not hold: %s." %
          ", ".join("I%s/%s" % (cat.nnn, n) for n in notin))


def md_shared_keys(a, plan):
    """pack.md: each shared key bound, how, and the text of the definition that supports it."""
    cat = plan.cat
    a("")
    a("## Shared-model keys")
    a("")
    binds = [b for b in plan.bindings]
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
            elif b["how"] == "chars":
                a("| `callsign` | I%s/%s | `field callsign … chars:icao6` (engine-spec 0.15): the characters as text, trailing spaces removed on decode; a code outside the ICAO set is `transform-decode`. The field's raw integer key stays declared in the module and is not on the line, as `also` keeps the transform | %s |"
                  % (cat.nnn, b["ident"], b["evidence"]))
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
        for b in binds:
            item = b["ident"].split("/")[0]
            held = [arm["name"] for arm in plan.arms if any(e["name"] == item for e in arm["entries"])]
            if plan.arms and len(held) < len(plan.arms):
                a("")
                a("`%s` stands in I%s/%s, which only UAP %s holds: it is read and written only in %s case. An entity" % (
                    b["key"], cat.nnn, item, ", ".join("`%s`" % h for h in held), "that"))
                a("converted from another format reaches it only when it also holds `%s` with that UAP's value." % plan.sel["key"])
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


def md_converting(a, plan):
    """pack.md: what encode writes."""
    cat = plan.cat
    a("")
    a("## Converting to this pack")
    a("")
    a("The kind has no `requires` line: the definition does not mark items as mandatory, so encode writes the")
    a("items whose keys the entity holds. A field of a written item whose key is absent is written as zero.")
    if plan.sel:
        a("The UAP follows `%s` as written (section \"The UAPs\"): an entity without it is written with UAP" % plan.sel["key"])
        a("`%s`, and keys of items only another UAP holds are left out." % plan.arms[0]["name"])
    a("Keys of `%s` that another format does not carry (SAC and SIC, for example) are given as context." % cat.module)


def md_beside_hand_written(a, plan):
    """pack.md of a renamed category: the generated pack beside the hand-written one."""
    cat = plan.cat
    if cat.num in RENAME:
        a("")
        a("## Beside the hand-written pack")
        a("")
        a("| | `asterix-cat062` (hand-written) | `%s` (generated) |" % cat.format)
        a("|---|---|---|")
        a("| written from | the EUROCONTROL document, edition 1.21 | the transcription of edition %s in `%s` |" % (cat.edition, REPO))
        a("| FRNs mapped | 7: I062/010, 070, 105, 185, 040, 080, 130 | %d of %d; a record with any item of the UAP decodes |" % (
            sum(1 for e in plan.entries if e["nodes"]), sum(1 for e in plan.entries if e["name"])))
        a("| module | `cat062`: 9 keys named by meaning (`sac`, `time_of_day_s`, `track_number`, `mon`, `cnf`, `sim`, `tse`, `cst`) | `%s`: %d keys and %d lists named by item (`i010_sac`, `i070`, `i040`, `i080_mon`) |" % (cat.module, len(plan.keys), len(plan.lists)))
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


def md_vectors(a, made, track_vec):
    """pack.md: one row per vector."""
    a("")
    a("## Vectors")
    a("")
    a("Input and expected bytes are computed by the generator from the definition, with a codec of its own;")
    a("the generator then reloads the pack and replays every vector through a second codec written from")
    a("`spec/engine-spec.md`.")
    a("")
    a("| File | Shows |")
    a("|---|---|")
    for fn, _, what in made:
        a("| `%s` | %s |" % (fn, what))
    if track_vec:
        a("| `packs/canonical-track-v2/vectors/%s.json` | from `canonical-track-v2` to this pack: %s |" % (track_vec["name"], track_vec["reference"]))
    a("")


def emit_pack_md(plan, sha, made, track_vec):
    """The text of pack.md. `made` is the vectors of the pack as `make_vectors` returns them."""
    lines = []
    a = lines.append
    md_intro(a, plan, sha)
    md_layout(a, plan)
    md_items(a, plan)
    md_not_mapped(a, plan)
    md_shared_keys(a, plan)
    md_converting(a, plan)
    md_beside_hand_written(a, plan)
    md_vectors(a, made, track_vec)
    return "\n".join(lines)


def emit_pack_provenance(cat, sha, master, definition_sha256):
    """The text of the pack's PROVENANCE.md: edition, where the definition is, both commits and
    the SHA-256 of the definition file."""
    return "\n".join([
        "# Provenance: %s" % cat.format, "",
        "| Fact | Value |", "|---|---|",
        "| category | ASTERIX Category %s, %s |" % (cat.nnn, cat.title),
        "| edition | %s, dated %s in the definition |" % (cat.edition, cat.date),
        "| specified by | EUROCONTROL (https://www.eurocontrol.int/asterix) |",
        "| definition read | `%s` of https://github.com/%s |" % (cat.rel, REPO),
        "| commit (branch `gh-pages`, the published JSON) | `%s` |" % sha,
        "| built from commit (branch `master`) | `%s` |" % master,
        "| SHA-256 of the definition | `%s` |" % definition_sha256,
        "| licence of the repository | BSD 3-Clause, copyright (c) 2019 KZPS (`LICENSE` at the `master` commit; verbatim in `sources/PROVENANCE.md`) |",
        "| generator | `tools/gen/asterix2pack.py`; key names pinned in `tools/gen/names/%s.json` |" % cat.format,
        ""])


def emit_names(names):
    """The text of a names file: item path -> key name, sorted by item path."""
    return json.dumps(OrderedDict(sorted(names.items())), indent=1)


# ---------------------------------------------------------------- one category

def module_path(cat):
    return "model/%s.def" % cat.module


def pack_dir(cat):
    return "packs/" + cat.format


def names_path(cat):
    return "tools/gen/names/%s.json" % cat.format


def track_vector_path(cat):
    """The vector that converts a track to this pack belongs to the pack that owns its input."""
    return "packs/canonical-track-v2/vectors/gen-to-%s.json" % cat.format


class Generated:
    """Everything one category gives: the plan, and the text of every file, by output path.
    `vectors` holds the files of the pack's vectors directory apart, because the directory is
    emptied of other `*.json` files when it is written. `track_vector` is a text or None."""

    def __init__(self, plan):
        self.plan, self.cat = plan, plan.cat
        self.files = OrderedDict()
        self.vectors = OrderedDict()
        self.track_vector = None


def generate(cat, pinned, sha, master, definition_sha256):
    """Plan one category, emit its module and pack, load both back through gtcheck, check that
    they have the shape the codec reads, and make the vectors. Nothing is written here."""
    plan = plan_category(cat, pinned)
    module_text = emit_module(plan, sha)
    pack_text = emit_pack(plan, sha)
    model = shared_model()
    module = load_module(model, module_text, module_path(cat))
    if module.name != cat.module:
        raise GenError("the module is named %s" % module.name, file=module_path(cat))
    pack = load_pack(model, pack_text, pack_dir(cat) + "/pack.def")
    check_shape(pack, module)
    mapped_keys = {n["raw"].split(".", 1)[1] for e in plan.unique_entries() if e["nodes"]
                   for n, _ in walk_fields(e["nodes"]) if n["declare"]}
    if set(module.keys) != mapped_keys:
        raise GenError("module keys and mapped keys differ: %s" % sorted(set(module.keys) ^ mapped_keys)[:5],
                       file=module_path(cat))
    made, track_vec = make_vectors(plan, pack, model)
    g = Generated(plan)
    g.files[module_path(cat)] = module_text
    g.files[pack_dir(cat) + "/pack.def"] = pack_text
    g.files[pack_dir(cat) + "/pack.md"] = emit_pack_md(plan, sha, made, track_vec)
    g.files[pack_dir(cat) + "/PROVENANCE.md"] = emit_pack_provenance(cat, sha, master, definition_sha256)
    g.files[names_path(cat)] = emit_names(plan.names_file())
    for file_name, text, _ in made:
        g.vectors[pack_dir(cat) + "/vectors/" + file_name] = text
    if track_vec:
        g.track_vector = json_text(track_vec)
    return g


def vector_files(out, cat):
    """The `*.json` files of the pack's vectors directory as the run sees them, sorted."""
    vdir = pack_dir(cat) + "/vectors"
    return [vdir + "/" + name for name in out.listdir(vdir) if name.endswith(".json")]


def write_category(out, g):
    """Write the files of one category through genio. Vectors of an earlier run that this run
    does not write are removed, and so is a track vector the category no longer gives."""
    for rel in vector_files(out, g.cat):
        if rel not in g.vectors:
            out.remove(rel)
    for rel, text in list(g.vectors.items()) + list(g.files.items()):
        out.write(rel, ending_in_newline(text))
    if g.track_vector:
        out.write(track_vector_path(g.cat), ending_in_newline(g.track_vector))
    else:
        out.remove(track_vector_path(g.cat))


def remove_outputs(out, cat):
    """A category that failed leaves no files: remove what an earlier run wrote for it. The names
    file stays; it pins names across runs."""
    pdir = pack_dir(cat)
    for rel in vector_files(out, cat) + [pdir + "/" + f for f in ("pack.def", "pack.md", "PROVENANCE.md")] + \
            [module_path(cat), track_vector_path(cat)]:
        out.remove(rel)
    if not out.check:
        for d in (out.path(pdir + "/vectors"), out.path(pdir)):
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)


def read_names(out, cat):
    """The names file of an earlier run: item path -> key name. {} when there is none."""
    rel = names_path(cat)
    if not out.exists(rel):
        return {}
    try:
        names = json.loads(out.read(rel))
    except json.JSONDecodeError as x:
        raise GenError("not JSON: %s" % x.msg, file=rel, line=x.lineno)
    if not isinstance(names, dict) or not all(isinstance(v, str) for v in names.values()):
        raise GenError("not an object of item path -> key name", file=rel)
    return names


# ---------------------------------------------------------------- self-check: what was written, read back

def self_check(out, generated):
    """Read every module, pack and vector back as the run left them, load them through gtcheck
    into one model, and replay every vector through the codec -> the number replayed. A file that
    holds the output directory or the home directory as text is refused."""
    model = shared_model()
    packs = {}
    for g in generated:
        load_module(model, out.read(module_path(g.cat)), module_path(g.cat))
    needles = (out.root, os.path.expanduser("~"))
    for g in generated:
        cat, pdir = g.cat, pack_dir(g.cat)
        for rel in [pdir + "/" + name for name in out.listdir(pdir)] + vector_files(out, cat) + [module_path(cat)]:
            if any(needle in out.read(rel) for needle in needles):
                raise GenError("holds a local path", file=rel)
        pack = load_pack(model, out.read(pdir + "/pack.def"), pdir + "/pack.def")
        check_shape(pack, model.modules[cat.module])
        if pack.format != cat.format:
            raise GenError("the format is named %s" % pack.format, file=pdir + "/pack.def")
        packs[cat.format] = pack
    derives = all_derives(model)
    n = 0
    for g in generated:
        cat, seen = g.cat, set()
        track = track_vector_path(cat)
        for rel in vector_files(out, cat) + ([track] if out.exists(track) else []):
            v = json.loads(out.read(rel))
            if rel != track:
                if v["name"] in seen or v["from"] != cat.format:
                    raise GenError("vector name or owner", file=rel)
                seen.add(v["name"])
            try:
                replay(v, packs, derives)
            except GenError as x:
                raise GenError(x.message, file=x.file or rel)
            n += 1
    return n


def check_lib(lib):
    """Compare the built-in tables of `core`, `track`, `geojson` and `canonical-track-v2` with the
    files of a goat-transformers checkout; a difference is a GenError naming the file."""
    def text(rel):
        return read_text(lib, rel)

    def module(rel):
        try:
            return gtcheck.parse_module(text(rel), rel)
        except gtcheck.CheckError as e:
            raise GenError("%s: %s" % (e.kind, e.message), file=rel, line=e.line)

    def fields(rel):
        try:
            return [toks for _, toks in gtcheck.directive_lines(text(rel), rel) if toks[0] == "field"]
        except gtcheck.CheckError as e:
            raise GenError("%s: %s" % (e.kind, e.message), file=rel, line=e.line)

    differs = "of --lib differs from the built-in table %s of the generator"
    if module("model/core.def").keys != dict(CORE_KEYS):
        raise GenError(differs % "CORE_KEYS", file="model/core.def")
    track = module("model/track.def")
    if track.keys != dict(TRACK_KEYS) or tuple(track.lists) != TRACK_LISTS:
        raise GenError(differs % "TRACK_KEYS", file="model/track.def")
    if [(d.target, d.function + (":" + d.parameter if d.parameter is not None else ""), d.arguments)
            for d in track.derives] != TRACK_DERIVES:
        raise GenError(differs % "TRACK_DERIVES", file="model/track.def")
    if [(a[1], a[2]) for a in fields("packs/geojson/pack.def")] != GEOJSON_FIELDS:
        raise GenError(differs % "GEOJSON_FIELDS", file="packs/geojson/pack.def")
    have = {(a[1], a[2], a[3]) for a in fields("packs/canonical-track-v2/pack.def") if len(a) == 4}
    if not set(TRACK_JSON_FIELDS) <= have:
        raise GenError(differs % "TRACK_JSON_FIELDS", file="packs/canonical-track-v2/pack.def")


# ---------------------------------------------------------------- command line

def summary_line(g, n_vectors):
    """One line of the run report for a category that was written."""
    plan, cat = g.plan, g.cat
    mapped = plan.mapped()
    by_kind = ", ".join("%s %d" % (k, sum(1 for e in mapped if e["kind"] == k))
                        for k in ("fixed", "extended", "repetitive", "compound", "explicit")
                        if any(e["kind"] == k for e in mapped))
    return ("%s  edition %s  FRNs %d  mapped %d (%s)  not mapped %d  keys %d  lists %d  fields %d  vectors %d%s  shared: %s" % (
        cat.format, cat.edition, len(plan.entries), len(mapped), by_kind, len(plan.unmapped()), len(plan.keys),
        len(plan.lists), plan.field_count(), n_vectors, "+1 from track" if g.track_vector else "",
        ", ".join(b["key"] for b in plan.bindings) or "none"))


def sources_and_commits(args, out):
    """-> (commit of the published JSON, commit of its sources). With --commit the source files
    are listed (and with --fetch downloaded first) and sources/PROVENANCE.md is written; without
    it both commits are read back from that file."""
    root = out.root
    if not args.commit:
        return read_commits(read_text(root, SOURCES_PROVENANCE))
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise GenError("--commit takes a full 40-digit SHA")
    got, master = source_list(root, args.commit, download=curl if args.fetch else None)
    out.write(SOURCES_PROVENANCE, ending_in_newline(emit_sources_provenance(root, args.commit, got, master)))
    return args.commit, master


def run(args, out):
    """The whole run -> exit status. A category that is refused is reported and leaves no files;
    the others are still written."""
    root = out.root
    sha, master = sources_and_commits(args, out)
    manifest = read_json(root, SOURCES_DIR + "/manifest.json")
    avail = OrderedDict((n, (name, rel)) for n, name, rel in definition_files(manifest))
    others = other_edition_files(manifest)
    try:
        want = sorted(avail) if args.cats == "all" else [int(x) for x in args.cats.split(",")]
    except ValueError:
        raise GenError("--cats takes category numbers separated by commas, or `all`: %r" % args.cats)
    if args.lib:
        check_lib(args.lib)
    done, failed = [], []
    for n in [c for c in PRIORITY if c in want] + [c for c in want if c not in PRIORITY]:
        if n not in avail:
            failed.append((n, GenError("holds no category %03d" % n, file=SOURCES_DIR + "/manifest.json")))
            continue
        for name, rel, other in [avail[n] + (False,)] + [(on, orl, True) for on, orl in others.get(n, [])]:
            cat = None
            try:
                cat = load_category(root, name, rel, other)
                definition_sha256 = hashlib.sha256(read_bytes(root, cat.label)).hexdigest()
                g = generate(cat, read_names(out, cat), sha, master, definition_sha256)
                write_category(out, g)
                done.append(g)
            except (GenError, WireError) as x:
                if cat is not None:
                    remove_outputs(out, cat)
                label = SOURCES_DIR + "/" + name
                failed.append((n, GenError(x.message, file=x.file or label, line=x.line) if isinstance(x, GenError)
                               else GenError(str(x), file=label)))
    n_vec = self_check(out, done)
    for g in done:
        print(summary_line(g, len(g.vectors)))
        for e in g.plan.unmapped():
            if e["kind"] != "spare":
                print("    not mapped: FRN %d %s: %s" % (e["frn"], e["name"] or "", e["reason"]))
    for n, why in failed:
        print("cat%03d  NOT GENERATED: %s" % (n, why.message))
        print("%s: %s" % (NAME, why), file=sys.stderr)
    print("self-check: %d vectors replayed, %d packs" % (n_vec, len(done)))
    return 1 if failed else 0


def build_parser():
    ap = argparse.ArgumentParser(prog=NAME + ".py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    genio.add_arguments(ap, what="output root: holds sources/ (read), and model/, packs/, tools/gen/names/ (written)")
    ap.add_argument("--commit", metavar="SHA",
                    help="gh-pages commit of %s the sources are at; writes sources/PROVENANCE.md" % REPO)
    ap.add_argument("--fetch", action="store_true",
                    help="with --commit: download every source file at that commit with curl before reading it")
    ap.add_argument("--cats", default="all", metavar="LIST", help="comma-separated category numbers, or `all` (default)")
    ap.add_argument("--lib", metavar="DIR", help="goat-transformers checkout, to check the built-in tables against")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.fetch and not args.commit:
        ap.error("--fetch needs --commit: the commit names what to download")
    if args.fetch and args.check:
        ap.error("--fetch downloads the sources and --check writes nothing: use one of them")
    out = genio.Output(args.out, check=args.check)
    try:
        status = run(args, out)
    except GenError as x:
        print("%s: %s" % (NAME, x), file=sys.stderr)
        return 1
    return max(status, out.report(NAME))


if __name__ == "__main__":
    sys.exit(main())
