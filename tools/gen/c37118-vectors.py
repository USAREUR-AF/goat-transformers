#!/usr/bin/env python3
"""Derive the vectors of the c37118-* packs without an engine.

Python 3 standard library only; imports nothing from engines/ and does not read
the packs. Each frame is built with struct from this program's own statement of
the frame layout that pypmu (https://github.com/iicsys/pypmu, BSD-3-Clause)
writes, an implementation of IEEE C37.118.2-2011:

  SYNC     0xAA, then a reserved bit, the frame type (3 bits), the version (4 bits)
  FRAMESIZE, IDCODE (u16); SOC (u32); FRACSEC: flags and time quality (u8), fraction (24 bits)
  the body of the frame type
  CHK      CRC-CCITT, polynomial 0x1021, initial value 0xFFFF, over every byte before it

All values are chosen here; no sample frame of the standard or of pypmu is used.

Usage:
  python3 -I tools/gen/c37118-vectors.py <checkout>           write the vectors
  python3 -I tools/gen/c37118-vectors.py <checkout> --check   exit 1 when a file differs
"""
import json
import os
import struct
import sys

SOURCE = "derived by tools/gen/c37118-vectors.py from the layout pypmu writes; no engine run"
REF = "pypmu commit 66e6c495a91e synchrophasor/frame.py (CommonFrame, DataFrame, ConfigFrame1/2, CommandFrame)"


