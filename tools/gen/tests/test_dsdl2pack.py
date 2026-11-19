"""Tests of tools/gen/dsdl2pack.py, DroneCAN (UAVCAN v0) and Cyphal (UAVCAN v1).

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_dsdl2pack*.py'

`fixtures/dsdl2pack/<family>/input/` holds a small DSDL tree written for these
tests (`dsdl/`, namespace `testns`) and the `tools/gen/sources/` PROVENANCE.md
that states the SHA-256 of each file. The definition files carry a `.txt`
suffix, because the boundary gate admits no `.uavcan` or `.dsdl` file; each
test copies the tree to a scratch directory without the suffix. After an edit of a fixture file, rewrite
that table with `--commit 0123456789abcdef0123456789abcdef01234567` into a
scratch directory and copy it back, then run once with GT_UPDATE_GOLDEN=1 and
review the diff of `expected/`.
"""
import support

import os
import struct
import tempfile
import unittest
from fractions import Fraction

import dsdl2pack as gen

FIXTURES = os.path.join(support.FIXTURES, "dsdl2pack")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")


class FamilyCase(unittest.TestCase):
    FAMILY = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.input = os.path.join(FIXTURES, self.FAMILY, "input")
        self.expected = os.path.join(FIXTURES, self.FAMILY, "expected")

    def make_root(self):
        root = os.path.join(self.tmp, "root")
        support.copy_tree(os.path.join(self.input, "tools"), os.path.join(root, "tools"))
        return root

    def dsdl(self):
        """The fixture tree, copied with the `.txt` suffix of each definition removed."""
        staged = os.path.join(self.tmp, "staged-dsdl")
        if not os.path.isdir(staged):
            support.copy_tree(os.path.join(self.input, "dsdl"), staged)
            for directory, _, names in os.walk(staged):
                for name in names:
                    if name.endswith((".uavcan.txt", ".dsdl.txt")):
                        os.rename(os.path.join(directory, name), os.path.join(directory, name[:-4]))
        return staged

    def run_gen(self, root, *more, dsdl=None):
        argv = ["--dsdl", dsdl or self.dsdl(), "--out", root, "--namespaces", "testns", "--core-def", CORE_DEF]
        if self.FAMILY == "cyphal":
            argv.append("--cyphal")
        return support.run_main(gen.main, argv + list(more))

    def check_golden(self):
        root = self.make_root()
        status, out, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("self-check      ok", out)
        support.assert_same_tree(self, self.expected, root, ignore=("tools/",))
        return root

    def check_second_run_and_check_mode(self):
        root = self.make_root()
        self.assertEqual(self.run_gen(root)[0], 0)
        first = support.tree(root)
        status, _, err = self.run_gen(root, "--check")
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(self.run_gen(root)[0], 0)
        self.assertEqual(support.tree(root), first)

    def check_changed_source_refused(self):
        dsdl = support.copy_tree(self.dsdl(), os.path.join(self.tmp, "dsdl"))
        name = sorted(n for n in os.listdir(os.path.join(dsdl, "testns")) if not os.path.isdir(
            os.path.join(dsdl, "testns", n)))[0]
        with open(os.path.join(dsdl, "testns", name), "a", encoding="utf-8") as fh:
            fh.write("\n")
        root = self.make_root()
        status, _, err = self.run_gen(root, dsdl=dsdl)
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs")))

    def pack_text(self, root, fmt):
        with open(os.path.join(root, "packs", fmt, "pack.def"), encoding="utf-8") as fh:
            return fh.read()


class DroneCAN(FamilyCase):
    FAMILY = "dronecan"

    def test_fixture_gives_the_expected_tree(self):
        self.check_golden()

    def test_second_run_and_check_mode(self):
        self.check_second_run_and_check_mode()

    def test_a_changed_source_is_refused(self):
        self.check_changed_source_refused()

    def test_layout(self):
        root = self.make_root()
        self.assertEqual(self.run_gen(root)[0], 0)
        sample = self.pack_text(root, "dronecan-testns-sample")
        self.assertIn("bit_order     msb", sample)
        self.assertIn("field  dctestns.sample_count  32  uint  swap", sample)
        self.assertIn("pad    16", sample)                       # float16
        self.assertIn("field  dctestns.sample_origin_x  16  twos  swap", sample)
        self.assertIn("pad    12", sample)                       # uint12
        self.assertIn("group  dctestns.sample_path  count 2", sample)
        self.assertIn("# not mapped from here on: tail array", sample)
        choice = self.pack_text(root, "dronecan-testns-choice")
        self.assertIn("kind   large\nwhen   2  1", choice)
        self.assertFalse(os.path.exists(os.path.join(root, "packs", "dronecan-testns-point")),
                         "a type with no data type ID gets no pack")

    def test_serializer_bit_order(self):
        """A 12-bit value: the low byte, then the top four bits in the high
        half of the next byte (DroneCAN's order)."""
        w = gen.BitWriter()
        w.write_uint(0xABC, 12)
        self.assertEqual(w.to_bytes(), bytes([0xBC, 0xA0]))


