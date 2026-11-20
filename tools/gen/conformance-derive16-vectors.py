#!/usr/bin/env python3
"""Write the vectors of spec 0.16, derive functions for time, distance and
frames: the vectors of `conformance-derive-functions` from 21, and the load
vectors from 610.

Every expected value here is worked out from the spec text (Version 0.16, its
rulings 1 to 8, and Version 0.6, Derived keys and Order inside `convert`) and
the `derive` lines of model/probe.def. The integer functions are computed with
Python's exact integers (`//` is floor division, ruling 3). The float functions
are computed by `spec_*` below, which follow the formulas of the spec in the
order it states them, with the double functions of Python's `math`. Each float
result is checked against a second, independent derivation (`alt_*`: the radii
and the forward transform written with `b` in place of `e²`, and the inverse
by fixed-point iteration instead of Heikkinen's closed form) before it is
written. Nothing calls an engine.

The derived floats are not members of the pack: a vector states them in
`model` under "@complete": true (compared within 1e-9 relative or 1e-7
absolute), and a target that must stay absent under "@absent". Each vector
gives `"context": {}`, so that a same-format `convert` applies the derivations
(Order inside `convert`, 0.6).

Inputs: none; every value is stated in this file. Writes, under --out, the
vector files named above. With --check nothing is written and the exit
status is 1 when a committed file differs from what this script writes.

Usage: python3 -I tools/gen/conformance-derive16-vectors.py [--out DIR] [--check]
"""
import json
import math
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

INT_MIN, INT_MAX = -(1 << 63), (1 << 63) - 1

# ------------------------------------------------------------------------------
# The functions as the spec states them
# ------------------------------------------------------------------------------
A = 6378137.0
F_ = 1 / 298.257223563
E2 = F_ * (2 - F_)
B = A * (1 - F_)
D2R = math.pi / 180      # "the quotient first"
R2D = 180 / math.pi


class Absent(Exception):
    """The target stays absent (ruling 1)."""


def fin(v):
    if not math.isfinite(v):
        raise Absent()
    return v


def sqrt(v):
    if not math.isfinite(v) or v < 0:
        raise Absent()
    return math.sqrt(v)


def div(n, d):
    if d == 0:
        raise Absent()
    return fin(n / d)


def pw(v, k):
    try:
        return fin(math.pow(v, k))
    except (OverflowError, ValueError):
        raise Absent()


def irange(v):
    if not INT_MIN <= v <= INT_MAX:
        raise Absent()
    return v


