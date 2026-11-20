"""Tests of the --date-time and --evidence options of tools/gen/jsonschema2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_jsonschema2pack_datetime*.py'

The schema is written by the test (synthetic): a timestamp stated by a pattern only (no
`format`), an identifier and a number. Without the options the output is the one the
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
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Identifier written for the test."},
        "stamp": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}(\\\\.[0-9]+)?Z$",
                  "description": "A time written for the test."},
        "level": {"type": "number"},
    },
}


class DateTimeEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="jsonschema2pack-dt-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        os.makedirs(os.path.join(self.work, "model"))
        src = os.path.join(support.FIXTURES, "jsonschema2pack", "input", "model")
        for f in ("core.def", "track.def"):
            shutil.copy(os.path.join(src, f), os.path.join(self.work, "model", f))
        self.schema = os.path.join(self.work, "s.json")
        with open(self.schema, "w", encoding="utf-8") as fh:
            json.dump(SCHEMA, fh)

    def run_gen(self, *extra):
        argv = ["--schema", self.schema, "--message", "Doc=" + self.schema, "--format", "dt",
                "--module", "dt", "--title", "date-time test", "--license", "written for the tests",
                "--out", self.work, "--model-dir", os.path.join(self.work, "model"),
                "--names-file", os.path.join(self.work, "names", "dt.json")] + list(extra)
        return support.run_main(j.main, argv)

    def read(self, *parts):
        with open(os.path.join(self.work, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_without_date_time_a_pattern_string_cannot_bind_time_ms(self):
        status, _, err = self.run_gen("--map", "Doc:stamp=time_ms")
        self.assertEqual(status, 1)
        self.assertIn("the leaf is string, the key time_ms is int", err)

    def test_date_time_binds_with_iso8601_ms_and_samples_a_timestamp(self):
        status, _, err = self.run_gen("--date-time", "Doc:stamp", "--map", "Doc:stamp=time_ms")
        self.assertEqual(status, 0, err)
        self.assertIn("field  time_ms  stamp  iso8601_ms\nfield  dt.stamp  stamp  string\n",
                      self.read("packs", "dt", "pack.def"))
        v = json.loads(self.read("packs", "dt", "vectors", "gen-001-doc-roundtrip.json"))
        stamp = json.loads(v["input"])["stamp"]
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(v["input"], v["expect"])
        self.assertIn("| `doc` | `stamp` | `time_ms` (int, ms) | string, date-time | \"A time written for the test.\" |",
                      self.read("packs", "dt", "pack.md"))

    def test_evidence_replaces_the_quoted_description(self):
        status, _, err = self.run_gen("--map", "Doc:id=uid", "--evidence", "Doc:id=s.json names the record")
        self.assertEqual(status, 0, err)
        md = self.read("packs", "dt", "pack.md")
        self.assertIn("| Kind | Path | Key | Schema type | Evidence (in this project's words; the notes name the source) |", md)
        self.assertIn("| `doc` | `id` | `uid` (string, -) | string | s.json names the record |", md)
        self.assertNotIn("Identifier written for the test.", md)

    def test_refusals(self):
        cases = [
            (("--date-time", "Doc:level"), "the leaf is number, not a string"),
            (("--date-time", "Doc:nothing"), "no mapped leaf at that path"),
            (("--date-time", "Other:stamp"), "names no --message Other"),
            (("--evidence", "Doc:id=text"), "no --map binding at that path"),
            (("--map", "Doc:id=uid", "--evidence", "Doc:id=a | b"), "empty or contains |"),
        ]
        for extra, needle in cases:
            status, _, err = self.run_gen(*extra)
            self.assertEqual(status, 1, extra)
            self.assertIn(needle, err, extra)


if __name__ == "__main__":
    unittest.main()
