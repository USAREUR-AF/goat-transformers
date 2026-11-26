#!/usr/bin/env python3
"""The single-wire check of the Python engine (spec/engine-spec.md, Version
0.24, rulings 1b, 1c and 1d). From the repository root:

    python3 -I engines/python/single-wire-check.py
    GOAT_WIRES="tlv cbor" python3 -I engines/python/single-wire-check.py   # fewer wires

For each of the eight wires it makes two builds with `build.py`, and checks
each in a fresh interpreter whose package is that build:

1. the wire alone. Every module the build holds imports; the modules of the
   other wires are absent; every model module and every pack on the wire
   loads; every conversion vector whose `from` and `to` packs are on the wire
   passes, and there is at least one. A wire alone can do this: no wire needs
   another to read or write its messages, and each has vectors from its packs
   to its packs. So the check does not add `json` to any build.
2. every wire but it. The same imports and loads; of the conversion vectors,
   those between packs on two different wires of the build, which no build of
   part 1 can run. The vectors within one wire are not run again here: this
   engine is slow, and part 1 runs each of them.

In both, every pack on a wire the build lacks is `unknown-wire`, with a
message that names the wire and says this build does not have it.

Vectors whose `from` or `to` names no pack (an `unknown-format` vector), and
vectors of an outer pack (ruling 1 of 0.34: whether its inner pack loads
differs between builds), are run by the full suite only. Exits non-zero at the first failure."""

import contextlib
import glob
import importlib
import importlib.util
import io
import json
import os
import pkgutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PACKS = os.path.join(ROOT, "packs")
PACKAGE = "goat_transformers"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _packs():
    """-> [(directory, format, wire, outer)] of every pack, from the text alone;
    `outer` when the pack has an `inner` line (0.34)."""
    out = []
    for path in sorted(glob.glob(os.path.join(PACKS, "*", "pack.def"))):
        head, outer = {}, False
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                toks = line.split()
                if len(toks) >= 2 and toks[0] in ("format", "wire"):
                    head.setdefault(toks[0], toks[1].strip('"'))
                outer = outer or (len(toks) >= 2 and toks[0] == "inner")
        out.append((os.path.dirname(path), head.get("format"), head.get("wire"), outer))
    return out


# --- the worker: runs in a fresh interpreter on one build -------------------


class Failed(Exception):
    pass


