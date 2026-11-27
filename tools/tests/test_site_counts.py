"""The site's counts are not committed: site/index.html holds a placeholder in
each count marked data-stat, and site/build.sh writes the tree's counts at
build time (site/bundle.py --counts-only --write). A pull request that adds a
pack then never changes index.html. Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import REPO

SITE = os.path.join(REPO, "site")


def check(site_dir, *more):
    return subprocess.run([sys.executable, "-I", os.path.join(site_dir, "bundle.py"), "--counts-only", *more],
                          capture_output=True, text=True)


class SiteCounts(unittest.TestCase):
    def test_the_committed_page_holds_only_placeholders(self):
        r = check(SITE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_committed_count_fails_and_clear_puts_the_placeholder_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("bundle.py", "index.html"):
                shutil.copy(os.path.join(SITE, name), tmp)
            page = os.path.join(tmp, "index.html")
            with open(page, encoding="utf-8") as f:
                html = f.read()
            self.assertIn('data-stat="conversion_vectors">…<', html)
            with open(page, "w", encoding="utf-8") as f:
                f.write(html.replace('data-stat="conversion_vectors">…<', 'data-stat="conversion_vectors">26,593<'))
            r = check(tmp)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("conversion_vectors: index.html commits 26,593", r.stdout)
            self.assertEqual(check(tmp, "--clear").returncode, 0)
            self.assertEqual(check(tmp).returncode, 0)
            with open(page, encoding="utf-8") as f:
                self.assertEqual(f.read(), html)


if __name__ == "__main__":
    unittest.main()
