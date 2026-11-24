"""Tests for tools/model-checks.py (meaning is tested, not only agreement).
Standard library only:

    python3 -I -m unittest discover -s tools/tests

Most tests run the tool on a small invented tree in a temporary directory: a
core and a track module, a module with a list and a flag, a few packs on the
json wire and their vectors. The rules are the repository's own
tools/model-ranges.json. One test runs `--check` on this repository.
"""
import json
import os
import time
import unittest

from support import REPO, TempTree, load_tool, run_main

mc = load_tool("model-checks.py")

HEAD = 'version 0.1.0\ndistribution public\nsource "an invented public document"\n'
MODELS = {
    "model/core.def": "module core\n" + HEAD + (
        'key uid string - "identifier"\n'
        'key time_ms int ms "time, epoch milliseconds UTC"\n'
        'key stale_ms int ms "stale time, epoch milliseconds UTC"\n'
        'key lat float deg "latitude"\nkey lon float deg "longitude"\n'
        'key hae float m "height above the WGS84 ellipsoid"\n'
        'key course float deg "course"\nkey speed_ms float m/s "ground speed"\n'),
    "model/track.def": "module track\n" + HEAD + (
        'key class string - "track class: unknown, uas, bird"\n'
        'key confidence float - "confidence in [0,1]"\n'),
    "model/probe.def": "module probe\n" + HEAD + (
        'key on int - "flag: the thing is on"\n'
        'key count int - "a count, not a flag"\n'
        'key alt_msl float m "altitude above mean sea level"\n'
        'list points "points"\n'),
}
# A pack on the json wire that maps every key above; `lat` 91 means absent in
# `withsentinel`.
FIELDS = (
    "wire json\nfield uid id string\nfield time_ms t int\nfield stale_ms s int\n"
    "field lon lon float\nfield hae h float\nfield course c float\nfield speed_ms v float\n"
    "field track.class cls string\nfield track.confidence conf float\n"
    "field probe.on on int\nfield probe.count n int\n"
    "group probe.points pts\n  field lat lat float\nend\n")
GOOD = {"id": "u1", "t": 1700000000000, "s": 1700000060000, "lat": 10.5, "lon": 20.5, "h": 100.0,
        "c": 90.0, "v": 3.0, "cls": "uas", "conf": 0.5, "on": 1, "n": 7, "pts": [{"lat": 1.0}]}
ELLIPSOID_MD = "# alpha\n\n`hae` is the height above the WGS 84 ellipsoid.\n"


def pack(name, lat_options=""):
    return "format %s\n" % name + HEAD + "uses track\nuses probe\n" + FIELDS + "field lat lat float%s\n" % lat_options


def vector(name, msg, to="alpha", frm="alpha"):
    return json.dumps({"name": name, "from": frm, "to": to, "input": json.dumps(msg), "expect": ""})


