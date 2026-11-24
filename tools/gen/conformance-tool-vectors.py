#!/usr/bin/env python3
"""Write the tool vectors that pin the command-line contract of spec 0.23
(spec/engine-spec.md, Version 0.23; spec/vector-format.md, Tool vectors).

Every expected output is worked out here, never by running an engine:

- a `capability` line from each capability vector of 0.11, which is pinned;
- a `matrix` from the `field` lines of three probe packs that have no kinds,
  groups or blocks (ruling 6 of 0.11), checked against the capability vectors
  that name the same pairs;
- a `list-formats` line from the `format`, `version` and `wire` lines of a
  pack;
- a `convert` result from a conversion vector of a `json` or hex wire, whose
  `expect` is the canonical output byte for byte;
- the exit status and error kind of a usage, load or call failure from the
  rule the contract states.

The script writes, and owns, packs/conformance/tool-vectors/. With --check
nothing is written, and the exit status is 1 when a committed file differs or
is missing or extra.

Usage: python3 -I tools/gen/conformance-tool-vectors.py [--out DIR] [--check]
"""
import json
import os
import shlex
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKS = os.path.join(ROOT, "packs")
OWNED = os.path.join("packs", "conformance", "tool-vectors")
P = ["--packs", "{packs}"]
CAP_011_LAST = 18     # the last capability vector of 0.11


