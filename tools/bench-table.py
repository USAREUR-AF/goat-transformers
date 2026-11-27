#!/usr/bin/env python3
"""bench-table: one table of the engines' benchmark runs (engine-spec 0.25).

Each engine runs bench/set.json with its own command (its README states it;
the conformance workflow runs all seven and keeps each run as an artifact,
bench-<engine>.jsonl). This tool reads such files and prints one Markdown
table: a row per vector of the set, a column per engine, each cell the time
of one conversion in microseconds, and a last row with the time the engine
took to load the set's packs, in milliseconds.

Usage:
  python3 -I tools/bench-table.py [--set bench/set.json] bench-rust.jsonl bench-go.jsonl ...
  python3 -I tools/bench-table.py --check bench-*.jsonl      check the files only

The engine of a file is the <engine> of its name bench-<engine>.jsonl (or the
file's stem). A file must be what ruling 2c states: one JSON object per line,
`{"vector": <path>, "iterations": <n>, "ns_per_op": <n>}` for each vector of
the set in its order, then `{"load": <packs>, "ns": <n>}`. A file that is not
is named on standard error and the exit status is 1. No number fails anything
(ruling 2d): the numbers are one machine at one time, and engines that ran on
different machines are not compared by this table, only listed side by side.
Standard library only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


class BadRun(Exception):
    pass


def engine_name(path):
    stem = os.path.basename(path)
    if stem.endswith(".jsonl"):
        stem = stem[:-len(".jsonl")]
    return stem[len("bench-"):] if stem.startswith("bench-") else stem


def is_count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def read_run(path, vectors):
    """The ns per op of each vector, in the set's order, and the load (packs, ns)."""
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    if len(lines) != len(vectors) + 1:
        raise BadRun("%s: %d lines, the set has %d vectors and one load line" % (path, len(lines), len(vectors)))
    ns = []
    for i, (line, want) in enumerate(zip(lines, vectors), 1):
        try:
            obj = json.loads(line)
        except ValueError:
            raise BadRun("%s:%d: not a JSON object" % (path, i))
        if not isinstance(obj, dict) or set(obj) != {"vector", "iterations", "ns_per_op"}:
            raise BadRun("%s:%d: not a vector line (vector, iterations, ns_per_op)" % (path, i))
        if obj["vector"] != want:
            raise BadRun("%s:%d: vector %r, the set has %r here" % (path, i, obj["vector"], want))
        if not (is_count(obj["iterations"]) and is_count(obj["ns_per_op"])):
            raise BadRun("%s:%d: iterations and ns_per_op are non-negative integers" % (path, i))
        ns.append(obj["ns_per_op"])
    try:
        last = json.loads(lines[-1])
    except ValueError:
        raise BadRun("%s:%d: not a JSON object" % (path, len(lines)))
    if not isinstance(last, dict) or set(last) != {"load", "ns"} or not (is_count(last["load"]) and is_count(last["ns"])):
        raise BadRun("%s:%d: not the load line (load, ns)" % (path, len(lines)))
    return ns, (last["load"], last["ns"])


def short(vector):
    """packs/<format>/vectors/<name>.json -> <format>/<name>"""
    parts = vector.split("/")
    name = parts[-1][:-len(".json")] if parts[-1].endswith(".json") else parts[-1]
    return "%s/%s" % (parts[1], name) if len(parts) >= 4 and parts[0] == "packs" else name


def us(ns):
    return "%.1f" % (ns / 1000.0)


def table(vectors, runs):
    names = [n for n, _, _ in runs]
    out = ["| Vector | " + " | ".join(names) + " |",
           "|---|" + "---:|" * len(names)]
    for i, v in enumerate(vectors):
        out.append("| `%s` | %s |" % (short(v), " | ".join(us(ns[i]) for _, ns, _ in runs)))
    out.append("| load, ms (packs) | %s |" % " | ".join(
        "%.0f (%d)" % (load[1] / 1e6, load[0]) for _, _, load in runs))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench-table", description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", default=os.path.join(REPO, "bench", "set.json"), help="the benchmark set")
    ap.add_argument("--check", action="store_true", help="check the files only, print no table")
    ap.add_argument("runs", nargs="+", metavar="bench-<engine>.jsonl")
    a = ap.parse_args(argv)
    with open(a.set, encoding="utf-8") as f:
        vectors = json.load(f)["vectors"]
    runs, bad = [], 0
    for path in a.runs:
        try:
            ns, load = read_run(path, vectors)
        except (BadRun, OSError) as e:
            print("bench-table: %s" % e, file=sys.stderr)
            bad += 1
            continue
        runs.append((engine_name(path), ns, load))
    if bad:
        return 1
    if a.check:
        print("bench-table: ok, %d run(s) of %d vectors" % (len(runs), len(vectors)), file=sys.stderr)
        return 0
    sys.stdout.write(table(vectors, runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