def check(src, wires, alone):
    """Check the build under `src`. -> the counts; raises Failed."""
    import build as builder  # engines/python/build.py, for the module map

    sys.path.insert(0, src)
    pkg = importlib.import_module(PACKAGE)
    pkg_dir = os.path.dirname(os.path.abspath(pkg.__file__))
    if pkg_dir != os.path.join(src, PACKAGE):
        raise Failed("imported %s, not the build under %s" % (pkg_dir, src))
    if tuple(pkg._build.WIRES) != wires:
        raise Failed("the build has %s, not %s" % (pkg._build.WIRES, wires))

    modules = sorted(m.name for m in pkgutil.iter_modules([pkg_dir]))
    extra = sorted(set(modules) & builder.left_out(wires))
    if extra:
        raise Failed("the build holds modules of other wires: %s" % ", ".join(extra))
    for name in modules:
        if name == "__main__":
            continue  # runs the tool as it is imported; `help` below
        try:
            importlib.import_module(PACKAGE + "." + name)
        except Exception as e:
            raise Failed("module %s does not import: %s: %s" % (name, type(e).__name__, e))

    argv, sys.argv = sys.argv, ["goat-xf-py", "help"]
    try:
        with contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO())):
            importlib.import_module(PACKAGE + ".__main__")
        raise Failed("module __main__ did not run the tool")
    except SystemExit as e:
        if e.code not in (None, 0):
            raise Failed("module __main__: `help` exits %s" % e.code)
    finally:
        sys.argv = argv

    from goat_transformers import Engine, GTError, load_model_file, load_pack
    from goat_transformers.engine import _model_order

    tv = _load_module("goat_vectors", os.path.join(HERE, "tests", "test_vectors.py"))

    packs = _packs()
    engine = Engine()
    wire_of, outers = {}, set()
    try:
        for path in _model_order(os.path.join(ROOT, "model")):
            engine.add_model(load_model_file(path, models=engine.models, max_distribution="controlled"))
    except Exception as e:
        raise Failed("the model modules do not load: %s: %s" % (type(e).__name__, e))
    refused = 0
    for path, fmt, wire, outer in packs:
        if outer:
            outers.add(fmt)
        rel = os.path.relpath(path, ROOT)
        if wire in wires:
            try:
                engine.add(load_pack(path))
            except Exception as e:
                raise Failed("%s on %s does not load: %s: %s" % (rel, wire, type(e).__name__, e))
            wire_of[fmt] = wire
            continue
        try:
            load_pack(path)
        except GTError as e:
            msg = str(e)
            if not (e.code == "unknown-wire" and msg.startswith("unknown-wire:") and repr(wire) in msg
                    and "this build does not have" in msg):
                raise Failed("%s on %s: not the unknown-wire this build needs: %s" % (rel, wire, msg))
        except Exception as e:
            raise Failed("%s on %s: not unknown-wire but %s: %s" % (rel, wire, type(e).__name__, e))
        else:
            raise Failed("%s loaded in a build without %s" % (rel, wire))
        refused += 1
    if set(engine.formats()) != set(wire_of):
        raise Failed("the loaded formats are not the formats of the packs on %s" % ", ".join(wires))

    run = 0
    for path in sorted(glob.glob(os.path.join(PACKS, "*", "vectors", "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            vec = json.load(fh)
        ends = (wire_of.get(vec.get("from")), wire_of.get(vec.get("to")))
        # ruling 1 of 0.34: the reduced-build check runs no vector of an outer pack
        if None in ends or (not alone and ends[0] == ends[1]) or {vec.get("from"), vec.get("to")} & outers:
            continue
        try:
            problems = tv.run_conversion_vector(engine, os.path.relpath(path, PACKS), vec)
        except Exception as e:
            problems = ["unexpected %s: %s" % (type(e).__name__, e)]
        if problems:
            raise Failed("vector %s: %s" % (os.path.relpath(path, ROOT), "; ".join(problems)))
        run += 1
    if run == 0:
        raise Failed("no conversion vector ran")
    return "%d modules imported, %d packs loaded, %d refused, %d vectors passed" % (
        len(modules), len(wire_of), refused, run)


def worker(src, wires, mode):
    try:
        print(check(src, tuple(wires.split(",")), mode == "alone"))
    except Failed as e:
        print("FAIL %s" % e)
        return 1
    return 0


# --- the driver -------------------------------------------------------------


def main():
    sys.path.insert(0, HERE)
    import build as builder

    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        return worker(*sys.argv[2:])
    if len(sys.argv) != 1:
        sys.stderr.write("usage: [GOAT_WIRES=\"a b\"] single-wire-check.py\n")
        return 2
    try:
        chosen = builder.parse_wires(",".join(os.environ["GOAT_WIRES"].split())) if "GOAT_WIRES" in os.environ \
            else builder.WIRES
    except ValueError as e:
        sys.stderr.write("single-wire-check: %s\n" % e)
        return 2
    if not chosen:
        sys.stderr.write("single-wire-check: GOAT_WIRES names no wire\n")
        return 2

    start = time.monotonic()
    for wire in chosen:
        others = tuple(w for w in builder.WIRES if w != wire)
        for mode, label, wires in (("alone", "%s alone" % wire, (wire,)), ("but", "all but %s" % wire, others)):
            t = time.monotonic()
            built = builder.build(wires, os.path.join(HERE, "build", "single-wire", mode + "-" + wire))
            proc = subprocess.run(
                [sys.executable, "-I", os.path.abspath(__file__), "--worker", built["src"], ",".join(wires), mode],
                stdout=subprocess.PIPE, universal_newlines=True,
            )
            sys.stdout.write("%-17s %s (%.0f s)\n" % (label, proc.stdout.strip(), time.monotonic() - t))
            sys.stdout.flush()
            if proc.returncode != 0:
                sys.stdout.write("single-wire check: FAILED on %s (exit %d)\n" % (label, proc.returncode))
                return 1
    sys.stdout.write("single-wire check: passed, %d wires, %.0f s\n" % (len(chosen), time.monotonic() - start))
    return 0


if __name__ == "__main__":
    sys.exit(main())
