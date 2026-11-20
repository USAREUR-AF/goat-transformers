#!/usr/bin/env python3
"""flows-vectors: write the vectors of the flow export packs.

Packs: ipfix-message, ipfix-ipv4-flow, ipfix-ipv6-flow, netflow9-packet,
netflow9-ipv4-flow, netflow5, sflow5-datagram.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts
below are this program's own restatement of RFC 7011 sections 3.1 to 3.4 (IPFIX message
header, set header, template and options template records, field specifiers), RFC 3954
sections 5.1 to 5.3 (NetFlow version 9 packet header, FlowSet header, template records)
Cisco's NetFlow Export Datagram Format page (version 5 header and flow record) and the
sFlow(R) version 5 specification of sflow.org (datagram, samples, flow and counter records,
XDR: big-endian 32-bit units, opaque data padded with zero octets to a multiple of 4): each
part is a list of (field, bits) in wire order, most significant bit first, multi-octet
fields big-endian. A record of a fixed-template pack is laid out as the template of that
pack's pack.md states it.

Inputs: messages built here field by field from values chosen here. No message is taken
from a document. Addresses are from the documentation ranges of RFC 5737 and RFC 3849;
the enterprise number 32473 is the one RFC 5612 reserves for documentation.

`expect` of a same-format vector is this program's packing of the decoded values, which
for these messages is the input. `expect` of a conversion is this program's packing of
the values the target maps, worked out from the rules of spec/engine-spec.md: a key the
source does not map is absent and its field is written as zero bits, or as the pack's
`default`; `time_ms` follows the integer scale of the export time (Version 0.15, round
half away from zero) and, for NetFlow version 5, the derive lines of model/netflow5.def
(`ms_of`, `sec_of`, `nsec_of`, Version 0.16). `model` holds the values that were packed.

Usage: python3 -I tools/gen/flows-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = ("built by tools/gen/flows-vectors.py from values chosen there; layouts restated "
          "from %s; expect derived there, no engine run")


def pack(layout, values):
    total = sum(n for _, n in layout)
    assert total % 8 == 0, total
    acc = 0
    for name, n in layout:
        v = values.get(name, 0)
        assert 0 <= v < (1 << n), (name, v, n)
        acc = (acc << n) | v
    return acc.to_bytes(total // 8, "big")


def v4(text):
    return int(ipaddress.IPv4Address(text))


def v6_groups(text):
    b = ipaddress.IPv6Address(text).packed
    return [(b[2 * i] << 8) | b[2 * i + 1] for i in range(8)]


# ---------------------------------------------------------------- IPFIX (RFC 7011)

def ipfix_header(length, export_s, seq, odid):
    return pack([("version", 16), ("length", 16), ("export", 32), ("seq", 32), ("odid", 32)],
                {"version": 10, "length": length, "export": export_s, "seq": seq, "odid": odid})


def ipfix_message(export_s, seq, odid, sets):
    body = b"".join(sets)
    return ipfix_header(16 + len(body), export_s, seq, odid) + body


def ipfix_set(set_id, content):
    return pack([("id", 16), ("len", 16)], {"id": set_id, "len": 4 + len(content)}) + content


def spec(ie, length, enterprise=None):
    if enterprise is None:
        return pack([("e", 1), ("id", 15), ("len", 16)], {"e": 0, "id": ie, "len": length})
    return pack([("e", 1), ("id", 15), ("len", 16), ("ent", 32)],
                {"e": 1, "id": ie, "len": length, "ent": enterprise})


def template_record(tid, specs):
    return pack([("tid", 16), ("n", 16)], {"tid": tid, "n": len(specs)}) + b"".join(spec(*s) for s in specs)


def options_template_record(tid, scope_count, specs):
    return pack([("tid", 16), ("n", 16), ("scope", 16)], {"tid": tid, "n": len(specs), "scope": scope_count}) + \
        b"".join(spec(*s) for s in specs)


# the record layouts of the fixed-template packs (pack.md of each states the template)
IPFIX_V4 = [("src", 8, 32), ("dst", 12, 32), ("sport", 7, 16), ("dport", 11, 16), ("proto", 4, 8),
            ("octets", 1, 64), ("packets", 2, 64), ("start_ms", 152, 64), ("end_ms", 153, 64)]
IPFIX_V6 = [("src%d" % g, 27, 16) for g in range(8)] + [("dst%d" % g, 28, 16) for g in range(8)] + \
    [("sport", 7, 16), ("dport", 11, 16), ("proto", 4, 8), ("octets", 1, 64), ("packets", 2, 64),
     ("start_ms", 152, 64), ("end_ms", 153, 64)]
NF9_V4 = [("src", 8, 32), ("dst", 12, 32), ("sport", 7, 16), ("dport", 11, 16), ("proto", 4, 8),
          ("octets", 1, 32), ("packets", 2, 32), ("first", 22, 32), ("last", 21, 32)]
NF5 = [("src", 32), ("dst", 32), ("nexthop", 32), ("input", 16), ("output", 16), ("packets", 32),
       ("octets", 32), ("first", 32), ("last", 32), ("sport", 16), ("dport", 16), ("pad1", 8),
       ("tcp_flags", 8), ("proto", 8), ("tos", 8), ("src_as", 16), ("dst_as", 16), ("src_mask", 8),
       ("dst_mask", 8), ("pad2", 16)]

KEY = {"src": "ipfix.source_ipv4_address", "dst": "ipfix.destination_ipv4_address",
       "sport": "ipfix.source_transport_port", "dport": "ipfix.destination_transport_port",
       "proto": "ipfix.protocol_identifier", "octets": "ipfix.octet_delta_count",
       "packets": "ipfix.packet_delta_count", "start_ms": "ipfix.flow_start_milliseconds",
       "end_ms": "ipfix.flow_end_milliseconds", "first": "ipfix.flow_start_sys_up_time",
       "last": "ipfix.flow_end_sys_up_time", "nexthop": "ipfix.ip_next_hop_ipv4_address",
       "input": "ipfix.ingress_interface", "output": "ipfix.egress_interface",
       "tcp_flags": "ipfix.tcp_control_bits", "tos": "ipfix.ip_class_of_service",
       "src_as": "ipfix.bgp_source_as_number", "dst_as": "ipfix.bgp_destination_as_number",
       "src_mask": "ipfix.source_ipv4_prefix_length", "dst_mask": "ipfix.destination_ipv4_prefix_length"}
for g in range(8):
    KEY["src%d" % g] = "ipfix.source_ipv6_address_g%d" % g
    KEY["dst%d" % g] = "ipfix.destination_ipv6_address_g%d" % g


def record(layout, values):
    return pack([(n, b) for n, _, b in layout], values)


def items_model(prefix, recs, names):
    m = {prefix + ".#": str(len(recs))}
    for i, r in enumerate(recs):
        for n in names:
            m["%s[%d].%s" % (prefix, i, KEY[n])] = str(r.get(n, 0))
    return m


EXPORT_S = 1773480413                      # 2026-03-14T09:26:53Z
REC_A = {"src": v4("192.0.2.10"), "dst": v4("198.51.100.20"), "sport": 49152, "dport": 443, "proto": 6,
         "octets": 52310, "packets": 61, "start_ms": 1773480401250, "end_ms": 1773480412875}
REC_B = {"src": v4("203.0.113.5"), "dst": v4("192.0.2.53"), "sport": 53001, "dport": 53, "proto": 17,
         "octets": 142, "packets": 2, "start_ms": 1773480410004, "end_ms": 1773480410019}


def vec(name, frm, to, inp, expect=None, model=None, error=None, ref=""):
    v = {"name": name, "from": frm, "to": to, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


R7011 = "RFC 7011 sections 3.1 to 3.4"
R3954 = "RFC 3954 sections 5.1 to 5.3"
RNF5 = "Cisco's NetFlow Export Datagram Format page (version 5)"


def ipfix_vectors():
    out = []
    v4tpl = template_record(256, [(ie, b // 8) for _, ie, b in IPFIX_V4])
    enttpl = template_record(257, [(8, 4), (1, 4, 32473)])
    data = ipfix_set(256, record(IPFIX_V4, REC_A))
    msg = ipfix_message(EXPORT_S, 1041, 7, [ipfix_set(2, v4tpl + enttpl), data])
    m = {"@kind": "message", "time_ms": str(EXPORT_S * 1000), "ipfixmsg.sequence_number": "1041",
         "ipfixmsg.observation_domain_id": "7", "ipfixmsg.sets.#": "2",
         "ipfixmsg.sets[0].ipfixmsg.set_id": "2",
         "ipfixmsg.sets[0].ipfixmsg.template_records.#": "2",
         "ipfixmsg.sets[0].ipfixmsg.template_records[0].ipfixmsg.template_id": "256",
         "ipfixmsg.sets[0].ipfixmsg.template_records[0].ipfixmsg.field_specifiers.#": "9",
         "ipfixmsg.sets[0].ipfixmsg.template_records[0].ipfixmsg.field_specifiers[8].ipfixmsg.ie_id": "153",
         "ipfixmsg.sets[0].ipfixmsg.template_records[0].ipfixmsg.field_specifiers[8].ipfixmsg.field_length": "8",
         "ipfixmsg.sets[0].ipfixmsg.template_records[1].ipfixmsg.field_specifiers[1].ipfixmsg.enterprise_number": "32473",
         "ipfixmsg.sets[1].ipfixmsg.set_id": "256",
         "ipfixmsg.sets[1].ipfixmsg.set_octets.#": "45",
         "ipfixmsg.sets[1].ipfixmsg.set_octets[0].ipfixmsg.octet": "192"}
    out.append(("ipfix-message", "01-template-and-data-roundtrip.json",
                vec("template-and-data-roundtrip", "ipfix-message", "ipfix-message", msg, msg, m,
                    ref=R7011 + "; a Template Set with the IPv4 flow template (256) and a template with an "
                        "enterprise-specific element (257), then a Data Set of one record kept as octets")))
    opt = options_template_record(258, 1, [(149, 4), (41, 8)])
    msg2 = ipfix_message(EXPORT_S + 60, 1042, 7, [ipfix_set(3, opt)])
    m2 = {"ipfixmsg.sets.#": "1", "ipfixmsg.sets[0].ipfixmsg.set_id": "3",
          "ipfixmsg.sets[0].ipfixmsg.template_records[0].ipfixmsg.template_id": "258",
          "ipfixmsg.sets[0].ipfixmsg.template_records[0].ipfixmsg.scope_field_count": "1",
          "ipfixmsg.sets[0].ipfixmsg.template_records[0].ipfixmsg.field_specifiers.#": "2",
          "ipfixmsg.sets[0].ipfixmsg.template_records[0].ipfixmsg.field_specifiers[0].ipfixmsg.ie_id": "149"}
    out.append(("ipfix-message", "02-options-template-roundtrip.json",
                vec("options-template-roundtrip", "ipfix-message", "ipfix-message", msg2, msg2, m2,
                    ref=R7011 + "; an Options Template Set: scope observationDomainId, then "
                        "exportedMessageTotalCount")))
    bad = bytearray(msg2)
    bad[1] = 9
    out.append(("ipfix-message", "03-version-9-is-no-kind.json",
                vec("version-9-is-no-kind", "ipfix-message", "ipfix-message", bytes(bad), error="no-kind",
                    ref=R7011 + "; the second message with version 9 in place of 10")))
    out.append(("ipfix-message", "04-truncated-is-malformed.json",
                vec("truncated-is-malformed", "ipfix-message", "ipfix-message", msg2[:-4], error="malformed-wire",
                    ref=R7011 + "; the second message without its last four octets, shorter than its length field")))

    recs = [REC_A, REC_B]
    msg3 = ipfix_message(EXPORT_S, 2002, 7, [ipfix_set(256, b"".join(record(IPFIX_V4, r) for r in recs))])
    m3 = {"@kind": "message", "time_ms": str(EXPORT_S * 1000), "ipfixmsg.set_id": "256"}
    m3.update(items_model("ipfix.records", recs, [n for n, _, _ in IPFIX_V4]))
    out.append(("ipfix-ipv4-flow", "01-two-records-roundtrip.json",
                vec("two-records-roundtrip", "ipfix-ipv4-flow", "ipfix-ipv4-flow", msg3, msg3, m3,
                    ref=R7011 + "; one Data Set of template 256 with two IPv4 flow records")))
    # to NetFlow version 5: time_ms 1773480413000 -> unix_secs 1773480413, unix_nsecs 0;
    # sys_uptime, flow_sequence, engine and sampling absent (zero); each record keeps the
    # addresses, ports, protocol, packets and octets; the other v5 fields are zero
    nf5 = nf5_packet({"secs": EXPORT_S, "nsecs": 0}, [nf5_from(r) for r in recs])
    out.append(("ipfix-ipv4-flow", "02-to-netflow5.json",
                vec("to-netflow5", "ipfix-ipv4-flow", "netflow5", msg3, nf5,
                    ref=R7011 + " and " + RNF5 + "; the records carry the keys both packs map, the export "
                        "time becomes unix_secs and unix_nsecs through the derive lines of netflow5")))

    v6a = {"sport": 50001, "dport": 443, "proto": 6, "octets": 9001, "packets": 12,
           "start_ms": 1773480400000, "end_ms": 1773480405500}
    for g, x in enumerate(v6_groups("2001:db8::10")):
        v6a["src%d" % g] = x
    for g, x in enumerate(v6_groups("2001:db8:0:1::53")):
        v6a["dst%d" % g] = x
    msg4 = ipfix_message(EXPORT_S, 3, 9, [ipfix_set(300, record(IPFIX_V6, v6a))])
    m4 = {"time_ms": str(EXPORT_S * 1000), "ipfixmsg.set_id": "300"}
    m4.update(items_model("ipfix.records", [v6a], [n for n, _, _ in IPFIX_V6]))
    out.append(("ipfix-ipv6-flow", "01-record-roundtrip.json",
                vec("record-roundtrip", "ipfix-ipv6-flow", "ipfix-ipv6-flow", msg4, msg4, m4,
                    ref=R7011 + "; one Data Set of template 300 with one IPv6 flow record, 2001:db8::10 to "
                        "2001:db8:0:1::53")))
    return out


# ---------------------------------------------------------------- NetFlow v9 (RFC 3954)

def nf9_header(count, uptime, secs, seq, source):
    return pack([("version", 16), ("count", 16), ("uptime", 32), ("secs", 32), ("seq", 32), ("source", 32)],
                {"version": 9, "count": count, "uptime": uptime, "secs": secs, "seq": seq, "source": source})


def nf9_flowset(fid, content):
    return pack([("id", 16), ("len", 16)], {"id": fid, "len": 4 + len(content)}) + content


def nf9_template(tid, specs):
    return pack([("tid", 16), ("n", 16)], {"tid": tid, "n": len(specs)}) + \
        b"".join(pack([("t", 16), ("l", 16)], {"t": t, "l": ln}) for t, ln in specs)


NF9_A = {"src": v4("192.0.2.10"), "dst": v4("198.51.100.20"), "sport": 49152, "dport": 443, "proto": 6,
         "octets": 52310, "packets": 61, "first": 3600250, "last": 3611875}
NF9_B = {"src": v4("203.0.113.5"), "dst": v4("192.0.2.53"), "sport": 53001, "dport": 53, "proto": 17,
         "octets": 142, "packets": 2, "first": 3609004, "last": 3609019}


def nf9_vectors():
    out = []
    tpl = nf9_template(256, [(t, b // 8) for _, t, b in NF9_V4])
    pkt = nf9_header(2, 3612000, EXPORT_S, 88, 1) + nf9_flowset(0, tpl) + nf9_flowset(256, record(NF9_V4, NF9_A))
    m = {"@kind": "packet", "netflow9.count": "2", "netflow9.sys_uptime": "3612000",
         "time_ms": str(EXPORT_S * 1000), "netflow9.sequence_number": "88", "netflow9.source_id": "1",
         "netflow9.flowsets.#": "2", "netflow9.flowsets[0].netflow9.flowset_id": "0",
         "netflow9.flowsets[0].netflow9.template_records[0].netflow9.template_id": "256",
         "netflow9.flowsets[0].netflow9.template_records[0].netflow9.field_specifiers.#": "9",
         "netflow9.flowsets[0].netflow9.template_records[0].netflow9.field_specifiers[5].netflow9.field_type": "1",
         "netflow9.flowsets[1].netflow9.flowset_id": "256",
         "netflow9.flowsets[1].netflow9.flowset_octets.#": "29"}
    out.append(("netflow9-packet", "01-template-and-data-roundtrip.json",
                vec("template-and-data-roundtrip", "netflow9-packet", "netflow9-packet", pkt, pkt, m,
                    ref=R3954 + "; a Template FlowSet with the IPv4 flow template (256), then a Data FlowSet "
                        "of one record kept as octets")))
    bad = bytearray(pkt)
    bad[1] = 10
    out.append(("netflow9-packet", "02-version-10-is-no-kind.json",
                vec("version-10-is-no-kind", "netflow9-packet", "netflow9-packet", bytes(bad), error="no-kind",
                    ref=R3954 + "; the packet with version 10 in place of 9")))

    recs = [NF9_A, NF9_B]
    pkt2 = nf9_header(2, 3612000, EXPORT_S, 89, 1) + nf9_flowset(256, b"".join(record(NF9_V4, r) for r in recs))
    m2 = {"@kind": "packet", "time_ms": str(EXPORT_S * 1000), "netflow9.flowset_id": "256"}
    m2.update(items_model("ipfix.records", recs, [n for n, _, _ in NF9_V4]))
    out.append(("netflow9-ipv4-flow", "01-two-records-roundtrip.json",
                vec("two-records-roundtrip", "netflow9-ipv4-flow", "netflow9-ipv4-flow", pkt2, pkt2, m2,
                    ref=R3954 + "; one Data FlowSet of template 256 with two IPv4 flow records")))
    # to IPFIX: sequence number and observation domain are other keys (absent, zero), the
    # set ID takes the pack's default 256; records keep the 5-tuple, octets and packets;
    # flowStart/EndMilliseconds are absent (zero): version 9 states uptime, not a date
    conv = [{k: r[k] for k in ("src", "dst", "sport", "dport", "proto", "octets", "packets")} for r in recs]
    ipfix = ipfix_message(EXPORT_S, 0, 0, [ipfix_set(256, b"".join(record(IPFIX_V4, r) for r in conv))])
    out.append(("netflow9-ipv4-flow", "02-to-ipfix-ipv4-flow.json",
                vec("to-ipfix-ipv4-flow", "netflow9-ipv4-flow", "ipfix-ipv4-flow", pkt2, ipfix,
                    ref=R3954 + " and " + R7011 + "; the records carry the keys both packs map, the export "
                        "time carries as time_ms")))
    return out


# ---------------------------------------------------------------- NetFlow v5 (Cisco)

def nf5_packet(h, recs):
    head = pack([("version", 16), ("count", 16), ("uptime", 32), ("secs", 32), ("nsecs", 32), ("seq", 32),
                 ("etype", 8), ("eid", 8), ("smode", 2), ("sint", 14)],
                {"version": 5, "count": len(recs), "uptime": h.get("uptime", 0), "secs": h["secs"],
                 "nsecs": h["nsecs"], "seq": h.get("seq", 0), "etype": h.get("etype", 0),
                 "eid": h.get("eid", 0), "smode": h.get("smode", 0), "sint": h.get("sint", 0)})
    return head + b"".join(pack(NF5, r) for r in recs)


def nf5_from(r):
    return {k: r[k] for k in ("src", "dst", "sport", "dport", "proto", "octets", "packets")}


NF5_A = {"src": v4("192.0.2.10"), "dst": v4("198.51.100.20"), "nexthop": v4("192.0.2.1"), "input": 3,
         "output": 7, "packets": 61, "octets": 52310, "first": 3600250, "last": 3611875, "sport": 49152,
         "dport": 443, "tcp_flags": 0x1b, "proto": 6, "tos": 0, "src_as": 64496, "dst_as": 64511,
         "src_mask": 24, "dst_mask": 24}
NF5_B = {"src": v4("203.0.113.5"), "dst": v4("192.0.2.53"), "nexthop": v4("192.0.2.1"), "input": 7,
         "output": 3, "packets": 2, "octets": 142, "first": 3609004, "last": 3609019, "sport": 53001,
         "dport": 53, "tcp_flags": 0, "proto": 17, "tos": 0, "src_as": 64511, "dst_as": 64496,
         "src_mask": 24, "dst_mask": 24}


def nf5_vectors():
    out = []
    h = {"uptime": 3612000, "secs": EXPORT_S, "nsecs": 250000000, "seq": 1200, "etype": 0, "eid": 2,
         "smode": 1, "sint": 100}
    pkt = nf5_packet(h, [NF5_A, NF5_B])
    m = {"@kind": "packet", "netflow5.sys_uptime": "3612000", "netflow5.unix_secs": str(EXPORT_S),
         "netflow5.unix_nsecs": "250000000", "netflow5.flow_sequence": "1200", "netflow5.engine_id": "2",
         "netflow5.sampling_mode": "1", "netflow5.sampling_interval": "100"}
    m.update(items_model("ipfix.records", [NF5_A, NF5_B],
                         [n for n, _ in NF5 if not n.startswith("pad")]))
    out.append(("netflow5", "01-two-flows-roundtrip.json",
                vec("two-flows-roundtrip", "netflow5", "netflow5", pkt, pkt, m,
                    ref=RNF5 + "; a header and two flow records")))
    # time_ms = ms_of(1773480413, 250000000) = 1773480413250; IPFIX export time
    # round(1773480413250 / 1000) = 1773480413 (round half away from zero, below the half)
    ipfix = ipfix_message(EXPORT_S, 0, 0, [ipfix_set(256, b"".join(record(IPFIX_V4, nf5_from(r))
                                                                    for r in (NF5_A, NF5_B)))])
    out.append(("netflow5", "02-to-ipfix-ipv4-flow.json",
                vec("to-ipfix-ipv4-flow", "netflow5", "ipfix-ipv4-flow", pkt, ipfix,
                    ref=RNF5 + " and " + R7011 + "; time_ms from unix_secs and unix_nsecs (ms_of), written "
                        "as the export time in seconds; the records carry the keys both packs map")))
    empty = nf5_packet({"secs": EXPORT_S, "nsecs": 0}, [])
    out.append(("netflow5", "03-no-flows-roundtrip.json",
                vec("no-flows-roundtrip", "netflow5", "netflow5", empty, empty,
                    {"ipfix.records.#": "0", "netflow5.unix_secs": str(EXPORT_S)},
                    ref=RNF5 + "; a header that announces no flow")))
    out.append(("netflow5", "04-missing-record-is-malformed.json",
                vec("missing-record-is-malformed", "netflow5", "netflow5", pkt[:-48], error="malformed-wire",
                    ref=RNF5 + "; the first packet without its second record, so the count of 2 runs past "
                        "the input")))
    return out


# ---------------------------------------------------------------- sFlow version 5 (sflow.org)

def u32(*vals):
    return b"".join(v.to_bytes(4, "big") for v in vals)


def u64(v):
    return v.to_bytes(8, "big")


def xdr_opaque(data):
    return u32(len(data)) + data + b"\0" * (-len(data) % 4)


def sf_record(fmt, data):
    return u32(fmt) + xdr_opaque(data)


def sf_datagram(agent, sub_agent, seq, uptime, samples):
    if isinstance(agent, int):
        head = u32(5, 1, agent)
    else:
        head = u32(5, 2) + ipaddress.IPv6Address(agent).packed
    return head + u32(sub_agent, seq, uptime, len(samples)) + b"".join(samples)


IF_FIELDS = [("if_index", 32), ("if_type", 32), ("if_speed", 64), ("if_direction", 32), ("if_status", 32),
             ("if_in_octets", 64), ("if_in_ucast_pkts", 32), ("if_in_multicast_pkts", 32),
             ("if_in_broadcast_pkts", 32), ("if_in_discards", 32), ("if_in_errors", 32),
             ("if_in_unknown_protos", 32), ("if_out_octets", 64), ("if_out_ucast_pkts", 32),
             ("if_out_multicast_pkts", 32), ("if_out_broadcast_pkts", 32), ("if_out_discards", 32),
             ("if_out_errors", 32), ("if_promiscuous_mode", 32)]
ETH_FIELDS = ["dot3_alignment_errors", "dot3_fcs_errors", "dot3_single_collision_frames",
              "dot3_multiple_collision_frames", "dot3_sqe_test_errors", "dot3_deferred_transmissions",
              "dot3_late_collisions", "dot3_excessive_collisions", "dot3_internal_mac_transmit_errors",
              "dot3_carrier_sense_errors", "dot3_frame_too_longs", "dot3_internal_mac_receive_errors",
              "dot3_symbol_errors"]
IF_VALUES = {"if_index": 3, "if_type": 6, "if_speed": 10000000000, "if_direction": 1, "if_status": 3,
             "if_in_octets": 81234567890, "if_in_ucast_pkts": 912345, "if_in_multicast_pkts": 120,
             "if_in_broadcast_pkts": 31, "if_in_discards": 0, "if_in_errors": 2, "if_in_unknown_protos": 0,
             "if_out_octets": 70123456789, "if_out_ucast_pkts": 845002, "if_out_multicast_pkts": 64,
             "if_out_broadcast_pkts": 9, "if_out_discards": 1, "if_out_errors": 0, "if_promiscuous_mode": 0}
ETH_VALUES = {k: i for i, k in enumerate(ETH_FIELDS)}


def if_counters(v):
    return b"".join(u64(v[k]) if b == 64 else u32(v[k]) for k, b in IF_FIELDS)


# an Ethernet frame header (documentation MAC addresses of RFC 7042) and the first four octets
# of an IPv4 header: 18 octets, so the opaque header takes two octets of padding
SAMPLED = bytes.fromhex("00005e005301" "00005e005302" "0800" "45000034")
RSF = "the sFlow version 5 specification of sflow.org, section 5 (XDR of the datagram and of the records)"


def sflow_vectors():
    out = []
    flow = u32(17, (0 << 24) | 3, 400, 1600400, 0, (0 << 30) | 3, (0 << 30) | 7, 3) + \
        sf_record(1, u32(1, 82, 4) + xdr_opaque(SAMPLED)) + \
        sf_record(3, u32(64, 17, v4("192.0.2.10"), v4("198.51.100.20"), 53001, 53, 0, 0)) + \
        sf_record(1001, u32(10, 0, 20, 0))
    counters = u32(9, (0 << 24) | 3, 2) + sf_record(1, if_counters(IF_VALUES)) + \
        sf_record(2, b"".join(u32(ETH_VALUES[k]) for k in ETH_FIELDS))
    vendor = bytes.fromhex("0102030405060708")
    samples = [sf_record(1, flow), sf_record(2, counters), sf_record((4300 << 12) | 7, vendor)]
    dg = sf_datagram(v4("192.0.2.1"), 0, 345, 3612000, samples)
    m = {"@kind": "datagram", "sflow.agent_address_type": "1", "sflow.agent_ipv4": str(v4("192.0.2.1")),
         "sflow.sub_agent_id": "0", "sflow.datagram_sequence": "345", "sflow.uptime": "3612000",
         "sflow.samples.#": "3",
         "sflow.samples[0].sflow.sample_type": "1", "sflow.samples[0].sflow.sampling_rate": "400",
         "sflow.samples[0].sflow.input_value": "3", "sflow.samples[0].sflow.output_value": "7",
         "sflow.samples[0].sflow.flow_records.#": "3",
         "sflow.samples[0].sflow.flow_records[0].sflow.header_protocol": "1",
         "sflow.samples[0].sflow.flow_records[0].sflow.frame_length": "82",
         "sflow.samples[0].sflow.flow_records[0].sflow.header_octets.#": "18",
         "sflow.samples[0].sflow.flow_records[0].sflow.header_octets[12].sflow.octet": "8",
         "sflow.samples[0].sflow.flow_records[1].sflow.src_ipv4": str(v4("192.0.2.10")),
         "sflow.samples[0].sflow.flow_records[1].sflow.dst_port": "53",
         "sflow.samples[0].sflow.flow_records[2].sflow.flow_format": "1001",
         "sflow.samples[0].sflow.flow_records[2].sflow.record_octets.#": "16",
         "sflow.samples[1].sflow.sample_type": "2", "sflow.samples[1].sflow.counter_records.#": "2",
         "sflow.samples[1].sflow.counter_records[0].sflow.if_speed": "10000000000",
         "sflow.samples[1].sflow.counter_records[0].sflow.if_in_octets": "81234567890",
         "sflow.samples[1].sflow.counter_records[1].sflow.dot3_symbol_errors": "12",
         "sflow.samples[2].sflow.sample_type": str((4300 << 12) | 7),
         "sflow.samples[2].sflow.sample_octets.#": "8"}
    out.append(("sflow5-datagram", "01-flow-counter-vendor-roundtrip.json",
                vec("flow-counter-vendor-roundtrip", "sflow5-datagram", "sflow5-datagram", dg, dg, m,
                    ref=RSF + "; an IPv4 agent; a flow sample with a raw packet header (18 octets, padded "
                        "to 20), IPv4 data and a record of format 1001 kept as octets; a counter sample "
                        "with generic interface and Ethernet counters; a sample of enterprise 4300 kept as "
                        "octets")))
    v6rec = u32(1240, 6) + ipaddress.IPv6Address("2001:db8::10").packed + \
        ipaddress.IPv6Address("2001:db8:0:1::53").packed + u32(50001, 443, 0x18, 0)
    eflow = u32(18, 0, 3, 1000, 2001000, 1, 0, 3, 1, 260) + u32(1) + sf_record(4, v6rec)
    ectr = u32(10, 0, 3, 1) + sf_record(1, if_counters(IF_VALUES))
    dg2 = sf_datagram("2001:db8::1", 1, 346, 3613000, [sf_record(3, eflow), sf_record(4, ectr)])
    m2 = {"sflow.agent_address_type": "2", "sflow.agent_ipv6_g0": "8193", "sflow.agent_ipv6_g7": "1",
          "sflow.samples.#": "2", "sflow.samples[0].sflow.source_id_index": "3",
          "sflow.samples[0].sflow.output_format": "1", "sflow.samples[0].sflow.output_value": "260",
          "sflow.samples[0].sflow.flow_records[0].sflow.src_ipv6_g0": "8193",
          "sflow.samples[0].sflow.flow_records[0].sflow.dst_ipv6_g3": "1",
          "sflow.samples[0].sflow.flow_records[0].sflow.dst_port": "443",
          "sflow.samples[1].sflow.counter_records[0].sflow.if_out_octets": "70123456789"}
    out.append(("sflow5-datagram", "02-ipv6-agent-expanded-roundtrip.json",
                vec("ipv6-agent-expanded-roundtrip", "sflow5-datagram", "sflow5-datagram", dg2, dg2, m2,
                    ref=RSF + "; an IPv6 agent (2001:db8::1); an expanded flow sample with IPv6 data and an "
                        "output discarded for reason 260; an expanded counter sample")))
    bad = bytearray(dg2)
    bad[3] = 4
    out.append(("sflow5-datagram", "03-version-4-is-no-kind.json",
                vec("version-4-is-no-kind", "sflow5-datagram", "sflow5-datagram", bytes(bad), error="no-kind",
                    ref=RSF + "; the second datagram with version 4 in place of 5")))
    out.append(("sflow5-datagram", "04-truncated-is-malformed.json",
                vec("truncated-is-malformed", "sflow5-datagram", "sflow5-datagram", dg[:-12],
                    error="malformed-wire", ref=RSF + "; the first datagram without its last 12 octets")))
    return out


def build_files(out):
    written = {}
    for pack_name, fname, v in ipfix_vectors() + nf9_vectors() + nf5_vectors() + sflow_vectors():
        assert v["from"] == pack_name
        out.write("packs/%s/vectors/%s" % (pack_name, fname), json.dumps(v, indent=2) + "\n")
        written[pack_name] = written.get(pack_name, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("flows-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
