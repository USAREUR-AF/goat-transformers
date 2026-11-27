"""Tests of tools/gen/sbp2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_sbp2pack*.py'

`fixtures/sbp2pack/input/src/` is a small libsbp-shaped tree written for these
tests: a types file and one message package with a message for each rule.
`input/tools/gen/sources/sbp-PROVENANCE.md` states the SHA-256 of each file.
After an edit of a fixture file, rewrite that table with
`--commit 0123456789abcdef0123456789abcdef01234567 --tag v0.0.0-fixture` into a
scratch directory and copy it back, then run once with GT_UPDATE_GOLDEN=1 and
review the diff of `expected/`.
"""
import support

import json
import os
import struct
import tempfile
import unittest

import gtcheck
import sbp2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "sbp2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")
TRACK_DEF = os.path.join(support.REPO, "model", "track.def")
FMT = "sbp-fixture"


class SbpCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.src = support.copy_tree(os.path.join(INPUT, "src"), os.path.join(self.tmp, "src"))

    def make_root(self):
        root = os.path.join(self.tmp, "root")
        support.copy_tree(os.path.join(INPUT, "tools"), os.path.join(root, "tools"))
        return root

    def run_gen(self, root, *more):
        return support.run_main(gen.main, ["--src", self.src, "--out", root, "--core-def", CORE_DEF,
                                           "--track-def", TRACK_DEF] + list(more))

    def generated(self):
        root = self.make_root()
        status, out, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        return root

    def text(self, root, *path):
        with open(os.path.join(root, *path), encoding="utf-8") as fh:
            return fh.read()

    def pack(self, root):
        model = gtcheck.Model()
        model.add(self.text(support.REPO, "model", "core.def"), CORE_DEF)
        model.add(self.text(support.REPO, "model", "track.def"), TRACK_DEF)
        for module in ("sbp", "sbpfixture"):
            model.add(self.text(root, "model", module + ".def"), module)
        return gtcheck.load_pack(self.text(root, "packs", FMT, "pack.def"), model, FMT)


