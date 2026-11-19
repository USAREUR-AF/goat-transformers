"""Tests of tools/gen/dbc2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_dbc2pack*.py'

`fixtures/dbc2pack/input/src/` is a small opendbc-shaped tree written for these
tests: two DBC files and a generator file that imports a part. The DBC files
carry a `.txt` suffix, because the boundary gate admits no `.dbc` file; each
test copies the tree to a scratch directory without the suffix.
`input/tools/gen/sources/dbc-PROVENANCE.md` states the SHA-256 of each file.
After an edit of a fixture file, rewrite that table with
`--commit 0123456789abcdef0123456789abcdef01234567` into a scratch directory
and copy it back, then run once with GT_UPDATE_GOLDEN=1 and review the diff of
`expected/`.
"""
import support

import json
import os
import tempfile
import unittest

import dbc2pack as gen
import gtcheck

FIXTURE = os.path.join(support.FIXTURES, "dbc2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")


class DbcCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.src = os.path.join(self.tmp, "src")
        support.copy_tree(os.path.join(INPUT, "src"), self.src)
        for directory, _, names in os.walk(self.src):
            for name in names:
                if name.endswith(".dbc.txt"):
                    os.rename(os.path.join(directory, name), os.path.join(directory, name[:-4]))

    def make_root(self):
        root = os.path.join(self.tmp, "root")
        support.copy_tree(os.path.join(INPUT, "tools"), os.path.join(root, "tools"))
        return root

    def run_gen(self, root, *more):
        return support.run_main(gen.main, ["--src", self.src, "--out", root, "--core-def", CORE_DEF] + list(more))

    def generated(self):
        root = self.make_root()
        status, out, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        return root

    def pack(self, root, fmt, module):
        model = gtcheck.Model()
        model.add(open(CORE_DEF, encoding="utf-8").read(), CORE_DEF)
        with open(os.path.join(root, "model", module + ".def"), encoding="utf-8") as fh:
            model.add(fh.read(), module)
        with open(os.path.join(root, "packs", fmt, "pack.def"), encoding="utf-8") as fh:
            return gtcheck.load_pack(fh.read(), model, fmt)

    def text(self, root, fmt, name="pack.def"):
        with open(os.path.join(root, "packs", fmt, name), encoding="utf-8") as fh:
            return fh.read()


