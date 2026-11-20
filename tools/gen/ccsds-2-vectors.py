#!/usr/bin/env python3
"""ccsds-2-vectors: write the conversion vectors of the CCSDS USLP, CFDP and
Proximity-1 bits packs.

Python 3 standard library only; imports no engine and does not read any pack.def.
The layouts below are written from the CCSDS Blue Books (section numbers in each
table), in this program's own terms: (model key, first bit, bit count), bits
numbered from 0 at the first transmitted bit, most significant bit first (each
Blue Book's bit numbering convention). A header is packed from those tables by
`pack()` and the expected hex of every vector is that result.

  packs/ccsds-uslp-frame/vectors/*.json    CCSDS 732.1-B-3, 4.1.2 and annex D
  packs/ccsds-cfdp-pdu/vectors/*.json      CCSDS 727.0-B-5, 5.1 and 5.2.1
  packs/ccsds-prox1-frame/vectors/*.json   CCSDS 211.0-B-6, 3.2.2

Inputs are headers built here from values chosen here; no example frame or PDU
of a Blue Book is used. Bytes after the mapped header (data field, trailers,
directive parameters) are read over by the packs and not written: those
vectors expect the header alone.

Usage: python3 -I tools/gen/ccsds-2-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.
Every *.json in those three vectors directories is rewritten.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402


def pack(layout, values):
    """layout: [(key or None, bits[, constant])] in wire order; big-endian, bit 0
    the most significant bit of octet 0. A key absent from values is 0."""
    nbits = sum(it[1] for it in layout)
    assert nbits % 8 == 0, nbits
    acc = 0
    for it in layout:
        key, width = it[0], it[1]
        v = it[2] if key is None else values.get(key, 0)
        if not 0 <= v < (1 << width):
            raise ValueError("%s=%d does not fit %d bits" % (key, v, width))
        acc = (acc << width) | v
    return acc.to_bytes(nbits // 8, "big")


def signed64(v, width):
    """The model integer of an unsigned field: a 64-bit field whose top bit is set
    is the negative integer with the same bits (engine-spec 0.5, ruling 2)."""
    return v - (1 << 64) if width == 64 and v >= 1 << 63 else v


def model_of(values, keys, kind=None, prefix=""):
    m = {"@kind": kind} if kind else {}
    for k in keys:
        m[prefix + k] = str(values.get(k, 0))
    return m


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


# ---- USLP Transfer Frame, 732.1-B-3 4.1.2 ----------------------------------------

USLP_COMMON = [(None, 4, 12), ("spacecraft_id", 16), ("source_dest_id", 1), ("virtual_channel_id", 6),
               ("map_id", 4)]
USLP_REST = [("frame_length", 16), ("bypass_flag", 1), ("protocol_control_command_flag", 1),
             ("reserve_spares", 2), ("ocf_flag", 1), ("vcf_count_length", 3)]
USLP_COMMON_KEYS = ["spacecraft_id", "source_dest_id", "virtual_channel_id", "map_id"]
USLP_REST_KEYS = [k for k, _ in USLP_REST]
P_USLP = "ccsdsuslp."


def uslp(v, truncated=False):
    if truncated:
        b = pack(USLP_COMMON + [(None, 1, 1)], v)
        return b, model_of(v, USLP_COMMON_KEYS, "truncated", P_USLP)
    n = v.get("vcf_count_length", 0)
    b = pack(USLP_COMMON + [(None, 1, 0)] + USLP_REST + ([("vcf_count", 8 * n)] if n else []), v)
    keys = USLP_COMMON_KEYS + USLP_REST_KEYS + (["vcf_count"] if n else [])
    return b, model_of(v, keys, "non-truncated", P_USLP)


def uslp_frame():
    out = []
    F = "ccsds-uslp-frame"
    base = {"spacecraft_id": 0x0ABC, "virtual_channel_id": 5, "map_id": 2, "frame_length": 99}
    h, m = uslp(base)
    out.append(vec("no-vc-frame-count", F, (h + bytes(93)).hex(), h.hex(), model=m,
                   ref="non-truncated header with a count length of 0: 7 octets; spacecraft 0x0abc as source, "
                       "VC 5, MAP 2, frame length 99 (100 octets), the 93 octets after the header read over"))
    h1, m1 = uslp(dict(base, vcf_count_length=1, vcf_count=200, bypass_flag=1, source_dest_id=1))
    out.append(vec("one-octet-vc-frame-count", F, h1.hex(), h1.hex(), model=m1,
                   ref="an expedited frame (bypass flag 1) whose spacecraft ID names the destination, a 1-octet "
                       "VC frame count of 200: 8 octets"))
    h4, m4 = uslp(dict(base, vcf_count_length=4, vcf_count=0xDEADBEEF, ocf_flag=1))
    out.append(vec("four-octet-vc-frame-count", F, h4.hex(), h4.hex(), model=m4,
                   ref="OCF flag set and a 4-octet VC frame count 0xdeadbeef: 11 octets (the count starts at bit 56)"))
    e = {"spacecraft_id": 0xFFFF, "source_dest_id": 1, "virtual_channel_id": 63, "map_id": 15,
         "frame_length": 0xFFFF, "bypass_flag": 1, "protocol_control_command_flag": 1, "reserve_spares": 3,
         "ocf_flag": 1, "vcf_count_length": 7, "vcf_count": (1 << 56) - 1}
    he, me = uslp(e)
    out.append(vec("largest-values-seven-octet-count", F, he.hex(), he.hex(), model=me,
                   ref="every field at its largest value, the reserve spares included (the pack does not check "
                       "them), and a 7-octet count of 2^56-1: 14 octets"))
    ht, mt = uslp({"spacecraft_id": 0x0ABC, "virtual_channel_id": 5, "map_id": 2}, truncated=True)
    out.append(vec("truncated-header", F, (ht + bytes(8)).hex(), ht.hex(), model=mt,
                   ref="a truncated frame (end of frame primary header flag 1): the 4-octet header, the 8 octets "
                       "after it read over"))
    tm = bytes([0x0A, 0xBC, 0x00, 0x00, 0x00, 0x00, 0x18, 0x00])
    out.append(vec("tm-frame-is-no-kind", F, tm.hex(), error="no-kind",
                   ref="8 octets whose first four bits are 0000, the version of a TM frame, not 1100"))
    out.append(vec("frame-count-cut-short-is-malformed", F, h4[:9].hex(), error="malformed-wire",
                   ref="the 4-octet-count header cut to 9 octets, inside its count"))
    out.append(vec("six-octets-is-malformed", F, h[:6].hex(), error="malformed-wire",
                   ref="the first header cut to 6 octets: not truncated, so 7 octets are needed"))
    return F, out


# ---- CFDP PDU, 727.0-B-5 5.1 and 5.2.1 -------------------------------------------

CFDP_FIXED = [(None, 3, 1), ("pdu_type", 1), ("direction", 1), ("transmission_mode", 1), ("crc_flag", 1),
              ("large_file_flag", 1), ("data_field_length", 16), ("segmentation_control", 1),
              ("entity_id_length", 3), ("segment_metadata_flag", 1), ("tsn_length", 3)]
CFDP_FIXED_KEYS = [k for k, *_ in CFDP_FIXED if k and k != "pdu_type"]
P_CFDP = "ccsdscfdp."


def cfdp(v, directive=None):
    a, b = v["entity_id_length"], v["tsn_length"]
    E, T = 8 * (a + 1), 8 * (b + 1)
    layout = CFDP_FIXED + [("source_entity_id", E), ("transaction_seq_num", T), ("dest_entity_id", E)]
    vv = dict(v, pdu_type=0 if directive is not None else 1)
    if directive is not None:
        layout = layout + [("directive_code", 8)]
        vv["directive_code"] = directive
    h = pack(layout, vv)
    m = model_of(vv, CFDP_FIXED_KEYS, "file-directive" if directive is not None else "file-data", P_CFDP)
    for k, w in (("source_entity_id", E), ("transaction_seq_num", T), ("dest_entity_id", E)):
        m[P_CFDP + k] = str(signed64(vv[k], w))
    if directive is not None:
        m[P_CFDP + "directive_code"] = str(directive)
    return h, m


def cfdp_pdu():
    out = []
    F = "ccsds-cfdp-pdu"
    eof = {"entity_id_length": 0, "tsn_length": 0, "data_field_length": 10, "source_entity_id": 1,
           "transaction_seq_num": 42, "dest_entity_id": 2}
    h, m = cfdp(eof, directive=4)
    params = bytes([0x00]) + (0x12345678).to_bytes(4, "big") + (1000).to_bytes(4, "big")
    out.append(vec("eof-directive-one-octet-ids", F, (h + params).hex(), h.hex(), model=m,
                   ref="an EOF directive (code 4), acknowledged mode, 1-octet entity IDs 1 and 2, 1-octet "
                       "sequence number 42: a 7-octet header and the code; condition code, checksum and file size "
                       "(9 octets) read over"))
    fd = {"direction": 0, "transmission_mode": 1, "segmentation_control": 1, "segment_metadata_flag": 1,
          "entity_id_length": 1, "tsn_length": 3, "data_field_length": 520, "source_entity_id": 0x0101,
          "transaction_seq_num": 0x00010002, "dest_entity_id": 0x0202}
    hf, mf = cfdp(fd)
    out.append(vec("file-data-two-and-four-octet-fields", F, (hf + bytes(16)).hex(), hf.hex(), model=mf,
                   ref="a file data PDU, unacknowledged, record boundaries kept and segment metadata present, "
                       "2-octet entity IDs and a 4-octet sequence number: a 12-octet header, the data read over"))
    big = {"direction": 1, "crc_flag": 1, "large_file_flag": 1, "entity_id_length": 7, "tsn_length": 7,
           "data_field_length": 0xFFFF, "source_entity_id": (1 << 64) - 1,
           "transaction_seq_num": 0x8000000000000001, "dest_entity_id": 0x0123456789ABCDEF}
    hb, mb = cfdp(big, directive=7)
    out.append(vec("metadata-directive-eight-octet-fields", F, hb.hex(), hb.hex(), model=mb,
                   ref="a Metadata directive (code 7) toward the sender, CRC and large file flags set, 8-octet "
                       "entity IDs and sequence number: a 28-octet header and the code. A 64-bit value with its "
                       "top bit set is the negative model integer with the same bits"))
    ka = {"entity_id_length": 2, "tsn_length": 1, "data_field_length": 5, "source_entity_id": 0x010203,
          "transaction_seq_num": 0xFFFF, "dest_entity_id": 0x040506}
    hk, mk = cfdp(ka, directive=12)
    out.append(vec("keep-alive-directive-three-and-two-octet-fields", F, hk.hex(), hk.hex(), model=mk,
                   ref="a Keep Alive directive (code 12), 3-octet entity IDs, 2-octet sequence number: a 12-octet "
                       "header and the code"))
    hu, mu = cfdp(dict(eof, entity_id_length=3, tsn_length=6, source_entity_id=5, transaction_seq_num=6,
                       dest_entity_id=7), directive=0xFF)
    out.append(vec("reserved-directive-code-is-carried", F, hu.hex(), hu.hex(), model=mu,
                   ref="directive code 0xff, reserved: the pack carries the code and does not check it; 4-octet "
                       "IDs and a 7-octet sequence number"))
    out.append(vec("cut-inside-destination-id-is-malformed", F, hf[:11].hex(), error="malformed-wire",
                   ref="the file data header cut to 11 octets, inside its destination entity ID"))
    out.append(vec("directive-without-code-is-malformed", F, h[:7].hex(), error="malformed-wire",
                   ref="the EOF header without its directive code octet"))
    v0 = bytearray(h)
    v0[0] &= 0x1F
    out.append(vec("version-0-is-no-kind", F, bytes(v0).hex(), error="no-kind",
                   ref="the EOF PDU with version 000 (the first version of the protocol), not 001"))
    return F, out


# ---- Proximity-1 Version-3 Transfer Frame, 211.0-B-6 3.2.2 ------------------------

PROX = [(None, 2, 2), ("qos_indicator", 1), ("pdu_type", 1), ("dfc_id", 2), ("spacecraft_id", 10),
        ("physical_channel_id", 1), ("port_id", 3), ("source_dest_id", 1), ("frame_length", 11),
        ("frame_seq_number", 8)]
PROX_KEYS = [k for k, *_ in PROX if k and k != "pdu_type"]
P_PROX = "ccsdsprox1."


def prox1_frame():
    out = []
    F = "ccsds-prox1-frame"
    u = {"pdu_type": 0, "dfc_id": 0, "spacecraft_id": 0x2AA, "port_id": 3, "frame_length": 24,
         "frame_seq_number": 17}
    h = pack(PROX, u)
    out.append(vec("u-frame-packets", F, (h + bytes(20)).hex(), h.hex(),
                   model=model_of(u, PROX_KEYS, "u-frame", P_PROX),
                   ref="a sequence-controlled U-frame of packets (DFC 0) to port 3, spacecraft 0x2aa as source, "
                       "frame length 24 (25 octets), sequence 17; the 20 data octets read over"))
    p = {"pdu_type": 1, "qos_indicator": 1, "spacecraft_id": 0x2AA, "source_dest_id": 1, "frame_length": 6,
         "physical_channel_id": 1}
    hp = pack(PROX, p)
    out.append(vec("p-frame-expedited", F, hp.hex(), hp.hex(), model=model_of(p, PROX_KEYS, "p-frame", P_PROX),
                   ref="an expedited P-frame on physical channel 1, spacecraft ID naming the receiver, DFC and "
                       "port 0 as for a P-frame"))
    e = {"pdu_type": 0, "qos_indicator": 1, "dfc_id": 3, "spacecraft_id": 1023, "physical_channel_id": 1,
         "port_id": 7, "source_dest_id": 1, "frame_length": 2047, "frame_seq_number": 255}
    he = pack(PROX, e)
    out.append(vec("u-frame-largest-values", F, he.hex(), he.hex(), model=model_of(e, PROX_KEYS, "u-frame", P_PROX),
                   ref="a U-frame of user defined data (DFC 3) with every field at its largest value"))
    v0 = bytearray(h)
    v0[0] &= 0x3F
    out.append(vec("version-1-frame-is-no-kind", F, bytes(v0).hex(), error="no-kind",
                   ref="the U-frame with version bits 00 (a TM frame's), not 10"))
    out.append(vec("four-octets-is-malformed", F, h[:4].hex(), error="malformed-wire",
                   ref="the U-frame cut to 4 octets"))
    return F, out


def build(out):
    written = {}
    for make in (uslp_frame, cfdp_pdu, prox1_frame):
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
    return genio.vector_main("ccsds-2-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
