"""--geojson-groups in tools/gen/jsonschema2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_jsonschema2pack_geojson*.py'

Engine-spec 0.7: on the geojson wire a `group` may address an array member of `properties`
(`properties.<name>`), its items read as on json. With the option the generator writes such a
group, leaves booleans in the items out (`bool` is a json transform only), and its own codec
round-trips the vector; without the option the array stays residue. The schema is written by
the test (synthetic).
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
        "type": {"type": "string"},
        "geometry": {"type": "object"},
        "properties": {"type": "object", "properties": {
            "name": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "t": {"type": "string"},
                "v": {"type": "object", "properties": {"x": {"type": "number"}}},
                "ok": {"type": "boolean"}}}},
            "tags": {"type": "array", "items": {"type": "string"}}}},
    },
}


class GeojsonGroups(unittest.TestCase):
    def run_gen(self, groups):
        work = tempfile.mkdtemp(prefix="jsonschema2pack-gg-")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        os.makedirs(os.path.join(work, "model"))
        src = os.path.join(support.FIXTURES, "jsonschema2pack", "input", "model")
        for f in ("core.def", "track.def"):
            shutil.copy(os.path.join(src, f), os.path.join(work, "model", f))
        schema = os.path.join(work, "s.json")
        with open(schema, "w", encoding="utf-8") as fh:
            json.dump(SCHEMA, fh)
        args = ["--schema", schema, "--message", "Doc=" + schema, "--wire", "geojson",
                "--format", "gg", "--module", "gg", "--title", "t", "--license", "written for the tests",
                "--out", work, "--model-dir", os.path.join(work, "model"),
                "--names-file", os.path.join(work, "n.json"),
                "--map", "Doc:geometry.lon=lon", "--map", "Doc:geometry.lat=lat"]
        if groups:
            args.append("--geojson-groups")
        status, _, err = support.run_main(j.main, args)
        self.assertEqual(status, 0, err)
        with open(os.path.join(work, "packs", "gg", "pack.def"), encoding="utf-8") as fh:
            pack = fh.read()
        with open(os.path.join(work, "packs", "gg", "vectors", "gen-001-doc-roundtrip.json"), encoding="utf-8") as fh:
            vec = json.load(fh)
        return pack, vec

    def test_array_of_objects_is_a_group(self):
        pack, vec = self.run_gen(True)
        self.assertIn("group  gg.properties_steps  properties.steps", pack)
        self.assertIn("field  gg.properties_steps_v_x  v.x  float", pack)
        self.assertIn("group  gg.properties_tags  properties.tags", pack)
        self.assertNotIn("bool", pack)
        self.assertEqual(vec["input"], vec["expect"])
        self.assertIn('"steps":[{', vec["expect"])

    def test_without_the_option_arrays_stay_residue(self):
        pack, vec = self.run_gen(False)
        self.assertNotIn("group", pack)
        self.assertEqual(vec["input"], vec["expect"])


if __name__ == "__main__":
    unittest.main()
