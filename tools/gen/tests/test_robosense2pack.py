"""Tests of tools/gen/robosense2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_robosense2pack*.py'

fixtures/robosense2pack/input is a synthetic stand-in for an rs_driver tree,
written for these tests: three shared headers and three models. Model A has
distinct MSOP and DIFOP identities, nested struct arrays, a #define array size and
a long byte array; model B gives both packets the same identity bytes and names
its DIFOP struct with another prefix; model C states a length its struct does
not have. fixtures/robosense2pack/expected is the tree the run writes.
"""
import json
import os
import shutil
import tempfile
import unittest

import support

S = support.load_script("robosense2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "robosense2pack")
INPUTS = ("model/core.def",)
COMMIT = ["--commit", "5" * 40, "--ref", "v0-test"]
DEC = "src/rs_driver/driver/decoder"


class RoboSenseTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="robosense2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input"), os.path.join(self.work, "src"))
        self.gt = os.path.join(self.work, "gt")
        os.makedirs(os.path.join(self.gt, "model"))
        shutil.copy(os.path.join(support.REPO, "model", "core.def"), os.path.join(self.gt, "model", "core.def"))

    def run_gen(self, *extra):
        return support.run_main(S.main, ["--src", self.src, "--out", self.gt] + list(extra))

    def read(self, *parts):
        with open(os.path.join(self.gt, *parts), encoding="utf-8") as fh:
            return fh.read()

    def edit(self, name, old, new):
        path = os.path.join(self.src, *DEC.split("/"), name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen(*COMMIT)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("3 packs (4 kinds), 1 not built", out)
        self.assertIn("not built  RSC: RSCMsopPkt is 4 bytes, the msop length is 5", out)
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_layouts(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        a = self.read("packs", "robosense-rsa", "pack.def")
        for line in ("bit_order     msb\n", "kind      msop\nwhen      0:0:32  1437205770\n",
                     "field  robosense.rsa_msop_header_timestamp_sec_0  0:32:8  uint\n",
                     "group  robosense.rsa_msop_blocks  0:112  item 64  count 2\n",
                     "  group  robosense.rsa_msop_blocks_channels  0:16  item 24  count 2\n",
                     "field  robosense.rsa_msop_tail  0:240:16  twos\n",
                     "kind      difop\nwhen      0:0:32  2784952410\n",
                     "group  robosense.rsa_difop_gprmc  0:48  item 8  count 10\n",
                     "  field  robosense.rsa_difop_vert_angle_cali_value  0:8:16  uint\n"):
            self.assertIn(line, a)
        self.assertNotIn("header_id", a)
        b = self.read("packs", "robosense-rsb", "pack.def")
        self.assertIn("kind      msop\nwhen      0:0:16  4660\n", b)
        self.assertNotIn("difop", b)
        self.assertIn("kind      difop\n", self.read("packs", "robosense-rsb-difop", "pack.def"))
        self.assertIn("same identity bytes", self.read("packs", "robosense-rsb", "pack.md"))
        v = json.loads(self.read("packs", "robosense-rsa", "vectors", "gen-rt-msop.json"))
        self.assertTrue(v["input"].startswith("55aa050a"))

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(support.tree(self.work), before)

    def test_a_changed_source_is_refused(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        self.edit("decoder_RSA.hpp", "uint16_t rpm;", "uint32_t rpm;")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("decoder_RSA.hpp: SHA-256", err)

    def test_refusals(self):
        self.edit("decoder_RSA.hpp", "uint16_t rpm;", "float rpm;")
        status, out, err = self.run_gen(*COMMIT)
        self.assertEqual(status, 0, err)
        self.assertIn("not built  RSA: RSADifopPkt.rpm is of type float, which no packed region declares", out)
        self.edit("decoder_RSA.hpp", "float rpm;", "uint16_t rpm : 4;")
        status, _, err = self.run_gen(*COMMIT)
        self.assertEqual(status, 1)
        self.assertIn("the member `uint16_t rpm : 4`", err)


if __name__ == "__main__":
    unittest.main()
