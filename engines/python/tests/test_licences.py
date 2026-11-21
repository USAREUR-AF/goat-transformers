"""Version 0.29: licence profiles in the library loader and the line forms of
ruling 1, on the fixture trees and on temporary trees."""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
FIXTURES = os.path.normpath(os.path.join(HERE, "..", "..", "..", "packs", "conformance", "tool-fixtures"))

from goat_transformers import BadLicence, Engine, GTError, UnknownFormat  # noqa: E402
from goat_transformers import licence  # noqa: E402


def tree(name):
    return os.path.join(FIXTURES, name, "packs")


CORE = """module core
version 0.29.0
distribution public
source "unit test"
key lat float - "a key"
"""

PACK = """format {fmt}
version 0.29.0
distribution public
source "unit test"
wire json
field lat pos.lat float
"""


class TestLibraryProfile(unittest.TestCase):
    def test_no_profile_reads_no_licence_file(self):
        eng = Engine.from_dir(tree("licences-bad-table"))
        self.assertEqual(eng.formats(), ["lic-plain"])
        self.assertEqual(eng.licences, {})

    def test_profiles_on_fixture(self):
        want = {
            "open": ["lic-aa", "lic-plain"],
            "open+copyleft": ["lic-aa", "lic-copyleft", "lic-plain", "lic-uses-sa"],
            "everything": ["lic-aa", "lic-copyleft", "lic-fou", "lic-nc", "lic-not-in-table", "lic-plain",
                           "lic-unstated", "lic-uses-book", "lic-uses-derived", "lic-uses-sa"],
        }
        for profile, formats in want.items():
            with self.subTest(profile=profile):
                eng = Engine.from_dir(tree("licences-a"), profile=profile)
                self.assertEqual(eng.formats(), formats)
        eng = Engine.from_dir(tree("licences-a"), profile="open+copyleft")
        self.assertEqual(eng.licences["lic-copyleft"], ("copyleft", "CC-BY-SA-4.0", "open+copyleft"))
        self.assertEqual(eng.licences["lic-uses-sa"], ("uses-sa", "Apache-2.0", "open+copyleft"))
        self.assertIn("sa", eng.models)
        self.assertNotIn("book", eng.models)

    def test_packs_only_skips_and_checks_names_first(self):
        eng = Engine.from_dir(tree("licences-a"), packs_only=["nc", "plain"], profile="open")
        self.assertEqual(eng.formats(), ["lic-plain"])
        with self.assertRaises(UnknownFormat):
            Engine.from_dir(tree("licences-a"), packs_only=["no-such-pack"], profile="open")

    def test_unknown_profile_is_bad_licence_before_reading(self):
        for p in ("Open", "", "none", "commercial"):
            with self.subTest(profile=p), self.assertRaises(BadLicence) as cm:
                Engine.from_dir("/no/such/dir", profile=p)
            self.assertEqual(cm.exception.code, "bad-licence")
            self.assertTrue(str(cm.exception).startswith("bad-licence: "))

    def test_bad_files_with_a_profile(self):
        for name, only in (("licences-bad-table", None), ("licences-bad-pack", None),
                           ("licences-bad-module", ["plain"])):
            with self.subTest(tree=name), self.assertRaises(BadLicence):
                Engine.from_dir(tree(name), packs_only=only, profile="everything")
        eng = Engine.from_dir(tree("licences-bad-pack"), packs_only=["plain"], profile="everything")
        self.assertEqual(eng.formats(), ["lic-plain"])

    def test_core_counts_and_a_skipped_broken_pack(self):
        self.assertEqual(Engine.from_dir(tree("licences-core-copyleft"), profile="open").formats(), [])
        self.assertEqual(Engine.from_dir(tree("licences-core-copyleft"), profile="open+copyleft").formats(),
                         ["lic-plain"])
        with self.assertRaises(GTError) as cm:
            Engine.from_dir(tree("licences-core-copyleft"), profile="everything")
        self.assertEqual(cm.exception.code, "unknown-directive")

    def test_no_table_knows_only_apache(self):
        eng = Engine.from_dir(tree("licences-no-table"), profile="open+copyleft")
        self.assertEqual(eng.formats(), ["lic-plain"])
        self.assertEqual(Engine.from_dir(tree("licences-no-table"), profile="everything").formats(),
                         ["lic-copyleft", "lic-plain"])