class Cyphal(FamilyCase):
    FAMILY = "cyphal"

    def test_fixture_gives_the_expected_tree(self):
        self.check_golden()

    def test_second_run_and_check_mode(self):
        self.check_second_run_and_check_mode()

    def test_a_changed_source_is_refused(self):
        self.check_changed_source_refused()

    def test_layout(self):
        root = self.make_root()
        self.assertEqual(self.run_gen(root)[0], 0)
        report = self.pack_text(root, "cyphal-testns-report-1-0")
        self.assertIn("bit_order     lsb", report)
        self.assertIn("field  cytestns.report_1_0_pair_b  13  twos", report)
        self.assertIn("length 32 bytes\n  group  cytestns.report_1_0_note_text  count 8", report)
        self.assertIn("group  cytestns.report_1_0_pairs  count 8\n  align  8", report)
        self.assertIn("pad    5", report)
        md = open(os.path.join(root, "packs", "cyphal-testns-report-1-0", "pack.md"), encoding="utf-8").read()
        self.assertIn("fixed subject-ID 7000", md)
        response = self.pack_text(root, "cyphal-testns-query-1-0-response")
        self.assertIn("kind   pair\nwhen   8  1", response)
        md = open(os.path.join(root, "packs", "cyphal-testns-query-1-0-response", "pack.md"), encoding="utf-8").read()
        self.assertIn("fixed service-ID 300", md)

    def test_a_longer_delimited_composite_is_read_by_its_length(self):
        """A newer minor version of the delimited Note adds bytes the pack does
        not know; decode skips them by the delimiter header and reads on."""
        root = self.make_root()
        self.assertEqual(self.run_gen(root)[0], 0)
        _, _, scope = gen.cy_read_pack(self.pack_text(root, "cyphal-testns-report-1-0"))
        w = gen.CyWriter()
        w.write(5, 40)                          # time
        w.write(1, 3)                           # pair.a
        w.write(2, 13)                          # pair.b
        note = bytes([1, 0x41, 0, 0, 0xEE, 0xEE])   # text "A", weight, two bytes of a later version
        w.write(len(note), 32)
        for b in note:
            w.write(b, 8)
        w.write(0, 8)                           # no pairs
        w.write(0b101, 3)                       # flags
        w.write(0, 5)
        for b in struct.pack("<d", 2.5):
            w.write(b, 8)
        ent = {}
        gen.cy_dec_scope(gen.CyReader(w.to_bytes()), scope, ent)
        self.assertEqual(ent["cytestns.report_1_0_note_text"], [{"cytestns.report_1_0_note_text_item": 0x41}])
        self.assertEqual(ent["cytestns.report_1_0_value"], 2.5)
        self.assertEqual([ent["cytestns.report_1_0_flags_%d" % i] for i in range(3)], [1, 0, 1])
        out = gen.CyWriter()
        gen.cy_enc_scope(out, scope, ent)
        self.assertEqual(out.to_bytes()[7], 4, "encode writes the length of what it maps")

    def test_expressions(self):
        types = gen.cy_load(self.dsdl(), ["testns"])
        ev = gen.CyEval(types)
        t = types["testns.Report.1.0"]
        self.assertEqual(ev.value("testns.Limits.1.0.CAPACITY", t, t.bodies[0]), 5)
        self.assertEqual(ev.value("2 ** -11", t, t.bodies[0]), Fraction(1, 2048))
        self.assertEqual(ev.integer("0x10 + 64 * 8", t, t.bodies[0]), 528)
        self.assertEqual(types["testns.sub.Note.1.0"].bodies[0].fields[0].typ.n, 5)

    def test_length_prefix_and_tag_sizes(self):
        self.assertEqual(gen.cy_std_bits((255).bit_length(), 1), 8)
        self.assertEqual(gen.cy_std_bits((256).bit_length(), 1), 16)
        self.assertEqual(gen.cy_std_bits((70000).bit_length(), 1), 32)
        self.assertEqual(gen.cy_std_bits(1, 8), 8)

    def test_serializer_bit_order(self):
        """Least significant bit first: a 13-bit value after a 3-bit one."""
        w = gen.CyWriter()
        w.write(0b101, 3)
        w.write(0x1ABC, 13)
        self.assertEqual(w.to_bytes(), struct.pack("<H", (0x1ABC << 3) | 0b101))


if __name__ == "__main__":
    unittest.main()
