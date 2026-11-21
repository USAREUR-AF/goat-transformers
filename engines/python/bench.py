#!/usr/bin/env python3
"""The benchmark of spec version 0.25, ruling 2, for the Python engine.

    python3 -I engines/python/bench.py [set.json]      # from the repository root

The set defaults to `bench/set.json`; the vector paths in it, `packs/` and
`model/` are read relative to the current directory. The run loads, into one
engine, only the packs the set's vectors name (each vector's `from` and `to`)
and the model modules those packs use, and times that. Then, for each vector
in order, it converts the input once and compares the output with `expect`;
a difference, or an error, stops the run with exit status 1 and a message on
standard error. Then it converts the input `iterations` times and times that.

Standard output holds one JSON line per vector, then one for the load, and
nothing else:

    {"vector": "<path as in the set>", "iterations": <n>, "ns_per_op": <integer>}
    {"load": <number of packs>, "ns": <integer>}

The numbers are measurements of one machine at one time (ruling 2d)."""

import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "src"))

from goat_transformers import Engine, GTError  # noqa: E402


def _bytes(vec, key):
    if key in vec:
        return vec[key].encode("utf-8")
    if key + "_b64" in vec:
        return base64.b64decode(vec[key + "_b64"])
    raise ValueError("the vector has neither %s nor %s_b64" % (key, key))


def run(set_path, out, err):
    with open(set_path, "r", encoding="utf-8") as fh:
        bench = json.load(fh)
    iterations = bench["iterations"]
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        err.write("bench: iterations must be an integer of 1 or more, got %r\n" % (iterations,))
        return 1
    vectors = []
    for rel in bench["vectors"]:
        with open(rel, "r", encoding="utf-8") as fh:
            vectors.append((rel, json.load(fh)))
    names = []
    for _, vec in vectors:
        for fmt in (vec["from"], vec["to"]):
            if fmt not in names:
                names.append(fmt)

    t0 = time.perf_counter_ns()
    engine = Engine.from_dir("packs", packs_only=names)
    load_ns = time.perf_counter_ns() - t0

    for rel, vec in vectors:
        src, dst = vec["from"], vec["to"]
        data = _bytes(vec, "input")
        expect = _bytes(vec, "expect")
        context = vec.get("context")
        limit = vec.get("max_items")
        try:
            got = engine.convert(src, dst, data, context, max_items=limit)
        except GTError as e:
            err.write("bench: %s: convert(%s -> %s) failed: %s\n" % (rel, src, dst, e))
            return 1
        if got != expect:
            err.write(
                "bench: %s: convert(%s -> %s) differs from expect\n  got:    %s\n  expect: %s\n"
                % (rel, src, dst, got.decode("utf-8", "replace"), expect.decode("utf-8", "replace"))
            )
            return 1
        convert = engine.convert
        t0 = time.perf_counter_ns()
        for _ in range(iterations):
            convert(src, dst, data, context, max_items=limit)
        total = time.perf_counter_ns() - t0
        line = json.dumps({"vector": rel, "iterations": iterations, "ns_per_op": total // iterations})
        out.write(line + "\n")
        out.flush()
    out.write(json.dumps({"load": len(engine.packs), "ns": load_ns}) + "\n")
    out.flush()
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) > 1:
        sys.stderr.write("usage: bench.py [set.json]\n")
        return 2
    try:
        return run(argv[0] if argv else os.path.join("bench", "set.json"), sys.stdout, sys.stderr)
    except (OSError, ValueError, KeyError) as e:
        sys.stderr.write("bench: %s\n" % (e,))
        return 1


if __name__ == "__main__":
    sys.exit(main())
