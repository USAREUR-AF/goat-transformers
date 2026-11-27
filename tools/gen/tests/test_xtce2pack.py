"""Tests of tools/gen/xtce2pack.py, XTCE mission databases.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_xtce2pack*.py'

`fixtures/xtce2pack/input/probe.xml` is a small XTCE database written for
these tests, and `PROVENANCE.md` beside it states its SHA-256. After an edit of
the database, write its new SHA-256 into that table.
"""
import support

import json
import os
import shutil
import tempfile
import unittest

import xtce2pack as gen

INPUT = os.path.join(support.FIXTURES, "xtce2pack", "input")
PROVENANCE = os.path.join(INPUT, "PROVENANCE.md")


class Probe(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def run_gen(self, *more, src=INPUT):
        return support.run_main(gen.main, ["--src", src, "--provenance", PROVENANCE, "--out", self.tmp, *more])

    def read(self, rel):
        with open(os.path.join(self.tmp, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_a_kind_per_restricted_container(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        self.assertIn("xtce-probe-header: 2 kinds, 1 left out", out)
        pack = self.read("packs/xtce-probe-header/pack.def")
        # the criterion selects the kind and, bound with `as`, chooses it on encode; its bits are a pad
        self.assertIn("kind  status\nwhen  8  1  at 0  as xtceprobe.id\npad   8\n", pack)
        self.assertIn("field  xtceprobe.mode  4  uint\n", pack)
        # a polynomial calibrator of degree 1 on a two's complement integer is a signed scale
        self.assertIn("field  xtceprobe.temp  12  sscale:1/2:-40\n", pack)
        self.assertIn("field  xtceprobe.name  32  utf8\n# not mapped from here on: ContainerRefEntry\n", pack)
        self.assertNotIn("xtceprobe.rate", pack, "nothing is mapped after a stop")

    def test_a_criterion_this_phase_cannot_state_leaves_the_container_out(self):
        self.assertEqual(self.run_gen()[0], 0)
        md = self.read("packs/xtce-probe-header/pack.md")
        self.assertIn("- `Ranged`: comparison >", md)
        self.assertNotIn("kind  ranged", self.read("packs/xtce-probe-header/pack.def"))

    def test_the_round_trip_vector_is_written_from_the_entries(self):
        self.assertEqual(self.run_gen()[0], 0)
        v = json.loads(self.read("packs/xtce-probe-header/vectors/rt-status.json"))
        # id 1 (the criterion), then mode and temp from the sample values, most significant bit first
        self.assertEqual(v["input"], v["expect"])
        self.assertEqual(v["input"][:2], "01")
        self.assertEqual(v["model"]["@kind"], "status")
        self.assertEqual(v["model"]["xtceprobe.id"], "1")
        self.assertIn(v["model"]["xtceprobe.mode"], ("0", "3"), "an enumerated field takes a listed value")

    def test_second_run_and_check_mode(self):
        self.assertEqual(self.run_gen()[0], 0)
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)

    def test_a_vector_derived_by_hand_is_kept(self):
        self.assertEqual(self.run_gen()[0], 0)
        kept = os.path.join(self.tmp, "packs/xtce-probe-header/vectors/derived-x.json")
        with open(kept, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        self.assertEqual(self.run_gen()[0], 0)
        self.assertTrue(os.path.exists(kept))

    def test_a_changed_database_is_refused(self):
        src = os.path.join(self.tmp, "src")
        shutil.copytree(INPUT, src)
        with open(os.path.join(src, "probe.xml"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        status, _, err = self.run_gen(src=src)
        self.assertEqual(status, 1)
        self.assertIn("does not match the SHA-256", err)


class Paths(unittest.TestCase):
    def test_snake(self):
        self.assertEqual(gen.snake("CCSDS_Packet_ID/APID"), "ccsds_packet_id_apid")
        self.assertEqual(gen.snake("BusElectronics/Battery_Voltage"), "bus_electronics_battery_voltage")


if __name__ == "__main__":
    unittest.main()
