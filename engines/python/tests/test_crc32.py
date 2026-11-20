"""The CRC-32 of ISO/IEC 13818-1 (spec/engine-spec.md, Version 0.27, "The CRC")."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers.wire_tlv import checksum, crc32  # noqa: E402


class Crc32Test(unittest.TestCase):
    def test_check_value(self):
        self.assertEqual(crc32(b"123456789"), 0x0376E6E7)

    def test_no_bytes(self):
        self.assertEqual(crc32(b""), 0xFFFFFFFF)

    def test_not_the_reflected_crc(self):
        import zlib  # only to show the two algorithms differ
        self.assertNotEqual(crc32(b"123456789"), zlib.crc32(b"123456789"))

    def test_checksum_covers_bytes_before_end(self):
        buf = bytearray(b"123456789\x00\x00\x00\x00")
        self.assertEqual(checksum("crc32", buf, 9), 0x0376E6E7)


if __name__ == "__main__":
    unittest.main()
