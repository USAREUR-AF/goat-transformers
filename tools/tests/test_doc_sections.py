"""Tests for tools/doc-sections.py: sections written into README.md and
site/index.html from one Markdown source. Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import os
import unittest

from support import REPO, TempTree, load_tool, run_main

ds = load_tool("doc-sections.py")

SOURCE = """## A title

A paragraph with `code`, **bold** and [a link](spec/x.md),
on two lines.

![an image](site/assets/a.svg)

### Sub

| A | B |
|---|---|
| `x` | [y](https://example.org/) |

- one
- two
"""


class Render(unittest.TestCase):
    def test_html(self):
        out = ds.to_html("shared-model", SOURCE)
        self.assertIn('<section id="shared-model" aria-labelledby="h-shared-model">', out)
        self.assertIn('<h2 id="h-shared-model">A title</h2>', out)
        self.assertIn('<p>A paragraph with <code>code</code>, <b>bold</b> and '
                      '<a href="https://github.com/USAREUR-AF/goat-transformers/blob/main/spec/x.md">a link</a>, '
                      'on two lines.</p>', out)
        self.assertIn('<img src="assets/a.svg" alt="an image">', out)
        self.assertIn("<h3>Sub</h3>", out)
        self.assertIn('<td><code>x</code></td><td><a href="https://example.org/">y</a></td>', out)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", out)

    def test_escaping(self):
        out = ds.to_html("s", "## T\n\nA < B & `<tag>`\n")
        self.assertIn("<p>A &lt; B &amp; <code>&lt;tag&gt;</code></p>", out)

    def test_refused(self):
        for text in ("no heading\n", "## A\n\n## B\n", "## A\n\n> quote\n", "## A\n\n| a | b |\n| c |\n",
                     "## A\n\n| a | b |\n|---|---|\n| c |\n", "## A\n\n```\ncode\n```\n"):
            with self.subTest(text=text):
                with self.assertRaises(ds.SectionError):
                    ds.to_html("s", text)


class Files(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.tree.write("docs/shared-model-section.md", SOURCE)
        self.tree.write("README.md", "# R\n\ntext\n\n## Contributing, security, license\n\nend\n")
        self.tree.write("site/index.html", "<main>\n<section>a</section>\n</main>\n")

    def read(self, rel):
        with open(os.path.join(self.tree.root, *rel.split("/")), encoding="utf-8") as fh:
            return fh.read()

    def test_written_once_then_current(self):
        self.assertEqual(run_main(ds.main, "--check", root=self.tree.root)[0], 1)
        self.assertEqual(run_main(ds.main, root=self.tree.root)[0], 0)
        self.assertEqual(run_main(ds.main, "--check", root=self.tree.root)[0], 0)
        readme = self.read("README.md")
        start, end = ds.markers("shared-model")
        self.assertLess(readme.index(end), readme.index("## Contributing, security, license"))
        self.assertIn(SOURCE.rstrip("\n"), readme)
        self.assertLess(self.read("site/index.html").index(end), self.read("site/index.html").index("</main>"))
        # a second run changes nothing; an edit of the source makes both stale
        self.assertEqual(run_main(ds.main, root=self.tree.root)[1], "doc-sections: 0 file(s) written\n")
        self.tree.write("docs/shared-model-section.md", SOURCE + "\nMore.\n")
        code, _, err = run_main(ds.main, "--check", root=self.tree.root)
        self.assertEqual(code, 1)
        self.assertIn("README.md is stale", err)
        self.assertIn("site/index.html is stale", err)

    def test_a_hand_edit_inside_the_markers_is_stale(self):
        run_main(ds.main, root=self.tree.root)
        self.tree.write("README.md", self.read("README.md").replace("on two lines.", "on three lines."))
        self.assertEqual(run_main(ds.main, "--check", root=self.tree.root)[0], 1)


class Repository(unittest.TestCase):
    def test_this_repository_is_current(self):
        self.assertEqual(run_main(ds.main, "--check", root=REPO)[0], 0)


if __name__ == "__main__":
    unittest.main()
