#!/usr/bin/env python3
"""Write the igs-ssr pack, its module and vectors from this program's own
statement of the IGS SSR format, version 1.00 (IGS, 2020-10-05,
https://files.igs.org/pub/data/format/igs_ssr_v1.pdf, chapters 7 and 8).

Python 3 standard library only; imports nothing from engines/. The layouts
below are restated from the document's message tables (field order and bit
widths) and data field table (resolutions); each table's stated TOTAL is
checked against the sum of the widths here.

A message is the body of one RTCM 3 frame of message number 4076, after the
3-octet frame header and before the CRC-24Q, read most significant bit first
as a sequence (engine-spec 0.8 and 0.21). The 3-bit IGS SSR version is
common; the 8-bit IGS message number selects the kind.

The vectors are written with this program's bit writer from values it
chooses; they are not decoded by an engine.

Usage:
  python3 -I tools/gen/igsssr2pack.py <checkout>           write
  python3 -I tools/gen/igsssr2pack.py <checkout> --check   exit 1 when a file differs
"""
import json
import os
import sys
from fractions import Fraction

FMT = MOD = "igs-ssr"
MODULE = "igsssr"
DOC = "IGS State Space Representation (SSR) Format, Version 1.00, International GNSS Service, 2020-10-05"
URL = "https://files.igs.org/pub/data/format/igs_ssr_v1.pdf"
DOC_SHA = "2077dde0c87ff45069fd93ba44ee71a50657bddfc003f74f72316af5088f5f6e"

