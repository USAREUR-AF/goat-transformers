"""Core names for the ubx2pack tests, in the shape of pyubx2's ubxtypes_core.py."""

E1_N2 = 1e-2
E1_N5 = 1e-5
E1_N7 = 1e-7
P2_N24 = 5.960464477539063e-08
P2_P4 = 16

C6 = "C006"
CH = "CH"
I1 = "I001"
I2 = "I002"
I4 = "I004"
R4 = "R004"
R8 = "R008"
U1 = "U001"
U2 = "U002"
U3 = "U003"
U4 = "U004"
U12 = "U012"
X1 = "X001"
X2 = "X002"
A250 = "A250"
PMPLEN = "UPMP"
VARIABLE = "None"

UBX_CLASSES = {
    b"\x01": "NAV",
    b"\x13": "MGA",
    b"\x66": "FOO",
}

UBX_MSGIDS = {
    b"\x01\x07": "NAV-PVT",
    b"\x01\x02": "NAV-POSLLH",
    b"\x01\x12": "NAV-VELNED",
    b"\x01\x50": "NAV-MIXED",
    b"\x01\x51": "NAV-COUNTED",
    b"\x01\x52": "NAV-TEXT",
    b"\x01\x53": "NAV-VARIANT",
    b"\x13\x40\x00": "MGA-INI-POS",
    b"\x66\x66": "FOO-BAR",
}
