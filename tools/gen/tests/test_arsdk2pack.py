"""Tests of tools/gen/arsdk2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_arsdk2pack*.py'

`fixtures/arsdk2pack/input/xml/` holds two files written for these tests in the shape of
arsdk-xml: `ardrone3.xml`, a project with classes whose two position events the generator
binds, an argument-less command, a command with a `string` argument (not built) and one
with every integer width, an enum and a float; and `demo_feature.xml`, a feature without
classes with a feature-level enum, a bitfield, a `LIST_ITEM` event and an event with a
`binary` argument (not built). `expected/` is the tree the generator must write.
"""
import support

import json
import os
import struct
import tempfile
import unittest

import arsdk2pack as gen

FIXTURES = os.path.join(support.FIXTURES, "arsdk2pack")
XML_DIR = os.path.join(FIXTURES, "input", "xml")
MODEL_DIR = os.path.join(support.REPO, "model")
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class ArsdkTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def run_gen(self, *more, xml_dir=XML_DIR):
        return support.run_main(gen.main, ["--xml-dir", xml_dir, "--out", self.root, "--xml-commit", COMMIT,
                                           "--model-dir", MODEL_DIR] + list(more))

    def read(self, rel):
        with open(os.path.join(self.root, *rel.split("/")), encoding="utf-8") as fh:
            return fh.read()

    def test_golden(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        self.assertIn("commands built  6", out)
        self.assertIn("not built       2", out)
        self.assertIn("self-check      ok", out)
        support.assert_same_tree(self, os.path.join(FIXTURES, "expected"), self.root)

    def test_check_mode_and_second_run(self):
        self.assertEqual(self.run_gen()[0], 0)
        first = support.tree(self.root)
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(self.run_gen()[0], 0)
        self.assertEqual(support.tree(self.root), first)

    def test_check_mode_reports_an_edited_file(self):
        self.assertEqual(self.run_gen()[0], 0)
        with open(os.path.join(self.root, "packs", "arsdk-ardrone3", "pack.def"), "a") as fh:
            fh.write("# edited\n")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/arsdk-ardrone3/pack.def", err)

    def test_header_and_layout(self):
        self.assertEqual(self.run_gen()[0], 0)
        text = self.read("packs/arsdk-ardrone3/pack.def")
        self.assertIn("when      0:0:8 1", text)
        # project: class and command ids per kind; arguments from bit 32, little-endian
        self.assertIn("kind      piloting_move\nwhen      0:8:8 0\nwhen      0:16:16 3", text)
        self.assertIn("arsdkardrone3.piloting_move_roll", text)
        self.assertRegex(text, r"arsdkardrone3\.piloting_move_mode\s+0:80:32\s+uint")    # enum: 32 bits
        self.assertRegex(text, r"arsdkardrone3\.piloting_move_count\s+0:112:64\s+uint")   # after the enum
        feat = self.read("packs/arsdk-demo-feature/pack.def")
        self.assertIn("when      0:8:8 0\n", feat)                                          # no class: 0
        self.assertRegex(feat, r"arsdkdemofeature\.set_state_mask\s+0:64:16\s+uint")       # bitfield: base u16
        self.assertRegex(feat, r"arsdkdemofeature\.set_state_offset\s+0:80:32\s+twos")

    def test_commands_not_built_are_listed_with_the_reason(self):
        self.assertEqual(self.run_gen()[0], 0)
        md = self.read("packs/arsdk-ardrone3/pack.md")
        self.assertIn("| `piloting_set_name` | 0 | 2 | a `string` argument", md)
        self.assertIn("NUL-terminated string", md)
        self.assertNotIn("kind      piloting_set_name", self.read("packs/arsdk-ardrone3/pack.def"))
        self.assertIn("| `blob` | 0 | 3 | a `binary` argument", self.read("packs/arsdk-demo-feature/pack.md"))

    def test_bindings_sentinels_and_default_kind(self):
        self.assertEqual(self.run_gen()[0], 0)
        text = self.read("packs/arsdk-ardrone3/pack.def")
        f500 = struct.unpack("<Q", struct.pack("<d", 500.0))[0]
        self.assertRegex(text, r"field     lat\s+0:32:64\s+f64  absent %d" % f500)
        self.assertRegex(text, r"track\.sigma_north_m\s+0:224:8\s+sscale:1  absent 255")
        # the default kind is last and requires lat and lon; the others the raw feature id
        kinds = [l.split()[1] for l in text.splitlines() if l.startswith("kind ")]
        self.assertEqual(kinds[-1], "piloting_state_position_changed")
        self.assertIn("kind      piloting_state_position_changed\nwhen      0:8:8 4\nwhen      0:16:16 4\n"
                      "requires  lat lon", text)
        self.assertIn("kind      piloting_take_off\nwhen      0:8:8 0\nwhen      0:16:16 1\n"
                      "requires  arsdkardrone3.feature_id", text)
        self.assertNotIn("requires  lat lon", self.read("packs/arsdk-demo-feature/pack.def"))

    def test_geojson_vectors_are_the_position(self):
        self.assertEqual(self.run_gen()[0], 0)
        v = json.loads(self.read("packs/arsdk-ardrone3/vectors/gen-piloting-state-position-changed-to-geojson.json"))
        self.assertEqual(v["expect"], '{"type":"Feature","geometry":{"type":"Point","coordinates":[2.3125,48.875]},'
                                      '"properties":{}}')
        b = bytes.fromhex(v["input"])
        self.assertEqual(b[:4], bytes([1, 4, 4, 0]))
        self.assertEqual(struct.unpack("<dd", b[4:20]), (48.875, 2.3125))
        back = json.loads(self.read("packs/geojson/vectors/to-arsdk-ardrone3-piloting-state-position-changed.json"))
        self.assertEqual(back["input"], v["expect"])
        self.assertEqual(bytes.fromhex(back["expect"]), b[:20] + bytes(8))      # altitude absent: zero bits
        na = json.loads(self.read("packs/arsdk-ardrone3/vectors/"
                                  "gen-piloting-state-position-changed-unavailable-to-geojson.json"))
        self.assertEqual(na["expect"], '{"type":"Feature","geometry":null,"properties":{}}')

    def test_a_file_without_the_bsd_header_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.xml"), "w") as fh:
                fh.write('<?xml version="1.0"?>\n<feature id="9" name="x"><msgs/></feature>\n')
            status, _, err = self.run_gen(xml_dir=d)
        self.assertEqual(status, 1)
        self.assertIn("no BSD-3-Clause header", err)


if __name__ == "__main__":
    unittest.main()
