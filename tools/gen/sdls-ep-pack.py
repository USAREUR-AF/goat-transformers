#!/usr/bin/env python3
"""Write the CCSDS SDLS Extended Procedures PDU pack (355.1-B-1) and the CCSDS MO MAL Space Packet
pack (524.1-B-1, the fixed part of the secondary header), with their modules.

An SDLS EP PDU names its procedure by a tag (type, user flag, service group, procedure id) and
counts its data field in bits; the data field's layout is chosen by nested `switch` blocks on the
tag's fields. Many fields have managed lengths (never sent); those PDUs keep their data as octets
after the fields of fixed length.
The vectors are not written here: tools/gen/sdls-ep-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/sdls-ep-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "ep": 'source        "CCSDS 355.1-B-1 Space Data Link Security Protocol, Extended Procedures, Blue Book, February 2020, https://ccsds.org/Pubs/355x1b1.pdf (sha256 5864d866e9c66fc2e644225d6e61724bc6f2c140359e444377e74ceb1a722483), section 5; reuse with attribution under the CCSDS reproduction permission statement"',
    "mal": 'source        "CCSDS 524.1-B-1 Mission Operations, MAL Space Packet Transport Binding and Binary Encoding, Blue Book, August 2015, https://ccsds.org/Pubs/524x1b1.pdf (sha256 6daa871c4f1298fbd0789dd6073841f5c71e7860e44a0b613c17b156939332a4), sections 3.1 and 3.4, with the primary header of CCSDS 133.0-B-2; reuse with attribution under the CCSDS reproduction permission statement"',
}
E = "ccsdssdlsep"
M = "ccsdsmal"


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def sw(key, cases, other=None):
    L = ["switch  %s" % key]
    for vals, lines in cases:
        L.append("  case  %s" % vals)
        L += ind(2, lines)
    if other is not None:
        L.append("  else")
        L += ind(2, other)
    L.append("end")
    return L


def head(name, comment, sources, uses):
    L = ["# %s" % c for c in comment] + ["format        %s" % name, "version       0.1.0", "distribution  public"]
    L += [SRC[s] for s in sources]
    L += ["uses          %s" % u for u in uses]
    return L + ["wire          bits", "layout        sequential", "bit_order     msb", ""]


def text(L):
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- SDLS EP

def e(k, b, tr="uint"):
    return F(E, k, b, tr)


def data_octets():
    return octets(E, "data_octets")


def spi_only():
    return [e("spi", 16)]


def spi_then_octets():
    return [e("spi", 16)] + data_octets()


def key_management():
    inv = sw("ccsdssdlsep.procedure_type", [("1", [e("total_key_ids", 16)] + data_octets())], data_octets())
    return sw("ccsdssdlsep.procedure_id", [("7", inv)], data_octets())


def sa_management():
    start = [e("spi", 16), "group  ccsdssdlsep.gvc_ids  rest", "  " + e("gvc_id", 32), "end"]
    create = [e("spi", 16), e("encryption_flag", 1), e("authentication_flag", 1), e("iv_field_length", 6),
              e("sn_field_length", 6), e("pl_field_length", 2), e("mac_field_length", 8)] + data_octets()
    status = sw("ccsdssdlsep.procedure_type", [("1", [e("spi", 16), e("last_directive", 8)])], spi_only())
    read_arsn = sw("ccsdssdlsep.procedure_type", [("0", spi_only())], data_octets())
    return sw("ccsdssdlsep.procedure_id", [
        ("11", start), ("14,9,4", spi_only()), ("1", create), ("6,10,5", spi_then_octets()),
        ("15", status), ("0", read_arsn)], data_octets())


def monitoring():
    self_test = sw("ccsdssdlsep.procedure_type", [("1", [e("self_test_failed", 1), e("self_test_bits", 7)])], [])
    return sw("ccsdssdlsep.procedure_id", [("1,7", []), ("5", self_test)], data_octets())


def ep_pack():
    L = head("ccsds-sdls-ep-pdu", ["CCSDS SDLS Extended Procedures PDU (355.1-B-1 section 5): the tag (procedure type, user flag,",
                                   "service group, procedure identification), the data field length in bits, and the data field by",
                                   "procedure. Written by tools/gen/sdls-ep-pack.py; do not edit by hand."], ["ep"], [E])
    body = sw("ccsdssdlsep.user_flag", [("0", sw("ccsdssdlsep.service_group", [
        ("0", key_management()), ("1,2", sa_management()), ("3", monitoring())]))], data_octets())
    L += [e("procedure_type", 1), e("user_flag", 1), e("service_group", 2), e("procedure_id", 4), "length  16  bits"]
    L += ind(1, body) + ["end"]
    return text(L)


EP_KEYS = [
    ("key", "procedure_type", "0 a command (from the initiator), 1 a reply (from the recipient)"),
    ("key", "user_flag", "0 a CCSDS-defined procedure, 1 a user-defined procedure"),
    ("key", "service_group", "0 key management; 1 SA management of initiator-to-recipient SAs; 2 of recipient-to-initiator SAs; 3 security monitoring and control"),
    ("key", "procedure_id", "the procedure within the service group (key management: 1 OTAR, 2 activation, 3 deactivation, 4 verification, 6 destruction, 7 inventory; SA management: 0 read ARSN, 1 create, 4 delete, 5 set ARSN window, 6 rekey, 9 expire, 10 set ARSN, 11 start, 14 stop, 15 status request; monitoring and control: 1 ping, 2 log status, 3 dump log, 4 erase log, 5 self-test, 7 alarm flag reset)"),
    ("key", "spi", "the SPI of the security association the procedure acts on"),
    ("list", "gvc_ids", "start SA: the global virtual channel or MAP identifiers the SA is applied to"),
    ("key", "gvc_id", "one global virtual channel or global MAP identifier, 32 bits (its encoding is mission-specific)"),
    ("key", "encryption_flag", "create SA: the SA provides encryption"),
    ("key", "authentication_flag", "create SA: the SA provides authentication"),
    ("key", "iv_field_length", "create SA: the length of the security header's IV field"),
    ("key", "sn_field_length", "create SA: the length of the security header's sequence number field"),
    ("key", "pl_field_length", "create SA: the length of the security header's pad length field"),
    ("key", "mac_field_length", "create SA: the length of the security trailer's MAC field"),
    ("key", "last_directive", "SA status reply: the procedure identification of the last state transition directive applied to the SA"),
    ("key", "total_key_ids", "key inventory reply: the number of key IDs returned"),
    ("key", "self_test_failed", "self-test reply: 1 the self-test failed, 0 it passed"),
    ("key", "self_test_bits", "self-test reply: the 7 bits after the result, left to the implementer"),
    ("list", "data_octets", "the data field (or its part after the fields of fixed length) of a PDU whose fields have managed lengths, or of a user-defined procedure, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- MAL SPP

def m(k, b, tr="uint"):
    return F(M, k, b, tr)


def mal_pack():
    L = head("ccsds-mal-spp-packet", ["CCSDS MO MAL Space Packet (524.1-B-1 section 3): the space packet primary header on the",
                                      "ccsdssp keys, the fixed part of the MAL secondary header, the source and destination IDs and the",
                                      "segment counter when present, then the rest as octets. Written by tools/gen/sdls-ep-pack.py."],
             ["mal"], ["ccsdssp", M])
    L += ["kind    packet", "when    3  0", "field  ccsdssp.packet_type  1  uint", "field  ccsdssp.secondary_header_flag  1  uint",
          "field  ccsdssp.apid  11  uint", "field  ccsdssp.sequence_flags  2  uint"]
    L += sw("ccsdssp.packet_type", [("0", ["field  ccsdssp.sequence_count  14  uint"]),
                                    ("1", ["field  ccsdssp.sequence_count_or_name  14  uint"])])
    L += ["field  ccsdssp.data_length  16  uint",
          m("version", 3), m("sdu_type", 5), m("service_area", 16), m("service", 16), m("operation", 16), m("area_version", 8),
          m("is_error", 1), m("qos_level", 2), m("session", 2), m("secondary_apid", 11), m("secondary_apid_qualifier", 16),
          m("transaction_id", 64, "twos"), m("source_id_flag", 1), m("destination_id_flag", 1), m("priority_flag", 1),
          m("timestamp_flag", 1), m("network_zone_flag", 1), m("session_name_flag", 1), m("domain_flag", 1),
          m("authentication_id_flag", 1)]
    L += sw("ccsdsmal.source_id_flag", [("1", [m("source_id", 8)])], [])
    L += sw("ccsdsmal.destination_id_flag", [("1", [m("destination_id", 8)])], [])
    L += sw("ccsdssp.sequence_flags", [("0,1,2", [m("segment_counter", 32)])], [])
    L += octets(M, "rest_octets")
    return text(L)


MAL_KEYS = [
    ("key", "version", "MAL Space Packet binding version, 0"),
    ("key", "sdu_type", "the MAL interaction type and stage (SEND, SUBMIT, REQUEST, INVOKE, PROGRESS, PUBSUB stages ...), 5 bits"),
    ("key", "service_area", "MAL service area number"),
    ("key", "service", "MAL service number within the area"),
    ("key", "operation", "MAL operation number within the service"),
    ("key", "area_version", "version of the service area"),
    ("key", "is_error", "1 for an error message"),
    ("key", "qos_level", "MAL QoS level: 0 best effort, 1 assured, 2 queued, 3 timely"),
    ("key", "session", "MAL session type: 0 live, 1 simulation, 2 replay"),
    ("key", "secondary_apid", "the other peer's APID (the source's in a request, the destination's in a reply)"),
    ("key", "secondary_apid_qualifier", "the other peer's APID qualifier"),
    ("key", "transaction_id", "MAL transaction identifier, signed 64-bit"),
    ("key", "source_id_flag", "1: the source ID field is present"),
    ("key", "destination_id_flag", "1: the destination ID field is present"),
    ("key", "priority_flag", "1: the priority field is present"),
    ("key", "timestamp_flag", "1: the timestamp field is present"),
    ("key", "network_zone_flag", "1: the network zone field is present"),
    ("key", "session_name_flag", "1: the session name field is present"),
    ("key", "domain_flag", "1: the domain field is present"),
    ("key", "authentication_id_flag", "1: the authentication ID field is present"),
    ("key", "source_id", "source identifier within the APID, 8 bits"),
    ("key", "destination_id", "destination identifier within the APID, 8 bits"),
    ("key", "segment_counter", "segment counter of a segmented MAL message (present unless the packet is unsegmented)"),
    ("list", "rest_octets", "the priority, timestamp, network zone, session name, domain and authentication ID fields when present, then the MAL message body, as octets"),
    ("key", "octet", "one octet"),
]


def module(name, header, src, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/ccsds-sdls-ep-pdu/pack.def", ep_pack())
    out.write("packs/ccsds-mal-spp-packet/pack.def", mal_pack())
    out.write("model/ccsdssdlsep.def", module("ccsdssdlsep", ["# The ccsdssdlsep module: SDLS Extended Procedures PDUs (CCSDS 355.1-B-1). Written by tools/gen/sdls-ep-pack.py."],
                                              SRC["ep"], EP_KEYS))
    out.write("model/ccsdsmal.def", module("ccsdsmal", ["# The ccsdsmal module: the MAL Space Packet secondary header (CCSDS 524.1-B-1). Written by tools/gen/sdls-ep-pack.py."],
                                           SRC["mal"], MAL_KEYS))
    return {"sdls-ep": 4}


def main(argv=None):
    return genio.vector_main("sdls-ep-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
