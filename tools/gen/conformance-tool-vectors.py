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


def licence_vectors():
    vectors = []

    def add(name, args, exit, out=None, kind=None):
        v = {"name": name, "args": args, "exit": exit}
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
    return vectors


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
