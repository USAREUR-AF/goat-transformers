"""SET definitions for the ubx2pack tests, in the shape of pyubx2's ubxtypes_set.py."""

from pyubx2.ubxtypes_get import UBX_PAYLOADS_GET as UBX_GET

UBX_PAYLOADS_SET = {
    "NAV-MIXED": UBX_GET["NAV-MIXED"],
    "MGA-INI-POS": {"type": U1, "version": U1, "lat": (I4, E1_N7), "lon": (I4, E1_N7)},
}
