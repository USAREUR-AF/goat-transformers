"""Tests of the --max-depth, --max-nest and --limit-reason options of tools/gen/jsonschema2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_jsonschema2pack_limits*.py'

The schema is written by the test (synthetic): an object two levels deep, and an
array of objects whose items hold an array of objects. Without the options the
output is the one the golden test of test_jsonschema2pack.py pins.
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
        "ID": {"type": "string"},
        "OUTER": {"type": "object", "properties": {
            "INNER": {"type": "object", "properties": {"DEEP": {"type": "number"}}},
            "NEAR": {"type": "string"}}},
        "ROWS": {"type": "array", "items": {"type": "object", "properties": {
            "NAME": {"type": "string"},
            "CELLS": {"type": "array", "items": {"type": "object", "properties": {
                "V": {"type": "integer"}}}}}}},
    },
}


class LimitsTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="jsonschema2pack-limits-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.addCleanup(j.LIMITS.update, dict(j.LIMITS))
        os.makedirs(os.path.join(self.work, "model"))
        src = os.path.join(support.FIXTURES, "jsonschema2pack", "input", "model")
        for f in ("core.def", "track.def"):
            shutil.copy(os.path.join(src, f), os.path.join(self.work, "model", f))
        self.schema = os.path.join(self.work, "limits.json")
        with open(self.schema, "w", encoding="utf-8") as fh:
            json.dump(SCHEMA, fh)

    def run_gen(self, *extra):
        argv = ["--schema", self.schema, "--message", "Lim=" + self.schema, "--format", "lim",
                "--module", "lim", "--title", "limits test", "--license", "written for the tests",
                "--out", self.work, "--model-dir", os.path.join(self.work, "model"),
                "--names-file", os.path.join(self.work, "names", "lim.json")] + list(extra)
        status, _, err = support.run_main(j.main, argv)
        self.assertEqual(status, 0, err)
        with open(os.path.join(self.work, "packs", "lim", "pack.def"), encoding="utf-8") as fh:
            pack = fh.read()
        with open(os.path.join(self.work, "packs", "lim", "pack.md"), encoding="utf-8") as fh:
            md = fh.read()
        return pack, md

    def test_without_limits_everything_is_mapped_and_no_limit_is_stated(self):
        pack, md = self.run_gen()
        self.assertIn("OUTER.INNER.DEEP", pack)
        self.assertIn("group  lim.rows_cells  CELLS", pack)
        self.assertNotIn("Limits of this pack", md)

    def test_max_depth_cuts_deeper_objects_and_pack_md_says_why(self):
        pack, md = self.run_gen("--max-depth", "2", "--limit-reason", "kept small for the test.")
        self.assertIn("OUTER.NEAR", pack)
        self.assertNotIn("OUTER.INNER.DEEP", pack)
        self.assertNotIn("CELLS", pack)
        self.assertIn("| `lim` | `OUTER.INNER` | below depth 2 |", md)
        self.assertIn("Limits of this pack: objects nested deeper than 2 levels (an array counts as a level) "
                      "are not mapped (kept small for the test).", md)

    def test_max_nest_cuts_an_array_inside_an_array(self):
        pack, md = self.run_gen("--max-nest", "1")
        self.assertIn("group  lim.rows  ROWS", pack)
        self.assertIn("OUTER.INNER.DEEP", pack)
        self.assertNotIn("CELLS", pack)
        self.assertIn("| `lim` | `ROWS[].CELLS` | array inside 1 arrays (--max-nest 1) |", md)
        self.assertIn("Limits of this pack: an array inside 1 arrays is not mapped.", md)

    def test_a_limit_does_not_carry_into_the_next_run(self):
        self.run_gen("--max-depth", "1")
        shutil.rmtree(os.path.join(self.work, "names"))
        pack, md = self.run_gen()
        self.assertIn("OUTER.INNER.DEEP", pack)
        self.assertNotIn("Limits of this pack", md)

    def test_a_limit_below_one_is_refused(self):
        argv = ["--schema", self.schema, "--message", "Lim=" + self.schema, "--format", "lim",
                "--module", "lim", "--title", "t", "--license", "l", "--out", self.work,
                "--model-dir", os.path.join(self.work, "model"),
                "--names-file", os.path.join(self.work, "names", "lim.json"), "--max-depth", "0"]
        status, _, err = support.run_main(j.main, argv)
        self.assertEqual(status, 1)
        self.assertIn("--max-depth must be at least 1", err)


if __name__ == "__main__":
    unittest.main()
