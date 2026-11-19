"""Run every conversion vector of every pack under ../../packs, every load
vector and every capability vector (spec/vector-format.md). The packs are
loaded once. Each vector is run, every failure is reported with its pack and
vector name, the counts are printed, and only then does the run fail."""

import base64
import glob
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
PACKS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "packs"))

from goat_transformers import Engine, GTError  # noqa: E402
from goat_transformers.transforms import read_int_text, read_number_text, read_uint_text  # noqa: E402

LOAD_VECTORS = os.path.join(PACKS, "conformance", "load-vectors")
CAPABILITY_VECTORS = os.path.join(PACKS, "conformance", "capability-vectors")


def _vectors():
    out = []
    for path in sorted(glob.glob(os.path.join(PACKS, "*", "vectors", "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            out.append((os.path.relpath(path, PACKS), json.load(fh)))
    return out


def _bytes(vec, key):
    if key in vec:
        return vec[key].encode("utf-8")
    if key + "_b64" in vec:
        return base64.b64decode(vec[key + "_b64"])
    raise AssertionError("vector has neither %s nor %s_b64" % (key, key))


def _resolve(scope, key):
    """Follow a `model` key into the entity (spec/vector-format.md, "Lists in
    `model`") -> ("count", number of items or None for an absent list),
    ("value", the value) or ("missing", why). A model key never contains `[`
    and never ends in `.#`."""
    while True:
        cut = key.find("[")
        if cut < 0:
            break
        close = key.find("]", cut)
        name, index = key[:cut], key[cut + 1:close]
        if close < 0 or not index.isdigit() or key[close + 1:close + 2] != ".":
            return ("missing", "not a list step: %r" % key)
        items = scope.lists.get(name)
        if items is None:
            return ("missing", "list %r absent" % name)
        if int(index) >= len(items):
            return ("missing", "list %r has %d item(s), no item %s" % (name, len(items), index))
        scope = items[int(index)]
        key = key[close + 2:]
    if key.endswith(".#"):
        items = scope.lists.get(key[:-2])
        return ("count", None if items is None else len(items))
    if key == "@kind":  # 0.8: the kind an item recorded when it was decoded; not a model key
        kind = getattr(scope, "kind", None)
        if kind is None:
            return ("missing", "the item recorded no kind")
        return ("value", kind[1])
    if key not in scope.fields:
        return ("missing", "model key %r absent" % key)
    return ("value", scope.fields[key])


def _check_absent(ent, model, listed):
    """-> failure texts for `"@absent"` (0.9): each entry is a model key, an
    item path `"<list>[<i>].<key>"` (the item exists and lacks the key) or a
    list name (the entity has no such list). An entry that is also a member
    of `model` makes the vector invalid (ruling 21)."""
    if not isinstance(listed, list) or not all(isinstance(k, str) for k in listed):
        return ["@absent must be an array of model keys, got %r" % (listed,)]
    out = []
    for key in listed:
        if key in model:
            out.append("invalid vector: %r is in @absent and is also a member of model" % key)
            continue
        scope = ent
        rest = key
        problem = None
        while True:  # follow the item steps, as `_resolve` does
            cut = rest.find("[")
            if cut < 0:
                break
            close = rest.find("]", cut)
            name, index = rest[:cut], rest[cut + 1:close]
            if close < 0 or not index.isdigit() or rest[close + 1:close + 2] != ".":
                problem = "not a list step: %r" % key
                break
            items = scope.lists.get(name)
            if items is None or int(index) >= len(items):
                problem = "the item does not exist: list %r has %s" % (
                    name, "no items (absent)" if items is None else "%d item(s)" % len(items))
                break
            scope = items[int(index)]
            rest = rest[close + 2:]
        if problem is not None:
            out.append("@absent %s: %s" % (key, problem))
            continue
        if rest in scope.fields:
            out.append("@absent: model key %r decoded %r, expected absent" % (key, scope.fields[rest]))
        elif rest in scope.lists:
            out.append("@absent: list %r decoded with %d item(s), expected absent" % (key, len(scope.lists[rest])))
    return out


def _key_of(path):
    """The model key a `model` member names: the member itself, or the text
    after the last `[<i>].` of an item path."""
    cut = path.rfind("].")
    return path[cut + 2:] if cut >= 0 else path


def _read_want(engine, key, want):
    """Ruling 2c of 0.11: a `model` value named by a model key or an item path
    is read as that key's declared type (2a for `int`, 2b for `float`). ->
    (value, None), or (None, why the vector is invalid)."""
    if not isinstance(want, str):
        return None, "invalid vector: the model value of %r is not a string: %r" % (key, want)
    kind = engine._key_type(_key_of(key))
    try:
        if kind == "int":
            return read_int_text(want), None
        if kind == "float":
            return read_number_text(want), None
    except ValueError as e:
        return None, "invalid vector: the model value of %r is not %s text: %s" % (key, kind, e)
    return want, None


def _check_model(engine, rel, vec, data):
    """-> list of failure texts for the vector's `model` object. With
    `"@complete": true` the checks run on the completed entity: the decode, then
    the absent keys filled from `context`, then the derivations (whether or not
    `from == to`), and floats compare within 1e-9 relative. `"<list>.#"` and
    `"<list>[<i>].<key>"` check a list of the decoded entity, and
    `"<list>[<i>].@kind"` the kind an item selected (0.8)."""
    out = []
    ent = engine.decode(vec["from"], data, _max_items(vec))
    complete = vec["model"].get("@complete") is True
    if complete:
        ent = engine.complete(ent, vec.get("context"))
    for key, want in vec["model"].items():
        if key == "@absent":  # not a model key: keys the entity must not have (0.9)
            out.extend(_check_absent(ent, vec["model"], want))
            continue
        if key == "@complete":  # not a model key
            if want is not True:
                out.append("@complete must be true, got %r" % (want,))
            continue
        if key == "@kind":  # not a model key: the kind name the decode must select
            have = ent.kind[1] if ent.kind is not None else None
            if ent.kind is not None and ent.kind[0] != vec["from"]:
                out.append("Entity.kind names format %r, not %r" % (ent.kind[0], vec["from"]))
            if have != want:
                out.append("@kind: decode selected %r, expected %r" % (have, want))
            continue
        if key.endswith(".#"):  # a count is an unsigned decimal integer or `absent`
            if want != "absent":
                try:
                    want = read_uint_text(want) if isinstance(want, str) else None
                except ValueError:
                    want = None
                if want is None:
                    out.append("invalid vector: %s must be an unsigned decimal integer or 'absent'" % key)
                    continue
        elif not key.endswith("@kind"):
            want, why = _read_want(engine, key, want)
            if why is not None:
                out.append(why)
                continue
        what, have = _resolve(ent, key)
        if what == "missing":
            out.append("%s: %s" % (key, have) if "[" in key else have)
            continue
        if what == "count":
            if want == "absent":
                ok = have is None
            else:
                ok = have is not None and have == want
            if not ok:
                out.append(
                    "%s: decoded %s, expected %s" % (key, "absent" if have is None else "%d item(s)" % have, want)
                )
            continue
        if isinstance(have, float) and isinstance(want, float) and complete:
            ok = have == want or abs(have - want) < 1e-9 * max(abs(have), abs(want))
        elif isinstance(have, float) and isinstance(want, float):
            ok = abs(have - want) <= 1e-9
        else:
            ok = type(have) is type(want) and have == want
        if not ok:
            out.append("model key %r: decoded %r, expected %r" % (key, have, want))
    return out


def _max_items(vec):
    """The vector's `max_items` (ruling 7b of 0.11), or None for the default."""
    return vec.get("max_items")


def run_conversion_vector(engine, rel, vec):
    """-> list of failure texts; empty when the vector passes."""
    src, dst = vec["from"], vec["to"]
    data = _bytes(vec, "input")
    context = vec.get("context")  # caller-supplied keys, values in string form (spec 0.6)
    out = []
    limit = _max_items(vec)
    if "max_items" in vec and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        return ["invalid vector: max_items must be an integer of 0 or more, got %r" % (limit,)]
    if "expect_error" in vec:
        want = vec["expect_error"]
        try:
            got = engine.convert(src, dst, data, context, max_items=limit)
        except GTError as e:
            if e.code != want or not str(e).startswith(want + ":"):
                out.append("convert(%s -> %s) must fail with %s, failed with: %s" % (src, dst, want, e))
        else:
            out.append(
                "convert(%s -> %s) must fail with %s, returned: %s" % (src, dst, want, got.decode("utf-8", "replace"))
            )
        if "expect" in vec:
            out.append("vector carries both expect and expect_error")
    else:
        expect = _bytes(vec, "expect")
        try:
            got = engine.convert(src, dst, data, context, max_items=limit)
        except GTError as e:
            out.append("convert(%s -> %s) failed: %s" % (src, dst, e))
        else:
            if got != expect:
                out.append(
                    "convert(%s -> %s) mismatch\n      got:    %s\n      expect: %s"
                    % (src, dst, got.decode("utf-8", "replace"), expect.decode("utf-8", "replace"))
                )
    if vec.get("model"):
        try:
            out.extend(_check_model(engine, rel, vec, data))
        except GTError as e:
            out.append("decode(%s) for the model check failed: %s" % (src, e))
    return out


def _report(title, total, failures):
    """Print every failure (pack and vector name), then the counts."""
    w = sys.stderr.write
    for rel, name, problems in failures:
        w("FAIL %s  pack=%s  vector=%s\n" % (title, rel.split(os.sep)[0], name))
        w("     file: %s\n" % rel)
        for p in problems:
            w("     - %s\n" % p)
    w("[goat_transformers] %s executed: %d, passed: %d, failed: %d\n"
      % (title, total, total - len(failures), len(failures)))


class TestVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Engine.from_dir(PACKS)
        cls.vectors = _vectors()
        sys.stderr.write(
            "\n[goat_transformers] packs loaded (%d): %s\n"
            % (len(cls.engine.formats()), ", ".join(cls.engine.formats()))
        )

    def test_every_pack_loads(self):
        defs = glob.glob(os.path.join(PACKS, "*", "pack.def"))
        self.assertGreater(len(defs), 0, "no pack.def found under %s" % PACKS)
        self.assertEqual(len(self.engine.formats()), len(defs))

    def test_vectors_exist(self):
        self.assertGreater(len(self.vectors), 0, "no vectors found under %s" % PACKS)

    def test_vector_names_unique_within_pack(self):
        seen = set()
        for rel, vec in self.vectors:
            key = (rel.split(os.sep)[0], vec.get("name"))
            self.assertNotIn(key, seen, "vector name used twice in a pack: %s" % (key,))
            seen.add(key)

    def test_all_vectors(self):
        failures = []
        for rel, vec in self.vectors:
            try:
                problems = run_conversion_vector(self.engine, rel, vec)
            except Exception as e:  # an engine defect: report it against its vector, keep going
                problems = ["unexpected %s: %s" % (type(e).__name__, e)]
            if problems:
                failures.append((rel, vec.get("name"), problems))
        _report("conversion vectors", len(self.vectors), failures)
        self.assertEqual(
            failures, [], "%d of %d conversion vectors failed (listed above)" % (len(failures), len(self.vectors))
        )


class TestLoadVectors(unittest.TestCase):
    """spec/vector-format.md, "Load vectors": a fresh engine per vector, the
    modules in order then the pack, stopping at the first failure."""

    @classmethod
    def setUpClass(cls):
        cls.vectors = []
        for path in sorted(glob.glob(os.path.join(LOAD_VECTORS, "*.json"))):
            with open(path, "r", encoding="utf-8") as fh:
                cls.vectors.append((os.path.join("conformance", "load-vectors", os.path.basename(path)), json.load(fh)))

    def test_load_vectors_exist(self):
        self.assertGreater(len(self.vectors), 0, "no load vectors found under %s" % LOAD_VECTORS)

    @staticmethod
    def _first_failure(vec):
        """-> the first failure as a GTError, or None when every load succeeds."""
        eng = Engine()
        if "max_distribution" in vec:
            eng.set_max_distribution(vec["max_distribution"])
        try:
            for text in vec["models"]:
                eng.load_model(text)
            for text in vec["packs"] if "packs" in vec else [vec["pack"]]:  # `packs`: 0.11, ruling 5d
                eng.load(text)
        except GTError as e:
            return e
        return None

    def test_all_load_vectors(self):
        failures = []
        for rel, vec in self.vectors:
            want = vec.get("expect_error")
            problems = []
            try:
                err = self._first_failure(vec)
            except Exception as e:
                problems.append("unexpected %s: %s" % (type(e).__name__, e))
            else:
                if want is None:
                    if err is not None:
                        problems.append("every load must succeed, got: %s" % err)
                elif err is None:
                    problems.append("the load must fail with %s, nothing failed" % want)
                elif err.code != want or not str(err).startswith(want + ":"):
                    problems.append("the load must fail with %s, failed with: %s" % (want, err))
            if problems:
                failures.append((rel, vec.get("name"), problems))
        _report("load vectors", len(self.vectors), failures)
        self.assertEqual(
            failures, [], "%d of %d load vectors failed (listed above)" % (len(failures), len(self.vectors))
        )


class TestCapabilityVectors(unittest.TestCase):
    """spec/vector-format.md, "Capability vectors" (ruling 6 of 0.11): the
    model modules and the two packs loaded, `capability(from, to)` equal to
    the vector's grade and lists, entry for entry."""

    @classmethod
    def setUpClass(cls):
        cls.vectors = []
        for path in sorted(glob.glob(os.path.join(CAPABILITY_VECTORS, "*.json"))):
            with open(path, "r", encoding="utf-8") as fh:
                cls.vectors.append(
                    (os.path.join("conformance", "capability-vectors", os.path.basename(path)), json.load(fh))
                )

    def test_capability_vectors_exist(self):
        self.assertGreater(len(self.vectors), 0, "no capability vectors found under %s" % CAPABILITY_VECTORS)

    def test_all_capability_vectors(self):
        failures = []
        for rel, vec in self.vectors:
            problems = []
            try:
                eng = Engine.from_dir(PACKS, packs_only=sorted({vec["from"], vec["to"]}))
                got = eng.capability(vec["from"], vec["to"])
            except Exception as e:
                problems.append("unexpected %s: %s" % (type(e).__name__, e))
            else:
                for member in ("grade", "carried", "dropped"):
                    if got[member] != vec[member]:
                        problems.append("%s: got %r, expected %r" % (member, got[member], vec[member]))
            if problems:
                failures.append((rel, vec.get("name"), problems))
        _report("capability vectors", len(self.vectors), failures)
        self.assertEqual(
            failures, [], "%d of %d capability vectors failed (listed above)" % (len(failures), len(self.vectors))
        )


if __name__ == "__main__":
    unittest.main()
