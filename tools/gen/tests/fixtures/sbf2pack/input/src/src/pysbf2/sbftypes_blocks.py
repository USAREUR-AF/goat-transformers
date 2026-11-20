"""Block definitions for the sbf2pack tests, in the shape of pysbf2's sbftypes_blocks.py."""

SBF_POSITION_BLOCKS = {
    "Fix": {
        "TOW": U4,
        "WNc": U2,
        "Mode_bit": (X1, {"Type": U4, "Reserved1": U2, "AutoSet": U1, "TwoD": U1}),
        "Latitude": F8,
        "Longitude": F8,
        "Height": F8,
        "Speed": F4,
        "Drift": (F4, E1_N2),
        "Name": C6,
        "Wide": U12,
        "Age": (U2, E1_N2),
        "Count": (U2, E1_P3),
        "Tilt": (I2, P2_N5),
        "Spin": I4,
    },
    "Marker": {},
}

SBF_OTHER_BLOCKS = {
    "Quality": {"TOW": U4, "PDOP": (U2, E1_N2)},
    "Satellites": {"N": U1, "SBLength": U1, "sat_grp": ("N", {"SVID": U1, PAD: PD})},
    "Optional": {"Mode": U1, "part_grp": (("Mode", 1), {"Value": U4})},
    "Blob": {"Size": U2, "Data": V1},
    "Unnumbered": {"Value": U4},
}

SBF_BLOCKS = {
    **SBF_POSITION_BLOCKS,
    **SBF_OTHER_BLOCKS,
}
