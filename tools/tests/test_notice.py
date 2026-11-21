"""Tests for tools/notice.py: NOTICE written from tools/notice/header.txt and
one file per source under tools/notice/entries/. Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import os
import unittest

from support import REPO, TempTree, load_tool, run_main

notice = load_tool("notice.py")

HEADER = "project\nCopyright test\n\nThe sources below.\n"
A = "Pack a; module a\n  The A specification 1.0. https://example.org/a\n"
B = "Packs b, b-two; modules b,\nb2\n  The B schema.\n\n    Licence text, indented.\n"


class NoticeTest(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.tree.write("tools/notice/header.txt", HEADER)
        self.tree.write("tools/notice/entries/b.txt", B)
        self.tree.write("tools/notice/entries/a.txt", A)

    def run_tool(self, *argv):
        return run_main(notice.main, *argv, root=self.tree.root)

    def notice_text(self):
        with open(os.path.join(self.tree.root, "NOTICE"), encoding="utf-8") as fh:
            return fh.read()

    def test_write_orders_entries_by_file_name(self):
        self.assertEqual(self.run_tool()[0], 0)
        self.assertEqual(self.notice_text(), HEADER + "\n" + A + "\n" + B)
        code, out, _ = self.run_tool("--check-current")
        self.assertEqual(code, 0)
        self.assertIn("2 entries", out)

    def test_a_new_entry_is_a_note_in_check_and_a_failure_in_check_current(self):
        self.run_tool()
        self.tree.write("tools/notice/entries/c.txt", "Pack c\n  The C source.\n")
        code, out, _ = self.run_tool("--check")
        self.assertEqual(code, 0)
        self.assertIn("note: NOTICE is behind", out)
        code, _, err = self.run_tool("--check-current")
        self.assertEqual(code, 1)
        self.assertIn("NOTICE is behind", err)

    def test_an_edit_to_notice_itself_fails_check(self):
        self.run_tool()
        with open(os.path.join(self.tree.root, "NOTICE"), "a", encoding="utf-8") as fh:
            fh.write("\nPack d; module d\n  Added to NOTICE by hand.\n")
        code, _, err = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("'Pack d; module d'", err)

    def test_malformed_entries(self):
        cases = {
            "Upper.txt": A,
            "x.txt": "  Pack x indented\n",
            "y.txt": "Pack y\n  text\n\nPack z\n  a second entry in one file\n",
            "w.txt": "Pack w\n  text \n",
            "v.txt": "Pack v\n  text\n\n",
            "u.txt": "Pack u\r\n  text\r\n",
            "t.txt": "Pack t\n  one\n\n\n  two\n",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                self.assertTrue(notice.entry_problems(name, text), name)
        self.assertEqual(notice.entry_problems("a.txt", A), [])
        self.assertEqual(notice.entry_problems("b.txt", B), [])

    def test_two_entries_with_one_heading(self):
        self.tree.write("tools/notice/entries/a2.txt", A)
        code, _, err = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("begin with the same line", err)

    def test_write_refuses_a_malformed_entry(self):
        self.tree.write("tools/notice/entries/x.txt", "  indented\n")
        self.assertEqual(self.run_tool()[0], 1)
        self.assertFalse(os.path.exists(os.path.join(self.tree.root, "NOTICE")))

    def test_the_repository_entries_are_well_formed(self):
        code, _, err = run_main(notice.main, "--check", root=REPO)
        self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
