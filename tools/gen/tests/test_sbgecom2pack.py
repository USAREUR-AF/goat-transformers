"""Tests of tools/gen/sbgecom2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_sbgecom2pack*.py'

fixtures/sbgecom2pack/input/src is a synthetic stand-in for an sbgECom tree,
written for these tests: two classes of log ids (one implicit enum value), a
dispatch with four logs, and four parse functions: a navigation log with NED
velocity, an enum cast, latitude, longitude, altitude and undulation (lat, lon, and
hae by a derive) and an optional trailing field; a log that reads a byte
buffer whose size a header #define states; a log with a loop (not built); and a
class 1 log with a scaled read. Its documentation gives one payload size.
fixtures/sbgecom2pack/expected is the tree the run writes.
"""
import json
import os
import shutil
import tempfile
import unittest

import support

G = support.load_script("sbgecom2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "sbgecom2pack")
INPUTS = ("model/core.def", "model/track.def")
COMMIT = ["--commit", "4" * 40, "--ref", "v0-test"]


class SbgEComTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sbgecom2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input", "src"), os.path.join(self.work, "src"))
        self.gt = os.path.join(self.work, "gt")
        os.makedirs(os.path.join(self.gt, "model"))
        for rel in INPUTS:
            shutil.copy(os.path.join(support.REPO, *rel.split("/")), os.path.join(self.gt, *rel.split("/")))

    def run_gen(self, *extra):
        return support.run_main(G.main, ["--src", self.src, "--out", self.gt] + list(extra))

    def read(self, *parts):
        with open(os.path.join(self.gt, *parts), encoding="utf-8") as fh:
            return fh.read()

    def edit(self, rel, old, new):
        path = os.path.join(self.src, *rel.split("/"))
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen(*COMMIT)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("3 kinds from 3 parse functions (1 payload sizes agree with the documentation), "
                      "1 logs not built (1 functions), 13 keys, 8 vectors checked", out)
        self.assertIn("not built  sbgEComLogDemoLoopReadFromStream: a `for` statement", out)
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_lines(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        pack = self.read("packs", "sbgecom", "pack.def")
        for line in ("kind      nav\nwhen      0:0:8  8\nwhen      0:8:8  0\n",
                     "field     track.vel_north_ms  0:48:32  f32\n", "field     track.vel_east_ms  0:80:32  f32\n",
                     "field     sbgecom.ekf_nav_velocity_2  0:112:32  f32\n",
                     "field     sbgecom.ekf_nav_status  0:368:16  uint\n",
                     "field     sbgecom.ekf_nav_quality  0:384:8  twos  optional\n",
                     "kind      extra\nwhen      0:0:8  9\n", "field     sbgecom.demo_extra_blob_3  0:72:8  uint\n",
                     "kind      fast\nwhen      0:0:8  0\nwhen      0:8:8  1\n",
                     "field     sbgecom.demo_fast_accel  0:48:16  sscale:0.01\n", "uses          track\n"):
            self.assertIn(line, pack)
        self.assertNotIn("looped", pack)
        for line in ("requires  lat lon\n", "field     lat  0:144:64  f64\n", "field     lon  0:208:64  f64\n",
                     "field     sbgecom.ekf_nav_velocity_2  0:112:32  f32\nfield     track.vel_up_ms  0:112:32  f32scale:-1\n"):
            self.assertIn(line, pack)
        self.assertIn("derive  hae  add  sbgecom.ekf_nav_position_2  sbgecom.ekf_nav_undulation\n",
                      self.read("model", "sbgecom.def"))
        x = json.loads(self.read("packs", "sbgecom", "vectors", "gen-x-nav-to-geojson.json"))
        self.assertIn('"coordinates":[8.5455938,47.3977419,535.75]', x["expect"])
        self.assertIn('"properties":{"course":0,"speed_ms":5}', x["expect"])
        g = json.loads(self.read("packs", "geojson", "vectors", "gen-geojson-to-sbgecom-nav.json"))
        self.assertTrue(g["expect"].startswith("0800"))
        v = json.loads(self.read("packs", "sbgecom", "vectors", "gen-rt-nav-before-optional.json"))
        self.assertEqual(v["expect"], v["input"] + "00")

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(support.tree(self.work), before)

    def test_a_changed_source_is_refused(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        self.edit("src/logs/sbgEComLogDemo.h", "(4)", "(5)")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("src/logs/sbgEComLogDemo.h: SHA-256", err)

    def test_the_documented_size_must_agree(self):
        self.edit("doc/binaryMessages.md", "47 bytes", "48 bytes")
        status, _, err = self.run_gen(*COMMIT)
        self.assertEqual(status, 1)
        self.assertIn("give 47 payload bytes, doc/binaryMessages.md says 48", err)

    def test_refusals(self):
        cases = (
            ("pLogData->accel     = (float)sbgStreamBufferReadInt16LE(pStreamBuffer) * 0.01f;",
             "x = sbgStreamBufferReadInt16LE(pStreamBuffer);", "a read into a local variable"),
            ("    return sbgStreamBufferGetLastError(pStreamBuffer);\n}\n\nSbgErrorCode sbgEComLogDemoExtra",
             "    pLogData->late = sbgStreamBufferReadUint8(pStreamBuffer);\n"
             "    return sbgStreamBufferGetLastError(pStreamBuffer);\n}\n\nSbgErrorCode sbgEComLogDemoExtra",
             "a field read after an optional one"),
            ("pLogData->velocity[2]   = sbgStreamBufferReadFloatLE(pStreamBuffer);",
             "if (pLogData->timeStamp > 0) { pLogData->velocity[2] = sbgStreamBufferReadFloatLE(pStreamBuffer); }",
             "a condition `pLogData->timeStamp > 0`"),
        )
        for old, new, reason in cases:
            src = os.path.join(self.src, "src", "logs", "sbgEComLogDemo.c")
            with open(src, encoding="utf-8") as fh:
                keep = fh.read()
            self.edit("src/logs/sbgEComLogDemo.c", old, new)
            status, out, err = self.run_gen(*COMMIT)
            self.assertIn(reason, out + err, reason)
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(keep)


if __name__ == "__main__":
    unittest.main()
