#!/usr/bin/env python3
"""The shared model's core is governed like the specification: a change to
model/core.def or model/track.def carries a written decision record.

    python3 -I tools/model-governance.py --base <ref>
        For the change from <ref> (the target branch of a pull request) to
        HEAD: when it changes model/core.def or model/track.def, it must also
        add or change an ADR in docs/adr/ that
          - names each of those files in its section "## Changes",
          - has a section "## Consumers re-measured" with a table of at least
            one project row (the result of each consumer's comparison at the
            change, docs/consumer-proofs.md),
          - has a "Status:" line,
        and docs/adr/INDEX.md must list that ADR.

    python3 -I tools/model-governance.py
        Every ADR in docs/adr/ is listed in docs/adr/INDEX.md, numbered
        NNNN-<name>.md with no number used twice, and has a "Status:" line.

Exit status: 0 ok, 1 a rule is broken (each on its own line), 2 a wrong
command line. Standard library only; run with -I.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOVERNED = ("model/core.def", "model/track.def")
ADR = re.compile(r"^docs/adr/(\d{4})-[a-z0-9-]+\.md$")


def git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, check=True).stdout


def changed(root, base):
    """The files the change from `base` to HEAD adds, changes or deletes."""
    merge_base = git(root, "merge-base", base, "HEAD").strip()
    return [p for p in git(root, "diff", "--name-only", merge_base, "HEAD").splitlines() if p]


def section(text, heading):
    """The text of the `## heading` section, up to the next `## `."""
    m = re.search(r"^## %s\s*$(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    return m.group(1) if m else None


def adr_problems(root, rel, governed):
    """What an ADR lacks for a change to the `governed` files."""
    problems = []
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        text = fh.read()
    if not re.search(r"^Status: \S", text, re.M):
        problems.append("%s has no 'Status:' line" % rel)
    changes = section(text, "Changes")
    if changes is None:
        problems.append("%s has no section '## Changes'" % rel)
    else:
        for g in governed:
            if g not in changes:
                problems.append("%s: its '## Changes' section does not name %s" % (rel, g))
    measured = section(text, "Consumers re-measured")
    rows = [line for line in (measured or "").splitlines()
            if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line)]
    if measured is None:
        problems.append("%s has no section '## Consumers re-measured'" % rel)
    elif len(rows) < 2 or any("<" in r for r in rows[1:]):
        problems.append("%s: '## Consumers re-measured' needs a table with a filled row for each consumer" % rel)
    return problems


def index_problems(root):
    """Every ADR file is listed in INDEX.md; numbers are unique; each has a status."""
    problems, numbers = [], {}
    adr_dir = os.path.join(root, "docs", "adr")
    try:
        with open(os.path.join(adr_dir, "INDEX.md"), encoding="utf-8") as fh:
            index = fh.read()
    except OSError:
        return ["docs/adr/INDEX.md is missing"]
    for name in sorted(os.listdir(adr_dir)):
        if name in ("INDEX.md", "TEMPLATE.md") or not name.endswith(".md"):
            continue
        rel = "docs/adr/" + name
        m = ADR.match(rel)
        if not m:
            problems.append("%s is not named NNNN-<name>.md" % rel)
            continue
        if m.group(1) in numbers:
            problems.append("%s and %s have the same number" % (numbers[m.group(1)], rel))
        numbers[m.group(1)] = rel
        if "(%s)" % name not in index:
            problems.append("%s is not listed in docs/adr/INDEX.md" % rel)
        with open(os.path.join(adr_dir, name), encoding="utf-8") as fh:
            if not re.search(r"^Status: \S", fh.read(), re.M):
                problems.append("%s has no 'Status:' line" % rel)
    return problems


def check(root, base=None):
    problems = index_problems(root)
    if base is None:
        return problems
    files = changed(root, base)
    governed = [g for g in GOVERNED if g in files]
    if not governed:
        return problems
    adrs = [p for p in files if ADR.match(p) and os.path.isfile(os.path.join(root, p))]
    if not adrs:
        return problems + ["this change edits %s, so it must add or change an ADR in docs/adr/ "
                           "(start from docs/adr/TEMPLATE.md; AGENTS.md, the shared model is governed "
                           "like the specification)" % " and ".join(governed)]
    per_adr = {a: adr_problems(root, a, governed) for a in adrs}
    if any(not p for p in per_adr.values()):
        return problems  # one complete ADR is enough
    for p in per_adr.values():
        problems += p
    return problems


def main(argv, root=ROOT):
    if argv and (argv[0] != "--base" or len(argv) != 2):
        print(__doc__, file=sys.stderr)
        return 2
    base = argv[1] if argv else None
    try:
        problems = check(root, base)
    except (subprocess.CalledProcessError, OSError) as e:
        print("model-governance: cannot compare with %s: %s" % (base, e), file=sys.stderr)
        return 1
    for p in problems:
        print("model-governance: %s" % p, file=sys.stderr)
    if problems:
        return 1
    print("model-governance: ok" + ("" if base is None else " (change from %s)" % base))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
