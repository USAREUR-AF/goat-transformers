#!/usr/bin/env python3
"""ccsds-vectors: write the conversion vectors of the five CCSDS bits packs.

Python 3 standard library only; imports no engine and does not read any pack.def.
The layouts below are written from the CCSDS Blue Books (section numbers in each
table), in this program's own terms: (model key, first bit, bit count), bits
numbered from 0 at the first transmitted bit of the header, most significant bit
first (each Blue Book, section 1.6, bit numbering convention). A header is packed
from those tables by `pack()` and the expected hex of every vector is that result.

  packs/ccsds-space-packet/vectors/*.json   CCSDS 133.0-B-2, 4.1.3
  packs/ccsds-tm-frame/vectors/*.json       CCSDS 132.0-B-3, 4.1.2 and 4.1.3.2
  packs/ccsds-tc-frame/vectors/*.json       CCSDS 232.0-B-4, 4.1.2
  packs/ccsds-aos-frame/vectors/*.json      CCSDS 732.0-B-4, 4.1.2
  packs/ccsds-clcw/vectors/*.json           CCSDS 232.0-B-4, 4.2.1

Usage: python3 -I tools/gen/ccsds-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.
Every *.json in those five vectors directories is rewritten.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

# ---- layouts: (key, first bit, bits); constants are (None, first bit, bits, value)

SPACE_PACKET = [            # 133.0-B-2 4.1.3: 48 bits
    (None, 0, 3, 0),        # 4.1.3.2 packet version number '000'
    ("ccsdssp.packet_type", 3, 1),
    ("ccsdssp.secondary_header_flag", 4, 1),
    ("ccsdssp.apid", 5, 11),
    ("ccsdssp.sequence_flags", 16, 2),
    ("@seq", 18, 14),       # 4.1.3.4.3: count (type 0) or count or name (type 1)
    ("ccsdssp.data_length", 32, 16),
]
TM_PRIMARY = [              # 132.0-B-3 4.1.2: 48 bits
    (None, 0, 2, 0),        # 4.1.2.2.2 transfer frame version number '00'
    ("ccsdstm.spacecraft_id", 2, 10),
    ("ccsdstm.virtual_channel_id", 12, 3),
    ("ccsdstm.ocf_flag", 15, 1),
    ("ccsdstm.mc_frame_count", 16, 8),
    ("ccsdstm.vc_frame_count", 24, 8),
    ("ccsdstm.secondary_header_flag", 32, 1),
    ("ccsdstm.sync_flag", 33, 1),
    ("ccsdstm.packet_order_flag", 34, 1),
    ("ccsdstm.segment_length_id", 35, 2),
    ("ccsdstm.first_header_pointer", 37, 11),
]
TM_SECONDARY_ID = [         # 132.0-B-3 4.1.3.2: the first octet after the primary header
    ("ccsdstm.secondary_header_version", 48, 2),
    ("ccsdstm.secondary_header_length", 50, 6),
]
TC_PRIMARY = [              # 232.0-B-4 4.1.2: 40 bits
    (None, 0, 2, 0),        # 4.1.2.2 transfer frame version number '00'
    ("ccsdstc.bypass_flag", 2, 1),
    ("ccsdstc.control_command_flag", 3, 1),
    ("@spare", 4, 2),       # 4.1.2.4 reserved spare, '00'
    ("ccsdstc.spacecraft_id", 6, 10),
    ("ccsdstc.virtual_channel_id", 16, 6),
    ("ccsdstc.frame_length", 22, 10),
    ("ccsdstc.frame_sequence_number", 32, 8),
]
AOS_PRIMARY = [             # 732.0-B-4 4.1.2: 48 bits
    (None, 0, 2, 1),        # 4.1.2.2.2 transfer frame version number '01'
    ("ccsdsaos.spacecraft_id", 2, 8),
    ("ccsdsaos.virtual_channel_id", 10, 6),
    ("ccsdsaos.vc_frame_count", 16, 24),
    ("ccsdsaos.replay_flag", 40, 1),
    ("ccsdsaos.vc_count_cycle_use_flag", 41, 1),
    ("@spare", 42, 2),      # 4.1.2.5.4 reserved spare, '00'
    ("ccsdsaos.vc_count_cycle", 44, 4),
]
CLCW = [                    # 232.0-B-4 4.2.1: 32 bits
    ("@type", 0, 1),        # 4.2.1.2 control word type, '0'
    ("@version", 1, 2),     # 4.2.1.3 CLCW version number, '00'
    ("ccsdsclcw.status_field", 3, 3),
    ("ccsdsclcw.cop_in_effect", 6, 2),
    ("ccsdsclcw.virtual_channel_id", 8, 6),
    ("@spare14", 14, 2),    # 4.2.1.7 reserved spare
    ("ccsdsclcw.no_rf_available", 16, 1),
    ("ccsdsclcw.no_bit_lock", 17, 1),
    ("ccsdsclcw.lockout", 18, 1),
    ("ccsdsclcw.wait", 19, 1),
    ("ccsdsclcw.retransmit", 20, 1),
    ("ccsdsclcw.farm_b_counter", 21, 2),
    ("@spare23", 23, 1),    # 4.2.1.10 reserved spare
    ("ccsdsclcw.report_value", 24, 8),
]


def pack(layout, values, nbits):
    """Big-endian bit packing: bit 0 is the most significant bit of octet 0."""
    acc = 0
    for item in layout:
        key, first, width = item[0], item[1], item[2]
        v = item[3] if key is None else values.get(key, 0)
        if not 0 <= v < (1 << width):
            raise ValueError("%s=%d does not fit %d bits" % (key, v, width))
        acc |= v << (nbits - first - width)
    return acc.to_bytes(nbits // 8, "big").hex()


def version_override(layout, version):
    return [(None, it[1], it[2], version) if it[0] is None and it[1] == 0 else it for it in layout]


def model_of(values, keys):
    return {k: str(values[k]) for k in keys if k in values and not k.startswith("@")}


def vec(name, fmt, inp, expect=None, error=None, model=None, ref=""):
    v = {"name": name, "from": fmt, "to": fmt, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = ref
    return v


# ---- Space Packet --------------------------------------------------------------

def space_packet():
    fmt, out = "ccsds-space-packet", []
    ref = "CCSDS 133.0-B-2 4.1.3; bytes computed by tools/gen/ccsds-vectors.py"
    keys = [k[0] for k in SPACE_PACKET if k[0]]

    def hdr(v):
        return pack(SPACE_PACKET, v, 48)

    def mdl(v, kind):
        m = {"@kind": kind}
        m.update(model_of(v, keys))
        if kind == "telemetry":
            m["ccsdssp.sequence_count"] = str(v["@seq"])
        else:
            m["ccsdssp.sequence_count_or_name"] = str(v["@seq"])
        return m

    tm = {"ccsdssp.packet_type": 0, "ccsdssp.secondary_header_flag": 1, "ccsdssp.apid": 100,
          "ccsdssp.sequence_flags": 3, "@seq": 1234, "ccsdssp.data_length": 9}
    out.append(vec("telemetry-header-roundtrip", fmt, hdr(tm), hdr(tm), model=mdl(tm, "telemetry"),
                   ref=ref + ". The input is the primary header alone: the pack's message is the header."))
    tc = {"ccsdssp.packet_type": 1, "ccsdssp.secondary_header_flag": 0, "ccsdssp.apid": 1365,
          "ccsdssp.sequence_flags": 1, "@seq": 10922, "ccsdssp.data_length": 0}
    out.append(vec("telecommand-header-roundtrip", fmt, hdr(tc), hdr(tc), model=mdl(tc, "telecommand"),
                   ref=ref + ". Type 1, first segment; the 14 bits after the flags are a packet name here "
                             "(alternating bits, 0x2aaa)."))
    data = bytes(range(1, 11)).hex()            # data_length 9 -> 10 octets
    out.append(vec("telemetry-packet-data-field-not-carried", fmt, hdr(tm) + data, hdr(tm),
                   model=mdl(tm, "telemetry"),
                   ref=ref + ". A whole packet with a 10-octet data field (data_length 9): decode ignores "
                             "the octets after the header and encode writes the header only."))
    idle = {"ccsdssp.packet_type": 0, "ccsdssp.secondary_header_flag": 0, "ccsdssp.apid": 2047,
            "ccsdssp.sequence_flags": 3, "@seq": 0, "ccsdssp.data_length": 3}
    out.append(vec("idle-packet", fmt, hdr(idle) + "55555555", hdr(idle), model=mdl(idle, "telemetry"),
                   ref=ref + ". Idle packet: APID all ones (4.1.3.3.4.4), no secondary header (4.1.3.3.3.4); "
                             "a 4-octet idle pattern the mission would choose."))
    top = {"ccsdssp.packet_type": 0, "ccsdssp.secondary_header_flag": 1, "ccsdssp.apid": 2046,
           "ccsdssp.sequence_flags": 0, "@seq": 16383, "ccsdssp.data_length": 65535}
    out.append(vec("largest-count-and-length", fmt, hdr(top), hdr(top), model=mdl(top, "telemetry"),
                   ref=ref + ". Sequence count 16383 (the last before it wraps, 4.1.3.4.3.4) and data "
                             "length 65535 (a 65536-octet data field, 4.1.2.1)."))
    v1 = pack(version_override(SPACE_PACKET, 1), tm, 48)
    out.append(vec("version-not-000-is-no-kind", fmt, v1, error="no-kind",
                   ref=ref + ". Packet version number 001: not a packet of this standard (4.1.3.2.2)."))
    out.append(vec("header-cut-short", fmt, hdr(tm)[:10], error="malformed-wire",
                   ref=ref + ". Five octets: shorter than the 6-octet primary header."))
    return fmt, out


# ---- TM Transfer Frame ---------------------------------------------------------

def tm_frame():
    fmt, out = "ccsds-tm-frame", []
    ref = "CCSDS 132.0-B-3 4.1.2 and 4.1.3.2; bytes computed by tools/gen/ccsds-vectors.py"
    pkeys = [k[0] for k in TM_PRIMARY if k[0]]
    skeys = [k[0] for k in TM_SECONDARY_ID]

    def hdr(v):
        return pack(TM_PRIMARY, v, 48)

    def hdr_sh(v):
        return pack(TM_PRIMARY + TM_SECONDARY_ID, v, 56)

    base = {"ccsdstm.spacecraft_id": 677, "ccsdstm.virtual_channel_id": 5, "ccsdstm.ocf_flag": 1,
            "ccsdstm.mc_frame_count": 200, "ccsdstm.vc_frame_count": 17,
            "ccsdstm.secondary_header_flag": 0, "ccsdstm.sync_flag": 0, "ccsdstm.packet_order_flag": 0,
            "ccsdstm.segment_length_id": 3, "ccsdstm.first_header_pointer": 0}
    m = {"@kind": "primary-header"}
    m.update(model_of(base, pkeys))
    out.append(vec("primary-header-roundtrip", fmt, hdr(base), hdr(base), model=m,
                   ref=ref + ". No secondary header; packets in octets (sync flag 0, segment length id 3, "
                             "4.1.2.7.5.2); a packet starts at the first octet of the data field."))
    sh = dict(base, **{"ccsdstm.secondary_header_flag": 1, "ccsdstm.secondary_header_version": 0,
                       "ccsdstm.secondary_header_length": 3, "ccsdstm.first_header_pointer": 12})
    msh = {"@kind": "with-secondary-header"}
    msh.update(model_of(sh, pkeys + skeys))
    out.append(vec("with-secondary-header-roundtrip", fmt, hdr_sh(sh), hdr_sh(sh), model=msh,
                   ref=ref + ". Secondary header flag 1, so the next octet is the secondary header "
                             "identification: version 00, length 3 (4 octets in all)."))
    # a whole frame: primary header, 4-octet secondary header, 20-octet data field,
    # 4-octet operational control field, 2-octet frame error control field
    frame = (hdr_sh(sh) + "a1b2c3" + bytes(range(0x30, 0x44)).hex() + "01020304" + "beef")
    out.append(vec("whole-frame-only-headers-carried", fmt, frame, hdr_sh(sh), model=msh,
                   ref=ref + ". A whole frame (4.1.1.1): the secondary header data, the data field, the "
                             "operational control field and the frame error control field are not mapped; "
                             "encode writes the 7 mapped octets. The error control value here is not a "
                             "computed CRC: the pack does not read it."))
    top = dict(base, **{"ccsdstm.spacecraft_id": 1023, "ccsdstm.virtual_channel_id": 7,
                        "ccsdstm.ocf_flag": 0, "ccsdstm.mc_frame_count": 255,
                        "ccsdstm.vc_frame_count": 255, "ccsdstm.first_header_pointer": 2047})
    mt = {"@kind": "primary-header"}
    mt.update(model_of(top, pkeys))
    out.append(vec("no-packet-starts-and-largest-values", fmt, hdr(top), hdr(top), model=mt,
                   ref=ref + ". First header pointer all ones: no packet starts in this frame "
                             "(4.1.2.7.6.4); identifiers and counts at their largest values."))
    oid = dict(base, **{"ccsdstm.virtual_channel_id": 7, "ccsdstm.first_header_pointer": 2046})
    mo = {"@kind": "primary-header"}
    mo.update(model_of(oid, pkeys))
    out.append(vec("only-idle-data-frame", fmt, hdr(oid), hdr(oid), model=mo,
                   ref=ref + ". First header pointer 11111111110: only idle data in the data field "
                             "(4.1.2.7.6.5)."))
    vcda = dict(base, **{"ccsdstm.sync_flag": 1, "ccsdstm.packet_order_flag": 1,
                         "ccsdstm.segment_length_id": 0, "ccsdstm.first_header_pointer": 1365})
    mv = {"@kind": "primary-header"}
    mv.update(model_of(vcda, pkeys))
    out.append(vec("sync-flag-1-fields-carried-as-they-are", fmt, hdr(vcda), hdr(vcda), model=mv,
                   ref=ref + ". Sync flag 1 (a VCA_SDU in the data field): the packet order flag, segment "
                             "length identifier and first header pointer are undefined (4.1.2.7.4, "
                             "4.1.2.7.5, 4.1.2.7.6) and are carried as the wire holds them."))
    aos_like = pack(version_override(TM_PRIMARY, 1), base, 48)
    out.append(vec("version-01-is-no-kind", fmt, aos_like, error="no-kind",
                   ref=ref + ". Version number 01 is an AOS frame (CCSDS 732.0-B-4), not a TM frame "
                             "(4.1.2.2.2.2)."))
    out.append(vec("secondary-header-flag-set-header-only", fmt, hdr(sh), error="malformed-wire",
                   ref=ref + ". Secondary header flag 1, but the input ends after the primary header: the "
                             "kind's identification octet is missing."))
    out.append(vec("header-cut-short", fmt, hdr(base)[:10], error="malformed-wire",
                   ref=ref + ". Five octets: shorter than the 6-octet primary header."))
    return fmt, out


# ---- TC Transfer Frame ---------------------------------------------------------

def tc_frame():
    fmt, out = "ccsds-tc-frame", []
    ref = "CCSDS 232.0-B-4 4.1.2; bytes computed by tools/gen/ccsds-vectors.py"
    keys = [k[0] for k in TC_PRIMARY if k[0] and not k[0].startswith("@")]

    def hdr(v):
        return pack(TC_PRIMARY, v, 40)

    def mdl(v):
        m = {"@kind": "frame"}
        m.update(model_of(v, keys))
        return m

    ad = {"ccsdstc.bypass_flag": 0, "ccsdstc.control_command_flag": 0, "ccsdstc.spacecraft_id": 427,
          "ccsdstc.virtual_channel_id": 9, "ccsdstc.frame_length": 26, "ccsdstc.frame_sequence_number": 42}
    out.append(vec("type-ad-header-roundtrip", fmt, hdr(ad), hdr(ad), model=mdl(ad),
                   ref=ref + ". Bypass 0, control command 0: a type-AD frame (table 4-1). Frame length 26: "
                             "a 27-octet frame."))
    bc = {"ccsdstc.bypass_flag": 1, "ccsdstc.control_command_flag": 1, "ccsdstc.spacecraft_id": 1023,
          "ccsdstc.virtual_channel_id": 63, "ccsdstc.frame_length": 1023,
          "ccsdstc.frame_sequence_number": 255}
    out.append(vec("type-bc-largest-values", fmt, hdr(bc), hdr(bc), model=mdl(bc),
                   ref=ref + ". A type-BC frame (table 4-1) with every identifier and count at its largest "
                             "value; frame length 1023 is a 1024-octet frame (4.1.2.7.2)."))
    # whole frame: 5-octet header, 20-octet data field, 2-octet error control: 27 octets
    frame = hdr(ad) + bytes(range(0x40, 0x54)).hex() + "c0de"
    assert len(frame) // 2 == ad["ccsdstc.frame_length"] + 1
    out.append(vec("whole-frame-header-carried", fmt, frame, hdr(ad), model=mdl(ad),
                   ref=ref + ". A whole 27-octet frame: the data field and the frame error control field "
                             "are not mapped; encode writes the 5 header octets. The error control value is "
                             "not a computed CRC: the pack does not read it."))
    spare = pack(TC_PRIMARY, dict(ad, **{"@spare": 3}), 40)
    out.append(vec("reserved-spare-written-as-zero", fmt, spare, hdr(ad), model=mdl(ad),
                   ref=ref + ". The reserved spare bits 4-5 are 11 on the input; the pack does not map them, "
                             "so encode writes them as 00, the value 4.1.2.4.2 requires."))
    v1 = pack(version_override(TC_PRIMARY, 1), ad, 40)
    out.append(vec("version-not-00-is-no-kind", fmt, v1, error="no-kind",
                   ref=ref + ". Version number 01: not a TC frame of this standard (4.1.2.2.2)."))
    out.append(vec("header-cut-short", fmt, hdr(ad)[:8], error="malformed-wire",
                   ref=ref + ". Four octets: shorter than the 5-octet primary header."))
    return fmt, out


# ---- AOS Transfer Frame --------------------------------------------------------

def aos_frame():
    fmt, out = "ccsds-aos-frame", []
    ref = "CCSDS 732.0-B-4 4.1.2; bytes computed by tools/gen/ccsds-vectors.py"
    keys = [k[0] for k in AOS_PRIMARY if k[0] and not k[0].startswith("@")]

    def hdr(v):
        return pack(AOS_PRIMARY, v, 48)

    def mdl(v):
        m = {"@kind": "frame"}
        m.update(model_of(v, keys))
        return m

    a = {"ccsdsaos.spacecraft_id": 180, "ccsdsaos.virtual_channel_id": 12, "ccsdsaos.vc_frame_count": 74565,
         "ccsdsaos.replay_flag": 0, "ccsdsaos.vc_count_cycle_use_flag": 1, "ccsdsaos.vc_count_cycle": 9}
    out.append(vec("header-roundtrip", fmt, hdr(a), hdr(a), model=mdl(a),
                   ref=ref + ". Realtime frame, frame count 0x012345, the count cycle in use."))
    top = {"ccsdsaos.spacecraft_id": 255, "ccsdsaos.virtual_channel_id": 63,
           "ccsdsaos.vc_frame_count": 16777215, "ccsdsaos.replay_flag": 1,
           "ccsdsaos.vc_count_cycle_use_flag": 1, "ccsdsaos.vc_count_cycle": 15}
    out.append(vec("idle-channel-largest-values", fmt, hdr(top), hdr(top), model=mdl(top),
                   ref=ref + ". Virtual channel all ones (only idle data, 4.1.2.3 note 1), replay, and every "
                             "count at its largest value."))
    # whole frame: header, 2-octet frame header error control, 24-octet data field, 2-octet FECF
    frame = hdr(a) + "1234" + bytes(range(0x60, 0x78)).hex() + "f00d"
    out.append(vec("whole-frame-header-carried", fmt, frame, hdr(a), model=mdl(a),
                   ref=ref + ". A frame with the optional frame header error control (4.1.2.6), a data "
                             "field and a frame error control field: none is mapped; encode writes the 6 "
                             "header octets. The two check values are not computed codes."))
    spare = pack(AOS_PRIMARY, dict(a, **{"@spare": 3}), 48)
    out.append(vec("reserved-spare-written-as-zero", fmt, spare, hdr(a), model=mdl(a),
                   ref=ref + ". Signaling field spare bits 42-43 are 11 on the input; the pack does not map "
                             "them, so encode writes 00, the value 4.1.2.5.4.2 requires."))
    tm_like = pack(version_override(AOS_PRIMARY, 0), a, 48)
    out.append(vec("version-00-is-no-kind", fmt, tm_like, error="no-kind",
                   ref=ref + ". Version number 00 is a TM or TC frame, not an AOS frame (4.1.2.2.2.2)."))
    out.append(vec("header-cut-short", fmt, hdr(a)[:10], error="malformed-wire",
                   ref=ref + ". Five octets: shorter than the 6-octet primary header."))
    return fmt, out


# ---- CLCW ----------------------------------------------------------------------

def clcw():
    fmt, out = "ccsds-clcw", []
    ref = "CCSDS 232.0-B-4 4.2.1; bytes computed by tools/gen/ccsds-vectors.py"
    keys = [k[0] for k in CLCW if not k[0].startswith("@")]

    def word(v):
        return pack(CLCW, v, 32)

    def mdl(v):
        m = {"@kind": "clcw"}
        m.update(model_of(v, keys))
        return m

    zero_flags = {"ccsdsclcw.no_rf_available": 0, "ccsdsclcw.no_bit_lock": 0, "ccsdsclcw.lockout": 0,
                  "ccsdsclcw.wait": 0, "ccsdsclcw.retransmit": 0}
    n = dict(zero_flags, **{"ccsdsclcw.status_field": 0, "ccsdsclcw.cop_in_effect": 1,
                            "ccsdsclcw.virtual_channel_id": 3, "ccsdsclcw.farm_b_counter": 2,
                            "ccsdsclcw.report_value": 123})
    out.append(vec("nominal-roundtrip", fmt, word(n), word(n), model=mdl(n),
                   ref=ref + ". COP-1 in effect (4.2.1.5.2), no flag set, next expected frame number 123."))
    s = {"ccsdsclcw.status_field": 7, "ccsdsclcw.cop_in_effect": 1, "ccsdsclcw.virtual_channel_id": 63,
         "ccsdsclcw.no_rf_available": 1, "ccsdsclcw.no_bit_lock": 1, "ccsdsclcw.lockout": 1,
         "ccsdsclcw.wait": 1, "ccsdsclcw.retransmit": 1, "ccsdsclcw.farm_b_counter": 3,
         "ccsdsclcw.report_value": 255}
    out.append(vec("every-flag-set", fmt, word(s), word(s), model=mdl(s),
                   ref=ref + ". Every flag 1 and every field at its largest value."))
    t1 = pack(CLCW, dict(n, **{"@type": 1}), 32)
    out.append(vec("control-word-type-1-is-no-kind", fmt, t1, error="no-kind",
                   ref=ref + ". Control word type 1 is another kind of report in the operational control "
                             "field, not a CLCW (4.2.1.2)."))
    v1 = pack(CLCW, dict(n, **{"@version": 1}), 32)
    out.append(vec("version-not-00-is-no-kind", fmt, v1, error="no-kind",
                   ref=ref + ". CLCW version number 01: not defined by this standard (4.2.1.3.2)."))
    out.append(vec("word-cut-short", fmt, word(n)[:6], error="malformed-wire",
                   ref=ref + ". Three octets: shorter than the 4-octet word."))
    return fmt, out


def build(out):
    written = {}
    for make in (space_packet, tm_frame, tc_frame, aos_frame, clcw):
        fmt, vecs = make()
        vdir = "packs/%s/vectors" % fmt
        assert len({v["name"] for v in vecs}) == len(vecs), fmt
        names = set()
        for i, v in enumerate(vecs, 1):
            rel = "%s/%02d-%s.json" % (vdir, i, v["name"])
            names.add(rel.rsplit("/", 1)[1])
            out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        for old in out.listdir(vdir):
            if old.endswith(".json") and old not in names:
                out.remove(vdir + "/" + old)
        written[fmt] = len(vecs)
    return written


def main(argv=None):
    return genio.vector_main("ccsds-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