class Tree(unittest.TestCase):
    def setUp(self):
        self.t = TempTree()
        self.addCleanup(self.t.cleanup)
        for rel, text in MODELS.items():
            self.t.write(rel, text)
        self.t.write("packs/alpha/pack.def", pack("alpha"))
        self.t.write("packs/alpha/pack.md", ELLIPSOID_MD)
        self.allow = self.t.write("tools/model-checks-allow.txt", "")

    def vec(self, name, change=None, drop=(), **kw):
        msg = dict(GOOD)
        msg.update(change or {})
        for k in drop:
            msg.pop(k)
        pk = kw.pop("pack", "alpha")
        self.t.write("packs/%s/vectors/%s.json" % (pk, name), vector(name, msg, **kw))

    def run_tool(self, *args):
        return run_main(mc.main, "--root", self.t.root, *args)

    def failures(self):
        code, out, err = self.run_tool("--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)


class Values(Tree):
    def test_plausible_values_pass(self):
        self.vec("good")
        report = self.failures()
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["stats"]["decoded"], 1)
        self.assertEqual(report["stats"]["checked"]["lat"], 2)  # the entity's and the item's
        for key in ("lon", "hae", "time_ms", "stale_ms", "course", "speed_ms", "track.class",
                    "track.confidence", "probe.on"):
            self.assertEqual(report["stats"]["checked"].get(key), 1, key)
        self.assertNotIn("probe.count", report["stats"]["checked"])  # an int that is not a flag
        code, out, _ = self.run_tool("--check")
        self.assertEqual(code, 0, out)
        self.assertIn("0 failures", out)

    def test_each_rule_fails(self):
        cases = {
            "lat": ({"lat": 91.0}, "lat"),
            "lon": ({"lon": -180.5}, "lon"),
            "hae-deep": ({"h": -20000.0}, "hae"),
            "course": ({"c": 361.0}, "course"),
            "speed": ({"v": -1.0}, "speed_ms"),
            "fast": ({"v": 200000.0}, "speed_ms"),
            "time-relative": ({"t": 396, "s": 470}, "time_ms"),
            "class": ({"cls": "plane"}, "track.class"),
            "confidence": ({"conf": 7.75}, "track.confidence"),
            "flag": ({"on": 2}, "probe.on"),
            "item": ({"pts": [{"lat": 0.0}, {"lat": 95.0}]}, "probe.points[1].lat"),
        }
        for name, (change, _) in cases.items():
            self.vec(name, change)
        got = {(f["location"], f["key"]) for f in self.failures()["failures"]}
        for name, (_, key) in cases.items():
            self.assertIn(("alpha/" + name, key), got)

    def test_stale_before_time_fails(self):
        self.vec("stale", {"s": GOOD["t"] - 1})
        [f] = self.failures()["failures"]
        self.assertEqual((f["key"], f["value"]), ("stale_ms", GOOD["t"] - 1))
        self.assertIn("earlier than time_ms", f["why"])

    def test_not_finite_fails_a_range(self):
        self.assertIn("not finite", mc.check_value({"min": 0}, float("inf")))
        self.assertIn("not finite", mc.check_value({"max": 1}, float("nan")))
        self.assertIsNone(mc.check_value({"min": 0, "max": 360}, 360))

    def test_a_declared_sentinel_is_not_a_value(self):
        self.t.write("packs/alpha/pack.def", pack("alpha", " absent 91"))
        self.vec("not-available", {"lat": 91})  # top-level lat: the item `pts` keeps its own
        report = self.failures()
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["stats"]["checked"]["lat"], 1)  # the item's lat only

    def test_a_vector_that_does_not_decode_is_counted(self):
        self.t.write("packs/alpha/vectors/bad.json", json.dumps(
            {"name": "bad", "from": "alpha", "to": "alpha", "input": "{", "expect_error": "malformed-wire"}))
        stats = self.failures()["stats"]
        self.assertEqual((stats["decoded"], stats["not_decoded"]), (0, 1))

    def test_synthetic_packs_and_their_vectors_are_skipped(self):
        self.t.write("packs/conformance-x/pack.def", pack("conformance-x"))
        self.t.write("packs/conformance-x/pack.md", ELLIPSOID_MD)
        self.vec("edge", {"lat": 1e300}, pack="conformance-x", frm="conformance-x", to="conformance-x")
        self.vec("to-edge", {"lat": 1e300}, to="conformance-x")
        report = self.failures()
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["stats"]["skipped_synthetic"], 2)

    def test_shards_cover_the_tree_once(self):
        for name in ("beta", "gamma"):
            self.t.write("packs/%s/pack.def" % name, pack(name))
            self.t.write("packs/%s/pack.md" % name, ELLIPSOID_MD)
            self.vec("bad", {"lat": 99.0}, pack=name, frm=name, to=name)
        self.vec("bad", {"lat": 99.0})
        seen = []
        for i in range(2):
            code, out, err = self.run_tool("--json", "--shard", "%d/2" % i)
            self.assertEqual(code, 0, err)
            seen += [f["location"] for f in json.loads(out)["failures"]]
        self.assertEqual(sorted(seen), ["alpha/bad", "beta/bad", "gamma/bad"])
        self.assertEqual(self.run_tool("--shard", "2/2")[0], 2)


