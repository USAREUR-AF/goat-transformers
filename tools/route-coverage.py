#!/usr/bin/env python3
"""No key is lost on a declared route without a written reason.

A route is a conversion a deployment runs: a source format and a target format.
The capability report of the engine specification (Ruling 6) names the keys the
source pack maps and the target pack does not: the route drops them. This tool
reads the routes of tools/route-coverage.txt and fails when

  - a route drops a key the file does not list for that route,
  - the file lists a key the route does not drop (the line is stale),
  - a line says `derived:<key>` and the target pack does not map <key>,
  - a line says `not-carried` and gives no reason.

    python3 -I tools/route-coverage.py --check          check every route
    python3 -I tools/route-coverage.py --print FROM TO  the lines a new route needs

tools/route-coverage.txt, tab-separated, one line per dropped key:

    <from>  <to>  <key>  <state>  <note>

<key> is a model key as the capability report writes it, or `<module>.*` for
every key of one module. <state> is `derived:<target key>` when the value
reaches the target through a derive line of the model (the report does not
consult derive lines), or `not-carried`, with the reason in <note>: the target
format has no place for it, or the pack does not map it yet.

Exit status: 0 ok, 1 a rule is broken (one line each), 2 a wrong command line.
Standard library only; run with -I.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "tools", "route-coverage.txt")
TOOL = os.path.join(ROOT, "engines", "python", "goat-xf-py.py")


def capability(src, dst, root=ROOT):
    """(carried, dropped) of the route, from the Python engine's tool."""
    packs = src if src == dst else src + "," + dst
    run = subprocess.run(
        [sys.executable, TOOL, "capability", "--packs", os.path.join(root, "packs"),
         "--packs-only", packs, "--from", src, "--to", dst],
        capture_output=True, text=True)
    if run.returncode != 0:
        raise ValueError("%s -> %s: %s" % (src, dst, run.stderr.strip().splitlines()[-1] if run.stderr.strip() else "no report"))
    cells = run.stdout.rstrip("\n").split("\t")
    cells += [""] * (5 - len(cells))
    return cells[3].split(), cells[4].split()


def read_table(text):
    """The routes of the table, in order: {(from, to): [(key, state, note, line number)]}."""
    routes, problems = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cells = [c.strip() for c in line.split("\t")]
        if len(cells) < 4:
            problems.append("line %d: needs <from> <to> <key> <state> [<note>], separated by tabs" % number)
            continue
        src, dst, key, state = cells[:4]
        note = cells[4] if len(cells) > 4 else ""
        routes.setdefault((src, dst), []).append((key, state, note, number))
    return routes, problems


def matches(pattern, key):
    return key.startswith(pattern[:-1]) if pattern.endswith(".*") else key == pattern


def check_route(src, dst, lines, dropped, target_keys):
    """The broken rules of one route, one text each."""
    out, used = [], set()
    for key in dropped:
        hit = [l for l in lines if matches(l[0], key)]
        if not hit:
            out.append("%s -> %s drops %s and tools/route-coverage.txt does not say why" % (src, dst, key))
        used.update(l[3] for l in hit)
    for key, state, note, number in lines:
        where = "line %d (%s -> %s, %s)" % (number, src, dst, key)
        if number not in used:
            out.append("%s: the route does not drop that key; remove the line" % where)
        if state.startswith("derived:"):
            if state[len("derived:"):] not in target_keys:
                out.append("%s: %s is not a key the pack %s maps" % (where, state[len("derived:"):], dst))
        elif state == "not-carried":
            if len(note) < 12:
                out.append("%s: not-carried needs a reason" % where)
        else:
            out.append("%s: state is derived:<target key> or not-carried, not %r" % (where, state))
    return out


def check(text, report=capability):
    routes, problems = read_table(text)
    for (src, dst), lines in routes.items():
        try:
            _, dropped = report(src, dst)
            target_keys, _ = report(dst, dst)
        except ValueError as error:
            problems.append(str(error))
            continue
        problems += check_route(src, dst, lines, dropped, set(target_keys))
    return problems, len(routes)


def main(argv):
    if argv == ["--check"]:
        with open(TABLE, encoding="utf-8") as handle:
            problems, count = check(handle.read())
        for line in problems:
            print("route-coverage: " + line)
        if problems:
            return 1
        print("route-coverage: ok, %d routes" % count)
        return 0
    if len(argv) == 3 and argv[0] == "--print":
        try:
            _, dropped = capability(argv[1], argv[2])
        except ValueError as error:
            print("route-coverage: %s" % error, file=sys.stderr)
            return 1
        for key in dropped:
            print("\t".join([argv[1], argv[2], key, "not-carried", ""]))
        return 0
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print("usage: route-coverage.py --check | --print <from> <to>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
