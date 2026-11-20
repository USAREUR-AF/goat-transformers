"""Message definitions for the rtcm2pack tests, in the shape of pyrtcm's rtcmtypes_get.py."""

HDR_2001 = {
    "DF002": "Message Number",
    "DF003": "Station",
}

RTCM_PAYLOADS_GET = {
    "2001": {
        **HDR_2001,
        "DF012": "x",
        "DF015": "sm",
        "DF016": "is",
        "DF017": "fs",
        "DF018": "es",
        "DF019": "ts",
        "DF020": "us",
        "DF021": "smag",
        "res_grp": (NRES, {"DF020": "a repeat"}),
    },
    "2002": {
        "DF002": "Message Number",
        "DF013": "Counter",
        "chars_grp": ("DF013", {"DF014": "Character"}),
        "DF003": "Station",
        "DF013+1": "Counter",
        "sats_grp": ("DF013+1", {"PRN": "derived", "DF012": "x", "DF013": "inner count",
                                 "inner_grp": ("DF013", {"DF020": "inner value"})}),
    },
    "2003": {
        "DF002": "Message Number",
        "DF010": "flag a",
        "DF011": "flag b",
        "optA_alt": (("DF010", 1), {"DF012": "x"}),
        "optB_alt": (("DF011", 1), {"DF016": "y"}),
    },
    "2004": {
        "DF002": "Message Number",
        "DF013": "Counter",
        "DF003": "Station",
        "late_grp": ("DF013", {"DF020": "value"}),
    },
    "2005": {
        "DF003": "Station",
        "DF002": "Message Number",
    },
}
