#!/usr/bin/env python3
"""The reduced-build check of the Python engine (spec/engine-spec.md, Version
0.24, "What pins it"). From the repository root:

    python3 -I engines/python/reduced-build-check.py
    python3 -I engines/python/reduced-build-check.py --wires geojson   # another set

1. Builds the engine twice with `build.py`: with all seven wires, and with
   `xml`, `json` and `geojson` only.
2. In the reduced build (a fresh interpreter whose package is the reduced
   copy): the codec modules of the other wires are absent; every conversion
   vector whose `from` and `to` packs are on the three wires passes, with every
   pack on the three wires and every model module loaded; every load vector whose packs name only
   those wires (or no wire of the specification) gives the result it gives in
   a full build; one pack on `bits` (and one sequential `bits` pack), one on
   `protobuf`, one on `text` and one on `tlv` are each `unknown-wire` with a
   message that names the wire and says this build does not have it; a `wire`
   value that is no wire is still `unknown-wire`, without that text.
3. `model_keys` of every pack on the three wires, and the capability report of
   every pair a vector converts, are the same in both builds (ruling 1e).
4. Prints the size of the reduced wheel beside the full one.

Exits non-zero on any failure."""

import glob
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PACKS = os.path.join(ROOT, "packs")
LOAD_VECTORS = os.path.join(PACKS, "conformance", "load-vectors")
ALL = ("xml", "geojson", "json", "bits", "protobuf", "text", "tlv")
REDUCED = ("xml", "geojson", "json")  # the set "What pins it" names; `--wires` checks another
OTHERS = tuple(w for w in ALL if w not in REDUCED)


def _set_wires(wires):
    global REDUCED, OTHERS
    REDUCED = tuple(w for w in ALL if w in wires)
    OTHERS = tuple(w for w in ALL if w not in REDUCED)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _header(text):
    """-> {directive: first value} of `format`, `wire` and `layout`, and every
    `wire` value, read from the text alone (independent of the engine)."""
    out = {"wires": []}
    for line in text.splitlines():
        toks = line.split()
        if len(toks) >= 2 and toks[0] in ("format", "wire", "layout"):
            value = toks[1].strip('"')
            out.setdefault(toks[0], value)
            if toks[0] == "wire":
                out["wires"].append(value)
    return out


def _packs():
    """-> [(directory name, format, wire, layout)] of every pack."""
    out = []
    for path in sorted(glob.glob(os.path.join(PACKS, "*", "pack.def"))):
        with open(path, "r", encoding="utf-8") as fh:
            h = _header(fh.read())
        out.append((os.path.basename(os.path.dirname(path)), h.get("format"), h.get("wire"), h.get("layout")))
    return out


# --- the worker: runs in a fresh interpreter on one build -------------------


