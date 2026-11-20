"""The order of `when` members on the geojson wire in tools/gen/jsonschema2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_jsonschema2pack_geojson*.py'

Ruling 10 of 0.5: mapped members and `when` members are written in line order, common lines
first. A common `when properties.kind` is written before the kind's field lines, even when a
field line also maps that member. The schema is written by the test (synthetic).
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
        "id": {"type": "string"},
        "geometry": {"type": "object"},
        "properties": {"type": "object", "properties": {
            "name": {"type": "string"}, "kind": {"type": "string", "enum": ["a", "b"]},
            "size": {"type": "integer"}}},
    },
}


class GeojsonWhenOrder(unittest.TestCase):
    def test_common_when_members_come_first(self):
        work = tempfile.mkdtemp(prefix="jsonschema2pack-gw-")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        os.makedirs(os.path.join(work, "model"))
        src = os.path.join(support.FIXTURES, "jsonschema2pack", "input", "model")
        for f in ("core.def", "track.def"):
            shutil.copy(os.path.join(src, f), os.path.join(work, "model", f))
        schema = os.path.join(work, "s.json")
        with open(schema, "w", encoding="utf-8") as fh:
            json.dump(SCHEMA, fh)
        status, _, err = support.run_main(j.main, [
            "--schema", schema, "--message", "Doc=" + schema, "--when", "properties.kind=b",
            "--wire", "geojson", "--top-level-members", "id", "--format", "gw", "--module", "gw",
            "--title", "t", "--license", "written for the tests", "--out", work,
            "--model-dir", os.path.join(work, "model"), "--names-file", os.path.join(work, "n.json")])
        self.assertEqual(status, 0, err)
        with open(os.path.join(work, "packs", "gw", "vectors", "gen-001-doc-roundtrip.json"), encoding="utf-8") as fh:
            v = json.load(fh)
        self.assertIn('"properties":{"kind":"b","name":', v["expect"])
        self.assertEqual(v["input"], v["expect"])


if __name__ == "__main__":
    unittest.main()