class GoldenTree(DbcCase):
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
        with open(os.path.join(self.src, "opendbc", "dbc", "car_intel.dbc"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        root = self.make_root()
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs")))


class Layout(DbcCase):
    def setUp(self):
        super().setUp()
        self.root = self.generated()

    def test_an_intel_file_is_lsb_and_a_motorola_file_msb(self):
        self.assertIn("bit_order     lsb", self.text(self.root, "dbc-car-intel"))
        self.assertIn("bit_order     msb", self.text(self.root, "dbc-car-motorola"))

    def test_signal_places(self):
        intel = self.text(self.root, "dbc-car-intel")
        self.assertIn("field     dbccarintel.speed_vehicle_speed 0:64:16 uscale:1/100", intel)
        self.assertIn("field     dbccarintel.speed_temp 0:88:8 sscale:1/2:-40", intel)
        # Motorola in an Intel pack: one byte as it is, whole bytes with swap
        self.assertIn("field     dbccarintel.speed_big_endian_nibble 0:120:4 uint", intel)
        self.assertIn("field     dbccarintel.speed_big_endian_word 0:96:16 uint swap", intel)
        moto = self.text(self.root, "dbc-car-motorola")
        self.assertIn("field     dbccarmotorola.steer_angle 0:64:16 sscale:1/10", moto)
        self.assertIn("field     dbccarmotorola.steer_rate 0:82:12 uint", moto)
        self.assertIn("field     dbccarmotorola.steer_intel_nibble 0:100:4 uint", moto)
        self.assertIn("field     dbccarmotorola.steer_intel_word 0:112:16 uint swap", moto)
        # a negative factor is written as a decimal, not as a fraction
        self.assertIn("field     dbccarmotorola.flags_count 0:72:8 uscale:-0.5", moto)

    def test_what_is_not_mapped(self):
        md = self.text(self.root, "dbc-car-intel", "pack.md")
        self.assertIn("| SPEED | BIG_ENDIAN_ODD | Motorola signal over byte boundaries in an Intel (lsb) pack |", md)
        self.assertIn("| SPEED | OVERLAP | overlaps another signal of the message |", md)
        self.assertIn("| FD_FRAME | 1536 | CAN FD: 64 data bytes (struct canfd_frame) |", md)
        self.assertIn("| EMPTY | 700 | the message defines no signal |", md)
        self.assertIn("| FLOATS | SCALED_FLOAT | float signal with a factor or an offset |", md)
        self.assertIn("| EXTENDED | Flag | outside the 4 data bytes |", md)
        self.assertIn("not a frame", md)
        moto = self.text(self.root, "dbc-car-motorola", "pack.md")
        self.assertIn("| STEER | STRADDLE_INTEL | Intel signal over byte boundaries in a Motorola (msb) pack |", moto)

    def test_identifiers(self):
        intel = self.text(self.root, "dbc-car-intel")
        self.assertIn("kind      extended\nwhen      0:0:32 %d" % (0x200 | gen.EFF), intel)
        self.assertIn("kind      long_id_no_flag\nwhen      0:0:32 %d" % (418381312 | gen.EFF), intel)
        moto = self.text(self.root, "dbc-car-motorola")
        self.assertIn("when      0:0:32 %d" % int.from_bytes((512).to_bytes(4, "little"), "big"), moto)

    def test_multiplexed_messages_are_one_kind_per_value(self):
        pack = self.pack(self.root, "dbc-car-intel", "dbccarintel")
        kinds = {k.name: k for k in pack.kinds}
        self.assertIn("modes_m0", kinds)
        self.assertIn("modes_m1", kinds)
        whens = [(n.start, n.bits, n.value) for n in kinds["modes_m1"].lines if n.d == "when"]
        self.assertIn((64, 2, "1"), whens)

    def test_value_tables_only_when_complete(self):
        intel = self.text(self.root, "dbc-car-intel")
        self.assertIn('map   t_speed_gear  3  "D"', intel)
        self.assertIn("field     dbccarintel.speed_gear 0:80:3 uint via t_speed_gear", intel)
        self.assertNotIn("t_modes_common", intel)     # names two of 64 values

    def test_case_only_signal_names_get_distinct_keys(self):
        intel = self.text(self.root, "dbc-car-intel")
        self.assertIn("dbccarintel.long_id_no_flag_counter ", intel)
        self.assertIn("dbccarintel.long_id_no_flag_counter_2 ", intel)

    def test_gps_degrees_bind_core_and_convert_to_geojson(self):
        intel = self.text(self.root, "dbc-car-intel")
        self.assertIn("field     lat 0:64:28 sscale:1/1000000", intel)
        self.assertIn("field     lon 0:92:29 sscale:1/1000000", intel)
        path = os.path.join(self.root, "packs", "dbc-car-intel", "vectors", "x-01-gps-to-geojson.json")
        vec = json.load(open(path, encoding="utf-8"))
        self.assertEqual(vec["expect"], gen.CROSS_EXPECT)

    def test_generator_files_are_assembled_from_their_parts(self):
        gen_pack = self.text(self.root, "dbc-model-x-generated")
        self.assertIn("kind      shared", gen_pack)
        self.assertIn("kind      own", gen_pack)
        self.assertIn("generator/brand/_part.dbc", gen_pack)
        self.assertFalse(os.path.exists(os.path.join(self.root, "packs", "dbc-part")))


class NoTable(DbcCase):
    def test_no_table_leaves_the_value_table_out_and_keeps_the_number(self):
        root = self.make_root()
        status, _, err = self.run_gen(root, "--no-table", "car_intel:SPEED.GEAR")
        self.assertEqual((status, err), (0, ""))
        intel = self.text(root, "dbc-car-intel")
        self.assertNotIn("t_speed_gear", intel)
        self.assertIn("field     dbccarintel.speed_gear 0:80:3 uint\n", intel)
        self.assertIn("are left out by the run (`--no-table`)", self.text(root, "dbc-car-intel", "pack.md"))

    def test_a_malformed_no_table_is_a_refusal(self):
        root = self.make_root()
        status, _, err = self.run_gen(root, "--no-table", "car_intel")
        self.assertEqual(status, 1)
        self.assertIn("--no-table takes FILE:MESSAGE.SIGNAL", err)


class CantoolsFiles(unittest.TestCase):
    """Four DBC files from the tests of cantools (MIT; fixtures/dbc2pack/cantools,
    origin in its dbc-PROVENANCE.md): the generator reads them and every vector
    passes its own codec."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        base = os.path.join(support.FIXTURES, "dbc2pack", "cantools")
        self.src = support.copy_tree(os.path.join(base, "src"), os.path.join(self.tmp, "src"))
        for directory, _, names in os.walk(self.src):
            for name in names:
                if name.endswith(".dbc.txt"):
                    os.rename(os.path.join(directory, name), os.path.join(directory, name[:-4]))
        self.root = os.path.join(self.tmp, "root")
        support.copy_tree(os.path.join(base, "tools"), os.path.join(self.root, "tools"))
        status, out, err = support.run_main(gen.main, ["--src", self.src, "--out", self.root,
                                                       "--core-def", CORE_DEF])
        self.assertEqual((status, err), (0, ""))
        self.assertIn("self-check      ok", out)

    def text(self, fmt):
        with open(os.path.join(self.root, "packs", fmt, "pack.def"), encoding="utf-8") as fh:
            return fh.read()

    def test_multiplexed_message_gives_one_kind_per_value(self):
        self.assertRegex(self.text("dbc-multiplex"), r"kind      message1_m8\n")

    def test_float_signals_are_f32_and_f64(self):
        fp = self.text("dbc-floating-point")
        self.assertIn(" f64", fp)
        self.assertIn(" f32", fp)

    def test_a_motorola_file_is_msb(self):
        self.assertIn("bit_order     msb", self.text("dbc-motohawk"))


class Encodings(DbcCase):
    def test_a_windows_1252_file_is_read(self):
        path = os.path.join(self.src, "opendbc", "dbc", "car_intel.dbc")
        with open(path, "rb") as fh:
            data = fh.read().replace(b'"degC"', b'"\xb0C"')
        with open(path, "wb") as fh:
            fh.write(data)
        root = self.make_root()
        status, _, err = self.run_gen(root, "--commit", "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual((status, err), (0, ""))
        with open(os.path.join(root, "model", "dbccarintel.def"), encoding="utf-8") as fh:
            self.assertIn("speed_temp  float  \u00b0C", fh.read())


class Serializer(unittest.TestCase):
    def sig(self, start, length, motorola):
        return gen.Signal("S", start, length, motorola, False, "1", "0", "", None, False, 1)

    def test_intel_from_the_start_bit_upward(self):
        data = bytearray(8)
        gen.put_signal(data, self.sig(4, 8, False), 0xAB)
        self.assertEqual(data[:2], bytes([0xB0, 0x0A]))

    def test_motorola_from_the_most_significant_bit_through_the_dbc_numbering(self):
        data = bytearray(8)
        gen.put_signal(data, self.sig(3, 8, True), 0xAB)
        self.assertEqual(data[:2], bytes([0x0A, 0xB0]))

    def test_motorola_place_matches_the_serializer(self):
        sig = self.sig(21, 12, True)
        pos, swap = gen.place(sig, "msb")
        data = bytearray(8)
        gen.put_signal(data, sig, 0xABC)
        self.assertFalse(swap)
        self.assertEqual(gen.get_bits(bytes(data), pos, 12, "msb"), 0xABC)


if __name__ == "__main__":
    unittest.main()
