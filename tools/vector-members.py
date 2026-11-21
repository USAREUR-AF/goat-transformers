#!/usr/bin/env python3
"""vector-members: every vector holds only the members spec/vector-format.md
defines for its kind, so no engine meets one it was not told about.

The members of each kind are read from the spec's own tables, so the spec
stays the one place that says what a vector may hold:

  conversion  packs/<format>/vectors/**/*.json      the table under "## File"
  load        packs/conformance/load-vectors/*.json  "## Load vectors"
  capability  packs/conformance/capability-vectors/*.json  "## Capability vectors"
  tool        packs/conformance/tool-vectors/*.json  "## Tool vectors"

A file that is not one JSON object, or that holds a member its kind's table
does not list, fails, named with the member. Text for people (where the bytes
come from, the derivation) goes in a conversion vector's `source` and
`reference`, which no engine reads: an engine that reads vectors strictly
(engines/go) refuses any other member.

Usage (run with -I; standard library only):

  python3 -I tools/vector-members.py          exit 1 on any vector with a member
                                              the spec does not define (CI)
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join("spec", "vector-format.md")
KINDS = (
    ("conversion", "## File", "packs/*/vectors/**/*.json"),
    ("load", "## Load vectors", "packs/conformance/load-vectors/*.json"),
    ("capability", "## Capability vectors", "packs/conformance/capability-vectors/*.json"),
    ("tool", "## Tool vectors", "packs/conformance/tool-vectors/*.json"),
)
ROW = re.compile(r"^\| `([A-Za-z_@][A-Za-z0-9_@]*)` \|", re.M)


class SpecError(Exception):
    pass


def members(spec_text, heading):
    """The members a table under `heading` lists (its first column)."""
    parts = re.split(r"^%s\n" % re.escape(heading), spec_text, maxsplit=1, flags=re.M)
    if len(parts) != 2:
        raise SpecError("%s has no section %r" % (SPEC, heading))
    section = re.split(r"^## ", parts[1], maxsplit=1, flags=re.M)[0]
    found = set(ROW.findall(section))
    if not found:
        raise SpecError("the section %r of %s has no table of members" % (heading, SPEC))
    return found


def check(root):
    """-> (problems, counts by kind)."""
    with open(os.path.join(root, SPEC), encoding="utf-8") as fh:
        spec = fh.read()
    problems, counts = [], {}
    for kind, heading, pattern in KINDS:
        allowed = members(spec, heading)
        files = sorted(glob.glob(os.path.join(root, pattern), recursive=True))
        counts[kind] = len(files)
        for path in files:
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            try:
                with open(path, encoding="utf-8") as fh:
                    vec = json.load(fh)
            except (OSError, ValueError) as e:
                problems.append("%s: not readable as JSON: %s" % (rel, e))
                continue
            if not isinstance(vec, dict):
                problems.append("%s: a %s vector is one JSON object" % (rel, kind))
                continue
            for m in sorted(set(vec) - allowed):
                hint = (" (text for people goes in `source` or `reference`)"
                        if kind == "conversion" and {"source", "reference"} <= allowed else "")
                problems.append("%s: member `%s` is not one %s defines for a %s vector%s"
                                % (rel, m, SPEC, kind, hint))
    return problems, counts


def main(argv=None, root=ROOT):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        problems, counts = check(root)
    except (OSError, SpecError) as e:
        print("vector-members: %s" % e, file=sys.stderr)
        return 1
    for p in problems:
        print("vector-members:", p, file=sys.stderr)
    if problems:
        print("vector-members: %d member%s the spec does not define" % (len(problems), "" if len(problems) == 1 else "s"),
              file=sys.stderr)
        return 1
    print("vector-members: ok, %s" % ", ".join("%d %s" % (n, k) for k, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
