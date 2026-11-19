"""Variant selection for the ubx2pack tests, in the shape of pyubx2's ubxvariants.py."""


def get_variant_dict(**kwargs):
    """Choose by the version byte, and by length for the long form."""
    ver = kwargs["payload"][0:1]
    if len(kwargs["payload"]) == 9:
        return UBX_PAYLOADS_GET["NAV-VARIANT-L"]
    if ver == b"\x01":
        return UBX_PAYLOADS_GET["NAV-VARIANTB"]
    return UBX_PAYLOADS_GET["NAV-VARIANT"]


VARIANTS = {
    GET: {b"\x01\x53": get_variant_dict},
}