class Allow(Tree):
    def test_a_new_failure_fails_the_check(self):
        self.vec("bad", {"lat": 91.0})
        code, out, _ = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("alpha/bad lat = 91.0", out)

    def test_an_allowed_failure_passes_and_is_marked(self):
        self.vec("bad", {"lat": 91.0})
        self.t.write("tools/model-checks-allow.txt", "# known\n\nalpha/bad lat defect(pack): no sentinel\n")
        code, out, _ = self.run_tool("--check")
        self.assertEqual(code, 0, out)
        self.assertNotIn("alpha/bad", out)
        self.assertIn("1 allowed, 0 new", out)
        self.assertIn("allowed alpha/bad lat", self.run_tool()[1])

    def test_an_allow_line_that_no_longer_fails_fails_the_check(self):
        self.vec("good")
        self.t.write("tools/model-checks-allow.txt", "alpha/good lat defect(pack): fixed since\n")
        code, out, _ = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("no longer fails, remove it: alpha/good lat", out)

    def test_an_allow_line_needs_a_reason_and_is_listed_once(self):
        self.vec("bad", {"lat": 91.0})
        self.t.write("tools/model-checks-allow.txt", "alpha/bad lat\n")
        code, out, _ = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("not `<pack>/<vector> <key> <reason>`", out)
        self.t.write("tools/model-checks-allow.txt", "alpha/bad lat one\nalpha/bad lat two\n")
        code, out, _ = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("listed twice", out)

    def test_a_shard_judges_only_its_own_allow_lines(self):
        self.t.write("packs/beta/pack.def", pack("beta"))
        self.t.write("packs/beta/pack.md", ELLIPSOID_MD)
        self.t.write("tools/model-checks-allow.txt", "beta/gone lat defect(vector): fixed since\n")
        self.assertEqual(self.run_tool("--check", "--shard", "0/2")[0], 0)  # alpha only
        self.assertEqual(self.run_tool("--check", "--shard", "1/2")[0], 1)  # beta


class Datum(Tree):
    def datum(self, md, fields=None):
        if fields is not None:
            self.t.write("packs/alpha/pack.def", "format alpha\n" + HEAD + "uses probe\nwire json\n" + fields)
        self.t.write("packs/alpha/pack.md", md)
        return [f for f in self.failures()["failures"] if f["key"] == "datum"]

    def test_the_height_keys_come_from_the_model(self):
        api = mc.engine_api()
        eng = api.Engine.from_dir(os.path.join(REPO, "packs"), os.path.join(REPO, "model"),
                                  packs_only=["nmea0183", "gpx", "misb-st0601"])
        with open(os.path.join(REPO, "tools", "model-ranges.json"), encoding="utf-8") as fh:
            rules = mc.Rules(json.load(fh), eng.models)
        for key in ("hae", "nmea0183.alt_msl_m", "gpx.ele", "misb0601.frame_center_hae"):
            self.assertIn(key, rules.heights)
        for key in ("le", "nmea0183.geoid_sep_m", "misb0601.sensor_true_altitude"):
            self.assertNotIn(key, rules.ellipsoid_keys)
        self.assertNotIn("le", rules.heights)
        self.assertNotIn("nmea0183.geoid_sep_m", rules.heights)  # a separation, not a height of the entity
        self.assertIn("misb0601.frame_center_hae", rules.ellipsoid_keys)

    def test_a_height_whose_datum_is_named_passes(self):
        self.assertEqual(self.datum(ELLIPSOID_MD), [])
        self.assertEqual(self.datum("| `h` | `hae` | metres, HAE |\n"), [])

    def test_a_pack_that_names_no_datum_fails(self):
        [f] = self.datum("# alpha\n\n`hae` is the altitude in metres.\n")
        self.assertIn("names its vertical datum", f["why"])
        self.assertEqual(f["location"], "alpha/pack.md")

    def test_a_datum_word_away_from_any_height_does_not_count(self):
        [f] = self.datum("# alpha\n\n`hae` is in metres.\n\nPositions are on the WGS 84 ellipsoid.\n")
        self.assertIn("names its vertical datum", f["why"])

    def test_mean_sea_level_mapped_to_hae_fails(self):
        [f] = self.datum("# alpha\n\n`hae` is the altitude above mean sea level.\n")
        self.assertIn("names only mean sea level", f["why"])

    def test_hae_from_a_source_that_states_no_datum_is_an_assumption(self):
        md = ("# alpha\n\nThe height is above the WGS 84 ellipsoid in the old pack. The source does not say what"
              " `altitude` is measured from; it is bound to `hae`.\n")
        [f] = self.datum(md)
        self.assertIn("the binding is an assumption", f["why"])
        md = "# alpha\n\nThe height is above the WGS 84 ellipsoid. `alt` has no stated reference, so it is not `hae`.\n"
        self.assertEqual(self.datum(md), [])

    def test_a_height_key_of_another_module_needs_a_datum(self):
        fields = "field uid id string\nfield probe.alt_msl a float\n"
        [f] = self.datum("# alpha\n\n`alt_msl` is in metres.\n", fields)
        self.assertIn("probe.alt_msl", f["why"])
        self.assertEqual(self.datum("# alpha\n\n`alt_msl` is above mean sea level.\n", fields), [])

    def test_a_pack_that_maps_no_height_is_not_read(self):
        self.assertEqual(self.datum("nothing\n", "field uid id string\nfield probe.count n int\n"), [])


