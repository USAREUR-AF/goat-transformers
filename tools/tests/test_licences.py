"""Tests for tools/licences.py: the licence of each pack (REUSE.toml), its
flags (licences.toml), its profile, and the generated licences.json and
LICENSING.md. Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import json
import os
import unittest

from support import REPO, TempTree, load_tool, run_main

lic = load_tool("licences.py")

HEAD = 'version 1.0.0\ndistribution public\nsource "test"\n'
ROW = 'commercial = "%s"\nshare_alike = %s\nattribution = true\nfield_of_use = [%s]\ndistribution = "%s"\n'
TABLE = {
    "Apache-2.0": ROW % ("yes", "false", "", "public"),
    "CC-BY-SA-4.0": ROW % ("yes", "true", "", "public"),
    "CC-BY-NC-SA-4.0": ROW % ("no", "true", "", "public"),
    "LicenseRef-fou": ROW % ("yes", "false", '"weapons"', "public"),
    "LicenseRef-unstated": ROW % ("unknown", "false", "", "public"),
    "LicenseRef-secret": ROW % ("yes", "false", "", "controlled"),
}


def reuse(*labels):
    out = ['version = 1\n\n[[annotations]]\npath = "**"\nprecedence = "override"\n'
           'SPDX-FileCopyrightText = "2026 test"\nSPDX-License-Identifier = "Apache-2.0"\n']
    for path, lid in labels:
        out.append('\n[[annotations]]\npath = %s\nprecedence = "override"\n'
                   'SPDX-FileCopyrightText = "2026 test"\nSPDX-License-Identifier = "%s"\n'
                   % (json.dumps(path), lid))
    return "".join(out)


class Tree(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.root = self.tree.root
        self.tree.write("licences.toml", "".join('[licences."%s"]\n%s\n' % kv for kv in TABLE.items()))
        self.tree.write("model/core.def", "module core\n" + HEAD)
        self.tree.write("model/book.def", "module book\n" + HEAD)
        self.tree.write("model/derived.def", "module derived\n" + HEAD + "uses book\n")
        for name in ("plain", "copyleft", "nc", "fou", "unstated", "uses-book", "uses-derived"):
            self.tree.write("packs/%s/pack.def" % name, "format f-%s\n" % name + HEAD + "wire json\n")
            self.tree.write("packs/%s/vectors/one.json" % name, "{}\n")
        self.tree.write("packs/uses-book/pack.def", "format f-uses-book\n" + HEAD + "uses book\nwire json\n")
        self.tree.write("packs/uses-derived/pack.def", "format f-uses-derived\n" + HEAD + "uses derived\nwire json\n")
        self.tree.write("LICENSES/Apache-2.0.txt", "text\n")
        self.labels = [("packs/copyleft/**", "CC-BY-SA-4.0"), ("packs/nc/**", "CC-BY-NC-SA-4.0"),
                       ("packs/fou/**", "LicenseRef-fou"), ("packs/unstated/**", "LicenseRef-unstated"),
                       ("model/book.def", "CC-BY-NC-SA-4.0")]
        self.tree.write("REUSE.toml", reuse(*self.labels))
        for lid in ("CC-BY-SA-4.0", "CC-BY-NC-SA-4.0", "LicenseRef-fou", "LicenseRef-unstated"):
            self.tree.write("LICENSES/%s.txt" % lid, "text\n")

    def profiles(self):
        return lic.pack_profiles(self.root)

    def test_profiles_follow_the_flags_and_the_modules(self):
        self.assertEqual(self.profiles(), {
            "copyleft": "open+copyleft", "fou": "everything", "nc": "everything", "plain": "open",
            "unstated": "everything", "uses-book": "everything", "uses-derived": "everything"})
        s = lic.survey(self.root)
        self.assertEqual(s["packs"]["uses-derived"]["because"], "uses module derived (Apache-2.0)")
        self.assertEqual(s["modules"]["derived.def"]["because"], "uses module book (CC-BY-NC-SA-4.0)")

    def test_excluded_by_profile(self):
        self.assertEqual(set(lic.excluded(self.root, "open")["packs"]),
                         {"copyleft", "fou", "nc", "unstated", "uses-book", "uses-derived"})
        self.assertEqual(set(lic.excluded(self.root, "open+copyleft")["packs"]),
                         {"fou", "nc", "unstated", "uses-book", "uses-derived"})
        self.assertEqual(lic.excluded(self.root, "everything")["packs"], {})
        self.assertEqual(set(lic.excluded(self.root, "open")["modules"]), {"book.def", "derived.def"})
        self.assertIn("f-nc", lic.excluded(self.root, "open")["formats"])

    def test_generated_files_and_check(self):
        self.assertEqual(run_main(lic.main, root=self.root)[0], 0)
        self.assertEqual(lic.check(self.root), [])
        with open(os.path.join(self.root, "licences.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertNotIn("plain", doc["packs"])
        self.assertEqual(doc["packs"]["nc"], {"format": "f-nc", "licence": "CC-BY-NC-SA-4.0", "profile": "everything"})
        self.assertEqual(doc["licences"]["CC-BY-NC-SA-4.0"]["profile"], "everything")
        with open(os.path.join(self.root, "LICENSING.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("| `packs/uses-book` | `f-uses-book` | Apache-2.0 | `everything` | uses module book", md)
        # a change of label makes both files stale
        self.tree.write("REUSE.toml", reuse(*self.labels[:-1]))
        self.assertTrue(any("stale" in p for p in lic.check(self.root)))

    def test_one_licence_per_pack(self):
        self.tree.write("REUSE.toml", reuse(*self.labels, ("packs/plain/vectors/*.json", "CC-BY-SA-4.0")))
        self.assertTrue(any("a pack has one licence" in p for p in lic.survey(self.root)["problems"]))

    def test_unknown_licence_and_missing_text(self):
        self.tree.write("REUSE.toml", reuse(*self.labels, ("packs/plain/**", "LicenseRef-nowhere")))
        problems = lic.check(self.root)
        self.assertTrue(any("LicenseRef-nowhere is not in licences.toml" in p for p in problems))
        self.assertTrue(any("LICENSES/LicenseRef-nowhere.txt is missing" in p for p in problems))

    def test_controlled_is_refused(self):
        self.tree.write("REUSE.toml", reuse(*self.labels, ("packs/plain/**", "LicenseRef-secret")))
        self.tree.write("LICENSES/LicenseRef-secret.txt", "text\n")
        self.assertTrue(any("controlled" in p for p in lic.check(self.root)))

    def test_every_annotation_overrides(self):
        self.tree.write("REUSE.toml", reuse(*self.labels).replace('precedence = "override"\n', "", 1))
        with self.assertRaises(lic.LicenceError):
            lic.survey(self.root)

    def test_a_pack_with_no_source_line(self):
        self.tree.write("packs/plain/pack.def", "format f-plain\nversion 1\ndistribution public\nwire json\n")
        self.assertIn("pack plain has no source line", lic.survey(self.root)["problems"])

    def test_list_and_totals(self):
        code, out, _ = run_main(lic.main, "--totals", root=self.root)
        self.assertEqual((code, out), (0, "open\t1\nopen+copyleft\t2\neverything\t7\n"))
        code, out, _ = run_main(lic.main, "--list", "--profile", "open", root=self.root)
        self.assertEqual(out, "plain\tf-plain\tApache-2.0\topen\n")

    def test_a_tree_without_licence_files_is_all_apache(self):
        for name in ("REUSE.toml", "licences.toml"):
            os.remove(os.path.join(self.root, name))
        self.assertEqual(set(self.profiles().values()), {"open"})
        self.assertEqual(lic.excluded(self.root, "open")["packs"], {})


class Globs(unittest.TestCase):
    def test_reuse_glob_rules(self):
        cases = [("packs/a/**", "packs/a/vectors/x.json", True), ("packs/a/*", "packs/a/vectors/x.json", False),
                 ("packs/a/*", "packs/a/pack.def", True), ("**", "README.md", True),
                 ("model/*.def", "model/x.def", True), ("model/\\*.def", "model/x.def", False),
                 ("model/\\*.def", "model/*.def", True)]
        for pattern, path, want in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(bool(lic.glob_regex(pattern).match(path)), want)


class Repository(unittest.TestCase):
    def test_this_repository_is_consistent(self):
        self.assertEqual(lic.check(REPO), [])


if __name__ == "__main__":
    unittest.main()
