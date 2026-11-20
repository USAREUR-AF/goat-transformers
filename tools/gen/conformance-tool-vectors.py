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
    for f in sorted(os.listdir(os.path.join(ROOT, cap_dir))):
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
    names = [v["name"] for v in vectors]
    assert len(set(names)) == len(names), "a name is used twice"
    return files


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
            print("stale: %s/%s" % (OWNED, b))
        return 1 if bad else 0
    os.makedirs(out, exist_ok=True)
    for h in have:
        if h.endswith(".json") and h not in files:
            os.remove(os.path.join(out, h))
    for name, text in files.items():
        with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    print("wrote %d tool vectors to %s" % (len(files), OWNED))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