class TestLineForms(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.root, "model"))
        os.mkdir(os.path.join(self.root, "packs"))
        self.write("model/core.def", CORE)
        self.write("packs/p/pack.def", PACK.format(fmt="f-p"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, rel, text, mode="w"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(text if isinstance(text, bytes) else text.encode("utf-8"))

    def load(self, profile="open"):
        return Engine.from_dir(os.path.join(self.root, "packs"), profile=profile)

    def test_reuse_lines(self):
        ok = [
            # REUSE-IgnoreStart: the quoted licence lines below are data
            'SPDX-License-Identifier = "Apache-2.0"',
            ' \tSPDX-License-Identifier\t=\t"Apache-2.0" \r',
            'SPDX-License-Identifier: CC0-1.0\nSPDX-License-Identifier="Apache-2.0"',
        ]
        for text in ok:
            with self.subTest(text=text):
                self.write("packs/p/REUSE.toml", text)
                self.assertEqual(self.load().formats(), ["f-p"])
        bad = [
            "",
            'SPDX-License-Identifier = "Apache-2.0"\nSPDX-License-Identifier = "Apache-2.0"',
            'SPDX-License-Identifier = "Apache-2.0" # c',
            'SPDX-License-Identifier = Apache-2.0',
            b'\xef\xbb\xbfSPDX-License-Identifier = "Apache-2.0"',  # a BOM is kept
            b'SPDX-License-Identifier = "Apache-2.0"\xff',
        ]
        for text in bad:
            with self.subTest(text=text):
                self.write("packs/p/REUSE.toml", text)
                with self.assertRaises(BadLicence):
                    self.load()
        os.remove(os.path.join(self.root, "packs/p/REUSE.toml"))
        os.mkdir(os.path.join(self.root, "packs/p/REUSE.toml"))
        with self.assertRaises(BadLicence):
            self.load()

    def test_module_lines(self):
        self.write("model/core.def.license", 'SPDX-License-Identifier = "x"\nSPDX-License-Identifier:\tApache-2.0\r\n')
        self.assertEqual(self.load().formats(), ["f-p"])
        for text in ("SPDX-License-Identifier:Apache-2.0", "SPDX-License-Identifier: a b", "nothing"):
            with self.subTest(text=text):
                self.write("model/core.def.license", text)
                with self.assertRaises(BadLicence):
                    self.load()

    def test_table(self):
        row = '[licences."Apache-2.0"]\ncommercial = "yes"\nshare_alike = false\nfield_of_use = []\n' \
              'distribution = "public"\n'
        self.write("licences.toml", "# t\n\n" + row + 'name = "A"\nurl\t= "u"\nattribution=true\n')
        self.assertEqual(self.load().formats(), ["f-p"])
        for text, formats in (
            (row.replace("= []", '= [""]'), []),
            (row.replace('"yes"', '"unknown"'), []),
            (row.replace('"public"', '"controlled"'), []),
            (row.replace("false", "true"), []),
        ):
            with self.subTest(text=text):
                self.write("licences.toml", text)
                self.assertEqual(self.load().formats(), formats)
        self.write("licences.toml", row.replace("false", "true"))
        self.assertEqual(self.load("open+copyleft").formats(), ["f-p"])
        bad = [
            "x = 1\n" + row,
            row + row,
            row.replace("= []", "= [ ]"),
            row.replace('"public"', '"public" # c'),
            row.replace('share_alike = false\n', ""),
            row + "share_alike = false\n",
            row + "colour = 1\n",
            row + "name = 1\nname = 2\n",
            row + "[other]\n",
            row.replace('[licences."Apache-2.0"]', '[licences. "Apache-2.0"]'),
        ]
        for text in bad:
            with self.subTest(text=text):
                self.write("licences.toml", text)
                with self.assertRaises(BadLicence):
                    self.load()

    def test_uses_through_others_and_name_twice(self):
        self.write("licences.toml",
                   '[licences."Apache-2.0"]\ncommercial = "yes"\nshare_alike = false\nfield_of_use = []\n'
                   'distribution = "public"\n')
        self.write("model/a.def", "module a\nversion 0.1.0\ndistribution public\nsource \"t\"\nuses b\n")
        self.write("model/b.def", "module b\nversion 0.1.0\ndistribution public\nsource \"t\"\nuses a\n")
        self.write("model/b.def.license", "SPDX-License-Identifier: CC0-1.0\n")  # not in the table
        # REUSE-IgnoreEnd
        self.write("packs/q/pack.def", PACK.format(fmt="f-q") + "uses a\n")
        lic = licence.Licences(os.path.join(self.root, "packs"), os.path.join(self.root, "model")).read()
        self.assertEqual(lic.module_files, ["core.def", "a.def", "b.def"])
        self.assertEqual(lic.module_rank, {"core.def": 0, "a.def": 2, "b.def": 2})
        self.assertEqual(lic.pack(os.path.join(self.root, "packs", "q")), ("Apache-2.0", 2))
        self.assertEqual(self.load().formats(), ["f-p"])

    def test_json_text(self):
        self.assertEqual(licence.json_text('a"b\\c\x01\té'), 'a\\"b\\\\c\\u0001\\u0009é')


if __name__ == "__main__":
    unittest.main()