def spec_sec_of(ms):
    return irange(ms // 1000)


def spec_nsec_of(ms):
    return irange((ms - 1000 * (ms // 1000)) * 1000000)


def spec_ms_of(sec, nsec):
    return irange(sec * 1000 + nsec // 1000000)


def spec_add_int(x0, x1):
    return irange(x0 + x1)


def spec_sub_int(x0, x1):
    return irange(x0 - x1)


def spec_add(x0, x1):
    return fin(x0 + x1)


def spec_sub(x0, x1):
    return fin(x0 - x1)


def spec_deg(r):
    return fin(r * R2D)


def spec_rad(d):
    return fin(d * D2R)


def phi_of(lat):
    if not -90 <= lat <= 90:      # ruling 6
        raise Absent()
    return lat * D2R


def radii(phi):
    s = math.sin(phi)
    w = 1 - E2 * s * s
    n = div(A, sqrt(w))
    m = div(A * (1 - E2), pw(w, 1.5))
    return n, m


def spec_deg_lat_of(dist, lat):
    _, m = radii(phi_of(lat))
    return fin(div(dist, m) * R2D)


def spec_deg_lon_of(dist, lat):
    phi = phi_of(lat)
    n, _ = radii(phi)
    c = abs(math.cos(phi))
    if c <= 1e-12:
        raise Absent()
    return fin(div(dist, n * c) * R2D)


def spec_m_lat_of(ang, lat):
    _, m = radii(phi_of(lat))
    return fin(ang * D2R * m)


def spec_m_lon_of(ang, lat):
    phi = phi_of(lat)
    n, _ = radii(phi)
    return fin(ang * D2R * n * abs(math.cos(phi)))


def spec_ecef(lat, lon, hae):
    phi = phi_of(lat)
    lam = lon * D2R
    n, _ = radii(phi)
    x = fin((n + hae) * math.cos(phi) * math.cos(lam))
    y = fin((n + hae) * math.cos(phi) * math.sin(lam))
    z = fin((n * (1 - E2) + hae) * math.sin(phi))
    return x, y, z


def spec_heikkinen(x, y, z):
    """(lat in degrees, h), in the order of the spec's closed form."""
    p = sqrt(fin(x * x + y * y))
    F = fin(54 * B * B * z * z)
    G = fin(p * p + (1 - E2) * z * z - E2 * (A * A - B * B))
    if G <= 0:                    # ruling 2
        raise Absent()
    e4 = E2 * E2
    c = div(fin(e4 * F * p * p), pw(G, 3))
    s = math.cbrt(fin(1 + c + sqrt(fin(c * c + 2 * c))))
    k = fin(s + 1 + div(1, s))
    P = div(F, fin(3 * k * k * G * G))
    Q = sqrt(fin(1 + 2 * e4 * P))
    r0 = fin(div(-P * E2 * p, 1 + Q)
             + sqrt(max(0.0, r0_radicand(A * A / 2 * (1 + div(1, Q)), div(P * (1 - E2) * z * z, Q * (1 + Q)),
                                         P * p * p / 2))))     # ruling 9
    U = sqrt(fin((p - E2 * r0) ** 2 + z * z))
    V = sqrt(fin((p - E2 * r0) ** 2 + (1 - E2) * z * z))
    z0 = div(B * B * z, A * V)
    h = fin(U * (1 - div(B * B, A * V)))
    phi = math.atan2(fin(z + (A * A - B * B) / (B * B) * z0), p)
    return fin(phi * R2D), h


def _radicand(t1, t2, t3):
    return fin(t1 - t2 - t3)


# The argument of the square root in r0. On the polar axis it is 0 in exact
# arithmetic, and the grouping of the products moves it by one unit in the
# last place either side of 0 (-0.015625 or 0 at the pole 100 m up); ruling 9
# takes a negative one as 0. `stable_on_the_axis` below recomputes the axis
# vectors with the argument moved by those amounts and checks the result does
# not change.
r0_radicand = _radicand


def spec_lat_of_ecef(x, y, z):
    return spec_heikkinen(x, y, z)[0]


def spec_hae_of_ecef(x, y, z):
    return spec_heikkinen(x, y, z)[1]


def spec_lon_of_ecef(x, y, z):
    if x == 0 and y == 0:
        raise Absent()
    d = fin(math.atan2(y, x) * R2D)
    return 180.0 if d == -180.0 else d    # ruling 5


# ------------------------------------------------------------------------------
# Independent derivations, to check the values above before they are written
# ------------------------------------------------------------------------------
def alt_radii(lat):
    phi = math.radians(lat)
    q = (A * math.cos(phi)) ** 2 + (B * math.sin(phi)) ** 2
    return A * A / math.sqrt(q), (A * B) ** 2 / q ** 1.5


def alt_ecef(lat, lon, hae):
    phi, lam = math.radians(lat), math.radians(lon)
    q = math.sqrt((A * math.cos(phi)) ** 2 + (B * math.sin(phi)) ** 2)
    return ((A * A / q + hae) * math.cos(phi) * math.cos(lam),
            (A * A / q + hae) * math.cos(phi) * math.sin(lam),
            (B * B / q + hae) * math.sin(phi))


def alt_geodetic(x, y, z):
    """Fixed-point iteration on the latitude (valid away from the axis)."""
    p = math.hypot(x, y)
    phi = math.atan2(z, p * (1 - E2))
    for _ in range(200):
        n = A / math.sqrt(1 - E2 * math.sin(phi) ** 2)
        phi = math.atan2(z + E2 * n * math.sin(phi), p)
    # the height as the distance along the normal, well conditioned at any latitude
    h = p * math.cos(phi) + z * math.sin(phi) - A * math.sqrt(1 - E2 * math.sin(phi) ** 2)
    return math.degrees(phi), h


def near(got, want, rel=1e-9, ab=1e-7):
    return abs(got - want) < ab or abs(got - want) <= rel * max(abs(got), abs(want))


def plain(v):
    """Float text of ruling 3 of 0.1.1: shortest round trip, plain notation."""
    if v == 0:
        return "0"
    s = format(Decimal(repr(v)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def tryv(fn, *args):
    try:
        return fn(*args)
    except Absent:
        return None


# The pack's members in field-line order (packs/conformance-derive-functions/pack.def)
MEMBERS = [
    ("t", "time_ms", "iso"), ("x", "probe.x", "int"), ("y", "probe.y", "int"), ("z", "probe.z", "int"),
    ("s1", "probe.s1", "str"), ("n", "probe.n", "int"), ("ds", "probe.ds", "float"),
    ("any", "probe.any1", "int"), ("notx", "probe.notx", "int"), ("parsed", "probe.parsed", "int"),
    ("text", "probe.text", "str"),
    ("tms", "probe.t_ms", "int"), ("usec", "probe.u_sec", "int"), ("unsec", "probe.u_nsec", "int"),
    ("i0", "probe.i0", "int"), ("i1", "probe.i1", "int"),
    ("r", "probe.ang_r", "float"), ("d", "probe.ang_d", "float"),
    ("f0", "probe.f0", "float"), ("f1", "probe.f1", "float"),
    ("dist", "probe.dist", "float"), ("lat", "probe.at_lat", "float"), ("arc", "probe.arc", "float"),
    ("glat", "probe.g_lat", "float"), ("glon", "probe.g_lon", "float"), ("ghae", "probe.g_hae", "float"),
    ("ex", "probe.e_x", "float"), ("ey", "probe.e_y", "float"), ("ez", "probe.e_z", "float"),
    ("tsec", "probe.t_sec", "int"), ("tnsec", "probe.t_nsec", "int"), ("ums", "probe.u_ms", "int"),
    ("isum", "probe.isum", "int"), ("idiff", "probe.idiff", "int"),
]
BY_KEY = {k: (m, t) for m, k, t in MEMBERS}

# The derive lines of 0.16 in model/probe.def: target, function, arguments.
DERIVES = [
    ("probe.t_sec", spec_sec_of, ("probe.t_ms",)),
    ("probe.t_nsec", spec_nsec_of, ("probe.t_ms",)),
    ("probe.u_ms", spec_ms_of, ("probe.u_sec", "probe.u_nsec")),
    ("probe.ang_r_deg", spec_deg, ("probe.ang_r",)),
    ("probe.ang_d_rad", spec_rad, ("probe.ang_d",)),
    ("probe.isum", spec_add_int, ("probe.i0", "probe.i1")),
    ("probe.idiff", spec_sub_int, ("probe.i0", "probe.i1")),
    ("probe.fsum", spec_add, ("probe.f0", "probe.f1")),
    ("probe.fdiff", spec_sub, ("probe.f0", "probe.f1")),
    ("probe.dist_dlat", spec_deg_lat_of, ("probe.dist", "probe.at_lat")),
    ("probe.dist_dlon", spec_deg_lon_of, ("probe.dist", "probe.at_lat")),
    ("probe.arc_mlat", spec_m_lat_of, ("probe.arc", "probe.at_lat")),
    ("probe.arc_mlon", spec_m_lon_of, ("probe.arc", "probe.at_lat")),
    ("probe.back_mlat", spec_m_lat_of, ("probe.dist_dlat", "probe.at_lat")),
    ("probe.back_mlon", spec_m_lon_of, ("probe.dist_dlon", "probe.at_lat")),
    ("probe.g_x", lambda *a: spec_ecef(*a)[0], ("probe.g_lat", "probe.g_lon", "probe.g_hae")),
    ("probe.g_y", lambda *a: spec_ecef(*a)[1], ("probe.g_lat", "probe.g_lon", "probe.g_hae")),
    ("probe.g_z", lambda *a: spec_ecef(*a)[2], ("probe.g_lat", "probe.g_lon", "probe.g_hae")),
    ("probe.g_rlat", spec_lat_of_ecef, ("probe.g_x", "probe.g_y", "probe.g_z")),
    ("probe.g_rlon", spec_lon_of_ecef, ("probe.g_x", "probe.g_y", "probe.g_z")),
    ("probe.g_rhae", spec_hae_of_ecef, ("probe.g_x", "probe.g_y", "probe.g_z")),
    ("probe.e_lat", spec_lat_of_ecef, ("probe.e_x", "probe.e_y", "probe.e_z")),
    ("probe.e_lon", spec_lon_of_ecef, ("probe.e_x", "probe.e_y", "probe.e_z")),
    ("probe.e_hae", spec_hae_of_ecef, ("probe.e_x", "probe.e_y", "probe.e_z")),
]


def complete(entity):
    """Version 0.6, Derived keys: passes until one sets nothing, at most 8."""
    e = dict(entity)
    for _ in range(8):
        changed = False
        for target, fn, args in DERIVES:
            if target in e or not all(a in e for a in args):
                continue
            v = tryv(fn, *(e[a] for a in args))
            if v is not None:
                e[target] = v
                changed = True
        if not changed:
            break
    return e


def encode(entity):
    """The canonical json of the pack: members in field-line order."""
    parts = []
    for member, key, typ in MEMBERS:
        if key not in entity:
            continue
        v = entity[key]
        parts.append(json.dumps(member) + ":" + (str(v) if typ == "int" else plain(v)))
    return "{" + ",".join(parts) + "}"


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written = {}
    DF = "conformance-derive-functions"
    num = [20]     # 1 to 20 are hand-written or written by other scripts

    def vec(name, inputs, state, absent=(), unstated=(), input_text=None, check=None):
        """`inputs`: {key: value}; `state`: the derived keys stated in `model`;
        `absent`: the derived keys stated under "@absent"; `unstated`: keys the
        vector leaves unchecked. Every derived key is one of the three."""
        num[0] += 1
        e = complete(inputs)
        derived = set(e) - set(inputs)
        for k in state:
            assert k in e, (name, k)
        for k in absent:
            assert k not in e, (name, k, e.get(k))
        assert derived <= set(state) | set(unstated), (name, derived - set(state) - set(unstated))
        if check:
            check(e)
        model = {"@complete": True}
        for k in state:
            v = e[k]
            model[k] = str(v) if isinstance(v, int) else plain(v)
        if absent:
            model["@absent"] = list(absent)
        text = input_text if input_text is not None else encode(inputs)
        d = {"name": name, "from": DF, "to": DF, "input": text, "context": {},
             "expect": encode({k: v for k, v in e.items() if k in BY_KEY}), "model": model}
        sink.write("packs/%s/vectors/%02d-%s.json" % (DF, num[0], name),
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[DF] = written.get(DF, 0) + 1

    # ==========================================================================
    # sec_of and nsec_of (ruling 3: floor, exact integers)
    # ==========================================================================
    for label, ms, sec, nsec in (
        ("1500", 1500, 1, 500000000),
        ("minus-1", -1, -1, 999000000),                      # the spec's example
        ("minus-1000", -1000, -1, 0),
        ("minus-1001", -1001, -2, 999000000),
        ("999999999999999999", 999999999999999999, 999999999999999, 999000000),
        ("largest-64-bit", INT_MAX, 9223372036854775, 807000000),
        ("smallest-64-bit", INT_MIN, -9223372036854776, 192000000),   # ruling 3's example
    ):
        assert (spec_sec_of(ms), spec_nsec_of(ms)) == (sec, nsec), label
        vec("sec-of-nsec-of-" + label, {"probe.t_ms": ms}, ["probe.t_sec", "probe.t_nsec"])

    # ==========================================================================
    # ms_of (ruling 7: any nsec, floor; ruling 3: only the result is range-checked)
    # ==========================================================================
    for label, sec, nsec, ms in (
        ("ruling-07-0-minus-1", 0, -1, -1),
        ("ruling-07-999999-ns-floors", 1, 999999, 1000),
        ("ruling-07-oversized-ns", 1, 1500000000, 2500),
        ("minus-1-s-999999999-ns", -1, 999999999, -1),
        ("ns-smallest-64-bit", 0, INT_MIN, -9223372036855),
        ("largest-64-bit-result", 9223372036854775, 807000000, INT_MAX),
        ("one-beyond-the-largest", 9223372036854775, 808000000, None),
        ("largest-from-sec-times-1000-beyond-the-range", 9223372036854776, -193000000, INT_MAX),
        ("smallest-from-sec-times-1000-beyond-the-range", -9223372036854776, 192000000, INT_MIN),
        ("one-below-the-smallest-by-floor", -9223372036854776, 191999999, None),
    ):
        assert tryv(spec_ms_of, sec, nsec) == ms, label
        if ms is None:
            vec("ms-of-" + label, {"probe.u_sec": sec, "probe.u_nsec": nsec}, [], absent=["probe.u_ms"])
        else:
            vec("ms-of-" + label, {"probe.u_sec": sec, "probe.u_nsec": nsec}, ["probe.u_ms"])

    # ==========================================================================
    # add and sub on int (exact; a result outside 64 bits is absent)
    # ==========================================================================
    for label, i0, i1, s, d in (
        ("small", -5, 7, 2, -12),
        ("add-beyond-the-largest", INT_MAX, 1, None, INT_MAX - 1),
        ("sub-below-the-smallest", INT_MIN, 1, INT_MIN + 1, None),
        ("sub-of-the-smallest-beyond-the-largest", 0, INT_MIN, INT_MIN, None),
        ("add-below-the-smallest", INT_MIN, -1, None, INT_MIN + 1),
    ):
        assert (tryv(spec_add_int, i0, i1), tryv(spec_sub_int, i0, i1)) == (s, d), label
        state = [k for k, v in (("probe.isum", s), ("probe.idiff", d)) if v is not None]
        absent = [k for k, v in (("probe.isum", s), ("probe.idiff", d)) if v is None]
        vec("add-sub-int-" + label, {"probe.i0": i0, "probe.i1": i1}, state, absent=absent)

    # ==========================================================================
    # add and sub on float
    # ==========================================================================
    assert (spec_add(1.5, -0.25), spec_sub(1.5, -0.25)) == (1.25, 1.75)
    vec("add-sub-float-exact", {"probe.f0": 1.5, "probe.f1": -0.25}, ["probe.fsum", "probe.fdiff"])
    # a height above the ellipsoid of 100.5 m and a geoid separation of 47.25 m
    assert spec_sub(100.5, 47.25) == 53.25
    vec("add-sub-float-height-above-mean-sea-level", {"probe.f0": 100.5, "probe.f1": 47.25},
        ["probe.fsum", "probe.fdiff"])
    # 1e308 + 1e308 is infinite: absent; the difference is 0
    assert tryv(spec_add, 1e308, 1e308) is None and spec_sub(1e308, 1e308) == 0
    vec("add-sub-float-sum-not-finite", {"probe.f0": 1e308, "probe.f1": 1e308}, ["probe.fdiff"],
        absent=["probe.fsum"])

    # ==========================================================================
    # deg and rad (ruling 8: the quotient first)
    # ==========================================================================
    assert spec_deg(math.pi) == 180.0 and spec_rad(180.0) == math.pi
    vec("deg-of-pi-rad-of-180", {"probe.ang_r": math.pi, "probe.ang_d": 180.0},
        ["probe.ang_r_deg", "probe.ang_d_rad"],
        check=lambda e: assert_near(e["probe.ang_r_deg"], math.degrees(math.pi)))
    vec("deg-and-rad-negative", {"probe.ang_r": -0.5, "probe.ang_d": -30.0},
        ["probe.ang_r_deg", "probe.ang_d_rad"],
        check=lambda e: assert_near(e["probe.ang_r_deg"], -0.5 * 180 / math.pi)
        and assert_near(e["probe.ang_d_rad"], -math.pi / 6))
    # 1e308 radians is beyond the largest double in degrees: absent
    vec("deg-not-finite", {"probe.ang_r": 1e308, "probe.ang_d": 1e308},
        ["probe.ang_d_rad"], absent=["probe.ang_r_deg"])

    # ==========================================================================
    # deg_lat_of, deg_lon_of, m_lat_of, m_lon_of (ruling 6; the pole)
    # ==========================================================================
    def radii_check(lat):
        def chk(e):
            n, m = alt_radii(lat)
            if "probe.dist_dlat" in e:
                assert_near(e["probe.dist_dlat"], math.degrees(e["probe.dist"] / m))
                assert_near(e["probe.back_mlat"], e["probe.dist"])
            if "probe.dist_dlon" in e:
                assert_near(e["probe.dist_dlon"], math.degrees(e["probe.dist"] / (n * abs(math.cos(math.radians(lat))))))
                assert_near(e["probe.back_mlon"], e["probe.dist"])
            if "probe.arc_mlat" in e:
                assert_near(e["probe.arc_mlat"], math.radians(e["probe.arc"]) * m)
                assert_near(e["probe.arc_mlon"], math.radians(e["probe.arc"]) * n * abs(math.cos(math.radians(lat))))
            return True
        return chk

    DIST = ["probe.dist_dlat", "probe.dist_dlon", "probe.arc_mlat", "probe.arc_mlon",
            "probe.back_mlat", "probe.back_mlon"]
    for label, lat in (("45", 45.0), ("equator", 0.0), ("minus-60", -60.0), ("89.9999999999", 89.9999999999)):
        vec("distance-at-latitude-" + label, {"probe.dist": 1000.0, "probe.at_lat": lat, "probe.arc": 0.01},
            DIST, check=radii_check(lat))
    # |cos φ| ≤ 1e-12: deg_lon_of absent, and so back_mlon; m_lon_of is a tiny value
    for label, lat in (("90", 90.0), ("minus-90", -90.0), ("89.99999999999", 89.99999999999)):
        vec("distance-at-latitude-" + label + "-no-degrees-of-longitude",
            {"probe.dist": 1000.0, "probe.at_lat": lat, "probe.arc": 0.01},
            ["probe.dist_dlat", "probe.arc_mlat", "probe.arc_mlon", "probe.back_mlat"],
            absent=["probe.dist_dlon", "probe.back_mlon"], check=radii_check(lat))
    for label, lat in (("91", 91.0), ("minus-90.5", -90.5)):
        vec("ruling-06-latitude-" + label + "-distance-absent",
            {"probe.dist": 1000.0, "probe.at_lat": lat, "probe.arc": 0.01}, [], absent=DIST)

    # ==========================================================================
    # ecef_x, ecef_y, ecef_z, and back through Heikkinen's closed form
    # ==========================================================================
    def fwd_check(lat, lon, hae, back=True):
        def chk(e):
            for k, w in zip(("probe.g_x", "probe.g_y", "probe.g_z"), alt_ecef(lat, lon, hae)):
                assert_near(e[k], w)
            if back:
                assert_near(e["probe.g_rlat"], lat)
                assert_near(e["probe.g_rhae"], hae)
                assert_near(e["probe.g_rlon"], lon)
            return True
        return chk

    G3 = ["probe.g_x", "probe.g_y", "probe.g_z"]
    GR = ["probe.g_rlat", "probe.g_rlon", "probe.g_rhae"]
    for label, lat, lon, hae in (
        ("0-0-0", 0.0, 0.0, 0.0),
        ("0-90-0-x-is-near-0", 0.0, 90.0, 0.0),
        ("50-10-1000", 50.0, 10.0, 1000.0),
        ("minus-30-minus-120-minus-50", -30.0, -120.0, -50.0),
        ("10-180-0", 10.0, 180.0, 0.0),
    ):
        vec("ecef-of-" + label + "-and-back", {"probe.g_lat": lat, "probe.g_lon": lon, "probe.g_hae": hae},
            G3 + GR, check=fwd_check(lat, lon, hae))
    # At the pole x is (N + hae) cos φ, about 4e-10: the way back is near the
    # axis, where the argument of the square root in r0 is about 0 (ruling 9).
    def pole_back(e):
        fwd_check(90.0, 0.0, 100.0)(e)
        return stable_on_the_axis(e["probe.g_x"], e["probe.g_y"], e["probe.g_z"], 90.0, 100.0,
                                  "probe.g_rlat", "probe.g_rhae")(e)
    vec("ruling-09-ecef-of-90-0-100-and-back", {"probe.g_lat": 90.0, "probe.g_lon": 0.0, "probe.g_hae": 100.0},
        G3 + GR, check=pole_back)
    vec("ruling-06-ecef-of-latitude-91-absent", {"probe.g_lat": 91.0, "probe.g_lon": 0.0, "probe.g_hae": 0.0},
        [], absent=G3 + GR)

    # ==========================================================================
    # lat_of_ecef, lon_of_ecef, hae_of_ecef (rulings 1, 2, 5)
    # ==========================================================================
    EG = ["probe.e_lat", "probe.e_lon", "probe.e_hae"]

    def inv_check(lat, lon, hae):
        def chk(e):
            assert_near(e["probe.e_lat"], lat)
            assert_near(e["probe.e_hae"], hae)
            if lon is not None:
                assert_near(e["probe.e_lon"], lon)
            return True
        return chk

    def ecef_in(x, y, z):
        return {"probe.e_x": x, "probe.e_y": y, "probe.e_z": z}

    vec("geodetic-of-6378137-0-0", ecef_in(A, 0.0, 0.0), EG, check=inv_check(0.0, 0.0, 0.0))
    vec("geodetic-of-0-minus-6378137-0", ecef_in(0.0, -A, 0.0), EG, check=inv_check(0.0, -90.0, 0.0))
    vec("ruling-05-geodetic-of-minus-6378137-0-0", ecef_in(-A, 0.0, 0.0), EG, check=inv_check(0.0, 180.0, 0.0))
    # y is -0.0: atan2 gives -π, and -π × (180 / π) is -180 exactly
    assert math.atan2(-0.0, -A) * R2D == -180.0
    vec("ruling-05-geodetic-of-minus-6378137-minus-0-0", ecef_in(-A, -0.0, 0.0), EG,
        input_text='{"ex":-6378137,"ey":-0.0,"ez":0}', check=inv_check(0.0, 180.0, 0.0))
    # the pole 100 m above the ellipsoid: x and y are 0, so the longitude is
    # absent; latitude 90 and height 100 by ruling 9
    vec("ruling-09-geodetic-of-the-pole", ecef_in(0.0, 0.0, B + 100), ["probe.e_lat", "probe.e_hae"],
        absent=["probe.e_lon"], check=stable_on_the_axis(0.0, 0.0, B + 100, 90.0, 100.0, "probe.e_lat", "probe.e_hae"))
    vec("geodetic-of-10-m-from-the-pole-axis", ecef_in(10.0, 0.0, B + 100), EG,
        check=lambda e: assert_near(e["probe.e_lat"], alt_geodetic(10.0, 0.0, B + 100)[0])
        and assert_near(e["probe.e_hae"], alt_geodetic(10.0, 0.0, B + 100)[1]))
    # a point 1 km above 50 N 10 E, its coordinates rounded to the millimetre
    mx, my, mz = (round(v, 3) for v in alt_ecef(50.0, 10.0, 1000.0))
    ml, mh = alt_geodetic(mx, my, mz)
    vec("geodetic-of-a-mid-latitude-point", ecef_in(mx, my, mz), EG,
        check=inv_check(ml, math.degrees(math.atan2(my, mx)), mh))
    sx, sy, sz = (round(v, 3) for v in alt_ecef(-33.5, 151.25, -20.0))
    sl, sh = alt_geodetic(sx, sy, sz)
    vec("geodetic-of-a-southern-eastern-point", ecef_in(sx, sy, sz), EG,
        check=inv_check(sl, math.degrees(math.atan2(sy, sx)), sh))
    # ruling 2: G ≤ 0
    vec("ruling-02-geodetic-of-the-centre-all-absent", ecef_in(0.0, 0.0, 0.0), [], absent=EG)
    vec("ruling-02-geodetic-of-1000-0-0-longitude-only", ecef_in(1000.0, 0.0, 0.0), ["probe.e_lon"],
        absent=["probe.e_lat", "probe.e_hae"])
    vec("ruling-02-geodetic-of-1000-0-1000-longitude-only", ecef_in(1000.0, 0.0, 1000.0), ["probe.e_lon"],
        absent=["probe.e_lat", "probe.e_hae"])
    # ruling 1: x² is infinite, so is G, and c is 0 × ∞ / ∞; never an error
    vec("ruling-01-geodetic-of-1e200-0-0-longitude-only", ecef_in(1e200, 0.0, 0.0), ["probe.e_lon"],
        absent=["probe.e_lat", "probe.e_hae"])

    # ruling 11: a longitude has no range check. 370 gives what 10 gives (within
    # the tolerance: 370 × (π / 180) is not 10 × (π / 180) + 2π in doubles), and
    # the way back gives 10, in (−180, 180].
    def lon370(e):
        ten = complete({"probe.g_lat": 10.0, "probe.g_lon": 10.0, "probe.g_hae": 0.0})
        for k in G3 + GR:
            assert_near(e[k], ten[k])
        assert_near(e["probe.g_rlon"], 10.0)
        return fwd_check(10.0, 370.0, 0.0, back=False)(e)
    vec("ruling-11-ecef-of-10-370-0-as-of-10-10-0", {"probe.g_lat": 10.0, "probe.g_lon": 370.0, "probe.g_hae": 0.0},
        G3 + GR, check=lon370)

    # ==========================================================================
    # load vectors from 610
    # ==========================================================================
    MODELS_HEAD = ("module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\n"
                   "key ms int ms\nkey ms2 int ms\nkey sec int s\nkey nsec int ns\n"
                   "key a float -\nkey b float -\nkey c float -\nkey d float -\nkey i int -\nkey j int -\n")
    CORE = ("module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\n"
            "key type string -\nkey lat float deg\nkey lon float deg\nkey callsign string -\nkey time_ms int ms\n")
    PACK = 'format probe\nversion 0.16.0\ndistribution public\nsource "probe"\nuses probe\nwire json\nfield uid id string\n'
    lnum = [609]

    def L(name, derives, error="bad-directive"):
        lnum[0] += 1
        full = "%d-derive16-%s" % (lnum[0], name)
        d = {"name": full, "models": [CORE, MODELS_HEAD + "".join("derive " + x + "\n" for x in derives)],
             "pack": PACK}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full,
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1

    L("every-function-loads", [
        "probe.sec sec_of probe.ms", "probe.nsec nsec_of probe.ms", "probe.ms2 ms_of probe.sec probe.nsec",
        "probe.b deg probe.a", "probe.b rad probe.a", "probe.c add probe.a probe.b", "probe.c sub probe.a probe.b",
        "probe.j add probe.i probe.ms", "probe.j sub probe.i probe.ms",
        "probe.c deg_lat_of probe.a probe.b", "probe.c deg_lon_of probe.a probe.b",
        "probe.c m_lat_of probe.a probe.b", "probe.c m_lon_of probe.a probe.b",
        "probe.d ecef_x probe.a probe.b probe.c", "probe.d ecef_y probe.a probe.b probe.c",
        "probe.d ecef_z probe.a probe.b probe.c", "probe.d lat_of_ecef probe.a probe.b probe.c",
        "probe.d lon_of_ecef probe.a probe.b probe.c", "probe.d hae_of_ecef probe.a probe.b probe.c",
    ], error=None)
    # wrong argument count, one per arity
    L("sec-of-with-two-arguments", ["probe.sec sec_of probe.ms probe.ms2"])
    L("nsec-of-with-no-argument", ["probe.nsec nsec_of"])
    L("deg-with-two-arguments", ["probe.b deg probe.a probe.c"])
    L("ms-of-with-one-argument", ["probe.ms2 ms_of probe.sec"])
    L("add-with-three-arguments", ["probe.c add probe.a probe.b probe.d"])
    L("sub-with-one-argument", ["probe.c sub probe.a"])
    L("deg-lon-of-with-three-arguments", ["probe.c deg_lon_of probe.a probe.b probe.d"])
    L("ecef-x-with-two-arguments", ["probe.d ecef_x probe.a probe.b"])
    L("lat-of-ecef-with-four-arguments", ["probe.d lat_of_ecef probe.a probe.b probe.c probe.d"])
    # ruling 4: types
    L("ruling-04-deg-of-an-int-key", ["probe.b deg probe.i"])
    L("ruling-04-deg-to-an-int-target", ["probe.j deg probe.a"])
    L("ruling-04-sec-of-a-float-key", ["probe.sec sec_of probe.a"])
    L("ruling-04-sec-of-to-a-float-target", ["probe.a sec_of probe.ms"])
    L("ruling-04-ms-of-a-float-nsec", ["probe.ms2 ms_of probe.sec probe.a"])
    L("ruling-04-add-float-target-int-arguments", ["probe.a add probe.i probe.j"])
    L("ruling-04-add-float-and-int-arguments", ["probe.c add probe.a probe.i"])
    L("ruling-04-sub-int-target-float-arguments", ["probe.i sub probe.a probe.b"])
    L("ruling-04-deg-lat-of-an-int-latitude", ["probe.c deg_lat_of probe.a probe.i"])
    L("ruling-04-ecef-z-of-an-int-height", ["probe.d ecef_z probe.a probe.b probe.i"])
    L("ruling-04-hae-of-ecef-to-an-int-target", ["probe.i hae_of_ecef probe.a probe.b probe.c"])
    return written


def stable_on_the_axis(x, y, z, lat, hae, klat, khae):
    """The check of a vector on or near the polar axis: the stated values are
    `lat` and `hae` in exact arithmetic, and they do not change when the
    argument of the square root in r0 is moved by the amounts other groupings
    of the products give (-0.015625 to +0.015625: up to two units in the last
    place of terms near 4e13, either side)."""
    def chk(e):
        assert_near(e[klat], lat)
        assert_near(e[khae], hae)
        for shift in (-0.015625, -0.0078125, 0.0078125, 0.015625):
            global r0_radicand
            r0_radicand = lambda t1, t2, t3, d=shift: _radicand(t1, t2, t3) + d
            try:
                got = spec_heikkinen(x, y, z)
            finally:
                r0_radicand = _radicand
            assert_near(got[0], e[klat])
            assert_near(got[1], e[khae])
        return True
    return chk


def assert_near(got, want):
    assert near(got, want), (got, want)
    return True


def main(argv=None):
    return genio.vector_main("conformance-derive16-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