def crc_ccitt(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def frame(ftype, idcode, soc, frac, tq, body, version=1, leap=(0, 0, 0)):
    flags = (leap[0] << 6) | (leap[1] << 5) | (leap[2] << 4) | tq
    size = 16 + len(body)
    b = struct.pack(">BBHHII", 0xAA, (ftype << 4) | version, size, idcode, soc, (flags << 24) | frac) + body
    return b + struct.pack(">H", crc_ccitt(b))


def f32(x):
    return struct.unpack(">f", struct.pack(">f", x))[0]


def num(x):
    if isinstance(x, float) and x.is_integer():
        return repr(x)
    return repr(x)


def header_model(idcode, soc, frac, tq, version=1, leap=(0, 0, 0)):
    m = {"c37118.version": str(version), "c37118.idcode": str(idcode), "c37118.soc": str(soc),
         "c37118.leap_direction": str(leap[0]), "c37118.leap_occurred": str(leap[1]),
         "c37118.leap_pending": str(leap[2]), "c37118.time_quality": str(tq), "c37118.fracsec": str(frac)}
    return m


def stat(err=0, sync_lost=0, arrival=0, trig=0, cfgchg=0, mod=0, tq=0, unl=0, reason=0):
    return (err << 14) | (sync_lost << 13) | (arrival << 12) | (trig << 11) | (cfgchg << 10) | (mod << 9) | \
        (tq << 6) | (unl << 4) | reason


def vec(name, frm, inp, expect=None, error=None, model=None, ref=""):
    v = {"name": name, "from": frm, "to": frm, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = REF + ("; " + ref if ref else "")
    return v


SOC = 1763640000          # 2025-11-20T12:00:00Z


def data_a():
    p = "c37118-data-4ph-int-rect"
    ph = [(12000, 0), (-6000, -10392), (-6000, 10392), (900, -50)]
    an = [1.5, 230.25, -0.125]
    st = stat(tq=0, unl=0)
    body = struct.pack(">H", st) + b"".join(struct.pack(">hh", r, i) for r, i in ph) + \
        struct.pack(">hh", -15, 25) + b"".join(struct.pack(">f", a) for a in an) + struct.pack(">H", 0x00F0)
    fr = frame(0, 4321, SOC, 500000, 5, body)
    assert len(fr) == 52
    m = header_model(4321, SOC, 500000, 5)
    m.update({"@kind": "data", "c37118.phasors.#": "4", "c37118.phasors[1].c37118.phasor_real": "-6000",
              "c37118.phasors[1].c37118.phasor_imag": "-10392", "c37118.freq_dev_mhz": "-15",
              "c37118.rocof_hzs": "0.25", "c37118.analogs.#": "3", "c37118.analogs[1].c37118.analog_value": "230.25",
              "c37118.digital": "240", "c37118.stat_data_error": "0", "c37118.chk": str(struct.unpack(">H", fr[-2:])[0]),
              "@absent": ["time_ms", "lat", "lon", "time_error_ms"]})
    out = {"01-data-roundtrip": vec("data-roundtrip", p, fr, fr, model=m,
                                    ref="4 integer rectangular phasors, 3 floating-point analogs, integer frequency and "
                                        "rate of change (100 times Hz/s), one digital word; time quality 5 stays a raw code")}
    st2 = stat(err=2, sync_lost=1, arrival=1, trig=1, cfgchg=1, mod=1, tq=7, unl=3, reason=15)
    body2 = struct.pack(">H", st2) + body[2:]
    fr2 = frame(0, 65535, 0, 16777215, 0, body2, version=2, leap=(1, 1, 1))
    m2 = header_model(65535, 0, 16777215, 0, version=2, leap=(1, 1, 1))
    m2.update({"@kind": "data", "c37118.stat_data_error": "2", "c37118.stat_sync_lost": "1",
               "c37118.stat_sorted_arrival": "1", "c37118.stat_trigger": "1", "c37118.stat_config_change": "1",
               "c37118.stat_data_modified": "1", "c37118.stat_time_quality": "7", "c37118.stat_unlocked_time": "3",
               "c37118.stat_trigger_reason": "15", "@absent": ["time_error_ms", "time_utc_error_ms"]})
    out["02-data-every-flag-roundtrip"] = vec("data-every-flag-roundtrip", p, fr2, fr2, model=m2,
                                              ref="version 2, every STAT and leap flag set, the largest fraction; "
                                                  "time quality 0 (locked) as a raw code")
    out["03-other-config-size-is-no-kind"] = vec(
        "other-config-size-is-no-kind", p, frame(0, 4321, SOC, 0, 0, body + b"\0\0\0\0"), error="no-kind",
        ref="a data frame of another configuration (56 bytes) is not this pack's")
    out["04-truncated-is-malformed"] = vec("truncated-is-malformed", p, fr[:40], error="malformed-wire",
                                           ref="the frame cut inside its analog values")
    bad = bytes([0xAB]) + fr[1:]
    out["05-bad-sync-is-no-kind"] = vec("bad-sync-is-no-kind", p, bad, error="no-kind", ref="SYNC starts with 0xAA")
    return p, out


def data_b():
    p = "c37118-data-3ph-float-polar"
    ph = [(230.5, 0.5), (230.25, -1.5), (229.75, 2.625)]
    body = struct.pack(">H", stat()) + b"".join(struct.pack(">ff", mg, an) for mg, an in ph) + \
        struct.pack(">ff", 49.9921875, -0.03125) + struct.pack(">f", 12.5) + struct.pack(">H", 1)
    fr = frame(0, 1410, SOC + 1, 250000, 9, body)
    assert len(fr) == 56
    m = header_model(1410, SOC + 1, 250000, 9)
    m.update({"@kind": "data", "c37118.phasors.#": "3", "c37118.phasors[2].c37118.phasor_magnitude": "229.75",
              "c37118.phasors[2].c37118.phasor_angle": "2.625", "c37118.freq_hz": "49.9921875",
              "c37118.rocof_hzs": "-0.03125", "c37118.analogs[0].c37118.analog_value": "12.5", "c37118.digital": "1"})
    return p, {"01-data-roundtrip": vec("data-roundtrip", p, fr, fr, model=m,
                                        ref="3 floating-point polar phasors (magnitude, angle in radians), frequency "
                                            "and rate of change in floating point, one analog, one digital word; "
                                            "time quality 9 as a raw code")}


def command():
    p = "c37118-command"
    out = {}
    for i, (cmd, tq) in enumerate(((2, 0), (5, 4)), 1):
        fr = frame(4, 4321, SOC, 0, tq, struct.pack(">H", cmd))
        m = header_model(4321, SOC, 0, tq)
        m.update({"@kind": "command", "c37118.command": str(cmd)})
        out["%02d-command-%d-roundtrip" % (i, cmd)] = vec("command-%d-roundtrip" % cmd, p, fr, fr, model=m,
                                                         ref="command %d, no extended data: 18 bytes" % cmd)
    ext = frame(4, 4321, SOC, 0, 0, struct.pack(">H", 8) + b"\x01\x02")
    out["03-extended-command-is-no-kind"] = vec("extended-command-is-no-kind", p, ext, error="no-kind",
                                                ref="an extended frame (command 8 with data) is longer than 18 bytes")
    return p, out


def text16(s):
    return s.encode("ascii").ljust(16, b" ")


def config(p, nph, nan, ndg, fmt, phunits, anunits, names, station, rate):
    out = {}
    body_tail = struct.pack(">HHHHH", 4321, fmt, nph, nan, ndg) + b"".join(text16(n) for n in names) + \
        b"".join(struct.pack(">I", (t << 24) | s) for t, s in phunits) + \
        b"".join(struct.pack(">I", (t << 24) | (s & 0xFFFFFF)) for t, s in anunits) + \
        struct.pack(">HH", 0x0000, 0xFFFF) + struct.pack(">HHh", 1, 3, rate)
    body = struct.pack(">IH", 1000000, 1) + text16(station) + body_tail
    for i, (kind, ftype) in enumerate((("cfg2", 3), ("cfg1", 2)), 1):
        fr = frame(ftype, 4321, SOC, 0, 4, body)
        m = header_model(4321, SOC, 0, 4)
        m.update({"@kind": kind, "c37118.time_base": "1000000", "c37118.station_name": text16(station).decode(),
                  "c37118.pmu_idcode": "4321", "c37118.data_format": str(fmt), "c37118.channel_names.#": str(len(names)),
                  "c37118.channel_names[0].c37118.channel_name": text16(names[0]).decode(),
                  "c37118.channel_names[%d].c37118.channel_name" % (len(names) - 1): text16(names[-1]).decode(),
                  "c37118.phasor_units[%d].c37118.phasor_unit_type" % (nph - 1): str(phunits[-1][0]),
                  "c37118.phasor_units[0].c37118.phasor_unit_scale": str(phunits[0][1]),
                  "c37118.analog_units[0].c37118.analog_unit_scale": str(anunits[0][1]),
                  "c37118.digital_units[0].c37118.digital_valid_mask": "65535",
                  "c37118.fnom_50hz": "1", "c37118.config_count": "3", "c37118.data_rate": str(rate)})
        out["%02d-%s-roundtrip" % (i, kind)] = vec(
            "%s-roundtrip" % kind, p, fr, fr, model=m,
            ref="configuration frame %s of one PMU: %d phasors, %d analogs, %d digital word, %d channel names, "
                "50 Hz nominal, data rate %d" % (kind[-1], nph, nan, ndg, len(names), rate))
    two = frame(3, 4321, SOC, 0, 4, struct.pack(">IH", 1000000, 2) + text16(station) + body_tail)
    out["03-two-pmus-is-no-kind"] = vec("two-pmus-is-no-kind", p, two, error="no-kind",
                                        ref="NUM_PMU 2: the layout of a second PMU follows; this pack holds one")
    return p, out


def config_a():
    names = ["VA", "VB", "VC", "IA", "P", "Q", "F"] + ["BRK%d" % n for n in range(1, 17)]
    return config("c37118-config-4ph-int-rect", 4, 3, 1, 4, [(0, 800000), (0, 800000), (0, 800000), (1, 45000)],
                  [(0, 1), (1, 10), (2, -3)], names, "Grid West", 50)


def config_b():
    names = ["VA", "VB", "VC", "TEMP"] + ["IN%02d" % n for n in range(1, 17)]
    return config("c37118-config-3ph-float-polar", 3, 1, 1, 15, [(0, 0), (0, 0), (0, 0)], [(1, -1)], names,
                  "Bay 7", -5)


def main():
    gt = sys.argv[1]
    check = "--check" in sys.argv[2:]
    bad = 0
    for fn in (data_a, data_b, command, config_a, config_b):
        p, vs = fn()
        d = os.path.join(gt, "packs", p, "vectors")
        for name, v in vs.items():
            path = os.path.join(d, name + ".json")
            text = json.dumps(v, indent=2) + "\n"
            if check:
                cur = open(path, encoding="utf-8").read() if os.path.exists(path) else None
                if cur != text:
                    print("differs: " + os.path.relpath(path, gt))
                    bad += 1
            else:
                os.makedirs(d, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
    if check:
        print("c37118-vectors: %s" % ("ok" if not bad else "%d differ" % bad))
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
