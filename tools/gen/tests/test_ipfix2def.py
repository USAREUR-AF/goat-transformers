"""Tests of tools/gen/ipfix2def.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_ipfix2def*.py'

fixtures/ipfix2def/input/registry.txt is a registry in the layout of IANA's
ipfix-information-elements.csv, written for these tests (stored as .txt: the boundary gate
admits no .csv file): a reserved row, a 64-bit counter with a description over two lines,
an IPv4 and an IPv6 address, a deprecated string, an octet array, a float and a date in
milliseconds, and a range of unassigned numbers. fixtures/ipfix2def/expected is the tree
the run writes.
"""
import os
import shutil
import tempfile
import unittest

import support

G = support.load_script("ipfix2def.py")
FIXTURE = os.path.join(support.FIXTURES, "ipfix2def")


class Ipfix2defTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="ipfix2def-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def run_gen(self, *extra):
        return support.run_main(G.main, ["--csv", os.path.join(FIXTURE, "input", "registry.txt"),
                                         "--registry-date", "2026-01-01", "--out", self.work] + list(extra))

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        self.assertEqual(out, "model/ipfix.def: 13 keys, 1 elements without a key\n")
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.work)

    def test_keys(self):
        self.assertEqual(self.run_gen()[0], 0)
        with open(os.path.join(self.work, "model", "ipfix.def"), encoding="utf-8") as fh:
            text = fh.read()
        for line in ('key  example_octet_count ', 'key  example_ipv4_address ', 'key  example_ipv6_address_g0 ',
                     'key  example_ipv6_address_g7 ', 'key  example_name ', 'key  example_ratio ',
                     'list  records  '):
            self.assertIn(line, text)
        self.assertNotIn("example_octets ", text)
        self.assertNotIn("over two lines", text)
        self.assertIn("deprecated", text.split("key  example_name")[1].splitlines()[0])

    def test_check(self):
        self.assertEqual(self.run_gen()[0], 0)
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        os.remove(os.path.join(self.work, "model", "ipfix.def"))
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("model/ipfix.def is missing", err)

    def test_not_the_registry_is_refused(self):
        path = os.path.join(self.work, "other.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("a,b\n1,2\n")
        status, _, err = support.run_main(G.main, ["--csv", path, "--registry-date", "2026-01-01", "--out", self.work])
        self.assertEqual(status, 1)
        self.assertIn("not the IANA IPFIX Information Elements CSV", err)


if __name__ == "__main__":
    unittest.main()