class GoldenTree(SbpCase):
    def test_fixture_gives_the_expected_tree(self):
        root = self.make_root()
        status, out, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("self-check      ok", out)
        support.assert_same_tree(self, EXPECTED, root, ignore=("tools/",))

    def test_second_run_and_check_mode_change_nothing(self):
        root = self.generated()
        first = support.tree(root)
        status, _, err = self.run_gen(root, "--check")
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(self.run_gen(root)[0], 0)
        self.assertEqual(support.tree(root), first)

    def test_a_changed_source_is_refused(self):
        with open(os.path.join(self.src, gen.YAML_DIR, "fixture.yaml"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        root = self.make_root()
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs")))


class Layout(SbpCase):
    def setUp(self):
        super().setUp()
        self.root = self.generated()
        self.pdef = self.text(self.root, "packs", FMT, "pack.def")
        self.md = self.text(self.root, "packs", FMT, "pack.md")

    def test_frame_header_and_kind_selection(self):
        self.assertIn("when   0:0:8 85\n", self.pdef)
        self.assertIn("field  sbp.sender 0:24:16 uint\n", self.pdef)
        self.assertIn("kind      mixed\nwhen      0:8:16 28673\nwhen      0:40:8 34\n", self.pdef)

    def test_nested_types_arrays_strings_and_scales(self):
        for line in ("sbpfixture.mixed_t_tow 0:48:32 uint",
                     "sbpfixture.mixed_t_wn 0:80:16 uint",
                     "sbpfixture.mixed_cn0 0:112:8 uscale:1/4",
                     "sbpfixture.mixed_offset 0:120:16 sscale:2/5",
                     "sbpfixture.mixed_drift 0:136:32 sscale:1/34359738368",
                     "sbpfixture.mixed_days 0:168:16 uint",
                     "sbpfixture.mixed_temps_2 0:200:8 twos",
                     "sbpfixture.mixed_pairs_1_code 0:232:8 uint",
                     "sbpfixture.mixed_label 0:240:48 ascii",
                     "sbpfixture.mixed_ratio 0:288:32 f32"):
            self.assertIn("field     " + line + "\n", self.pdef)
        module = self.text(self.root, "model", "sbpfixture.def")
        self.assertIn("key  mixed_cn0  float  dB_Hz ", module)
        self.assertIn("key  mixed_days  int  day ", module)

    def test_shared_keys_with_evidence(self):
        for line in ("lat 0:80:64 f64", "lon 0:144:64 f64", "hae 0:208:64 f64",
                     "track.vel_north_ms 0:80:32 sscale:1/1000",
                     "track.vel_up_ms 0:144:32 sscale:-0.001",
                     "course 0:80:32 uscale:1/1000000",
                     "speed_ms 0:112:32 uscale:1/1000",
                     "track.vel_up_ms 0:144:32 sscale:1/1000"):
            self.assertIn("field     " + line + "\n", self.pdef)
        self.assertIn("uses          track\n", self.pdef)

    def test_what_is_not_built(self):
        self.assertNotIn("kind      trailing", self.pdef)
        self.assertNotIn("kind      counted", self.pdef)
        self.assertNotIn("kind      empty", self.pdef)
        self.assertNotIn("| MSG_TRAILING |", self.md)
        self.assertNotIn("| MSG_COUNTED |", self.md)
        self.assertIn("The 3 messages of this package whose payload length is not fixed are kinds of\n"
                      "the sequential pack `sbp-fixture-var`.", self.md)
        self.assertIn("| MSG_EMPTY | 0x7005 | an empty payload", self.md)

    def test_variable_messages_in_a_sequential_pack(self):
        vdef = self.text(self.root, "packs", FMT + "-var", "pack.def")
        self.assertIn("layout        sequential\n", vdef)
        # an array running to the end of the frame: a rest group of its elements
        self.assertIn("kind  trailing\nwhen  16  28674\nrequires  sbpfixture.trailing_seq\n"
                      "field  sbp.sender  16  uint\nlength  8  bytes\n"
                      "  field  sbpfixture.trailing_seq  32  uint\n"
                      "  group  sbpfixture.trailing_data  rest\n"
                      "    field  sbpfixture.trailing_data_item  8  uint\n  end\nend\n", vdef)
        # a text running to the end: a rest group, one byte per item
        self.assertIn("  group  sbpfixture.trailing_text_text  rest\n"
                      "    field  sbpfixture.trailing_text_text_byte  8  uint\n", vdef)
        # an array counted by an earlier field: that field's line is the count (0.21),
        # and fields after the group follow it
        self.assertIn("  count  n_n  8\n  group  sbpfixture.counted_items  count @n_n\n"
                      "    field  sbpfixture.counted_items_sat  8  uint\n"
                      "    field  sbpfixture.counted_items_code  8  uint\n  end\n"
                      "  field  sbpfixture.counted_tail  8  uint\nend\n", vdef)
        mod = self.text(self.root, "model", "sbpfixture.def")
        self.assertNotIn("key  counted_n ", mod)
        self.assertIn('list  counted_items  "the items of field items of MSG_COUNTED"', mod)
        # the round trip of the counted kind: n = 2, two (sat, code) items, then tail
        vec = json.loads(self.text(self.root, "packs", FMT + "-var", "vectors",
                                     "rt-7004-counted.json"))
        frame = bytes.fromhex(vec["input"])
        self.assertEqual(frame[5], len(frame) - 6)
        self.assertEqual(frame[6], 2)
        self.assertEqual(len(frame) - 6, 1 + 2 * 2 + 1)
        self.assertEqual(vec["model"]["sbpfixture.counted_items.#"], "2")

    def test_vectors_decode_through_the_pack(self):
        pack = self.pack(self.root)
        vdir = os.path.join(self.root, "packs", FMT, "vectors")
        names = sorted(os.listdir(vdir))
        self.assertIn("x-01-pos_llh-to-geojson.json", names)
        for name in names:
            vec = json.loads(self.text(vdir, name))
            kind, ent = gen.decode(pack, bytes.fromhex(vec["input"]))
            self.assertEqual(kind, vec["model"]["@kind"], name)
        cross = json.loads(self.text(vdir, "x-01-pos_llh-to-geojson.json"))
        self.assertEqual(cross["expect"], '{"type":"Feature","geometry":{"type":"Point",'
                         '"coordinates":[8.545594,47.397742,488.25]},"properties":{}}')


class Serializer(unittest.TestCase):
    def test_crc_of_the_check_string(self):
        # CRC-16/XMODEM of the ASCII digits 1 to 9 is 0x31C3
        self.assertEqual(gen.crc16(b"123456789"), 0x31C3)

    def test_frame_header_and_crc_place(self):
        data = gen.frame(0x020A, 0x1234, b"\x01\x02", True)
        self.assertEqual(data[:6], bytes([0x55, 0x0A, 0x02, 0x34, 0x12, 0x02]))
        self.assertEqual(data[6:8], b"\x01\x02")
        self.assertEqual(struct.unpack("<H", data[8:])[0], gen.crc16(data[1:8]))

    def test_unit_scales(self):
        F = gen.Fraction
        self.assertEqual(gen.unit_scale("0.005 m"), (F(1, 200), "m"))
        self.assertEqual(gen.unit_scale("dB Hz / 4"), (F(1, 4), "dB Hz"))
        self.assertEqual(gen.unit_scale("m * 0.02"), (F(1, 50), "m"))
        self.assertEqual(gen.unit_scale("1e-6 m/s^2"), (F(1, 1000000), "m/s^2"))
        self.assertEqual(gen.unit_scale("(s / s) / (2 ^ 31)"), (F(1, 2 ** 31), "s/s"))
        self.assertIsNone(gen.unit_scale("mm/s"))
        self.assertIsNone(gen.unit_scale("microdegrees"))


class Yaml(unittest.TestCase):
    def test_the_subset_the_definitions_use(self):
        doc = gen.load("a: 1  # note\nb: 'x # y'\nc: [u8, 'v']\nd: >\n  one\n  two\ne:\n - f: 2\n   g: 3\n")
        self.assertEqual(doc["a"], "1")
        self.assertEqual(doc["b"], "x # y")
        self.assertEqual(doc["c"], ["u8", "v"])
        self.assertEqual(doc["d"].strip(), "one two")
        self.assertEqual(doc["e"], [{"f": "2", "g": "3"}])


if __name__ == "__main__":
    unittest.main()
