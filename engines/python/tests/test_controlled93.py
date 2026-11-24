"""Version 0.93: a controlled pack is in no licence profile. Ruling 1 (shown
public), ruling 2 (the profile of a file not shown public) in the library
loader, ruling 5 (a profile sets the limit) and ruling 6 (the limit of an
engine instance after a load with a profile)."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import BadLicence, DistributionRefused, Engine, GTError  # noqa: E402
from goat_transformers import licence  # noqa: E402

TABLE = (
    '[licences."Apache-2.0"]\ncommercial = "yes"\nshare_alike = false\nfield_of_use = []\n'
    'distribution = "public"\n'
    '[licences."CC-BY-NC-SA-4.0"]\ncommercial = "no"\nshare_alike = true\nfield_of_use = []\n'
    'distribution = "public"\n'
)
# REUSE-IgnoreStart: the quoted licence line below is data
NC = 'SPDX-License-Identifier = "CC-BY-NC-SA-4.0"\n'
# REUSE-IgnoreEnd


def module(name, dist="public", uses=()):
    return "module %s\nversion 0.93.0\ndistribution %s\nsource \"unit test\"\n%s%s" % (
        name, dist, "".join("uses %s\n" % u for u in uses), 'key lat float - "a key"\n' if name == "core" else "")


def pack(fmt, dist="public", uses=()):
    return "format %s\nversion 0.93.0\ndistribution %s\nsource \"unit test\"\n%swire json\nfield lat pos.lat float\n" % (
        fmt, dist, "".join("uses %s\n" % u for u in uses))


class Tree(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.write("licences.toml", TABLE)
        self.write("model/core.def", module("core"))
        self.write("packs/pub/pack.def", pack("f-pub"))
        self.packs = os.path.join(self.root, "packs")

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(text if isinstance(text, bytes) else text.encode("utf-8"))

    def other_tree(self, packs):
        """A second packs directory beside the first, for a later load."""
        for rel, text in packs.items():
            self.write("other/" + rel, text)
        return os.path.join(self.root, "other")


class TestShownPublic(unittest.TestCase):
    """Ruling 1."""

    def test_forms(self):
        yes = ["distribution public\n", "distribution\tpublic", " distribution  public \r\n", "distribution public\r",
               "distribution public\ndistribution public\n", "x\ndistribution public\nmodule \"distribution\"\n"]
        no = [None, "", "distribution\n", "distribution controlled\n", 'distribution "public"\n',
              "distribution public\n\"distribution\" controlled\n", 'distribution public\ndistri"bution" x\n',
              'distribution public\ndistribution"controlled"\n', "distribution public\ndistribution # x\n",
              "distribution public # x\n", "﻿distribution public\n", "a﻿\ndistribution public\n",
              "distribution public\n\0", "distribution\rpublic\n", "\rdistribution public\n",
              "a\r\r\ndistribution public\n", "distribution public public\n"]
        for text in yes:
            with self.subTest(text=text):
                self.assertTrue(licence.shown_public(text))
        for text in no:
            with self.subTest(text=text):
                self.assertFalse(licence.shown_public(text))


class TestProfileOfAFile(Tree):
    """Ruling 2: a file not shown public is in no profile, whatever its licence."""

    def test_controlled_pack_under_a_public_licence(self):
        self.write("packs/ctl/pack.def", pack("f-ctl", "controlled"))
        self.write("packs/ctl-nc/pack.def", pack("f-ctl-nc", "controlled"))
        self.write("packs/ctl-nc/REUSE.toml", NC)
        for profile in ("open", "open+copyleft", "everything"):
            with self.subTest(profile=profile):
                self.assertEqual(Engine.from_dir(self.packs, profile=profile).formats(), ["f-pub"])
        self.assertEqual(Engine.from_dir(self.packs).formats(), ["f-ctl", "f-ctl-nc", "f-pub"])

    def test_controlled_module_and_core(self):
        self.write("model/ctl.def", module("ctl", "controlled"))
        self.write("model/via.def", module("via", uses=["ctl"]))
        self.write("packs/direct/pack.def", pack("f-direct", uses=["ctl"]))
        self.write("packs/through/pack.def", pack("f-through", uses=["via"]))
        eng = Engine.from_dir(self.packs, profile="everything")
        self.assertEqual(eng.formats(), ["f-pub"])
        self.assertNotIn("ctl", eng.models)
        self.write("model/core.def", module("core", "controlled"))
        self.assertEqual(Engine.from_dir(self.packs, profile="everything").formats(), [])


class TestLimit(Tree):
    """Rulings 5 and 6."""

    def test_profile_sets_public_also_beside_controlled(self):
        eng = Engine.from_dir(self.packs, max_distribution="controlled", profile="everything")
        self.assertEqual(eng.max_distribution, "public")
        eng = Engine(max_distribution="public")  # set before
        eng.load_dir(self.packs, profile="open")
        self.assertEqual(eng.max_distribution, "public")

    def test_a_file_that_reads_as_controlled_when_loaded_is_refused(self):
        # This engine reads a module file and a pack.def twice: once for the
        # profile and once to load it. The hooks change the file in between.
        real_pack = licence.Licences.pack

        def pack_then_change(lic, pack_dir):
            out = real_pack(lic, pack_dir)
            with open(os.path.join(pack_dir, "pack.def"), "w") as fh:
                fh.write(pack("f-pub", "controlled"))
            return out

        with mock.patch.object(licence.Licences, "pack", pack_then_change):
            with self.assertRaises(DistributionRefused) as cm:
                Engine.from_dir(self.packs, profile="everything")
        self.assertEqual(cm.exception.code, "distribution-refused")
        self.write("packs/pub/pack.def", pack("f-pub"))

        real_read = licence.Licences.read

        def read_then_change(lic):
            out = real_read(lic)
            with open(os.path.join(self.root, "model", "core.def"), "w") as fh:
                fh.write(module("core", "controlled"))
            return out

        with mock.patch.object(licence.Licences, "read", read_then_change):
            with self.assertRaises(DistributionRefused):
                Engine.from_dir(self.packs, profile="everything")

    def test_setting_controlled_afterwards_has_no_effect(self):
        eng = Engine.from_dir(self.packs, profile="open")
        eng.set_max_distribution("controlled")  # no error
        self.assertEqual(eng.max_distribution, "public")
        with self.assertRaises(ValueError):  # a value not one of the two is still refused
            eng.set_max_distribution("secret")

    def test_a_later_direct_load_is_bounded(self):
        eng = Engine.from_dir(self.packs, profile="open")
        with self.assertRaises(DistributionRefused):
            eng.load(pack("f-later", "controlled"))
        with self.assertRaises(DistributionRefused):
            eng.load_model(module("later", "controlled"))
        eng.load(pack("f-later"))
        self.assertIn("f-later", eng.formats())

    def test_a_later_load_without_profile_is_bounded_by_the_limit_not_the_profile(self):
        eng = Engine.from_dir(self.packs, profile="open")
        nc = self.other_tree({"packs/nc/pack.def": pack("f-nc"), "packs/nc/REUSE.toml": NC})
        eng.load_dir(os.path.join(nc, "packs"), models_dir=os.path.join(self.root, "empty"))
        self.assertEqual(eng.formats(), ["f-nc", "f-pub"])  # outside `open`, public: loaded
        ctl = self.other_tree({"packs/ctl/pack.def": pack("f-ctl", "controlled")})
        with self.assertRaises(DistributionRefused):
            eng.load_dir(os.path.join(ctl, "packs"), models_dir=os.path.join(self.root, "empty"),
                         packs_only=["ctl"])

    def test_an_instance_holding_a_controlled_file_refuses_before_reading(self):
        self.write("licences.toml", "not a table\n")  # read, it would be bad-licence
        for load in (lambda e: e.load(pack("f-ctl", "controlled")),
                     lambda e: e.load_model(module("ctl", "controlled"))):
            eng = Engine()
            eng.load_model(module("core"))
            load(eng)
            before = (dict(eng.models), dict(eng.packs), dict(eng.licences))
            with self.subTest(load=load), self.assertRaises(DistributionRefused):
                eng.load_dir(self.packs, profile="everything")
            # refused with the limit unchanged and no trace (0.93, ruling 6)
            self.assertEqual(eng.max_distribution, "controlled")
            self.assertEqual((dict(eng.models), dict(eng.packs), dict(eng.licences)), before)
            eng.load(pack("f-ctl2", "controlled"))  # still loads controlled

    def test_order_of_errors(self):
        eng = Engine()
        eng.load_model(module("core"))
        eng.load(pack("f-ctl", "controlled"))
        # 1. a profile name not one of the three: bad-licence, limit unchanged, no trace
        before = (dict(eng.models), dict(eng.packs), dict(eng.licences))
        with self.assertRaises(BadLicence):
            eng.load_dir(self.packs, profile="none")
        self.assertEqual(eng.max_distribution, "controlled")
        self.assertEqual((dict(eng.models), dict(eng.packs), dict(eng.licences)), before)
        # 2. then the instance check (the table would be bad-licence if read)
        self.write("licences.toml", "not a table\n")
        with self.assertRaises(DistributionRefused):
            eng.load_dir(self.packs, profile="open")
        # 3. then the limit is public, and stays so when the load fails later
        eng = Engine(max_distribution="controlled")
        with self.assertRaises(BadLicence):
            eng.load_dir(self.packs, profile="open")
        self.assertEqual(eng.max_distribution, "public")
        with self.assertRaises(GTError):
            eng.load(pack("f-ctl", "controlled"))


if __name__ == "__main__":
    unittest.main()
