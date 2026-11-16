"""Tests for tools/goat-options (docs/system-records.md). Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True  # the tool has no .py name; leave no cache beside it

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SKETCH = os.path.join(REPO, "examples", "stores", "sketch")
SITE = os.path.join(REPO, "examples", "sites", "forward.site")

_loader = importlib.machinery.SourceFileLoader("goat_options", os.path.join(REPO, "tools", "goat-options"))
_spec = importlib.util.spec_from_loader("goat_options", _loader)
go = importlib.util.module_from_spec(_spec)
_loader.exec_module(go)

sys.path.insert(0, os.path.join(REPO, "engines", "python", "src"))
from goat_transformers import Engine  # noqa: E402


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = go.main(list(argv))
    return code, out.getvalue()


def run_json(*argv):
    code, text = run(*argv)
    return code, json.loads(text)


class TempStore:
    """A store directory with the given files, removed afterwards."""

    def __init__(self, files):
        self.files = files

    def __enter__(self):
        self.dir = tempfile.mkdtemp()
        for name, text in self.files.items():
            path = os.path.join(self.dir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return self.dir

    def __exit__(self, *exc):
        shutil.rmtree(self.dir)


class Tokens(unittest.TestCase):
    def test_quotes_and_comments(self):
        self.assertEqual(go.tokens('emits "a b" status=proven evidence="x # y"  # tail'),
                         ["emits", "a b", "status=proven", "evidence=x # y"])

    def test_unbalanced_quote_is_an_error(self):
        with self.assertRaises(ValueError):
            go.tokens('name "open')

    def test_attributes(self):
        words, attrs = go.split_attrs(["sapient", "status=proven", "x-y_z=1", "a=b=c", "=v"])
        self.assertEqual(words, ["sapient", "=v"])
        self.assertEqual(attrs, {"status": "proven", "x-y_z": "1", "a": "b=c"})


class Records(unittest.TestCase):
    def test_unknown_is_kept_not_refused(self):
        text = "system t/one\nfrobnicate 1 2\nemits cot-xml status=proven evidence=e colour=blue\n"
        with TempStore({"one.rec": text}) as d:
            probs = []
            systems = go.load_stores([d], probs)
        s = systems["t/one"]
        self.assertEqual(s["records"][0]["extra"][0]["tokens"], ["frobnicate", "1", "2"])
        self.assertEqual(s["claims"][0]["attrs"]["colour"], "blue")
        self.assertEqual([(p.level, p.where) for p in probs], [("info", "one.rec:2"), ("info", "one.rec:3")])
        self.assertIn("attribute `colour`", probs[1].text)

    def test_no_system_line_is_skipped_with_a_warning(self):
        with TempStore({"x.rec": "emits cot-xml\n"}) as d:
            probs = []
            self.assertEqual(go.load_stores([d], probs), {})
        self.assertEqual(probs[0].level, "warning")

    def test_status_warnings(self):
        text = "system t/one\nemits a status=proven\nemits b status=great\n"
        with TempStore({"one.rec": text}) as d:
            probs = []
            go.load_stores([d], probs)
        texts = " | ".join(p.text for p in probs)
        self.assertIn("no evidence", texts)
        self.assertIn("read as unknown", texts)

    def test_merge_keeps_every_owner(self):
        a = "system t/s\nname \"S\"\nby owner-a\nemits cot-xml status=proven evidence=a1\n"
        b = "system t/s\nname \"S, as B calls it\"\nby owner-b\nemits cot-xml status=unknown\n"
        with TempStore({"a/s.rec": a, "b/s.rec": b}) as d:
            probs = []
            systems = go.load_stores([os.path.join(d, "a"), os.path.join(d, "b")], probs)
        s = systems["t/s"]
        self.assertEqual(s["names"], ["S", "S, as B calls it"])
        self.assertEqual([c["source"]["by"] for c in s["claims"]], ["owner-a", "owner-b"])

    def test_merge_order_does_not_change_the_answer(self):
        a = "system t/src\nemits cot-xml status=proven evidence=a\n"
        b = "system t/dst\naccepts geojson status=available\n"
        with TempStore({"a/x.rec": a, "b/y.rec": b}) as d:
            one = run_json("paths", "--store", os.path.join(d, "a"), "--store", os.path.join(d, "b"),
                           "--from", "t/src", "--to", "t/dst")[1]
            two = run_json("paths", "--store", os.path.join(d, "b"), "--store", os.path.join(d, "a"),
                           "--from", "t/src", "--to", "t/dst")[1]
        strip = lambda r: [(p["formats"], p["status"], p["carried"]) for p in r["paths"]]
        self.assertEqual(strip(one), strip(two))


class Paths(unittest.TestCase):
    def test_direct_path(self):
        _, r = run_json("paths", "--store", SKETCH, "--from", "example/acoustic-1", "--to", "example/c2-app")
        direct = [p for p in r["paths"] if p["conversions"] == 0]
        self.assertEqual([p["formats"] for p in direct], [["sapient"]])
        self.assertIsNone(direct[0]["carried"])

    def test_library_step_is_the_capability_report(self):
        _, r = run_json("paths", "--store", SKETCH, "--from", "example/c2-app", "--to", "example/edge-display")
        eng = Engine.from_dir(os.path.join(REPO, "packs"), packs_only=["cot-xml", "cot-protobuf"])
        cap = eng.capability("cot-xml", "cot-protobuf")
        step = [p for p in r["paths"] if p["formats"] == ["cot-xml", "cot-protobuf"]][0]["steps"][0]
        self.assertEqual((step["carried"], step["lost"], step["grade"]),
                         (cap["carried"], cap["dropped"], cap["grade"]))
        self.assertEqual(step["status"], "available")

    def test_translator_paths_and_status_is_the_weakest_step(self):
        _, r = run_json("paths", "--store", SKETCH, "--from", "example/rf-1", "--to", "example/c2-app")
        routes = {tuple(s["via"] for s in p["steps"]) + tuple(p["formats"]): p["status"] for p in r["paths"]}
        t, lib = "example/node-translator", "goat-transformers"
        self.assertEqual(routes[(t, t, "example rf-1 json", "canonical-track-v2", "cot-xml")], "proven")
        self.assertEqual(routes[(t, lib, "example rf-1 json", "canonical-track-v2", "cot-xml")], "available")
        self.assertEqual(r["counts"]["paths"], 4)

    def test_no_two_library_steps_in_a_row(self):
        for src in ("example/radar-1", "example/camera-1", "example/acoustic-1"):
            for dst in ("example/edge-display", "example/c2-app", "example/analytics-app"):
                _, r = run_json("paths", "--store", SKETCH, "--from", src, "--to", dst, "--max-conversions", "3")
                for p in r["paths"]:
                    vias = [s["via"] for s in p["steps"]]
                    for x, y in zip(vias, vias[1:]):
                        self.assertFalse(x == y == "goat-transformers", (src, dst, p["formats"]))
                    self.assertEqual(len(set(p["formats"])), len(p["formats"]))

    def test_formats_as_endpoints(self):
        _, r = run_json("paths", "--store", SKETCH, "--from", "sapient", "--to", "cot-xml")
        self.assertIn(["sapient", "cot-xml"], [p["formats"] for p in r["paths"]])

    def test_max_conversions_zero(self):
        _, r = run_json("paths", "--store", SKETCH, "--from", "example/rf-1", "--to", "example/c2-app",
                        "--max-conversions", "0")
        self.assertEqual(r["paths"], [])

    def test_keys_count(self):
        _, r = run_json("paths", "--store", SKETCH, "--from", "example/c2-app", "--to", "example/edge-display",
                        "--keys", "count")
        self.assertTrue(all(isinstance(p["carried"], int) for p in r["paths"]))


class Needs(unittest.TestCase):
    """A library step lists the required keys the source does not map: the
    library refuses the conversion unless the caller supplies them."""

    STORE = {"a.rec": "system t/radar\nemits asterix-cat062 transport=udp\n",
             "b.rec": "system t/app\naccepts canonical-track-v2 transport=zenoh\naccepts cot-xml transport=udp\n"}

    def test_needs_names_the_missing_required_keys(self):
        with TempStore(self.STORE) as d:
            _, r = run_json("paths", "--store", d, "--from", "t/radar", "--to", "t/app")
        steps = {p["formats"][-1]: p["steps"][0] for p in r["paths"]}
        self.assertEqual(steps["canonical-track-v2"]["needs"],
                         [{"kind": "Track", "missing": ["uid", "track.source_id", "track.generation", "time_ms"]}])
        self.assertIsNone(steps["cot-xml"]["needs"])  # cot-xml has no kind, so nothing is required

    def test_needs_agrees_with_the_engine(self):
        eng = Engine.from_dir(os.path.join(REPO, "packs"), packs_only=["asterix-cat062", "canonical-track-v2"])
        with open(os.path.join(REPO, "packs", "asterix-cat062", "vectors", "01-open-billie-sample-roundtrip.json")) as f:
            data = json.load(f)["input"].encode()
        with self.assertRaises(Exception):
            eng.convert("asterix-cat062", "canonical-track-v2", data)
        given = {"uid": "t-1", "track.source_id": "s", "track.generation": "g", "time_ms": "1000"}
        self.assertIn(b"trackId", eng.convert("asterix-cat062", "canonical-track-v2", data, given))

    def test_transports_differ_on_a_direct_path_only(self):
        store = {"a.rec": "system t/a\nemits cot-xml transport=udp\n",
                 "b.rec": "system t/b\naccepts cot-xml transport=zenoh\naccepts geojson transport=zenoh\n"}
        with TempStore(store) as d:
            _, r = run_json("paths", "--store", d, "--from", "t/a", "--to", "t/b")
        marked = {tuple(p["formats"]): p.get("transports_differ") for p in r["paths"]}
        self.assertEqual(marked[("cot-xml",)], ["udp", "zenoh"])
        self.assertIsNone(marked[("cot-xml", "geojson")])

    def test_table_shows_who_claimed_and_the_marks(self):
        store = dict(self.STORE, **{"c.rec": "system t/radar\nby other-owner\nemits asterix-cat062 version=2\n"})
        with TempStore(store) as d:
            _, text = run("paths", "--store", d, "--from", "t/radar", "--to", "t/app", "--table")
        self.assertIn("claims by", text)
        self.assertIn("other-owner 2 / ?", text)
        self.assertIn("canonical-track-v2 needs uid track.source_id track.generation time_ms", text)


class Site(unittest.TestCase):
    def test_on_hand(self):
        _, r = run_json("site", "--store", SKETCH, SITE)
        for it in r["intents"]:
            for p in it["paths"]:
                self.assertTrue(go.all_on_hand(p))
        self.assertEqual({(i["consumer"], i["source"]) for i in r["intents"]} >= {
            ("example/c2-app", "example/rf-1"), ("example/edge-display", "example/radar-1")}, True)

    def test_a_converter_not_on_hand(self):
        with TempStore({"s.site": "site s\nhave example/rf-1\nhave example/c2-app\nfeed example/c2-app\n"}) as d:
            _, r = run_json("site", "--store", SKETCH, os.path.join(d, "s.site"))
        paths = r["intents"][0]["paths"]
        self.assertTrue(paths)
        self.assertEqual(r["intents"][0]["paths_on_hand"], 0)
        self.assertTrue(all(s["on_hand"] is False for p in paths for s in p["steps"]))

    def test_on_hand_without_a_record_is_reported(self):
        with TempStore({"s.site": "site s\nhave t/ghost\n"}) as d:
            _, r = run_json("site", "--store", SKETCH, os.path.join(d, "s.site"))
        self.assertIn("t/ghost", [p["where"] for p in r["problems"]])


class Summary(unittest.TestCase):
    def test_sketch_counts(self):
        _, r = run_json("summary", "--store", SKETCH)
        self.assertEqual((r["systems"], r["producers"], r["consumers"], r["pairs"]), (8, 7, 4, 25))
        self.assertEqual(sum(r["pairs_by_strongest_path"].values()), 25)


class NotPrescriptive(unittest.TestCase):
    """The output lists options and evidence. It never says which to use.
    Key names come from the packs and may hold any word, so they are counted
    here, not listed."""

    WORDS = ("recommend", "best", "prefer", "should", "optimal", "score", "rank")

    def test_no_ranking_words_in_any_output(self):
        outs = [
            run("paths", "--store", SKETCH, "--from", "example/rf-1", "--to", "example/c2-app", "--keys", "count")[1],
            run("paths", "--store", SKETCH, "--from", "example/rf-1", "--to", "example/c2-app", "--table")[1],
            run("site", "--store", SKETCH, SITE, "--keys", "count")[1],
            run("site", "--store", SKETCH, SITE, "--table")[1],
            run("summary", "--store", SKETCH, "--table")[1],
        ]
        for text in outs:
            low = text.lower()
            for w in self.WORDS:
                self.assertNotIn(w, low.replace("not a preference", ""), w)


class Check(unittest.TestCase):
    def test_sketch_is_clean_under_strict(self):
        code, r = run_json("check", "--store", SKETCH, "--strict")
        self.assertEqual(code, 0, r["problems"])

    def test_strict_fails_on_a_warning(self):
        with TempStore({"x.rec": "system t/x\nemits a status=proven\n"}) as d:
            code, _ = run_json("check", "--store", d, "--strict")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
