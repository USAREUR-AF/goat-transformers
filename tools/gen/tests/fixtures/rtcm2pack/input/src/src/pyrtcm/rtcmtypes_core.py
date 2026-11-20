"""Core names for the rtcm2pack tests, in the shape of pyrtcm's rtcmtypes_core.py."""

NRES = 2
P2_P4 = 16
P2_31 = 4.656612873077393e-10
P2_66 = 1.3552527156068805e-20
BIT = "BIT"
CHA = "CHA"
STR = "STR"
INT = "INT"
UINT = "UINT"
INTS = "SNT"
PRN = "PRN"

RTCM_DATA_FIELDS = {
    "PRN": (PRN, 0, 0, "derived"),
    "DF002": (UINT, 12, 0, "message number"),
    "DF003": (UINT, 12, 0, "station"),
    "DF010": (BIT, 1, 0, "flag a"),
    "DF011": (BIT, 1, 0, "flag b"),
    "DF012": (INT, 20, 0.0001, "a coordinate"),
    "DF013": (UINT, 8, 0, "count"),
    "DF014": (CHA, 8, 0, "a character"),
    "DF015": (INTS, 10, P2_31, "sign and magnitude"),
    "DF016": (UINT, 10, P2_P4, "integer scale"),
    "DF017": (INT, 22, 1 / 256, "fraction scale"),
    "DF018": (INT, 16, 25 * 10 ** 6, "expression scale"),
    "DF019": (INT, 24, P2_66, "tiny scale"),
    "DF020": (UINT, 6, 1, "unit scale"),
    "DF021": (INTS, 8, 0, "sign and magnitude, unscaled"),
}

RTCM_MSGIDS = {"2001": "fixed", "2002": "groups", "2003": "gated"}
