"""Tests of tools/gen/lidar2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_lidar2pack*.py'

fixtures/lidar2pack/input holds synthetic stand-ins for the Ouster SDK, the
ROS velodyne driver and its gps_imu branch, written for these tests: small
profile tables (with an alias word and an arithmetic argument), packet sizes,
the header branches, a legacy IMU block, a two-block Velodyne packet and a
small position packet struct (its COPYING is kept as COPYING.txt). The run builds Ouster packs for 2 pixels per
column. fixtures/lidar2pack/expected is the tree it writes.
"""
import json
import os
import shutil
import tempfile
import unittest

import support

L = support.load_script("lidar2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "lidar2pack")
INPUTS = ("model/core.def",)
COMMITS = ["--commit-ouster", "1" * 40, "--ref-ouster", "v0", "--commit-velodyne", "2" * 40, "--ref-velodyne", "v0",
           "--commit-gpsimu", "3" * 40, "--ref-gpsimu", "branch"]


class LidarTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="lidar2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input"), os.path.join(self.work, "src"))
        # kept as COPYING.txt (the boundary gate's allowlist has no bare COPYING); the generator reads COPYING
        os.rename(os.path.join(self.src, "gpsimu", "COPYING.txt"), os.path.join(self.src, "gpsimu", "COPYING"))
        self.gt = os.path.join(self.work, "gt")
        os.makedirs(os.path.join(self.gt, "model"))
        shutil.copy(os.path.join(support.REPO, "model", "core.def"), os.path.join(self.gt, "model", "core.def"))

    def run_gen(self, *extra):
        return support.run_main(L.main, ["--ouster", os.path.join(self.src, "ouster"),
                                         "--velodyne", os.path.join(self.src, "velodyne"),
                                         "--gpsimu", os.path.join(self.src, "gpsimu"), "--pixels", "2",
                                         "--out", self.gt] + list(extra))

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
        status, out, err = self.run_gen(*COMMITS)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("5 packs", out)
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_layouts(self):
        self.assertEqual(self.run_gen(*COMMITS)[0], 0)
        rng = self.read("packs", "ouster-rng19-2", "pack.def")
        for line in ("when      0:0:8  1\n", "field  ouster.rng19_hdr_frame_id  0:8:8  uint\n",
                     "field  ouster.rng19_hdr_shot_limiting  0:32:4  uint\n", "field  ouster.rng19_gap_36  0:36:12  uint\n",
                     "group  ouster.rng19_columns  0:48  item 80  count 2\n",
                     "  group  ouster.rng19_columns_pixels  0:16  item 32  count 2\n",
                     "    field  ouster.rng19_columns_pixels_signal  0:24:8  uint\n",
                     "    field  ouster.rng19_columns_pixels_gap_19  0:19:5  uint\n"):
            self.assertIn(line, rng)
        leg = self.read("packs", "ouster-legacy-2", "pack.def")
        self.assertNotIn("when", leg.split("kind")[1])
        self.assertNotIn("raw32", leg)
        self.assertIn("  field  ouster.legacy_columns_status  0:96:8  uint\n", leg)
        imu = self.read("packs", "ouster-imu-legacy", "pack.def")
        self.assertIn("field  ouster.imu_la_x  0:32:32  f32\n", imu)
        self.assertNotIn("nmea", imu)
        data = self.read("packs", "velodyne-data", "pack.def")
        for line in ("group  velodyne.data_blocks  0:0  item 80  count 2\n", "field  velodyne.data_timestamp_us  0:160:32  uint\n",
                     "field  velodyne.data_product_id  0:200:8  uint\n"):
            self.assertIn(line, data)
        pos = self.read("packs", "velodyne-position-hdl32e", "pack.def")
        self.assertIn("  field  velodyne.pos_gyro_temp_accel_gyro  0:0:12  uint\n", pos)
        self.assertIn("group  velodyne.pos_nmea_sentence  0:112  item 8  count 4\n", pos)
        v = json.loads(self.read("packs", "ouster-rng19-2", "vectors", "gen-err-other-type.json"))
        self.assertEqual(v["expect_error"], "no-kind")

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_gen(*COMMITS)[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(support.tree(self.work), before)

    def test_a_changed_source_is_refused(self):
        self.assertEqual(self.run_gen(*COMMITS)[0], 0)
        self.edit("velodyne/velodyne_pointcloud/include/velodyne_pointcloud/rawdata.hpp", "SIZE_BLOCK = 10", "SIZE_BLOCK = 11")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("rawdata.hpp: SHA-256", err)

    def test_a_source_of_another_shape_stops_the_run(self):
        for rel, old, new, reason in (
                ("ouster/ouster_core/src/parsing.cpp", "col_header_size = legacy ? 4 : 2;", "col_header_size = 4;",
                 "col_header_size: 0 matches"),
                ("velodyne/velodyne_pointcloud/src/lib/rawdata.cpp", "block.data[k + 1]", "block.data[k - 1]",
                 "distance bytes: 0 matches"),
                ("gpsimu/velodyne_gps_imu/src/gpsimu_driver.h", "uint32_t gps_timestamp;", "double gps_timestamp;",
                 "a member `double gps_timestamp`"),
                ("velodyne/velodyne_pointcloud/include/velodyne_pointcloud/rawdata.hpp", "PACKET_SIZE = 26", "PACKET_SIZE = 27",
                 "blocks and tail are not PACKET_SIZE")):
            path = os.path.join(self.src, *rel.split("/"))
            with open(path, encoding="utf-8") as fh:
                keep = fh.read()
            self.edit(rel, old, new)
            status, _, err = self.run_gen(*COMMITS)
            self.assertEqual(status, 1, reason)
            self.assertIn(reason, err)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(keep)


if __name__ == "__main__":
    unittest.main()
