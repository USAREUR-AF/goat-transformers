#!/usr/bin/env python3
"""A pack never invents time quality (spec 0.32, "The rule").

    python3 -I tools/time-quality-guard.py [<root>]

For the time-quality keys of `core` (time_error_ms, time_state, time_utc_state,
time_utc_error_ms, time_anchor, time_anchor_age_ms, time_attested,
time_attestation), written bare or as `core.<key>`, it refuses:

  - a `default` line on one of them, in any pack (packs/*/pack.def);
  - an `absent` option on a field of one of them;
  - on a `bits` wire, a field of one of them that is neither `optional` nor
    inside a conditional block (`if`, `opt`, `chain`, `ext`, `choice`,
    `switch`), so an absent key is never written as zero bits;
  - a `derive` line whose target is one of them, in any model module
    (model/*.def), `core` included.

The engines load such a pack as any other; this check keeps it out of the
repository. Exit status: 0 ok, 1 a rule is broken (each on its own line).
Standard library only; run with -I.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gen"))
import gtcheck  # noqa: E402

KEYS = ("time_error_ms", "time_state", "time_utc_state", "time_utc_error_ms",
        "time_anchor", "time_anchor_age_ms", "time_attested", "time_attestation")
GATES = ("if", "opt", "chain", "ext", "choice", "switch")


def is_time_key(key):
    return key in KEYS or (key.startswith("core.") and key[5:] in KEYS)


def check_pack(text, label):
    """The broken rules of one pack.def, as messages."""
    out = []
    try:
        lines = gtcheck.directive_lines(text, label)
    except gtcheck.CheckError:
        return out              # gtcheck reports a pack that does not tokenize
    wire = next((toks[1] for _, toks in lines if toks[0] == "wire" and len(toks) > 1), None)
    stack = []                  # the blocks open at this line
    for line_no, toks in lines:
        d = toks[0]
        if (d in gtcheck.BLOCKS and not (d == "length" and "whole" in toks[1:])) or d == "switch":
            stack.append(d)     # gtcheck's rule for a line that opens a block closed by `end`
            continue
        if d == "end" and stack:
            stack.pop()
            continue
        if d == "default" and len(toks) > 1 and is_time_key(toks[1]):
            out.append("%s:%d: default on %s: time quality is never invented" % (label, line_no, toks[1]))
        if d == "field" and len(toks) > 1 and is_time_key(toks[1]):
            if "absent" in toks[2:]:
                out.append("%s:%d: absent on %s: time quality is never invented" % (label, line_no, toks[1]))
            if wire == "bits" and "optional" not in toks[2:] and not any(b in GATES for b in stack):
                out.append("%s:%d: %s on bits outside a conditional block and not optional: an absent key "
                           "would be written as zero bits" % (label, line_no, toks[1]))
    return out


def check_module(text, label):
    out = []
    try:
        lines = gtcheck.directive_lines(text, label)
    except gtcheck.CheckError:
        return out
    for line_no, toks in lines:
        if toks[0] == "derive" and len(toks) > 1 and is_time_key(toks[1]):
            out.append("%s:%d: derive of %s: time quality is never invented" % (label, line_no, toks[1]))
    return out


def run(root):
    errors = []
    for path in sorted(glob.glob(os.path.join(root, "packs", "*", "pack.def"))):
        with open(path, encoding="utf-8") as fh:
            errors += check_pack(fh.read(), os.path.relpath(path, root))
    for path in sorted(glob.glob(os.path.join(root, "model", "*.def"))):
        with open(path, encoding="utf-8") as fh:
            errors += check_module(fh.read(), os.path.relpath(path, root))
    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = argv[0] if argv else os.path.dirname(HERE)
    errors = run(root)
    for e in errors:
        print("time-quality-guard: " + e)
    if not errors:
        print("time-quality-guard: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
