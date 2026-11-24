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


ROOT_REUSE = ('version = 1\n\n[[annotations]]\npath = "**"\nprecedence = "closest"\n'
              'SPDX-FileCopyrightText = "2026 test"\nSPDX-License-Identifier = "Apache-2.0"\n')
PACK_REUSE = ('version = 1\n\n[[annotations]]\npath = "**"\nprecedence = "override"\n'
              'SPDX-FileCopyrightText = "2026 test"\nSPDX-License-Identifier = "%s"\n')


def label(tree, target, lid):
    """Label a pack (`packs/<name>`) or a module (`model/<file>.def`) in its own place."""
    if target.startswith("packs/"):
        tree.write(target + "/REUSE.toml", PACK_REUSE % lid)
    else:
        tree.write(target + ".license", "SPDX-FileCopyrightText: 2026 test\nSPDX-License-Identifier: %s\n" % lid)


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
        self.tree.write("REUSE.toml", ROOT_REUSE)
        for target, lid in (("packs/copyleft", "CC-BY-SA-4.0"), ("packs/nc", "CC-BY-NC-SA-4.0"),
                            ("packs/fou", "LicenseRef-fou"), ("packs/unstated", "LicenseRef-unstated"),
                            ("model/book.def", "CC-BY-NC-SA-4.0")):
            label(self.tree, target, lid)
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
        self.assertEqual(lic.check(self.root, current=True), ([], []))
        with open(os.path.join(self.root, "licences.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertNotIn("plain", doc["packs"])
        self.assertEqual(doc["packs"]["nc"], {"format": "f-nc", "licence": "CC-BY-NC-SA-4.0", "profile": "everything"})
        self.assertEqual(doc["licences"]["CC-BY-NC-SA-4.0"]["profile"], "everything")
        with open(os.path.join(self.root, "LICENSING.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("| `packs/uses-book` | `f-uses-book` | Apache-2.0 | `everything` | uses module book", md)
        # a new label makes both files behind: a note in a pull request, a failure in the counts PR
        label(self.tree, "packs/plain", "CC-BY-SA-4.0")
        problems, notes = lic.check(self.root)
        self.assertEqual(problems, [])
        self.assertEqual(len(notes), 2)
        self.assertEqual(len(lic.check(self.root, current=True)[0]), 2)
        self.assertEqual(run_main(lic.main, "--check", root=self.root)[0], 0)
        self.assertEqual(run_main(lic.main, "--check-current", root=self.root)[0], 1)

    def test_a_pack_label_covers_its_whole_directory_once(self):
        self.tree.write("packs/plain/REUSE.toml", PACK_REUSE.replace('path = "**"', 'path = "vectors/*.json"') % "CC-BY-SA-4.0")
        self.assertTrue(any("a pack has one licence" in p for p in lic.survey(self.root)["problems"]))
        self.tree.write("packs/plain/REUSE.toml", (PACK_REUSE % "CC-BY-SA-4.0").replace("override", "closest"))
        self.assertTrue(any("a pack has one licence" in p for p in lic.survey(self.root)["problems"]))

    def test_a_label_in_the_root_reuse_toml_is_refused(self):
        self.tree.write("REUSE.toml", ROOT_REUSE + '\n[[annotations]]\npath = "packs/plain/**"\nprecedence = "override"\n'
                        'SPDX-FileCopyrightText = "2026 test"\nSPDX-License-Identifier = "CC-BY-SA-4.0"\n')
        problems, _ = lic.check(self.root)
        self.assertTrue(any("root REUSE.toml: an annotation for" in p and "packs/<name>/REUSE.toml" in p for p in problems))

    def test_unknown_licence_and_missing_text(self):
        label(self.tree, "packs/plain", "LicenseRef-nowhere")
        problems, _ = lic.check(self.root)
        self.assertTrue(any("LicenseRef-nowhere is not in licences.toml" in p for p in problems))
        self.assertTrue(any("LICENSES/LicenseRef-nowhere.txt is missing" in p for p in problems))

    def test_controlled_is_refused(self):
        label(self.tree, "packs/plain", "LicenseRef-secret")
        self.tree.write("LICENSES/LicenseRef-secret.txt", "text\n")
        self.assertTrue(any("controlled" in p for p in lic.check(self.root)[0]))

    def test_a_malformed_module_companion(self):
        self.tree.write("model/book.def.license", "SPDX-FileCopyrightText: 2026 test\n")
        self.assertTrue(any("model/book.def.license" in p for p in lic.survey(self.root)["problems"]))

    def test_a_pack_with_no_source_line(self):
        self.tree.write("packs/plain/pack.def", "format f-plain\nversion 1\ndistribution public\nwire json\n")
        self.assertIn("pack plain has no source line", lic.survey(self.root)["problems"])

    def test_list_and_totals(self):
        code, out, _ = run_main(lic.main, "--totals", root=self.root)
        self.assertEqual((code, out), (0, "open\t1\nopen+copyleft\t2\neverything\t7\n"))
        code, out, _ = run_main(lic.main, "--list", "--profile", "open", root=self.root)
        self.assertEqual(out, "plain\tf-plain\tApache-2.0\topen\n")

    def test_a_tree_without_licence_files_is_all_apache(self):
        for name in ("REUSE.toml", "licences.toml", "packs/copyleft/REUSE.toml", "packs/nc/REUSE.toml",
                     "packs/fou/REUSE.toml", "packs/unstated/REUSE.toml", "model/book.def.license"):
            os.remove(os.path.join(self.root, *name.split("/")))
        self.assertEqual(set(self.profiles().values()), {"open"})
        self.assertEqual(lic.excluded(self.root, "open")["packs"], {})


    def test_core_counts_for_every_pack(self):
        label(self.tree, "model/core.def", "CC-BY-SA-4.0")
        self.assertEqual(self.profiles()["plain"], "open+copyleft")

    def test_a_controlled_licence_is_in_no_profile(self):
        label(self.tree, "packs/plain", "LicenseRef-secret")
        self.tree.write("LICENSES/LicenseRef-secret.txt", "text\n")
        self.assertEqual(self.profiles()["plain"], "none")
        self.assertIn("plain", lic.excluded(self.root, "everything")["packs"])

    # --- spec 0.93: a file is in a profile only when it shows itself public ---

    def test_a_controlled_pack_under_a_public_licence_is_in_no_profile(self):
        for target, lid in (("packs/plain", None), ("packs/copyleft", "CC-BY-SA-4.0"), ("packs/nc", "CC-BY-NC-SA-4.0")):
            name = target.split("/")[1]
            self.tree.write(target + "/pack.def", "format f-%s\n" % name + HEAD.replace("public", "controlled") + "wire json\n")
            self.assertEqual(self.profiles()[name], "none", lid)
            for profile in lic.PROFILES:
                self.assertIn(name, lic.excluded(self.root, profile)["packs"])
            problems, _ = lic.check(self.root)
            self.assertTrue(any("pack %s is not shown public" % name in p for p in problems), problems)

    def test_each_form_that_is_not_shown_public(self):
        body = "format f-plain\nversion 1.0.0\nsource \"test\"\nwire json\n"
        cases = {
            "no line": body.encode(),
            "quoted word": ('"distribution" public\n' + body).encode(),
            "quoted value": ('distribution "public"\n' + body).encode(),
            "comment": ("distribution public # x\n" + body).encode(),
            "public and a doubtful line": ('distribution public\ndistri"bution" controlled\n' + body).encode(),
            "glued": ('distribution public\ndistribution"controlled"\n' + body).encode(),
            "word alone": ("distribution public\ndistribution\n" + body).encode(),
            "two values": ("distribution public\ndistribution controlled\n" + body).encode(),
            "cr between words": ("distribution\rpublic\n" + body).encode(),
            "lone cr elsewhere": ("distribution public\n" + body + "x\ry\n").encode(),
            "bom": ("\ufeffdistribution public\n" + body).encode(),
            "bom later": ("distribution public\n# \ufeff\n" + body).encode(),
            "nul": ("distribution public\n" + body + "\0").encode(),
            "not utf-8": b"distribution public\n" + body.encode() + b"\xff\n",
        }
        for why, data in cases.items():
            self.tree.write("packs/plain/pack.def", data)
            self.assertEqual(self.profiles()["plain"], "none", why)
            self.assertIn("plain", lic.excluded(self.root, "everything")["packs"], why)

    def test_forms_that_are_shown_public(self):
        body = "format f-plain\nversion 1.0.0\nsource \"test\"\nwire json\n"
        for why, text in {"tab": "distribution\tpublic\n", "spaces around": "  distribution   public \t\n",
                          "crlf": "distribution public\r\n", "cr at the end": body + "distribution public\r",
                          "another word": "distributions are fine\ndistribution public\n"}.items():
            if why == "another word":
                continue  # judged below: a line that begins with the word is doubtful
            self.tree.write("packs/plain/pack.def", text if why == "cr at the end" else text + body)
            self.assertEqual(self.profiles()["plain"], "open", why)
        self.tree.write("packs/plain/pack.def", "distributions x\ndistribution public\n" + body)
        self.assertEqual(self.profiles()["plain"], "none", "a line that begins with the word is doubtful")

    def test_a_controlled_module_spreads_to_the_packs_that_use_it(self):
        self.tree.write("model/book.def", "module book\n" + HEAD.replace("public", "controlled"))
        p = self.profiles()
        self.assertEqual((p["uses-book"], p["uses-derived"], p["plain"]), ("none", "none", "open"))
        self.assertIn("derived.def", lic.excluded(self.root, "everything")["modules"])
        self.assertIn("is not shown public", lic.survey(self.root)["packs"]["uses-derived"]["because"])

    def test_a_core_not_shown_public_puts_every_pack_in_none(self):
        self.tree.write("model/core.def", "module core\nversion 1.0.0\nsource \"test\"\n")
        self.assertEqual(set(self.profiles().values()), {"none"})

    def test_a_doubtful_uses_line(self):
        for line in ('"uses" book', 'us"es" book', "uses book # x", "uses  book  x", 'uses"book"'):
            self.tree.write("packs/plain/pack.def", "format f-plain\n" + HEAD + line + "\nwire json\n")
            self.assertEqual(self.profiles()["plain"], "none", line)
            self.assertTrue(any("doubtful uses" in p for p in lic.check(self.root)[0]), line)
        self.tree.write("packs/plain/pack.def", "format f-plain\n" + HEAD + "uses\tbook\nwire json\n")
        self.assertEqual(self.profiles()["plain"], "everything")

    def test_a_tree_without_licence_files_still_leaves_out_a_controlled_pack(self):
        for name in ("REUSE.toml", "licences.toml", "packs/copyleft/REUSE.toml", "packs/nc/REUSE.toml",
                     "packs/fou/REUSE.toml", "packs/unstated/REUSE.toml", "model/book.def.license"):
            os.remove(os.path.join(self.root, *name.split("/")))
        self.tree.write("packs/plain/pack.def", "format f-plain\n" + HEAD.replace("public", "controlled") + "wire json\n")
        self.assertEqual(set(lic.excluded(self.root, "open")["packs"]), {"plain"})

    def test_a_pack_def_that_is_not_utf_8_does_not_stop_the_tool(self):
        self.tree.write("packs/plain/pack.def", b"format f-plain\n\xff\n")
        self.assertEqual(self.profiles()["plain"], "none")
        code, _, _ = run_main(lic.main, "--list", root=self.root)
        self.assertEqual(code, 0)

    def test_two_modules_of_one_name_take_the_wider(self):
        self.tree.write("model/book2.def", "module book\n" + HEAD)
        self.assertEqual(self.profiles()["uses-book"], "everything")

    def test_engine_forms(self):
        self.assertEqual(lic.engine_forms(self.root), [])
        self.tree.write("packs/plain/REUSE.toml", (PACK_REUSE % "MIT").replace('"MIT"', '"MIT" # note'))
        self.tree.write("model/book.def.license", "SPDX-License-" + "Identifier: MIT OR GPL-2.0\n")
        with open(os.path.join(self.root, "licences.toml"), "a", encoding="utf-8") as fh:
            fh.write('[licences."X"]\ncommercial = "yes"\nshare_alike = false\nfield_of_use = [ ]\ndistribution = "public"\n')
        problems = lic.engine_forms(self.root)
        self.assertTrue(any(p.startswith("packs/plain/REUSE.toml") for p in problems))
        self.assertTrue(any(p.startswith("model/book.def.license") for p in problems))
        self.assertTrue(any("licences.toml:" in p for p in problems))


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
        self.assertEqual(lic.check(REPO)[0], [])


if __name__ == "__main__":
    unittest.main()
