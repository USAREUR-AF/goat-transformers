"""Parse once (spec/engine-spec.md, Version 0.25, Ruling 1).

The engine keeps, for the life of an instance, what it parsed at load and the
layouts it works out from it (ruling 1a). These tests state that keeping is
not observable (1b), also from several threads at once (1c), and that a load
reads each file once (1d).

The inputs are the vectors of the benchmark set (`bench/set.json`, every
wire), each vector's input cut in half and with one character changed (so
that conversions fail), each `expect` converted back, and decodes. The
reference result of a case is taken on a new engine (see `reference`).
"""

import base64
import builtins
import json
import os
import random
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
PACKS = os.path.join(ROOT, "packs")

from goat_transformers import Engine, GTError  # noqa: E402

THREADS = 8
ROUNDS = 3  # each thread converts every case this many times, in its own order


def _bytes(vec, key):
    if key in vec:
        return vec[key].encode("utf-8")
    return base64.b64decode(vec[key + "_b64"])


def _cases():
    """-> ([pack names], [[(name, op, from, to, data, context)] of each vector]),
    op `convert` or `decode`; the vector's own conversion first in its group."""
    with open(os.path.join(ROOT, "bench", "set.json"), "r", encoding="utf-8") as fh:
        bench = json.load(fh)
    names, cases = [], []
    for rel in bench["vectors"]:
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
            vec = json.load(fh)
        src, dst, ctx = vec["from"], vec["to"], vec.get("context")
        for fmt in (src, dst):
            if fmt not in names:
                names.append(fmt)
        data = _bytes(vec, "input")
        changed = bytearray(data)
        changed[len(data) // 3] = 0x7B if changed[len(data) // 3] != 0x7B else 0x5D
        expect = _bytes(vec, "expect")
        cases.append([
            (rel, "convert", src, dst, data, ctx),
            (rel + " (cut)", "convert", src, dst, data[: len(data) // 2], ctx),
            (rel + " (changed)", "convert", src, dst, bytes(changed), ctx),
            (rel + " (back)", "convert", dst, src, expect, None),
            (rel + " (decode)", "decode", src, None, data, None),
            (rel + " (decode cut)", "decode", src, None, data[: len(data) // 2], None),
        ])
    return names, cases


def _result(engine, case):
    """What can be observed of one case: the bytes, or the decoded entity
    (model values, lists, residue, kind), or the named error and its text."""
    _, op, src, dst, data, ctx = case
    try:
        if op == "convert":
            return ("bytes", engine.convert(src, dst, data, ctx))
        ent = engine.decode(src, data)
        return ("entity", ent.fields, ent.lists, ent.residue, ent.kind)
    except GTError as e:
        return ("error", e.code, str(e))


NAMES, GROUPS = _cases()
CASES = [c for g in GROUPS for c in g]
_REFERENCE = None


def reference():
    """Each case's result on a new engine: one per vector, loaded with the
    packs of the vector's two formats, which converts the vector first and
    then its other cases in order. (An engine per case would load the packs
    some ninety times.)"""
    global _REFERENCE
    if _REFERENCE is None:
        out = []
        for group in GROUPS:
            _, _, src, dst, _, _ = group[0]
            engine = Engine.from_dir(PACKS, packs_only=sorted({src, dst}))
            out.extend(_result(engine, c) for c in group)
        _REFERENCE = out
    return _REFERENCE


class TestKeepingIsNotObservable(unittest.TestCase):
    """Ruling 1b: on an instance that converted other messages before, failed
    ones included, every case gives the result of a new instance."""

    def test_after_other_conversions(self):
        ref = reference()
        self.assertTrue(any(r[0] == "error" for r in ref), "the cases hold no failing conversion")
        self.assertTrue(any(r[0] == "bytes" for r in ref))
        engine = Engine.from_dir(PACKS, packs_only=NAMES)
        order = list(range(len(CASES)))
        for _ in range(2):  # forward, then in reverse, so each case comes after every other
            for i in order:
                self.assertEqual(_result(engine, CASES[i]), ref[i], CASES[i][0])
            order.reverse()


class TestThreads(unittest.TestCase):
    """Ruling 1c: one instance, new at the start, used from several threads at
    once; every conversion gives the result of 1b. The switch interval is
    made short so that the threads interleave inside the work of one case,
    and the first conversions, which work out the kept layouts, race."""

    def test_one_instance_many_threads(self):
        ref = reference()
        engine = Engine.from_dir(PACKS, packs_only=NAMES)
        start = threading.Barrier(THREADS)
        wrong = []
        lock = threading.Lock()

        def work(seed):
            rng = random.Random(seed)
            order = list(range(len(CASES)))
            start.wait()
            for _ in range(ROUNDS):
                rng.shuffle(order)
                for i in order:
                    try:
                        got = _result(engine, CASES[i])
                    except Exception as e:  # anything but a named error is wrong too
                        got = ("raised", type(e).__name__, str(e))
                    if got != ref[i]:
                        with lock:
                            wrong.append((seed, CASES[i][0], got, ref[i]))

        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            threads = [threading.Thread(target=work, args=(n,)) for n in range(THREADS)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old)
        self.assertEqual(wrong[:3], [], "%d conversion(s) differ from a new instance's" % len(wrong))


class TestLoadReadsEachFileOnce(unittest.TestCase):
    """Ruling 1d: a load opens each module and pack file once; a second load of
    the same directory into the same instance is `duplicate-module`."""

    def test_each_file_opened_once(self):
        opened = []
        real = builtins.open

        def counting(path, *args, **kwargs):
            opened.append(os.path.realpath(path))
            return real(path, *args, **kwargs)

        builtins.open = counting
        try:
            Engine.from_dir(PACKS, packs_only=NAMES)
        finally:
            builtins.open = real
        self.assertTrue(opened)
        twice = sorted({p for p in opened if opened.count(p) > 1})
        self.assertEqual(twice, [])
        self.assertEqual(len([p for p in opened if p.endswith("pack.def")]), len(NAMES))

    def test_second_load_is_duplicate(self):
        engine = Engine.from_dir(PACKS, packs_only=["geojson"])
        core = os.path.join(ROOT, "model", "core.def")
        with open(core, "r", encoding="utf-8") as fh:
            text = fh.read()
        with self.assertRaises(GTError) as cm:
            engine.load_model(text, source=core)
        self.assertEqual(cm.exception.code, "duplicate-module")
        with open(os.path.join(PACKS, "geojson", "pack.def"), "r", encoding="utf-8") as fh:
            text = fh.read()
        with self.assertRaises(GTError) as cm:
            engine.load(text)
        self.assertEqual(cm.exception.code, "duplicate-format")


if __name__ == "__main__":
    unittest.main()