# key: (bits, signed, factor or None, unit, meaning). factor: the resolution in the key's unit.
F = {
    "epoch_s": (20, False, None, "s", "IDF003 SSR epoch time: full seconds since the start of the GPS week (of the day for GLONASS, which also counts in UTC); the week is not in the message"),
    "update_interval": (4, False, None, "-", "IDF004 SSR update interval code: 0 1 s, 1 2 s, 2 5 s, 3 10 s, 4 15 s, 5 30 s, 6 60 s, 7 120 s, 8 240 s, 9 300 s, 10 600 s, 11 900 s, 12 1800 s, 13 3600 s, 14 7200 s, 15 10800 s"),
    "multiple_message": (1, False, None, "-", "IDF005 multiple message indicator: 1 when more messages of the same number and epoch follow"),
    "iod_ssr": (4, False, None, "-", "IDF007 issue of data SSR: changes when the generating configuration changes"),
    "provider_id": (16, False, None, "-", "IDF008 SSR provider ID, assigned by RTCM"),
    "solution_id": (4, False, None, "-", "IDF009 SSR solution ID of the provider"),
    "regional_crs": (1, False, None, "-", "IDF006 orbit reference: 0 ITRF, 1 a regional frame"),
    "dispersive_consistent": (1, False, None, "-", "IDF032 dispersive bias consistency indicator"),
    "mw_consistent": (1, False, None, "-", "IDF033 Melbourne-Wubbena consistency indicator"),
    "vtec_quality": (9, False, Fraction(1, 20), "TECU", "IDF041 VTEC quality indicator, 0.05 TECU steps; 0 unknown"),
    "layer_count": (2, False, None, "-", "IDF035 number of ionospheric layers minus 1"),
    # satellite part
    "sat_id": (6, False, None, "-", "IDF011 GNSS satellite ID (PRN; the slot number for GLONASS)"),
    "iod": (8, False, None, "-", "IDF012 GNSS IOD: the issue of data of the broadcast ephemeris the correction applies to"),
    "radial_m": (22, True, Fraction(1, 10000), "m", "IDF013 radial orbit correction to the broadcast ephemeris, 0.1 mm steps"),
    "along_m": (20, True, Fraction(1, 2500), "m", "IDF014 along-track orbit correction, 0.4 mm steps"),
    "cross_m": (20, True, Fraction(1, 2500), "m", "IDF015 cross-track orbit correction, 0.4 mm steps"),
    "dot_radial_ms": (21, True, Fraction(1, 1000000), "m/s", "IDF016 rate of the radial orbit correction, 0.001 mm/s steps"),
    "dot_along_ms": (19, True, Fraction(1, 250000), "m/s", "IDF017 rate of the along-track orbit correction, 0.004 mm/s steps"),
    "dot_cross_ms": (19, True, Fraction(1, 250000), "m/s", "IDF018 rate of the cross-track orbit correction, 0.004 mm/s steps"),
    "clock_c0_m": (22, True, Fraction(1, 10000), "m", "IDF019 C0 coefficient of the clock correction to the broadcast clock, 0.1 mm steps"),
    "clock_c1_ms": (21, True, Fraction(1, 1000000), "m/s", "IDF020 C1 coefficient, 0.001 mm/s steps"),
    "clock_c2_mss": (27, True, Fraction(1, 50000000), "m/s^2", "IDF021 C2 coefficient, 0.00002 mm/s^2 steps"),
    "hr_clock_m": (22, True, Fraction(1, 10000), "m", "IDF022 high rate clock correction, added to the polynomial clock correction, 0.1 mm steps"),
    "signal_id": (5, False, None, "-", "IDF024 GNSS signal and tracking mode identifier (a table per GNSS)"),
    "code_bias_m": (14, True, Fraction(1, 100), "m", "IDF025 code bias for the signal, 0.01 m steps"),
    "yaw_deg": (9, False, Fraction(45, 64), "deg", "IDF026 yaw angle for the phase wind-up correction, 1/256 semicircle steps (degrees here)"),
    "yaw_rate_degs": (8, True, Fraction(45, 2048), "deg/s", "IDF027 yaw rate, 1/8192 semicircle per second steps (degrees per second here)"),
    "integer_indicator": (1, False, None, "-", "IDF029 signal integer indicator: 1 when the phase bias has the integer property"),
    "widelane_indicator": (2, False, None, "-", "IDF030 signals wide-lane integer indicator"),
    "discontinuity": (4, False, None, "-", "IDF031 signal discontinuity counter"),
    "phase_bias_m": (20, True, Fraction(1, 10000), "m", "IDF028 phase bias for the signal, 0.1 mm steps"),
    "ura": (6, False, None, "-", "IDF034 SSR URA: a 3-bit class and a 3-bit value, as the document defines them"),
}
HEAD = ["epoch_s", "update_interval", "multiple_message", "iod_ssr", "provider_id", "solution_id"]
# type: (header keys after HEAD, satellite keys, inner list, its count is adjacent, document totals header/sat/inner)
TYPES = [
    ("orbit", 1, ["regional_crs"], ["sat_id", "iod", "radial_m", "along_m", "cross_m", "dot_radial_ms", "dot_along_ms", "dot_cross_ms"], None, (79, 135)),
    ("clock", 2, [], ["sat_id", "clock_c0_m", "clock_c1_ms", "clock_c2_mss"], None, (78, 76)),
    ("orbit-clock", 3, ["regional_crs"], ["sat_id", "iod", "radial_m", "along_m", "cross_m", "dot_radial_ms", "dot_along_ms",
                                         "dot_cross_ms", "clock_c0_m", "clock_c1_ms", "clock_c2_mss"], None, (79, 205)),
    ("hr-clock", 4, [], ["sat_id", "hr_clock_m"], None, (78, 28)),
    ("code-bias", 5, [], ["sat_id"], ("biases", ["signal_id", "code_bias_m"], True), (78, 11, 19)),
    ("phase-bias", 6, ["dispersive_consistent", "mw_consistent"], ["sat_id", "yaw_deg", "yaw_rate_degs"],
     ("biases", ["signal_id", "integer_indicator", "widelane_indicator", "discontinuity", "phase_bias_m"], False), (80, 28, 32)),
    ("ura", 7, [], ["sat_id", "ura"], None, (78, 12)),
]
GNSS = [("gps", 20), ("glonass", 40), ("galileo", 60), ("qzss", 80), ("bds", 100), ("sbas", 120)]
COMMON_BITS = 12 + 3 + 8        # message number, version, IGS message number
LIST_OF = {"orbit": "orbit_sats", "clock": "clock_sats", "orbit-clock": "orbit_clock_sats", "hr-clock": "hr_clock_sats",
           "code-bias": "code_bias_sats", "phase-bias": "phase_bias_sats", "ura": "ura_sats"}


def check_totals():
    for name, _, hx, sat, inner, tot in TYPES:
        h = COMMON_BITS + sum(F[k][0] for k in HEAD + hx) + 6
        s = sum(F[k][0] for k in sat) + (5 if inner else 0)
        assert h == tot[0], (name, "header", h, tot[0])
        assert s == tot[1], (name, "satellite", s, tot[1])
        if inner:
            assert sum(F[k][0] for k in inner[1]) == tot[2], (name, "inner")
    assert COMMON_BITS + sum(F[k][0] for k in HEAD) + 9 + 2 == 83     # VTEC header total


def tr(k):
    bits, signed, factor, _, _ = F[k]
    if factor is None:
        return "twos" if signed else "uint"
    f = "%d/%d" % (factor.numerator, factor.denominator) if factor.denominator != 1 else str(factor.numerator)
    return ("sscale:" if signed else "uscale:") + f


def ktype(k):
    return "float" if F[k][2] is not None else "int"