class InnerKeys(Tree):
    """A pack and the pack its `inner` line names map no key in common (0.34)."""
    BITS = HEAD + "uses probe\nwire bits\nlayout sequential\nbit_order msb\n"

    def seq(self, name, body):
        self.t.write("packs/%s/pack.def" % name, "format %s\n" % name + self.BITS + body)

    def found(self, *args):
        code, out, err = self.run_tool("--inner-keys", *args)
        return code, out + err

    def test_packs_with_no_key_in_common_pass(self):
        self.seq("inside", "field probe.on 8 uint\n")
        self.seq("outside", "field probe.count 8 uint\ninner inside\n")
        code, out = self.found()
        self.assertEqual(code, 0, out)
        self.assertIn("1 packs with an inner line checked, 0 failures", out)

    def test_a_shared_key_is_refused(self):
        self.seq("inside", "field probe.on 8 uint\nfield probe.count 8 uint\n")
        self.seq("outside", "field probe.count 8 uint\ninner inside\n")
        code, out = self.found()
        self.assertEqual(code, 1)
        self.assertIn("outside/pack.def inner:inside = probe.count:", out)
        self.assertEqual(self.run_tool("--check")[0], 1)

    def test_also_as_partial_kinds_and_lengths_are_seen(self):
        self.seq("inside", "field probe.on 8 uint\n")
        self.seq("by-also", "field probe.count 8 uint\nalso probe.on\ninner inside\n")
        self.seq("by-as", "kind a\nwhen 8 1 as probe.on\ninner inside\n")
        self.seq("by-length", "length 8\n  inner inside partial\nend\nfield probe.on 8 uint\n")
        self.seq("by-kind", "kind a\nwhen 8 1\nfield probe.on 8 uint\ninner inside\n")
        code, out = self.found()
        self.assertEqual(code, 1)
        for name in ("by-also", "by-as", "by-length", "by-kind"):
            self.assertIn("%s/pack.def inner:inside = probe.on:" % name, out)

    def test_a_list_both_map_is_one_key_and_item_keys_are_not_shared(self):
        self.seq("inside", "group probe.points rest\n  field probe.on 8 uint\nend\n")
        self.seq("samelist", "group probe.points count 8\n  field probe.count 8 uint\nend\ninner inside\n")
        self.seq("itemkey", "field probe.on 8 uint\ninner inside\n")
        code, out = self.found()
        self.assertEqual(code, 1)
        self.assertIn("samelist/pack.def inner:inside = probe.points[]:", out)
        self.assertNotIn("itemkey/", out)

    def test_an_inner_pack_outside_the_tree_is_refused(self):
        self.seq("outside", "field probe.count 8 uint\ninner elsewhere\n")
        code, out = self.found()
        self.assertEqual(code, 1)
        self.assertIn("not in the tree", out)

    def test_conformance_packs_are_not_checked(self):
        self.seq("inside", "field probe.count 8 uint\n")
        self.seq("conformance-out", "field probe.count 8 uint\ninner inside\n")
        code, out = self.found()
        self.assertEqual(code, 0, out)

    def test_the_allow_file_does_not_waive_it(self):
        self.seq("inside", "field probe.count 8 uint\n")
        self.seq("outside", "field probe.count 8 uint\ninner inside\n")
        self.t.write("tools/model-checks-allow.txt", "outside/pack.def inner:inside defect(pack): known\n")
        self.assertEqual(self.found()[0], 1)
        code, out, err = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("does not waive", out)
        self.assertIn("outside/pack.def inner:inside", out)


class Repository(unittest.TestCase):
    def test_this_repository_passes_the_check(self):
        started = time.monotonic()
        code, out, err = run_main(mc.main, "--check")
        self.assertEqual(code, 0, out + err)
        self.assertIn("0 new, 0 allow lines stale", out)
        self.assertLess(time.monotonic() - started, 600)


if __name__ == "__main__":
    unittest.main()
