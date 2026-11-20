"""Message definitions for the uni2pack tests, in the shape of pyunigps's unitypes_get.py."""

FLAGS = {
    "flags_bit": (X1, {"good": U1, "mode": U3, "reserved9": U4}),
}

UNI_PAYLOADS_GET = {
    "FIXNAV": {
        "solstatus": U4,
        "lat": R8,
        "lon": R8,
        "hmsl": R8,
        "datumid": U4,
        "stationid": C4,
        **FLAGS,
        "pair_grp": (2, {"prn": U1, "level": (S2, 0.01)}),
        "wide": U10,
        "speed": R4,
        "drift": (R4, 0.0078125),
        "offset": S4,
        "age": (U2, 0.25),
    },
    "QUALITY": {"gdop": R4, "count": U1},
    "SATS": {"numsat": U1, "sat_grp": ("numsat", {"prn": U1})},
    "INFO": {"text": CV},
    "NOID": {"value": U4},
}