def pack_text():
    o = ["# IGS SSR format v1.00 messages: RTCM 3 message 4076 and its IGS sub-types, one kind per IGS",
         "# message number (7 correction types for each of GPS, GLONASS, Galileo, QZSS, BDS and SBAS, and",
         "# the VTEC header). Generated by tools/gen/igsssr2pack.py; do not edit by hand.",
         "# The message is the body of one RTCM 3 frame: after the 3-octet frame header, before the",
         "# CRC-24Q; most significant bit first, read in sequence.",
         "# Licence: LicenseRef-unstated (the IGS document states no licence; layouts restated).",
         "format        %s" % FMT, "version       0.1.0", "distribution  public",
         'source        "%s, %s (sha256 %s), chapters 7 and 8; no licence stated: LicenseRef-unstated"' % (DOC, URL, DOC_SHA),
         "uses          %s" % MODULE, "wire          bits", "layout        sequential", "bit_order     msb",
         "# RTCM message number 4076 (IGS proprietary) and the IGS SSR version.",
         "when          12 4076",
         "field         %s.version 3 uint" % MODULE]
    for g, base in GNSS:
        for name, n, hx, sat, inner, _ in TYPES:
            lst = "%s.%s" % (MODULE, LIST_OF[name])
            o += ["", "kind          %s-%s" % (g, name), "when          8 %d" % (base + n), "requires      %s" % lst]
            for k in HEAD + hx:
                o.append("field         %s.%s %d %s" % (MODULE, k, F[k][0], tr(k)))
            o.append("group         %s count 6" % lst)
            if inner and not inner[2]:
                # phase bias: the bias count comes before yaw angle and yaw rate (engine-spec 0.21 count)
                o.append("  field       %s.%s %d %s" % (MODULE, sat[0], F[sat[0]][0], tr(sat[0])))
                o.append("  count       nbias 5")
                for k in sat[1:]:
                    o.append("  field       %s.%s %d %s" % (MODULE, k, F[k][0], tr(k)))
                o.append("  group       %s.%s count @nbias" % (MODULE, inner[0]))
            else:
                for k in sat:
                    o.append("  field       %s.%s %d %s" % (MODULE, k, F[k][0], tr(k)))
                if inner:
                    o.append("  group       %s.%s count 5" % (MODULE, inner[0]))
            if inner:
                for k in inner[1]:
                    o.append("    field     %s.%s %d %s" % (MODULE, k, F[k][0], tr(k)))
                o.append("  end")
            o.append("end")
    o += ["", "# VTEC spherical harmonics: the header only; the layers are not read (pack.md).",
          "kind          vtec", "when          8 201", "requires      %s.vtec_quality" % MODULE]
    for k in HEAD + ["vtec_quality", "layer_count"]:
        o.append("field         %s.%s %d %s" % (MODULE, k, F[k][0], tr(k)))
    return "\n".join(o) + "\n"


def module_text():
    o = ["# The igsssr module: the fields of IGS SSR v1.00 messages. Generated by tools/gen/igsssr2pack.py.",
         "module        %s" % MODULE, "version       0.1.0", "distribution  public",
         'source        "%s, %s; no licence stated: LicenseRef-unstated"' % (DOC, URL),
         'key  version  int  -  "IDF001 IGS SSR version: 1 to 6"']
    for k, (bits, signed, factor, unit, meaning) in F.items():
        o.append('key  %s  %s  %s  "%s"' % (k, ktype(k), unit, meaning))
    for name, lst in LIST_OF.items():
        o.append('list %s  "the satellites of a %s message, one item each"' % (lst, name.replace("-", " ")))
    o.append('list biases  "the code or phase biases of one satellite, one item per signal"')
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------- vectors ---