def worker(src, mode, out_path, wires):
    _set_wires(wires.split(","))
    sys.path.insert(0, src)
    import goat_transformers  # noqa: E402  (the build under test)
    from goat_transformers import Engine, GTError  # noqa: E402
    from goat_transformers import _build  # noqa: E402

    pkg_dir = os.path.dirname(goat_transformers.__file__)
    if os.path.normpath(os.path.dirname(pkg_dir)) != os.path.normpath(src):
        raise SystemExit("worker: imported %s, not the build under %s" % (pkg_dir, src))
    tv = _load_module("goat_vectors", os.path.join(HERE, "tests", "test_vectors.py"))
    sys.path[:] = [p for p in sys.path if os.path.normpath(p) != os.path.normpath(os.path.join(HERE, "src"))]

    packs = _packs()
    on_set = [p for p in packs if p[2] in REDUCED]
    formats = {p[1] for p in on_set}
    result = {"wires": list(_build.WIRES), "failures": [], "package": pkg_dir}
    fail = result["failures"].append

    # every model module, as the full suite loads them (a `derive` line of a
    # module no loaded pack uses still runs), then every pack on the three wires
    from goat_transformers.engine import _model_order  # noqa: E402
    from goat_transformers.modeldef import load_model_file  # noqa: E402
    from goat_transformers.packdef import load_pack  # noqa: E402

    engine = Engine()
    for path in _model_order(os.path.join(ROOT, "model")):
        engine.add_model(load_model_file(path, models=engine.models, max_distribution="controlled"))
    for p in on_set:
        engine.add(load_pack(os.path.join(PACKS, p[0])))
    result["loaded"] = len(engine.formats())
    if set(engine.formats()) != formats:
        fail("loaded formats differ from the packs on %s" % ", ".join(REDUCED))

    vectors = []
    for path in sorted(glob.glob(os.path.join(PACKS, "*", "vectors", "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            vec = json.load(fh)
        if vec.get("from") in formats and vec.get("to") in formats:
            vectors.append((os.path.relpath(path, PACKS), vec))
    result["vectors_total"] = len(glob.glob(os.path.join(PACKS, "*", "vectors", "*.json")))
    result["model_keys"] = {f: engine.model_keys(f) for f in sorted(formats)}
    pairs = sorted({(v["from"], v["to"]) for _, v in vectors if v["from"] != v["to"]})
    result["capability"] = {"%s>%s" % p: engine.capability(*p) for p in pairs}

    if mode == "full":
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh)
        return 0

    # the codec modules of the other wires are not in the build
    import build as builder  # noqa: E402  (engines/python/build.py)

    absent = sorted(builder.left_out(tuple(_build.WIRES)))
    result["absent_modules"] = absent
    for mod in absent:
        if importlib.util.find_spec("goat_transformers." + mod) is not None:
            fail("module %s is in the reduced build" % mod)

    failures = []
    for rel, vec in vectors:
        try:
            problems = tv.run_conversion_vector(engine, rel, vec)
        except Exception as e:
            problems = ["unexpected %s: %s" % (type(e).__name__, e)]
        if problems:
            failures.append((rel, vec.get("name"), problems))
    tv._report("reduced-build conversion vectors", len(vectors), failures)
    result["vectors_run"] = len(vectors)
    result["vectors_passed"] = len(vectors) - len(failures)
    for rel, name, problems in failures:
        fail("vector %s (%s): %s" % (rel, name, "; ".join(problems)))

    # load vectors whose packs name only the three wires, or no wire of the specification
    lv = []
    for path in sorted(glob.glob(os.path.join(LOAD_VECTORS, "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            vec = json.load(fh)
        texts = vec["packs"] if "packs" in vec else [vec["pack"]]
        if all(w not in OTHERS for t in texts for w in _header(t)["wires"]):
            lv.append((os.path.basename(path), vec))
    lv_fail = []
    for name, vec in lv:
        want = vec.get("expect_error")
        try:
            err = tv.TestLoadVectors._first_failure(vec)
        except Exception as e:
            lv_fail.append((name, "unexpected %s: %s" % (type(e).__name__, e)))
            continue
        if want is None and err is not None:
            lv_fail.append((name, "every load must succeed, got: %s" % err))
        elif want is not None and (err is None or err.code != want or not str(err).startswith(want + ":")):
            lv_fail.append((name, "the load must fail with %s, got: %s" % (want, err)))
    result["load_vectors_run"] = len(lv)
    result["load_vectors_passed"] = len(lv) - len(lv_fail)
    for name, why in lv_fail:
        fail("load vector %s: %s" % (name, why))

    if tuple(_build.WIRES) != REDUCED:
        fail("the build has %s, not %s" % (", ".join(_build.WIRES), ", ".join(REDUCED)))

    # one pack on each wire the build lacks: unknown-wire, naming the wire
    chosen = []
    for w in OTHERS:
        first = next((p for p in packs if p[2] == w), None)
        if first is None:
            fail("no pack on %s to load" % w)
            continue
        chosen.append((w, first[0]))
    seq = next((p for p in packs if p[2] == "bits" and p[3] == "sequential"), None)
    if "bits" in OTHERS and seq is not None and seq[0] not in [c[1] for c in chosen]:
        chosen.append(("bits", seq[0]))
    loads = []
    for w, name in chosen:
        try:
            Engine.from_dir(PACKS, packs_only=[name])
        except GTError as e:
            msg = str(e)
            ok = (e.code == "unknown-wire" and msg.startswith("unknown-wire:") and repr(w) in msg
                  and "this build does not have" in msg)
            loads.append({"wire": w, "pack": name, "ok": ok, "message": msg})
            if not ok:
                fail("pack %s on %s: not the unknown-wire this build needs: %s" % (name, w, msg))
        else:
            loads.append({"wire": w, "pack": name, "ok": False, "message": "loaded"})
            fail("pack %s on %s loaded in a build without %s" % (name, w, w))
    # a value that is no wire at all: unknown-wire as before, not "this build"
    eng = Engine()
    try:
        eng.load("format no-such\nversion 1\nwire morse\n")
    except GTError as e:
        ok = e.code == "unknown-wire" and "this build does not have" not in str(e)
        loads.append({"wire": "morse", "pack": "(text)", "ok": ok, "message": str(e)})
        if not ok:
            fail("wire 'morse': %s" % e)
    else:
        fail("wire 'morse' loaded")
    result["loads"] = loads

    # no module of a lacking wire was imported along the way
    for mod in absent:
        if "goat_transformers." + mod in sys.modules:
            fail("module %s was imported" % mod)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0


# --- the driver -------------------------------------------------------------


def run_worker(src, mode, out_path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, "-I", os.path.abspath(__file__), "--worker", src, mode, out_path, ",".join(REDUCED)],
        env=env,
    )
    if proc.returncode != 0:
        return None
    with open(out_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main():
    if len(sys.argv) == 6 and sys.argv[1] == "--worker":
        sys.path.insert(0, HERE)  # build.py, for the module map
        return worker(*sys.argv[2:6])
    sys.path.insert(0, HERE)
    import build as builder

    if len(sys.argv) == 3 and sys.argv[1] == "--wires":
        try:
            _set_wires(builder.parse_wires(sys.argv[2]))
        except ValueError as e:
            sys.stderr.write("reduced-build-check: %s\n" % e)
            return 2
    elif len(sys.argv) != 1:
        sys.stderr.write("usage: reduced-build-check.py [--wires <wire>[,<wire>...]]\n")
        return 2
    if not REDUCED or not OTHERS:
        sys.stderr.write("reduced-build-check: the set must hold at least one wire and lack at least one\n")
        return 2

    base = os.path.join(HERE, "build", "reduced-check")
    full = builder.build(builder.WIRES, os.path.join(base, "full"))
    reduced = builder.build(builder.parse_wires(",".join(REDUCED)), os.path.join(base, "reduced"))

    problems = []
    r = run_worker(reduced["src"], "reduced", os.path.join(base, "reduced.json"))
    f = run_worker(full["src"], "full", os.path.join(base, "full.json"))
    if r is None:
        problems.append("the reduced-build worker failed (see above)")
    if f is None:
        problems.append("the full-build worker failed (see above)")
    if r is not None:
        problems.extend(r["failures"])
    if r is not None and f is not None:
        if r["model_keys"] != f["model_keys"]:
            diff = [k for k in f["model_keys"] if r["model_keys"].get(k) != f["model_keys"][k]]
            problems.append("model_keys differ between the builds for: %s" % ", ".join(diff[:20]))
        if r["capability"] != f["capability"]:
            diff = [k for k in f["capability"] if r["capability"].get(k) != f["capability"][k]]
            problems.append("the capability report differs between the builds for: %s" % ", ".join(diff[:20]))

    w = sys.stdout.write
    w("\n== reduced-build check (spec 0.24), Python engine ==\n")
    w("reduced build: %s; left out: %s\n" % (", ".join(REDUCED), ", ".join(reduced["left_out"])))
    if r is not None:
        w("packs loaded on %s: %d\n" % (", ".join(REDUCED), r["loaded"]))
        w("conversion vectors: %d of %d run, %d passed, %d failed\n" % (
            r["vectors_run"], r["vectors_total"], r["vectors_passed"], r["vectors_run"] - r["vectors_passed"]))
        w("load vectors on those wires: %d run, %d passed, %d failed\n" % (
            r["load_vectors_run"], r["load_vectors_passed"], r["load_vectors_run"] - r["load_vectors_passed"]))
        for ld in r["loads"]:
            msg = ld["message"].replace(ROOT + os.sep, "")
            w("load %-8s %-26s %s  %s\n" % (ld["wire"], ld["pack"], "ok  " if ld["ok"] else "FAIL", msg))
    if r is not None and f is not None:
        w("model_keys (%d formats) and capability (%d pairs): %s\n" % (
            len(f["model_keys"]), len(f["capability"]),
            "same in both builds" if r["model_keys"] == f["model_keys"] and r["capability"] == f["capability"]
            else "DIFFER"))
    w("size, wheel:   full %d bytes, reduced %d bytes (%.0f%%)\n" % (
        full["wheel_bytes"], reduced["wheel_bytes"], 100.0 * reduced["wheel_bytes"] / full["wheel_bytes"]))
    w("size, source:  full %d bytes (%d modules), reduced %d bytes (%d modules)\n" % (
        full["package_bytes"], len(full["modules"]), reduced["package_bytes"], len(reduced["modules"])))
    for p in problems:
        w("FAIL %s\n" % p)
    w("reduced-build check: %s\n" % ("FAILED (%d problem(s))" % len(problems) if problems else "passed"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
