"""Tests for tools/markdown-tables.py: a blank line splitting a Markdown
table, and rows with another number of cells. Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import unittest

from support import REPO, load_tool, run_main

mt = load_tool("markdown-tables.py")

TABLE = "| a | b |\n|---|---|\n| 1 | 2 |\n"


class Tables(unittest.TestCase):
    def problems(self, text):
        return mt.problems_in(text, "f.md")

    def test_a_whole_table(self):
        self.assertEqual(self.problems("text\n\n" + TABLE + "\nmore\n"), [])

    def test_a_blank_line_that_splits_rows_off(self):
        out = self.problems(TABLE + "\n| 3 | 4 |\n| 5 | 6 |\n")
        self.assertEqual(out, ["f.md:5: a blank line at line 4 splits this row from the table above it"])

    def test_two_tables_separated_by_a_blank_line(self):
        self.assertEqual(self.problems(TABLE + "\n" + TABLE), [])

    def test_rows_after_text_are_a_stray_table(self):
        self.assertEqual(self.problems(TABLE + "\ntext\n\n| 3 | 4 |\n"),
                         ["f.md:7: a table row with no table: no header and delimiter row above it"])

    def test_cell_counts(self):
        self.assertEqual(self.problems("| a | b |\n|---|---|\n| 1 | 2 | 3 |\n"),
                         ["f.md:3: the row has 3 cells; the table's header has 2"])
        self.assertEqual(self.problems("| a | b |\n|---|\n| 1 | 2 |\n"),
                         ["f.md:2: the delimiter row has 1 cells; the header has 2"])

    def test_escaped_pipes_and_alignment(self):
        self.assertEqual(self.problems("| a | b |\n|:--|--:|\n| `x \\| y` | 2 |\n"), [])

    def test_code_fences_are_not_read(self):
        self.assertEqual(self.problems("```\n| not | a table |\n\n| still not |\n```\n"), [])


class Repository(unittest.TestCase):
    def test_readme_and_docs(self):
        self.assertEqual(run_main(mt.main, root=REPO)[0], 0)


if __name__ == "__main__":
    unittest.main()
