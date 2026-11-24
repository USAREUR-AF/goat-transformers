#!/usr/bin/env python3
"""sdls-ep-vectors: write the vectors of the SDLS Extended Procedures and MAL Space Packet packs.

Packs: ccsds-sdls-ep-pdu, ccsds-mal-spp-packet.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of CCSDS 355.1-B-1 section 5 and CCSDS 524.1-B-1 sections 3.1 and
3.4 with the primary header of CCSDS 133.0-B-2: every multi-octet field big-endian, bit fields most
significant bit first.

Inputs: PDUs and packets built here field by field from values chosen here; none is taken from a
document or a capture.

`expect` of a round trip is this program's packing of the decoded values, which for these PDUs is
the input; of a conversion, the target header packed here from the shared values; `model` holds
values that were packed.

Usage: python3 -I tools/gen/sdls-ep-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/sdls-ep-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_EP = "CCSDS 355.1-B-1 section 5"
R_MAL = "CCSDS 524.1-B-1 sections 3.1 and 3.4 and CCSDS 133.0-B-2 section 4.1.3"


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def bits(fields):
    acc, n = 0, 0
    for v, w in fields:
        assert 0 <= v < (1 << w), (v, w)
        acc, n = (acc << w) | v, n + w
    assert n % 8 == 0, n
    return acc.to_bytes(n // 8, "big")


def vec(pack, name, inp, model=None, error=None, ref="", to=None, expect=None):
    v = {"name": name, "from": pack, "to": to or pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


def u32(*v):
    return b"".join(x.to_bytes(4, "big") for x in v)


def pdu(ptype, user, group, proc, data=b"", length_bits=None):
    n = len(data) * 8 if length_bits is None else length_bits
    return bits([(ptype, 1), (user, 1), (group, 2), (proc, 4)]) + u16(n) + data


def ep_vectors():
    p = "ccsds-sdls-ep-pdu"
    out = []
    a = pdu(0, 0, 1, 11, u16(5) + u32(0x00010203, 0x80000001))
    out.append((p, "01-start-sa-roundtrip.json", vec(p, "start-sa-roundtrip", a,
                {"ccsdssdlsep.procedure_type": "0", "ccsdssdlsep.service_group": "1", "ccsdssdlsep.procedure_id": "11",
                 "ccsdssdlsep.spi": "5", "ccsdssdlsep.gvc_ids.#": "2", "ccsdssdlsep.gvc_ids[1].ccsdssdlsep.gvc_id": str(0x80000001),
                 "ccsdssdlsep.gvc_ids[0].ccsdssdlsep.gvc_id": str(0x00010203)},
                ref=R_EP + "; a Start SA command for SPI 5 on two GVC/GMAP identifiers of 32 bits each (5.5.1.2.2.2 b; data field 80 bits)")))
    b = pdu(0, 0, 2, 14, u16(5))
    out.append((p, "02-stop-sa-roundtrip.json", vec(p, "stop-sa-roundtrip", b,
                {"ccsdssdlsep.service_group": "2", "ccsdssdlsep.procedure_id": "14", "ccsdssdlsep.spi": "5"},
                ref=R_EP + "; a Stop SA command for a recipient-to-initiator SA")))
    c = pdu(0, 0, 1, 1, u16(9) + bits([(1, 1), (1, 1), (12, 6), (4, 6), (0, 2), (16, 8)]) + bytes([1, 0x20, 0, 1, 0x30, 0]))
    out.append((p, "03-create-sa-roundtrip.json", vec(p, "create-sa-roundtrip", c,
                {"ccsdssdlsep.procedure_id": "1", "ccsdssdlsep.spi": "9", "ccsdssdlsep.encryption_flag": "1",
                 "ccsdssdlsep.authentication_flag": "1", "ccsdssdlsep.iv_field_length": "12", "ccsdssdlsep.sn_field_length": "4",
                 "ccsdssdlsep.pl_field_length": "0", "ccsdssdlsep.mac_field_length": "16", "ccsdssdlsep.data_octets.#": "6"},
                ref=R_EP + "; a Create SA command: SPI 9, authenticated encryption, the header and trailer field lengths, "
                    "then the cipher suite, IV, bit mask and ARSN parts kept as octets")))
    d = pdu(1, 0, 2, 15, u16(5) + bytes([11]))
    out.append((p, "04-sa-status-reply-roundtrip.json", vec(p, "sa-status-reply-roundtrip", d,
                {"ccsdssdlsep.procedure_type": "1", "ccsdssdlsep.procedure_id": "15", "ccsdssdlsep.spi": "5",
                 "ccsdssdlsep.last_directive": "11"},
                ref=R_EP + "; an SA Status Request reply: the SA's last directive was Start SA (11)")))
    e = pdu(1, 0, 0, 7, u16(2) + bytes([0, 1, 3, 0, 2, 2]))
    out.append((p, "05-key-inventory-reply-roundtrip.json", vec(p, "key-inventory-reply-roundtrip", e,
                {"ccsdssdlsep.service_group": "0", "ccsdssdlsep.procedure_id": "7", "ccsdssdlsep.total_key_ids": "2",
                 "ccsdssdlsep.data_octets.#": "6"},
                ref=R_EP + "; a Key Inventory reply with two (key ID, key state) pairs of managed length, kept as octets")))
    f = pdu(0, 0, 3, 1)
    out.append((p, "06-ping-command-roundtrip.json", vec(p, "ping-command-roundtrip", f,
                {"ccsdssdlsep.service_group": "3", "ccsdssdlsep.procedure_id": "1"}, ref=R_EP + "; a Ping command, no data field")))
    g = pdu(1, 0, 3, 5, bytes([0x80]))
    out.append((p, "07-self-test-failed-reply-roundtrip.json", vec(p, "self-test-failed-reply-roundtrip", g,
                {"ccsdssdlsep.procedure_id": "5", "ccsdssdlsep.self_test_failed": "1", "ccsdssdlsep.self_test_bits": "0"},
                ref=R_EP + "; a Self-Test reply reporting a failure")))
    h = pdu(0, 1, 0, 5, b"\x01\x02\x03")
    out.append((p, "08-user-defined-roundtrip.json", vec(p, "user-defined-roundtrip", h,
                {"ccsdssdlsep.user_flag": "1", "ccsdssdlsep.data_octets.#": "3"},
                ref=R_EP + "; a user-defined procedure, its data field kept as octets")))
    i = pdu(0, 0, 0, 1, bytes(range(40)))
    out.append((p, "09-otar-command-roundtrip.json", vec(p, "otar-command-roundtrip", i,
                {"ccsdssdlsep.procedure_id": "1", "ccsdssdlsep.data_octets.#": "40"},
                ref=R_EP + "; an OTAR command, whose fields have managed lengths, kept as octets")))
    j = pdu(0, 0, 1, 0, u16(5))
    out.append((p, "10-read-arsn-command-roundtrip.json", vec(p, "read-arsn-command-roundtrip", j,
                {"ccsdssdlsep.procedure_id": "0", "ccsdssdlsep.spi": "5"}, ref=R_EP + "; a Read ARSN command for SPI 5")))
    out.append((p, "11-cut-data-field-is-malformed.json", vec(p, "cut-data-field-is-malformed", a[:5], error="malformed-wire",
                ref=R_EP + "; the Start SA PDU of vector 01 cut inside its data field")))
    return out


def primary(ptype, apid, seqflags, count, data_len):
    return bits([(0, 3), (ptype, 1), (1, 1), (apid, 11), (seqflags, 2), (count, 14), (data_len - 1, 16)])


def mal_secondary(sdu, area, service, op, aver, err, qos, sess, sapid, qual, txid, flags, src=None, dst=None, seg=None):
    s = bits([(0, 3), (sdu, 5), (area, 16), (service, 16), (op, 16), (aver, 8), (err, 1), (qos, 2), (sess, 2),
              (sapid, 11), (qual, 16)]) + struct.pack(">q", txid) + bits([(f, 1) for f in flags])
    if src is not None:
        s += bytes([src])
    if dst is not None:
        s += bytes([dst])
    if seg is not None:
        s += struct.pack(">I", seg)
    return s


def mal_vectors():
    p = "ccsds-mal-spp-packet"
    out = []
    sec = mal_secondary(3, 4, 2, 1, 1, 0, 1, 0, 200, 417, 12345, [1, 1, 0, 0, 0, 0, 0, 0], src=2, dst=3)
    body = b"\x01\x02\x03\x04"
    a = primary(1, 100, 3, 42, len(sec) + len(body)) + sec + body
    out.append((p, "01-telecommand-with-ids-roundtrip.json", vec(p, "telecommand-with-ids-roundtrip", a,
                {"ccsdssp.packet_type": "1", "ccsdssp.apid": "100", "ccsdssp.sequence_flags": "3",
                 "ccsdssp.sequence_count_or_name": "42", "ccsdssp.data_length": str(len(sec) + len(body) - 1),
                 "ccsdsmal.sdu_type": "3", "ccsdsmal.service_area": "4", "ccsdsmal.service": "2", "ccsdsmal.operation": "1",
                 "ccsdsmal.qos_level": "1", "ccsdsmal.secondary_apid": "200", "ccsdsmal.secondary_apid_qualifier": "417",
                 "ccsdsmal.transaction_id": "12345", "ccsdsmal.source_id_flag": "1", "ccsdsmal.source_id": "2",
                 "ccsdsmal.destination_id": "3", "ccsdsmal.rest_octets.#": "4"},
                ref=R_MAL + "; an unsegmented telecommand with source and destination IDs and a 4-octet body")))
    sec2 = mal_secondary(7, 4, 2, 3, 1, 1, 2, 1, 1000, 0, -5, [0, 0, 0, 1, 0, 0, 0, 0], seg=7)
    body2 = bytes(range(10))
    b = primary(0, 50, 1, 9, len(sec2) + len(body2)) + sec2 + body2
    out.append((p, "02-segmented-telemetry-roundtrip.json", vec(p, "segmented-telemetry-roundtrip", b,
                {"ccsdssp.packet_type": "0", "ccsdssp.sequence_flags": "1", "ccsdssp.sequence_count": "9",
                 "ccsdsmal.is_error": "1", "ccsdsmal.session": "1", "ccsdsmal.transaction_id": "-5",
                 "ccsdsmal.timestamp_flag": "1", "ccsdsmal.segment_counter": "7", "ccsdsmal.rest_octets.#": "10"},
                ref=R_MAL + "; the first segment of a telemetry error message: a negative transaction ID, the segment counter, "
                    "and the timestamp and body as octets")))
    out.append((p, "03-to-ccsds-space-packet.json", vec(p, "to-ccsds-space-packet", b, to="ccsds-space-packet",
                expect=primary(0, 50, 1, 9, len(sec2) + len(body2)),
                ref=R_MAL + "; the primary header carries over; ccsds-space-packet writes the 6 header octets")))
    out.append((p, "04-other-packet-version-is-no-kind.json", vec(p, "other-packet-version-is-no-kind",
                bytes([0x20 | a[0]]) + a[1:], error="no-kind", ref=R_MAL + "; a packet version number of 1")))
    out.append((p, "05-cut-secondary-header-is-malformed.json", vec(p, "cut-secondary-header-is-malformed", a[:12],
                error="malformed-wire", ref=R_MAL + "; the packet of vector 01 cut inside the secondary header")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in ep_vectors() + mal_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("sdls-ep-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