def read_json(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return json.load(fh)


def pack_lines(fmt):
    """The non-comment lines of a pack, as token lists (quotes removed)."""
    out = []
    with open(os.path.join(PACKS, fmt, "pack.def"), encoding="utf-8") as fh:
        for line in fh:
            if line.lstrip().startswith("#") or not line.strip():
                continue
            out.append(shlex.split(line, comments=True))
    return out


def header(fmt):
    """`list-formats` line of a pack: format, version, wire."""
    got = {}
    for t in pack_lines(fmt):
        if t[0] in ("format", "version", "wire"):
            got[t[0]] = t[1]
    return "%s\t%s\t%s\n" % (got["format"], got["version"], got["wire"])


SIMPLE = {"format", "version", "distribution", "source", "uses", "wire", "root", "field"}


def model_keys(fmt):
    """Ruling 6a for a pack of `field` lines only: each key once, in order."""
    keys = []
    for t in pack_lines(fmt):
        if t[0] not in SIMPLE:
            raise SystemExit("%s: line %r is not a field line; derive its keys by hand" % (fmt, t))
        if t[0] == "field" and t[1] not in keys:
            keys.append(t[1])
    return keys


def report(src, dst):
    """Ruling 6d and 6e."""
    to_keys = model_keys(dst)
    carried = [k for k in model_keys(src) if k in to_keys]
    dropped = [k for k in model_keys(src) if k not in to_keys]
    grade = "none" if not carried else ("full" if not dropped else "partial")
    return grade, carried, dropped


def line(src, dst, grade, carried, dropped):
    return "%s\t%s\t%s\t%s\t%s\n" % (src, dst, grade, " ".join(carried), " ".join(dropped))


def only(*fmts):
    names = []
    for f in fmts:
        if f not in names:
            names.append(f)
    return ["--packs-only", ",".join(names)]


def build():
    """{file name: vector}."""
    vectors = []

    def add(name, args, exit, stdin=None, out=None, kind=None, any_out=False):
        v = {"name": name, "args": args}
        if stdin is not None:
            v["stdin_hex"] = stdin.hex() if isinstance(stdin, bytes) else stdin.encode("utf-8").hex()
        v["exit"] = exit
        if out is not None:
            v["stdout_text"] = out
        if any_out:
            v["stdout_any"] = True
        if kind is not None:
            v["error_kind"] = kind
        vectors.append(v)

    cap_a, cap_b, cap_c = "conformance-cap-a", "conformance-cap-b", "conformance-cap-c"

    # --- help: exit 0, text not compared
    add("help", ["help"], 0, any_out=True)
    add("help-short", ["-h"], 0, any_out=True)
    add("help-long", ["--help"], 0, any_out=True)
    add("help-ignores-what-follows", ["help", "convert", "--packs"], 0, any_out=True)

    # --- list-formats: byte order of format name, whatever the --packs-only order
    fmts = [cap_c, "conformance-json", cap_a, "conformance-absent-bits-lsb"]
    add("list-formats-byte-order", ["list-formats"] + P + only(*fmts), 0,
        out="".join(header(f) for f in sorted(fmts, key=lambda s: s.encode())))
    add("list-formats-one-pack", ["list-formats"] + only(cap_a) + P, 0, out=header(cap_a))
    add("max-items-leading-zeros", ["list-formats"] + P + only(cap_a) + ["--max-items", "0000000000000000000000001"],
        0, out=header(cap_a))
    add("max-items-largest", ["list-formats"] + P + only(cap_a) + ["--max-items", "9223372036854775807"],
        0, out=header(cap_a))
    add("max-items-zero", ["list-formats"] + P + only(cap_a) + ["--max-items", "0"], 0, out=header(cap_a))
    add("max-distribution-public-loads-a-public-pack",
        ["list-formats"] + P + only(cap_a) + ["--max-distribution", "public"], 0, out=header(cap_a))
    add("models-given", ["list-formats"] + P + ["--models", "{models}"] + only(cap_a), 0, out=header(cap_a))

    # --- capability: one line per pinned capability vector
    cap_dir = os.path.join("packs", "conformance", "capability-vectors")
    pinned = {}
    # The capability vectors of 0.11 (01 to 18) only: those of 0.34 (19 on)
    # load the pack an `inner` line names as well, which `--packs-only` of
    # the two formats does not, and adding them would renumber every vector
    # of 0.23 after these.
    for f in sorted(os.listdir(os.path.join(ROOT, cap_dir))):
        if int(f.split("-")[0]) > CAP_011_LAST:
            continue
        cv = read_json(os.path.join(cap_dir, f))
        pinned[(cv["from"], cv["to"])] = (cv["grade"], cv["carried"], cv["dropped"])
        add("capability-" + cv["name"], ["capability", "--from", cv["from"], "--to", cv["to"]] + P + only(cv["from"], cv["to"]),
            0, out=line(cv["from"], cv["to"], cv["grade"], cv["carried"], cv["dropped"]))

    # --- matrix of three probe packs, every ordered pair, a format with itself included
    trio = [cap_a, cap_b, cap_c]
    rows = ["from\tto\tgrade\tcarried\tdropped\n"]
    for s in sorted(trio, key=lambda x: x.encode()):
        for d in sorted(trio, key=lambda x: x.encode()):
            g = report(s, d)
            if (s, d) in pinned and pinned[(s, d)] != (g[0], g[1], g[2]):
                raise SystemExit("matrix pair %s -> %s differs from its capability vector" % (s, d))
            rows.append(line(s, d, *g))
    assert len(rows) == len(trio) ** 2 + 1
    add("matrix-three-formats", ["matrix"] + P + only(cap_c, cap_b, cap_a), 0, out="".join(rows))
    add("matrix-one-format", ["matrix"] + P + only(cap_a), 0,
        out=rows[0] + line(cap_a, cap_a, *report(cap_a, cap_a)))

    # --- convert: input and canonical output of pinned conversion vectors
    def from_vector(name, rel, hexwire=False, extra=()):
        cv = read_json(rel)
        args = ["convert", "--from", cv["from"], "--to", cv["to"]]
        for k, val in cv.get("context", {}).items():
            args += ["--set", "%s=%s" % (k, val)]
        args += list(extra) + P + only(cv["from"], cv["to"])
        if "expect_error" in cv:
            add(name, args, 1, stdin=cv["input"], kind=cv["expect_error"])
        else:
            add(name, args, 0, stdin=cv["input"], out=cv["expect"])
        return cv

    from_vector("convert-json-canonical-output", "packs/conformance-json/vectors/01-member-order-and-nested-residue.json")
    cv = from_vector("convert-bits-hex-text", "packs/conformance-absent-bits-lsb/vectors/01-every-field-holds-its-sentinel-roundtrip.json")
    # hex text may be surrounded by whitespace (ruling 36 of 0.8); no line feed is added to the result
    add("convert-hex-text-with-a-line-feed", ["convert", "--from", cv["from"], "--to", cv["to"]] + P + only(cv["from"]),
        0, stdin=cv["input"] + "\n", out=cv["expect"])
    from_vector("convert-set-is-the-context", "packs/conformance-absent-json/vectors/05-ruling-6-context-and-a-derivation-fill-keys-left-absent.json")
    from_vector("convert-malformed-wire", "packs/conformance-malformed-json/vectors/03-cut-after-the-opening-brace.json")
    from_vector("convert-transform-decode", "packs/conformance-absent-json/vectors/04-string-that-is-not-the-canonical-sentinel-on-a-float-field.json")

    a_in = '{"id":"x"}'
    conv_a = ["convert", "--from", cap_a, "--to", cap_a] + P + only(cap_a)
    add("convert-same-format-no-context", conv_a, 0, stdin=a_in, out=a_in)
    add("convert-json-with-a-line-feed", conv_a, 0, stdin=a_in + "\n", out=a_in)
    add("convert-set-fills-an-absent-key", conv_a + ["--set", "lat=1"], 0, stdin=a_in, out='{"id":"x","pos":{"lat":1}}')
    add("convert-set-twice-takes-the-last-value", conv_a + ["--set", "lat=abc", "--set", "lat=2.5"], 0,
        stdin=a_in, out='{"id":"x","pos":{"lat":2.5}}')
    add("convert-set-value-may-hold-equals", conv_a + ["--set", "callsign=a=b"], 0,
        stdin=a_in, out='{"id":"x","name":"a=b"}')
    add("convert-set-undeclared-key", conv_a + ["--set", "probe.nosuch=1"], 1, stdin=a_in, kind="undeclared-key")
    add("convert-set-key-with-a-space", conv_a + ["--set", "a b=1"], 1, stdin=a_in, kind="undeclared-key")
    add("convert-set-type-mismatch", conv_a + ["--set", "lat=abc"], 1, stdin=a_in, kind="key-type-mismatch")
    add("convert-set-checked-in-the-order-given", conv_a + ["--set", "probe.nosuch=1", "--set", "lat=abc"], 1,
        stdin=a_in, kind="undeclared-key")
    add("convert-set-checked-in-the-order-given-the-other-way", conv_a + ["--set", "lat=abc", "--set", "probe.nosuch=1"], 1,
        stdin=a_in, kind="key-type-mismatch")
    add("convert-set-repeated-key-keeps-its-first-place",
        conv_a + ["--set", "lat=abc", "--set", "probe.nosuch=1", "--set", "lat=1"], 1, stdin=a_in, kind="undeclared-key")
    add("convert-input-not-utf8", conv_a, 1, stdin=bytes.fromhex("7b226964223a22ff227d"), kind="malformed-wire")
    add("convert-empty-input", conv_a, 1, stdin="", kind="malformed-wire")
    add("convert-unknown-from", ["convert", "--from", "conformance-not-loaded", "--to", cap_a] + P + only(cap_a), 1,
        stdin=a_in, kind="unknown-format")
    add("convert-unknown-to", ["convert", "--from", cap_a, "--to", "conformance-not-loaded"] + P + only(cap_a), 1,
        stdin=a_in, kind="unknown-format")
    add("convert-unknown-format-before-the-input-is-read",
        ["convert", "--from", "conformance-not-loaded", "--to", cap_a] + P + only(cap_a), 1,
        stdin="not a message", kind="unknown-format")
    add("convert-empty-from", ["convert", "--from", "", "--to", cap_a] + P + only(cap_a), 1, stdin=a_in, kind="unknown-format")

    # --- capability failures and argument values
    add("capability-unknown-from", ["capability", "--from", "conformance-not-loaded", "--to", cap_a] + P + only(cap_a),
        1, kind="unknown-format")
    add("capability-unknown-to", ["capability", "--from", cap_a, "--to", "conformance-not-loaded"] + P + only(cap_a),
        1, kind="unknown-format")
    add("capability-value-that-looks-like-an-option", ["capability"] + P + ["--from", "--to", "--to", cap_a] + only(cap_a),
        1, kind="unknown-format")

    # --- load failures
    add("packs-only-unknown-name", ["list-formats"] + P + only(cap_a, "conformance-no-such-pack"), 1, kind="unknown-format")
    add("packs-only-dot-dot", ["list-formats"] + P + ["--packs-only", ".."], 1, kind="unknown-format")
    add("packs-only-dot", ["list-formats"] + P + ["--packs-only", "."], 1, kind="unknown-format")
    add("packs-only-a-path", ["list-formats"] + P + ["--packs-only", "conformance/../" + cap_a], 1, kind="unknown-format")
    add("packs-only-name-twice", ["list-formats"] + P + ["--packs-only", cap_a + "," + cap_a], 1, kind="duplicate-format")
    add("models-with-no-module", ["list-formats"] + P + ["--models", "{packs}/conformance/capability-vectors"] + only(cap_a),
        1, kind="unknown-module")
    add("models-that-do-not-exist", ["list-formats"] + P + ["--models", "{packs}/conformance-no-such-directory"] + only(cap_a),
        1, kind="unknown-module")
    add("packs-that-do-not-exist", ["matrix", "--packs", "{packs}/conformance-no-such-directory"], 1)
    # modules load before --packs is read: a failing module is the error even when --packs cannot be read
    add("a-failing-module-before-unreadable-packs",
        ["list-formats", "--packs", "{packs}/conformance-no-such-directory",
         "--models", "{packs}/conformance/tool-fixtures/bad-model"], 1, kind="unknown-directive")
    # with --packs-only, --packs is not listed: each name is looked up in it
    add("packs-only-in-packs-that-do-not-exist",
        ["list-formats", "--packs", "{packs}/conformance-no-such-directory"] + only(cap_a), 1, kind="unknown-format")

    # --- usage errors: exit 2, before anything is loaded
    usage = [
        ("no-argument", []),
        ("unknown-subcommand", ["transcode"] + P),
        ("subcommand-not-first", P + ["list-formats"]),
        ("help-after-the-subcommand", ["convert", "--help"]),
        ("unknown-option", ["list-formats"] + P + ["--x-no-such-option", "1"]),
        ("option-with-equals", ["list-formats", "--packs={packs}"]),
        ("prefix-of-an-option", ["list-formats", "--pack", "{packs}"]),
        ("single-dash-option", ["list-formats", "-packs", "{packs}"]),
        ("double-dash-alone", ["list-formats", "--"] + P),
        ("bare-word", ["matrix"] + P + ["foo"]),
        ("option-without-value", ["list-formats", "--packs"]),
        ("option-given-twice", ["list-formats"] + P + P),
        ("from-on-list-formats", ["list-formats"] + P + ["--from", cap_a]),
        ("set-on-capability", ["capability", "--from", cap_a, "--to", cap_a, "--set", "lat=1"] + P),
        ("convert-without-to", ["convert", "--from", cap_a] + P),
        ("convert-without-from", ["convert", "--to", cap_a] + P),
        ("capability-without-from", ["capability", "--to", cap_a] + P),
        ("set-without-equals", ["convert", "--from", cap_a, "--to", cap_a, "--set", "lat"] + P),
        ("set-with-empty-key", ["convert", "--from", cap_a, "--to", cap_a, "--set", "=1"] + P),
        ("max-items-plus", ["list-formats"] + P + ["--max-items", "+1"]),
        ("max-items-minus", ["list-formats"] + P + ["--max-items", "-1"]),
        ("max-items-decimal-point", ["list-formats"] + P + ["--max-items", "1.0"]),
        ("max-items-empty", ["list-formats"] + P + ["--max-items", ""]),
        ("max-items-above-2-63-minus-1", ["list-formats"] + P + ["--max-items", "9223372036854775808"]),
        ("max-distribution-unknown", ["list-formats"] + P + ["--max-distribution", "restricted"]),
        ("packs-only-empty", ["list-formats"] + P + ["--packs-only", ""]),
        ("packs-only-empty-name", ["list-formats"] + P + ["--packs-only", cap_a + ",," + cap_b]),
        ("packs-only-trailing-comma", ["list-formats"] + P + ["--packs-only", cap_a + ","]),
        ("usage-before-loading", ["convert", "--packs", "{packs}/conformance-no-such-directory", "--from"]),
    ]
    for name, args in usage:
        add("usage-" + name, args, 2)
    add("usage-before-reading-input", ["convert", "--from", cap_a] + P, 2, stdin=a_in)

    files = {}
    for i, v in enumerate(vectors, 1):
        fname = "%03d-%s.json" % (i, v["name"])
        files[fname] = json.dumps(v, indent=2, ensure_ascii=False) + "\n"
    assert len(vectors) < 100, "the vectors of 0.23 are numbered below 101"
    lic = licence_vectors()
    for i, v in enumerate(lic, 101):
        fname = "%03d-%s.json" % (i, v["name"])
        files[fname] = json.dumps(v, indent=2, ensure_ascii=False) + "\n"
    names = [v["name"] for v in vectors + lic]
    assert len(set(names)) == len(names), "a name is used twice"
    return files


# --------------------------------------------------------------------------
# Version 0.29: licence profiles (tool vectors from 101, their fixture trees)
# --------------------------------------------------------------------------

FIX = os.path.join("packs", "conformance", "tool-fixtures")
LIC_TAG = "SPDX-License-" + "Identifier"  # split so no tool reads this file as labelled
SRC = 'source  "goat-transformers spec/engine-spec.md, Version 0.29 (synthetic fixture, no external standard)"'

TABLE_ROWS = [
    # id, commercial, share_alike, field_of_use, distribution  -> profile (ruling 2a)
    ("Apache-2.0", "yes", "false", "[]", "public"),                   # open
    ("CC-BY-SA-4.0", "yes", "true", "[]", "public"),                  # open+copyleft
    ("CC-BY-NC-SA-4.0", "no", "true", "[]", "public"),                # everything
    ("CC-BY-4.0", "yes", "false", '["weapons that can harm humans"]', "public"),  # everything (field of use)
    ("LicenseRef-unstated", "unknown", "false", "[]", "public"),      # everything
    ("OGL-UK-3.0", "yes", "false", "[]", "controlled"),               # none
]


def table_text(rows, crlf=False, extra=""):
    out = ["# The flags of the fixture's licences (spec 0.29, ruling 1c).", ""]
    for lid, com, sa, fou, dist in rows:
        out += ['[licences."%s"]' % lid, 'name = "%s"' % lid, "commercial = \"%s\"" % com,
                "share_alike\t=  %s" % sa, "attribution = true", "field_of_use = %s" % fou,
                'distribution = "%s"' % dist, ""]
    text = "\n".join(out) + extra
    return text.replace("\n", "\r\n") if crlf else text


def module_text(name, uses=(), keys=()):
    lines = ["module %s" % name, "version 0.29.0", "distribution public", SRC.replace("source  ", "source ")]
    lines += ["uses %s" % u for u in uses]
    lines += ['key %s float - "a fixture key"' % k for k in keys]
    return "\n".join(lines) + "\n"


def pack_text(fmt, uses=(), extra=""):
    lines = ["format %s" % fmt, "version 0.29.0", "distribution public", SRC]
    lines += ["uses %s" % u for u in uses]
    lines += ["wire json", "field lat pos.lat float"]
    return "\n".join(lines) + "\n" + extra


def pack_reuse(*lids):
    out = ["version = 1"]
    for lid in lids:
        out += ["", "[[annotations]]", 'path = "**"', 'precedence = "override"',
                'SPDX-FileCopyrightText = "2026 goat-transformers fixture"', '%s = "%s"' % (LIC_TAG, lid)]
    return "\n".join(out) + "\n"


def module_licence(*lids, indent="", crlf=False):
    text = "SPDX-FileCopyrightText: 2026 goat-transformers fixture\n" + "".join(
        "%s%s:\t%s\n" % (indent, LIC_TAG, lid) for lid in lids)
    return text.replace("\n", "\r\n") if crlf else text


CORE = module_text("core", keys=["lat"])

# Tree a: one pack per profile, through its own licence or a module it uses.
# dir: (format, uses, pack licence or None, expected profile)
TREE_A_PACKS = {
    "plain": ("lic-plain", (), None, "open"),
    "copyleft": ("lic-copyleft", (), "CC-BY-SA-4.0", "open+copyleft"),
    "nc": ("lic-nc", (), "CC-BY-NC-SA-4.0", "everything"),
    "fou": ("lic-fou", (), "CC-BY-4.0", "everything"),
    "unstated": ("lic-unstated", (), "LicenseRef-unstated", "everything"),
    "not-in-table": ("lic-not-in-table", (), "CC0-1.0", "everything"),
    "closed": ("lic-closed", (), "OGL-UK-3.0", "none"),
    "uses-book": ("lic-uses-book", ("book",), None, "everything"),
    "uses-derived": ("lic-uses-derived", ("derived",), None, "everything"),
    "uses-sa": ("lic-uses-sa", ("sa",), None, "open+copyleft"),
    "zz-first-by-format": ("lic-aa", (), None, "open"),
}
TREE_A_MODULES = {
    "core.def": (CORE, None),
    "book.def": (module_text("book"), module_licence("CC-BY-NC-SA-4.0")),
    "derived.def": (module_text("derived", uses=["book"]), None),
    "sa.def": (module_text("sa"), module_licence("CC-BY-SA-4.0", indent="  ", crlf=True)),
}
RANK = ["open", "open+copyleft", "everything", "none"]


def licence_trees():
    """{repository path: bytes} of every fixture tree of 0.29."""
    files = {}

    def put(rel, text):
        files[os.path.join(FIX, rel)] = text.encode("utf-8")

    a = "licences-a"
    put(a + "/licences.toml", table_text(TABLE_ROWS))
    for f, (text, lic) in TREE_A_MODULES.items():
        put("%s/model/%s" % (a, f), text)
        if lic:
            put("%s/model/%s.license" % (a, f), lic)
    for d, (fmt, uses, lid, _) in TREE_A_PACKS.items():
        put("%s/packs/%s/pack.def" % (a, d), pack_text(fmt, uses))
        if lid:
            put("%s/packs/%s/REUSE.toml" % (a, d), pack_reuse(lid))

    # bad-table: field_of_use = [ ] is no form of ruling 1c
    t = "licences-bad-table"
    put(t + "/licences.toml", table_text(TABLE_ROWS[:1]).replace("field_of_use = []", "field_of_use = [ ]"))
    put(t + "/model/core.def", CORE)
    put(t + "/packs/plain/pack.def", pack_text("lic-plain"))

    # bad-pack: two licence lines in one pack's REUSE.toml (valid REUSE, two annotations)
    t = "licences-bad-pack"
    put(t + "/licences.toml", table_text(TABLE_ROWS))
    put(t + "/model/core.def", CORE)
    put(t + "/packs/plain/pack.def", pack_text("lic-plain"))
    put(t + "/packs/two/pack.def", pack_text("lic-two"))
    put(t + "/packs/two/REUSE.toml", pack_reuse("CC-BY-SA-4.0", "CC-BY-NC-SA-4.0"))

    # bad-module: a module nobody uses has two licence lines; read before any module loads (3b)
    t = "licences-bad-module"
    put(t + "/licences.toml", table_text(TABLE_ROWS))
    put(t + "/model/core.def", CORE)
    put(t + "/model/zz.def", module_text("zz"))
    put(t + "/model/zz.def.license", module_licence("CC-BY-SA-4.0", "Apache-2.0"))
    put(t + "/packs/plain/pack.def", pack_text("lic-plain"))

    # core-copyleft: core counts for every pack (2c); a broken pack is skipped unread (3d)
    t = "licences-core-copyleft"
    put(t + "/licences.toml", table_text(TABLE_ROWS, crlf=True))
    put(t + "/model/core.def", CORE)
    put(t + "/model/core.def.license", module_licence("CC-BY-SA-4.0"))
    put(t + "/packs/plain/pack.def", pack_text("lic-plain"))
    put(t + "/packs/broken/pack.def", pack_text("lic-broken", extra="frobnicate everything\n"))
    put(t + "/packs/broken/REUSE.toml", pack_reuse("CC-BY-NC-SA-4.0"))

    # no-table: without licences.toml only Apache-2.0 is known (1c)
    t = "licences-no-table"
    put(t + "/model/core.def", CORE)
    put(t + "/packs/plain/pack.def", pack_text("lic-plain"))
    put(t + "/packs/copyleft/pack.def", pack_text("lic-copyleft"))
    put(t + "/packs/copyleft/REUSE.toml", pack_reuse("CC-BY-SA-4.0"))
    return files


def file_value(data):
    """A value of `files`: the text, or the bytes as hex where the file is not
    UTF-8 text or holds a control character other than tab and line feed."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"hex": data.hex()}
    if any(unicodedata.category(c) == "Cc" and c not in "\t\n" for c in text):
        return {"hex": data.hex()}
    return text


def licence_vectors():
    vectors = []

    def add(name, args, exit, out=None, kind=None, tree_files=None):
        v = {"name": name, "args": args}
        if tree_files is not None:
            v["files"] = {path: file_value(data) for path, data in sorted(tree_files.items())}
        v["exit"] = exit
        if out is not None:
            v["stdout_text"] = out
        if kind is not None:
            v["error_kind"] = kind
        vectors.append(v)

    def tree(t):
        return ["--packs", "%s/%s/packs" % (FIX.replace(os.sep, "/"), t)]

    A = tree("licences-a")
    rows = sorted(TREE_A_PACKS.items(), key=lambda kv: kv[0].encode())

    def held(prof, p):
        return RANK.index(prof) <= RANK.index(p)

    def text_list(p=None):
        return "".join("%s\t%s\t%s\t%s\n" % (d, fmt, lid or "Apache-2.0", prof)
                       for d, (fmt, _, lid, prof) in rows if p is None or held(prof, p))

    def json_list(p=None):
        objs = ['{"pack":"%s","format":"%s","licence":"%s","profile":"%s"}' % (d, fmt, lid or "Apache-2.0", prof)
                for d, (fmt, _, lid, prof) in rows if p is None or held(prof, p)]
        return '{"packs":[' + ",".join(objs) + "]}\n"

    def formats(p=None):
        fmts = sorted((fmt for _, (fmt, _, _, prof) in rows if p is None or held(prof, p)), key=lambda s: s.encode())
        return "".join("%s\t0.29.0\tjson\n" % f for f in fmts)

    add("licences-every-pack", ["licences"] + A, 0, out=text_list())
    for p in ("open", "open+copyleft", "everything"):
        add("licences-profile-" + p.replace("+", "-"), ["licences"] + A + ["--profile", p], 0, out=text_list(p))
    add("licences-json", ["licences"] + A + ["--json"], 0, out=json_list())
    add("licences-json-first", ["licences", "--json"] + A, 0, out=json_list())
    add("licences-json-between", ["licences", "--profile", "open", "--json"] + A, 0, out=json_list("open"))
    add("list-formats-every-pack", ["list-formats"] + A, 0, out=formats())
    add("list-formats-profile-open", ["list-formats"] + A + ["--profile", "open"], 0, out=formats("open"))
    add("list-formats-profile-open-copyleft", ["list-formats"] + A + ["--profile", "open+copyleft"], 0,
        out=formats("open+copyleft"))
    add("packs-only-skips-a-pack-outside-the-profile",
        ["list-formats"] + A + ["--profile", "open", "--packs-only", "nc,plain"], 0, out="lic-plain\t0.29.0\tjson\n")
    add("packs-only-skips-it-twice",
        ["list-formats"] + A + ["--profile", "open", "--packs-only", "nc,nc,plain"], 0, out="lic-plain\t0.29.0\tjson\n")
    add("packs-only-name-checks-first",
        ["list-formats"] + A + ["--profile", "open", "--packs-only", "no-such-pack"], 1, kind="unknown-format")
    add("convert-a-format-outside-the-profile",
        ["convert", "--from", "lic-nc", "--to", "lic-plain", "--profile", "open"] + A, 1, kind="unknown-format")
    add("capability-a-format-outside-the-profile",
        ["capability", "--from", "lic-plain", "--to", "lic-copyleft", "--profile", "open"] + A, 1, kind="unknown-format")
    add("matrix-profile-open", ["matrix", "--profile", "open", "--packs-only", "plain,copyleft"] + A, 0,
        out="from\tto\tgrade\tcarried\tdropped\nlic-plain\tlic-plain\tfull\tlat\t\n")
    add("closed-is-in-no-profile", ["list-formats", "--profile", "everything", "--packs-only", "closed"] + A, 0, out="")

    add("bad-table-with-a-profile", ["list-formats", "--profile", "everything"] + tree("licences-bad-table"), 1,
        kind="bad-licence")
    add("bad-table-without-a-profile", ["list-formats"] + tree("licences-bad-table"), 0, out="lic-plain\t0.29.0\tjson\n")
    add("bad-table-licences", ["licences"] + tree("licences-bad-table"), 1, kind="bad-licence")
    add("bad-pack-when-reached", ["list-formats", "--profile", "everything"] + tree("licences-bad-pack"), 1,
        kind="bad-licence")
    add("bad-pack-not-reached", ["list-formats", "--profile", "everything", "--packs-only", "plain"]
        + tree("licences-bad-pack"), 0, out="lic-plain\t0.29.0\tjson\n")
    add("bad-module-read-before-loading", ["list-formats", "--profile", "open", "--packs-only", "plain"]
        + tree("licences-bad-module"), 1, kind="bad-licence")
    add("bad-module-without-a-profile", ["list-formats", "--packs-only", "plain"] + tree("licences-bad-module"), 0,
        out="lic-plain\t0.29.0\tjson\n")
    add("core-counts-for-every-pack", ["list-formats", "--profile", "open"] + tree("licences-core-copyleft"), 0, out="")
    add("core-counts-and-a-broken-pack-is-skipped",
        ["list-formats", "--profile", "open+copyleft"] + tree("licences-core-copyleft"), 0,
        out="lic-plain\t0.29.0\tjson\n")
    add("a-broken-pack-held-is-loaded", ["list-formats", "--profile", "everything"] + tree("licences-core-copyleft"),
        1, kind="unknown-directive")
    add("no-table-knows-only-apache", ["licences", "--profile", "open+copyleft"] + tree("licences-no-table"), 0,
        out="plain\tlic-plain\tApache-2.0\topen\n")
    add("no-table-every-pack", ["licences"] + tree("licences-no-table"), 0,
        out="copyleft\tlic-copyleft\tCC-BY-SA-4.0\teverything\nplain\tlic-plain\tApache-2.0\topen\n")

    for name, args in [
        ("profile-unknown", ["list-formats"] + A + ["--profile", "commercial"]),
        ("profile-empty", ["list-formats"] + A + ["--profile", ""]),
        ("profile-upper-case", ["list-formats"] + A + ["--profile", "Open"]),
        ("profile-without-value", ["list-formats"] + A + ["--profile"]),
        ("profile-twice", ["list-formats"] + A + ["--profile", "open", "--profile", "open"]),
        ("json-on-list-formats", ["list-formats"] + A + ["--json"]),
        ("json-twice", ["licences", "--json", "--json"] + A),
        ("json-with-a-value", ["licences"] + A + ["--json=yes"]),
        ("licences-with-from", ["licences"] + A + ["--from", "lic-plain"]),
    ]:
        add("usage-" + name, args, 2)
    controlled_vectors(add)
    return vectors


# --------------------------------------------------------------------------
# Version 0.93: a controlled pack or module is in no profile (tool vectors
# from 139). Every expected output below is written out literally. Each vector
# carries its tree in `files`: no controlled file stands in the repository.
# --------------------------------------------------------------------------

PUB, CTL = "distribution public", "distribution controlled"


def text93(kind, name, *dist, uses=(), extra=""):
    """A module or pack with the `distribution` lines given as they stand."""
    lines = ["%s %s" % (kind, name), "version 0.93.0"] + list(dist)
    lines.append('source "goat-transformers spec/engine-spec.md, Version 0.93 (synthetic fixture, no external standard)"')
    lines += ["uses %s" % u for u in uses]
    if kind == "format":
        lines += ["wire json", "field lat pos.lat float"]
    elif name == "core":
        lines.append('key lat float - "a fixture key"')
    return "\n".join(lines) + "\n" + extra


# The forms of the `distribution` line of a pack.def: (directory, lines).
# By ruling 1 a pack of the first list is not shown public; one of the second is.
MARKED_FORMS = [
    ("m-adjacent-quote", ['distribution"public"']),
    ("m-alone", ["distribution"]),
    ("m-carriage-return-before", ["\rdistribution public"]),
    ("m-carriage-return-between", ["distribution\rpublic"]),
    ("m-comment", ["distribution public # note"]),
    ("m-controlled", [CTL]),
    ("m-controlled-tabs", ["\tdistribution\tcontrolled\t"]),
    ("m-extra-token", ["distribution public public"]),
    ("m-no-line", []),
    ("m-other-value", ["distribution restricted"]),
    ("m-public-and-adjacent-quote", [PUB, 'distribution"controlled"']),
    ("m-public-and-carriage-return", [PUB, "\rdistribution controlled"]),
    ("m-public-and-comment", [PUB, "distribution # x"]),
    ("m-public-and-longer-word", [PUB, "distributions controlled"]),
    ("m-public-and-quote-inside", [PUB, 'distri"bution" controlled']),
    ("m-public-and-quoted-line", [PUB, '"distribution public"']),
    ("m-public-and-quoted-word", [PUB, '"distribution" controlled']),
    ("m-quoted", ['distribution "public"']),
    ("m-quoted-controlled", ['distribution "controlled"']),
    ("m-quoted-word", ['"distribution" public']),
    ("m-two-lines", [PUB, CTL]),
    ("m-two-lines-reversed", [CTL, PUB]),
    ("m-upper-case-value", ["distribution Public"]),
]
UNMARKED_FORMS = [
    ("u-commented-out", ["# distribution controlled", PUB]),
    ("u-plain", [PUB]),
    ("u-source-text", [PUB, 'source "distribution controlled"']),
    ("u-spaces-and-tabs", [" \tdistribution \t public\t "]),
]


def controlled_trees():
    """{tree: {path: bytes}} of the trees of 0.93."""
    trees = {}

    def put(rel, text):
        t, path = rel.split("/", 1)
        trees.setdefault(t, {})[path] = text if isinstance(text, bytes) else text.encode("utf-8")

    def start(t, core=PUB):
        put(t + "/licences.toml", table_text(TABLE_ROWS))
        put(t + "/model/core.def", text93("module", "core", core))

    def pack(t, d, *dist, lid=None, uses=(), extra="", lids=()):
        put("%s/packs/%s/pack.def" % (t, d), text93("format", "c-" + d, *dist, uses=uses, extra=extra))
        if lid or lids:
            put("%s/packs/%s/REUSE.toml" % (t, d), pack_reuse(*(lids or [lid])))

    # packs: controlled packs under an open, a copyleft and a non-commercial
    # licence, beside a public pack under each
    t = "packs"
    start(t)
    put(t + "/model/ctl.def", text93("module", "ctl", CTL))
    for d, dist in (("ctl", CTL), ("pub", PUB)):
        pack(t, d + "-apache", dist)
        pack(t, d + "-nc", dist, lid="CC-BY-NC-SA-4.0")
        pack(t, d + "-sa", dist, lid="CC-BY-SA-4.0")
    pack(t, "ctl-uses-ctl", CTL, uses=["ctl"])

    # module: a controlled module under a public licence, used directly and through others
    t = "module"
    start(t)
    put(t + "/model/ctl.def", text93("module", "ctl", CTL))
    put(t + "/model/mid.def", text93("module", "mid", PUB, uses=["ctl"]))
    put(t + "/model/top.def", text93("module", "top", PUB, uses=["mid"]))
    pack(t, "direct", PUB, uses=["ctl"])
    pack(t, "plain", PUB)
    pack(t, "through", PUB, uses=["mid"])
    pack(t, "through-two", PUB, uses=["top"])

    # core: a controlled core; every pack uses it. The module zz is public.
    t = "core"
    start(t, CTL)
    put(t + "/model/zz.def", text93("module", "zz", PUB))
    pack(t, "ctl", CTL)
    pack(t, "pub", PUB)

    # unread: a marked pack that does not load, and one with two licence lines
    t = "unread"
    start(t)
    pack(t, "broken", CTL, extra="frobnicate everything\n")
    pack(t, "plain", PUB)
    t = "bad-licence"
    start(t)
    pack(t, "plain", PUB)
    pack(t, "two", CTL, lids=["CC-BY-SA-4.0", "CC-BY-NC-SA-4.0"])

    # lines: the forms of the `distribution` line, in packs and in modules
    t = "lines"
    start(t)
    put(t + "/model/mc.def", text93("module", "mc", "distribution public # note"))
    put(t + "/model/mq.def", text93("module", "mq", 'distribution "public"'))
    put(t + "/model/mu.def", text93("module", "mu", "distribution\tpublic"))
    for d, lines in MARKED_FORMS + UNMARKED_FORMS:
        pack(t, d, *lines)
    # a byte-order mark directly before the one line
    put(t + "/packs/m-byte-order-mark/pack.def", "\ufeffdistribution public\n" + text93("format", "c-m-byte-order-mark"))
    # the same before `format`, with an exact line later
    put(t + "/packs/m-byte-order-mark-first/pack.def", "\ufeff" + text93("format", "c-m-byte-order-mark-first", PUB))
    # a byte that is not UTF-8, and a NUL byte, in a file that holds the exact line
    put(t + "/packs/m-not-utf-8/pack.def", text93("format", "c-m-not-utf-8", PUB).encode() + b"# \xff\n")
    pack(t, "m-nul", '"distribution" controlled', "\0", PUB)
    pack(t, "m-nul-in-a-comment", "# \0", PUB)
    pack(t, "m-uses-mc", PUB, uses=["mc"])
    pack(t, "m-uses-mq", PUB, uses=["mq"])
    pack(t, "u-uses-mu", PUB, uses=["mu"])

    # twice: two lines of the exact form; quoted-uses: a `uses` that 2b of 0.29 does not read
    t = "twice"
    start(t)
    pack(t, "twice", PUB, PUB)
    # core-not-utf-8: the name of core is not read, so it adds nothing (2b), and it is not loaded
    t = "core-not-utf-8"
    start(t)
    put(t + "/model/core.def", text93("module", "core", PUB).encode() + b"# \xff\n")
    pack(t, "plain", PUB)
    t = "quoted-uses"
    start(t)
    put(t + "/model/ctl.def", text93("module", "ctl", CTL))
    pack(t, "quoted", PUB, uses=['"ctl"'])
    # a module shown public whose `module` line 2b does not read: a comment, a
    # quoted name; used by a pack, and by another module
    t = "noted-name"
    start(t)
    put(t + "/model/mx.def", text93("module", "mx # note", PUB))
    pack(t, "uses-mx", PUB, uses=["mx"])
    t = "noted-name-module"
    start(t)
    put(t + "/model/mid.def", text93("module", "mid", PUB, uses=["mx"]))
    put(t + "/model/mx.def", text93("module", "mx # note", PUB))
    pack(t, "plain", PUB)
    t = "quoted-name"
    start(t)
    put(t + "/model/mx.def", text93("module", '"mx"', PUB))
    pack(t, "uses-mx", PUB, uses=["mx"])
    return trees


def controlled_vectors(add_vector):
    trees = controlled_trees()

    def add(name, args, exit, out=None, kind=None):
        t, = [a[1:] for a in args if a.startswith("@")]
        args = ["{files}/packs" if a.startswith("@") else a for a in args]
        add_vector("controlled-" + name, args, exit, out=out, kind=kind, tree_files=trees[t])

    def at(t):
        return ["--packs", "@" + t]

    P = at("packs")
    PROFILES = ("open", "open+copyleft", "everything")
    row = {"ctl-apache": "Apache-2.0\tnone", "ctl-nc": "CC-BY-NC-SA-4.0\tnone", "ctl-sa": "CC-BY-SA-4.0\tnone",
           "ctl-uses-ctl": "Apache-2.0\tnone", "pub-apache": "Apache-2.0\topen",
           "pub-nc": "CC-BY-NC-SA-4.0\teverything", "pub-sa": "CC-BY-SA-4.0\topen+copyleft"}
    held = {"open": ["pub-apache"], "open+copyleft": ["pub-apache", "pub-sa"],
            "everything": ["pub-apache", "pub-nc", "pub-sa"]}
    every = ["ctl-apache", "ctl-nc", "ctl-sa", "ctl-uses-ctl", "pub-apache", "pub-nc", "pub-sa"]

    def text(dirs):
        return "".join("%s\tc-%s\t%s\n" % (d, d, row[d]) for d in dirs)

    def js(dirs):
        return '{"packs":[' + ",".join('{"pack":"%s","format":"c-%s","licence":"%s","profile":"%s"}'
                                       % ((d, d) + tuple(row[d].split("\t"))) for d in dirs) + "]}\n"

    def formats(dirs):
        return "".join("c-%s\t0.93.0\tjson\n" % d for d in dirs)

    # rulings 2 and 7: each profile, and no profile
    add("licences-every-pack", ["licences"] + P, 0, out=text(every))
    add("licences-json-every-pack", ["licences", "--json"] + P, 0, out=js(every))
    add("list-formats-every-pack", ["list-formats"] + P, 0, out=formats(every))
    for p in PROFILES:
        add("licences-" + p.replace("+", "-"), ["licences", "--profile", p] + P, 0, out=text(held[p]))
        add("licences-json-" + p.replace("+", "-"), ["licences", "--json", "--profile", p] + P, 0, out=js(held[p]))
        add("list-formats-" + p.replace("+", "-"), ["list-formats", "--profile", p] + P, 0, out=formats(held[p]))
    # rulings 4, 5 and 7: the caller's limit
    add("limit-controlled-beside-a-profile",
        ["list-formats", "--profile", "everything", "--max-distribution", "controlled"] + P, 0,
        out=formats(held["everything"]))
    add("limit-public-beside-a-profile-skips-first",
        ["list-formats", "--profile", "everything", "--max-distribution", "public"] + P, 0,
        out=formats(held["everything"]))
    add("limit-public-without-a-profile", ["list-formats", "--max-distribution", "public"] + P, 1,
        kind="distribution-refused")
    # ruling 4: --packs-only, and a format that is as if it were not there
    for p in PROFILES:
        add("packs-only-" + p.replace("+", "-"), ["list-formats", "--profile", p, "--packs-only",
            "ctl-apache,pub-apache,ctl-sa,ctl-nc"] + P, 0, out=formats(["pub-apache"]))
    add("packs-only-a-marked-name-alone", ["list-formats", "--profile", "everything", "--packs-only", "ctl-apache"] + P,
        0, out="")
    add("packs-only-a-marked-name-twice",
        ["list-formats", "--profile", "everything", "--packs-only", "ctl-apache,ctl-apache"] + P, 0, out="")
    add("packs-only-a-marked-name-without-a-profile", ["list-formats", "--packs-only", "ctl-apache"] + P, 0,
        out=formats(["ctl-apache"]))
    add("convert-from-a-skipped-format", ["convert", "--from", "c-ctl-apache", "--to", "c-pub-apache", "--profile",
                                          "everything"] + P, 1, kind="unknown-format")
    add("matrix-without-a-skipped-format", ["matrix", "--profile", "open"] + P, 0,
        out="from\tto\tgrade\tcarried\tdropped\nc-pub-apache\tc-pub-apache\tfull\tlat\t\n")
    # ruling 2: through a controlled module. Without a profile the public
    # module mid, which uses it, is distribution-violation (0.8, ruling 29).
    for p in PROFILES:
        add("module-" + p.replace("+", "-"), ["licences", "--profile", p] + at("module"), 0,
            out="plain\tc-plain\tApache-2.0\topen\n")
    add("module-without-a-profile", ["list-formats", "--packs-only", "plain"] + at("module"), 1,
        kind="distribution-violation")
    for p in PROFILES:
        add("core-" + p.replace("+", "-"), ["licences", "--json", "--profile", p] + at("core"), 0,
            out='{"packs":[]}\n')
    add("core-without-a-profile", ["licences", "--packs-only", "ctl"] + at("core"), 0,
        out="ctl\tc-ctl\tApache-2.0\tnone\n")
    add("core-public-pack-without-a-profile", ["list-formats", "--packs-only", "pub"] + at("core"), 1,
        kind="distribution-violation")
    # rulings 3 and 4: a skipped pack is not otherwise read; its licence is read first
    add("a-broken-marked-pack-is-skipped", ["list-formats", "--profile", "everything"] + at("unread"), 0,
        out="c-plain\t0.93.0\tjson\n")
    add("a-broken-marked-pack-without-a-profile", ["list-formats"] + at("unread"), 1, kind="unknown-directive")
    add("a-marked-pack-with-a-bad-licence", ["list-formats", "--profile", "everything"] + at("bad-licence"), 1,
        kind="bad-licence")
    # ruling 1: the forms of the line
    unmarked = ["u-commented-out", "u-plain", "u-source-text", "u-spaces-and-tabs", "u-uses-mu"]
    for p in PROFILES:
        add("lines-" + p.replace("+", "-"), ["list-formats", "--profile", p] + at("lines"), 0, out=formats(unmarked))
    add("lines-marked-packs-that-load-without-a-profile",
        ["licences", "--max-distribution", "public", "--packs-only", "m-comment,m-quoted,m-uses-mc,m-uses-mq,u-plain"]
        + at("lines"), 0,
        out="m-comment\tc-m-comment\tApache-2.0\tnone\nm-quoted\tc-m-quoted\tApache-2.0\tnone\n"
            "m-uses-mc\tc-m-uses-mc\tApache-2.0\tnone\nm-uses-mq\tc-m-uses-mq\tApache-2.0\tnone\n"
            "u-plain\tc-u-plain\tApache-2.0\topen\n")
    add("no-line-without-a-profile", ["list-formats", "--packs-only", "m-no-line"] + at("lines"), 1,
        kind="missing-distribution")
    add("no-line-in-packs-only", ["list-formats", "--profile", "open", "--packs-only", "m-no-line,u-plain"]
        + at("lines"), 0, out="c-u-plain\t0.93.0\tjson\n")
    add("two-exact-lines-are-shown-public", ["list-formats", "--profile", "open"] + at("twice"), 1,
        kind="bad-directive")
    add("core-not-utf-8", ["list-formats", "--profile", "open"] + at("core-not-utf-8"), 1, kind="unknown-module")
    # ruling 4: 2b does not read a quoted `uses`, so the pack is held and its module is not there
    add("quoted-uses-of-a-skipped-module", ["list-formats", "--profile", "open"] + at("quoted-uses"), 1,
        kind="unknown-module")
    # ruling 2: a module that 2b gives no name is not loaded, also when it is shown public
    add("noted-module-name", ["list-formats", "--profile", "open"] + at("noted-name"), 1, kind="unknown-module")
    add("noted-module-name-without-a-profile", ["list-formats"] + at("noted-name"), 0, out="c-uses-mx\t0.93.0\tjson\n")
    add("noted-module-name-used-by-a-module", ["list-formats", "--profile", "open"] + at("noted-name-module"), 1,
        kind="unknown-module")
    add("quoted-module-name", ["list-formats", "--profile", "open"] + at("quoted-name"), 1, kind="unknown-module")


def fixture_problems(write):
    """Write, or compare, the fixture trees of 0.29 (this script owns
    packs/conformance/tool-fixtures/licences-*/). -> stale paths."""
    want = licence_trees()
    have = set()
    base = os.path.join(ROOT, FIX)
    for d in sorted(os.listdir(base)):
        if d.startswith("licences-"):
            for folder, _, names in os.walk(os.path.join(base, d)):
                have |= {os.path.relpath(os.path.join(folder, n), ROOT) for n in names}
    stale = []
    for rel in sorted(have - set(want)):
        stale.append(rel)
        if write:
            os.remove(os.path.join(ROOT, rel))
    for rel, data in sorted(want.items()):
        path = os.path.join(ROOT, rel)
        try:
            with open(path, "rb") as fh:
                same = fh.read() == data
        except OSError:
            same = False
        if not same:
            stale.append(rel)
            if write:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(data)
    return stale


def main(argv):
    out = os.path.join(ROOT, OWNED)
    check = "--check" in argv
    if "--out" in argv:
        out = os.path.join(argv[argv.index("--out") + 1], OWNED)
    files = build()
    have = set(os.listdir(out)) if os.path.isdir(out) else set()
    if check:
        bad = sorted(set(files) ^ {h for h in have if h.endswith(".json")})
        for name, text in files.items():
            path = os.path.join(out, name)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    if fh.read() != text:
                        bad.append(name)
        for b in bad:
            print("stale: %s/%s" % (OWNED, b), file=sys.stderr)
        fixtures = fixture_problems(write=False) if out == os.path.join(ROOT, OWNED) else []
        for b in fixtures:
            print("stale: %s" % b, file=sys.stderr)
        if bad or fixtures:
            return 1
        print("conformance-tool-vectors.py --check: ok (%d tool vectors)" % len(files), file=sys.stderr)
        return 0
    os.makedirs(out, exist_ok=True)
    for h in have:
        if h.endswith(".json") and h not in files:
            os.remove(os.path.join(out, h))
    for name, text in files.items():
        with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    if out == os.path.join(ROOT, OWNED):
        fixture_problems(write=True)
    print("wrote %d tool vectors to %s" % (len(files), OWNED))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
