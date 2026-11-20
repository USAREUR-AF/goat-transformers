"""GET definitions for the ubx2pack tests, in the shape of pyubx2's ubxtypes_get.py."""

from pyubx2.ubxtypes_core import U1, U2, U4

UBX_PAYLOADS_GET = {
    "NAV-PVT": {
        "iTOW": U4,
        "fixType": U1,
        "flags_bit": (X1, {"gnssFixOk": U1, "diffSoln": U1, "psmState": U3, "spare": U3}),
        "numSV": U1,
        "lon": (I4, E1_N7),
        "lat": (I4, E1_N7),
        "height": I4,
        "hMSL": I4,
        "velN": I4,
        "velE": I4,
        "velD": I4,
        "gSpeed": I4,
        "headMot": (I4, E1_N5),
        "headVeh": (I4, 180 * P2_N24),
        "pDOP": (U2, E1_N2),
        "reserved1": U3,
    },
    "NAV-MIXED": {
        "version": U1,
        "name": C6,
        "ratio": R4,
        "value": R8,
        "small": I1,
        "pair_grp": (2, {"svId": U1, "cno": (U1, P2_P4)}),
        "big": U12,
        "tail_bit": (X2, {"low": U4, "mid": I2}),
    },
    "NAV-VELNED": {
        "iTOW": U4,
        "velN": I4,
        "velE": I4,
        "velD": I4,
        "gSpeed": U4,
        "heading": (I4, E1_N5),
    },
    "NAV-COUNTED": {
        "numCh": U1,
        "ch_grp": ("numCh", {"svId": U1}),
    },
    "NAV-TEXT": {"code": U2, "text": CH},
    "NAV-VARIANT": {"version": U1, "a": U4},
    "NAV-VARIANTB": {"version": U1, "b": U4},
    "NAV-VARIANT-L": {"version": U1, "c": U4, "d": U4},
    "FOO-BAR": {"spam": U1},
}

_UBX_PAYLOADS_GET_EXTRA = {
    "NAV-POSLLH": UBX_PAYLOADS_GET["NAV-PVT"],
}

UBX_PAYLOADS_GET.update(_UBX_PAYLOADS_GET_EXTRA)
