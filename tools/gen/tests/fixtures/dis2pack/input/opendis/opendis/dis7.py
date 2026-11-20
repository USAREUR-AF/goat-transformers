"""PDU type annotations for the dis2pack tests, in the shape of open-dis-python's dis7.py."""


class TrackStatePdu:
    pduType: int = 1


class FastTrackStatePdu:
    pduType: int = 1


class PingPdu:
    pduType: int = 2


class TwoListsPdu:
    pduType: int = 3


class SkippedPdu:
    pduType: int = 4
