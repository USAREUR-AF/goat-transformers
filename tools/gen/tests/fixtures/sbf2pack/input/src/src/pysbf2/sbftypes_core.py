"""Core names for the sbf2pack tests, in the shape of pysbf2's sbftypes_core.py."""

E1_N2 = 1e-2
E1_P3 = 1000
P2_N5 = 0.03125
PAD = "_Padding"
PD = "SBLength"
C6 = "C006"
I2 = "I002"
I4 = "I004"
U1 = "U001"
U2 = "U002"
U3 = "U003"
U4 = "U004"
U12 = "U012"
F4 = "F004"
F8 = "F008"
X1 = "X001"
V1 = "V001"

SBF_MSGIDS = {
    4007: ("Fix", "a fix"),
    4001: ("Quality", "quality numbers"),
    4027: ("Satellites", "a list of satellites"),
    4060: ("Optional", "a part for one mode"),
    4061: ("Blob", "data to the end"),
    5921: ("Marker", "an epoch marker"),
    4101: ("Track", "tracked satellites, counted"),
    4102: ("Odd", "a group of single bytes"),
}