class Bits:
    def __init__(self):
        self.v, self.n = 0, 0

    def put(self, value, n):
        self.v = (self.v << n) | (value & ((1 << n) - 1))
        self.n += n

    def bytes(self):
        pad = -self.n % 8
        return ((self.v << pad).to_bytes((self.n + pad) // 8, "big"))


def raw_of(k, x):
    """Wire integer for the model value x of key k (exact by construction)."""
    factor = F[k][2]
    return x if factor is None else int(Fraction(x) / factor)


def model_text(k, raw):
    factor = F[k][2]
    if factor is None:
        return str(raw)
    return repr(float(raw * factor))


def sample(k, i):
    """A raw wire value for key k, item i: inside the field's range, a signed one negative for odd i."""
    bits, signed = F[k][0], F[k][1]
    top = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
    v = (37 * (i + 1) + bits * 11) % (top + 1)
    return -v if signed and i % 2 else v


def vectors():
    out = {}
    for g, base in GNSS:
        for name, n, hx, sat, inner, _ in TYPES:
            b = Bits()
            b.put(4076, 12)
            b.put(1, 3)
            b.put(base + n, 8)
            m = {"@kind": "%s-%s" % (g, name), "igsssr.version": "1"}
            for j, k in enumerate(HEAD + hx):
                r = 345600 + base + n if k == "epoch_s" else sample(k, j)
                b.put(r, F[k][0])
                m["igsssr." + k] = model_text(k, r)
            nsat = 2
            b.put(nsat, 6)
            lst = "igsssr." + LIST_OF[name]
            m[lst + ".#"] = str(nsat)
            for s in range(nsat):
                vals = {k: (s + 5 if k == "sat_id" else sample(k, s)) for k in sat}
                nb = s + 1
                if inner and not inner[2]:
                    b.put(vals["sat_id"], 6)
                    b.put(nb, 5)
                    for k in sat[1:]:
                        b.put(vals[k], F[k][0])
                else:
                    for k in sat:
                        b.put(vals[k], F[k][0])
                    if inner:
                        b.put(nb, 5)
                for k in sat:
                    m["%s[%d].igsssr.%s" % (lst, s, k)] = model_text(k, vals[k])
                if inner:
                    m["%s[%d].igsssr.biases.#" % (lst, s)] = str(nb)
                    for t in range(nb):
                        for k in inner[1]:
                            r = sample(k, t + s)
                            b.put(r, F[k][0])
                            m["%s[%d].igsssr.biases[%d].igsssr.%s" % (lst, s, t, k)] = model_text(k, r)
            data = b.bytes().hex()
            ref = "%s, section 8: header part, %d satellites%s; values chosen here" % (
                DOC, nsat, " with 1 and 2 biases" if inner else "")
            out["%s-%s-roundtrip" % (g, name)] = {"name": "%s-%s-roundtrip" % (g, name), "from": FMT, "to": FMT,
                                                   "input": data, "expect": data, "model": m,
                                                   "source": "derived by tools/gen/igsssr2pack.py; no engine run",
                                                   "reference": ref}
    # VTEC: the header is read; the layers after it are not, so the output is the header only.
    b = Bits()
    b.put(4076, 12)
    b.put(1, 3)
    b.put(201, 8)
    m = {"@kind": "vtec"}
    for j, k in enumerate(HEAD + ["vtec_quality", "layer_count"]):
        r = 0 if k == "layer_count" else sample(k, j)
        b.put(r, F[k][0])
        m["igsssr." + k] = model_text(k, r)
    head_bits = b.n
    b.put(45, 8)          # one layer: height 450 km
    b.put(0, 4)           # degree N-1 = 0
    b.put(0, 4)           # order M-1 = 0
    for c in (100, -20, 30):
        b.put(c, 16)      # cosine C00, C10 and C11, then sine S11, for N = M = 1
    b.put(7, 16)
    full = b.bytes()
    hb = Bits()
    hb.v, hb.n = b.v >> (b.n - head_bits), head_bits
    out["vtec-header-only"] = {"name": "vtec-header-only", "from": FMT, "to": FMT, "input": full.hex(),
                               "expect": hb.bytes().hex(), "model": m,
                               "source": "derived by tools/gen/igsssr2pack.py; no engine run",
                               "reference": "%s, section 8.4: the VTEC header is read; the layer after it is not "
                                            "written" % DOC}
    b = Bits()
    b.put(4075, 12)
    b.put(1, 3)
    b.put(21, 8)
    out["other-message-number-is-no-kind"] = {"name": "other-message-number-is-no-kind", "from": FMT, "to": FMT,
                                              "input": b.bytes().hex(), "expect_error": "no-kind",
                                              "source": "derived by tools/gen/igsssr2pack.py; no engine run",
                                              "reference": "only RTCM message 4076 carries IGS SSR"}
    b = Bits()
    b.put(4076, 12)
    b.put(1, 3)
    b.put(28, 8)
    out["reserved-sub-type-is-no-kind"] = {"name": "reserved-sub-type-is-no-kind", "from": FMT, "to": FMT,
                                           "input": (b.bytes() + bytes(12)).hex(), "expect_error": "no-kind",
                                           "source": "derived by tools/gen/igsssr2pack.py; no engine run",
                                           "reference": "IGS message numbers 28 to 40 are reserved for GPS"}
    return out


def main():
    gt = sys.argv[1]
    check = "--check" in sys.argv[2:]
    check_totals()
    files = {os.path.join("packs", FMT, "pack.def"): pack_text(), os.path.join("model", MODULE + ".def"): module_text()}
    for i, (name, v) in enumerate(vectors().items(), 1):
        files[os.path.join("packs", FMT, "vectors", "%02d-%s.json" % (i, name))] = json.dumps(v, indent=2) + "\n"
    bad = 0
    for rel, text in files.items():
        path = os.path.join(gt, rel)
        if check:
            cur = open(path, encoding="utf-8").read() if os.path.exists(path) else None
            if cur != text:
                print("differs: " + rel)
                bad += 1
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    if check:
        print("igsssr2pack: %s" % ("ok" if not bad else "%d differ" % bad))
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
