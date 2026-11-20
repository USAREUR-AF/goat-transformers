"""CRC-16/X.25 and CRC-32C, written for deriving Bundle Protocol 7 vectors
(RFC 9171 section 4.2.1: CRC type 1 is the X.25 CRC-16, type 2 the
Castagnoli CRC-32C; the value is a byte string of 2 or 4 bytes holding the
CRC as an unsigned integer in network byte order, computed over the block's
CBOR encoding with the CRC byte string zero-filled). Standard library only,
bit by bit, no table, no import from the repository.

Checked at import against the standard check values (the CRC of the nine
ASCII bytes "123456789"): CRC-16/X.25 = 0x906e, CRC-32C = 0xe3069283.
"""

def crc16_x25(data):
    """Reflected polynomial 0x1021 (0x8408 reflected), init 0xffff, xorout 0xffff."""
    c = 0xffff
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
    return c ^ 0xffff

def crc32c(data):
    """Reflected polynomial 0x1edc6f41 (0x82f63b78 reflected), init and xorout 0xffffffff."""
    c = 0xffffffff
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x82f63b78 if c & 1 else c >> 1
    return c ^ 0xffffffff

def crc_bytes(crc_type, data):
    """The CRC field value of RFC 9171 4.2.1, big-endian."""
    if crc_type == 1: return crc16_x25(data).to_bytes(2, "big")
    if crc_type == 2: return crc32c(data).to_bytes(4, "big")
    raise ValueError("CRC type %r" % crc_type)

assert crc16_x25(b"123456789") == 0x906e, hex(crc16_x25(b"123456789"))
assert crc32c(b"123456789") == 0xe3069283, hex(crc32c(b"123456789"))
