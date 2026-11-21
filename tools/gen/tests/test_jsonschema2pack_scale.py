"""Tests of the --scale option of tools/gen/jsonschema2pack.py (engine-spec 0.15 `iscale`).

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_jsonschema2pack_scale*.py'

The schema is written by the test (synthetic): an integer of POSIX seconds, a number of
seconds with a fraction, a string and a float. Without --scale the output is the one the
golden test of test_jsonschema2pack.py pins.
"""
import json
import os
import shutil
import tempfile
import unittest

import support
import jsonschema2pack as j

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2019-09/schema",
    "type": "object",
    "properties": {
        "updated": {"type": "integer", "minimum": 0, "description": "Update time in POSIX seconds."},
        "now": {"type": "number", "description": "Seconds since the Unix epoch."},
        "name": {"type": "string"},
        "level": {"type": "number"},
    },
}


class ScaleTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="jsonschema2pack-scale-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        os.makedirs(os.path.join(self.work, "model"))
        src = os.path.join(support.FIXTURES, "jsonschema2pack", "input", "model")
        for f in ("core.def", "track.def"):
            shutil.copy(os.path.join(src, f), os.path.join(self.work, "model", f))
        self.schema = os.path.join(self.work, "s.json")
        with open(self.schema, "w", encoding="utf-8") as fh:
            json.dump(SCHEMA, fh)

    def argv(self, *extra):
        return ["--schema", self.schema, "--message", "Doc=" + self.schema, "--format", "sc",
                "--module", "sc", "--title", "scale test", "--license", "written for the tests",
                "--out", self.work, "--model-dir", os.path.join(self.work, "model"),
                "--names-file", os.path.join(self.work, "names", "sc.json")] + list(extra)

    def read(self, *parts):
        with open(os.path.join(self.work, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_seconds_bound_to_time_ms_with_iscale(self):
        status, _, err = support.run_main(j.main, self.argv("--map", "Doc:updated=time_ms",
                                                           "--scale", "Doc:updated=iscale:1000"))
        self.assertEqual(status, 0, err)
        pack = self.read("packs", "sc", "pack.def")
        self.assertIn("field  time_ms  updated  iscale:1000\nfield  sc.updated  updated  int\n", pack)
        md = self.read("packs", "sc", "pack.md")
        self.assertIn("| `doc` | `updated` | `time_ms` (int, ms) | integer, read with `iscale:1000` |", md)
        v = json.loads(self.read("packs", "sc", "vectors", "gen-001-doc-roundtrip.json"))
        doc = json.loads(v["input"])
        self.assertIsInstance(doc["updated"], int)
        self.assertEqual(v["input"], v["expect"])
        self.assertEqual(v["model"]["time_ms"], str(doc["updated"] * 1000))

    def test_a_number_with_a_fraction_is_read_exactly(self):
        self.assertEqual(j.dec_value(1714566600.5, "iscale:1000", "now"), 1714566600500)
        self.assertEqual(j.dec_value(-2.5, "iscale:1", "x"), -3)       # half away from zero
        self.assertEqual(j.dec_value(2.5, "iscale:1", "x"), 3)
        self.assertEqual(j.dec_value(7, "iscale:3:1", "x"), 22)
        self.assertEqual(j.dump(j.enc_value(1714566600500, "iscale:1000")), "1714566600.5")
        self.assertEqual(j.dump(j.enc_value(1714566601000, "iscale:1000")), "1714566601")
        self.assertEqual(j.dump(j.enc_value(-1, "iscale:1000")), "-0.001")
        with self.assertRaises(j.GenError):
            j.enc_value(1, "iscale:3")                                  # 1/3 does not terminate

    def test_a_float_member_is_scaled_on_the_shared_line(self):
        status, _, err = support.run_main(j.main, self.argv("--map", "Doc:now=time_ms",
                                                           "--scale", "Doc:now=iscale:1000"))
        self.assertEqual(status, 0, err)
        self.assertIn("field  time_ms  now  iscale:1000\nfield  sc.now  now  float\n",
                      self.read("packs", "sc", "pack.def"))

    def test_float_scale_puts_the_raw_line_first(self):
        status, _, err = support.run_main(j.main, self.argv("--map", "Doc:level=speed_ms",
                                                           "--scale", "Doc:level=scale:5/18"))
        self.assertEqual(status, 0, err)
        self.assertIn("field  sc.level  level  float\nfield  speed_ms  level  scale:5/18\n",
                      self.read("packs", "sc", "pack.def"))
        md = self.read("packs", "sc", "pack.md")
        self.assertIn("number, read with `scale:5/18`", md)
        self.assertIn("A path read with a float `scale` has its raw key's line first", md)
        v = json.loads(self.read("packs", "sc", "vectors", "gen-001-doc-roundtrip.json"))
        level = json.loads(v["input"])["level"]
        self.assertEqual(v["input"], v["expect"])
        self.assertEqual(float(v["model"]["speed_ms"]), level * 5.0 / 18.0)
        # the codec's arithmetic and order (ruling 1 of 0.5)
        self.assertEqual(j.dec_value(36.0, "scale:5/18", "x"), 36.0 * 5 / 18)
        self.assertEqual(j.enc_value(10.0, "scale:5/18"), 10.0 * 18 / 5)
        self.assertEqual(j.dec_value(2, "scale:0.5:1", "x"), 2.0)
        self.assertEqual(j.enc_value(2.0, "scale:0.5:1"), 2.0)

    def test_a_track_key_brings_uses_track(self):
        # a --map to a key of the track module needs `uses track` (engine-spec 0.4, module-not-used)
        status, _, err = support.run_main(j.main, self.argv("--map", "Doc:level=track.vel_north_ms"))
        self.assertEqual(status, 0, err)
        pack = self.read("packs", "sc", "pack.def")
        self.assertIn("uses          sc\nuses          track\nwire          json\n", pack)
        status, _, err = support.run_main(j.main, self.argv("--map", "Doc:level=speed_ms"))
        self.assertEqual(status, 0, err)
        self.assertNotIn("uses          track", self.read("packs", "sc", "pack.def"))

    def test_refusals(self):
        cases = [
            (("--scale", "Doc:updated=iscale:1000"), "no --map binding at that path"),
            (("--map", "Doc:name=uid", "--scale", "Doc:name=iscale:1000"), "the leaf is string, not a number"),
            (("--map", "Doc:level=lat", "--scale", "Doc:level=iscale:1000"), "iscale yields int, the key lat is float"),
            (("--map", "Doc:updated=time_ms", "--scale", "Doc:updated=scale:1000"),
             "scale yields float, the key time_ms is int"),
            (("--map", "Doc:updated=time_ms", "--scale", "Doc:updated=iscale:x"), "not iscale:<factor>[:<offset>]"),
            (("--map", "Doc:level=speed_ms", "--scale", "Doc:level=iscale:1000"),
             "iscale yields int, the key speed_ms is float"),
            (("--map", "Doc:level=speed_ms", "--scale", "Doc:level=scale:1/0"), "factor 0"),
            (("--map", "Doc:updated=time_ms", "--scale", "Doc:updated=iscale:0"), "factor 0"),
        ]
        for extra, needle in cases:
            status, _, err = support.run_main(j.main, self.argv(*extra))
            self.assertEqual(status, 1, extra)
            self.assertIn(needle, err, extra)


if __name__ == "__main__":
    unittest.main()
