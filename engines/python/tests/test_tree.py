"""`load_tree` loads the named packs and only the model modules they need."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))

from goat_transformers import Engine, UnknownFormat, load_tree  # noqa: E402

COT = (
    b'<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g">'
    b'<point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/>'
    b'<detail><contact callsign="GATOR"/></detail></event>'
)
GEOJSON = (
    b'{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},'
    b'"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,'
    b'"callsign":"GATOR"},"id":"J-01334"}'
)


class LoadTree(unittest.TestCase):
    def test_named_packs_and_the_modules_they_use(self):
        eng = load_tree(ROOT, ["cot-xml", "geojson"])
        self.assertEqual(eng.formats(), ["cot-xml", "geojson"])
        self.assertEqual(sorted(eng.models), ["core"])
        self.assertEqual(eng.convert("cot-xml", "geojson", COT), GEOJSON)

    def test_uses_through_modules_and_a_second_load(self):
        # asterix-cat062 uses cat062, and cat062 uses track
        eng = load_tree(ROOT, ["asterix-cat062"])
        self.assertEqual(sorted(eng.models), ["cat062", "core", "track"])
        self.assertIs(load_tree(ROOT, ["canonical-track-v2"], engine=eng), eng)
        self.assertEqual(eng.formats(), ["asterix-cat062", "canonical-track-v2"])

    def test_a_pack_the_tree_does_not_hold(self):
        with self.assertRaises(UnknownFormat):
            load_tree(ROOT, ["no-such-format"])

    def test_distribution_limit_is_kept(self):
        eng = load_tree(ROOT, ["geojson"], max_distribution="public")
        self.assertIsInstance(eng, Engine)
        self.assertEqual(eng.max_distribution, "public")


if __name__ == "__main__":
    unittest.main()
