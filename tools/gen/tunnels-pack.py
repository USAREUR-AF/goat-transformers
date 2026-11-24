#!/usr/bin/env python3
"""Write the tunnelling packs and their modules: the VXLAN-GPE header, the Geneve header with its
options read as type-length-value records, the MPLS label stack, and IKEv2 (the message with its
chain of generic payloads, and one pack per payload body that can be stated).

IKEv2 names the type of each payload in the payload before it, so the chain is read as generic
payloads (header and body octets); each body is laid out by its own pack, whose message is one
payload (generic header and body) as the chain holds it. Geneve option data is counted in 4-octet
words, so its size is chosen by a `switch` on the length; this script writes those cases.
The vectors are not written here: tools/gen/tunnels-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/tunnels-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SHA = {
    "7296": "b6c1bf3921e85dd3674f427ffcaded0209e1f9718e8d601e2f918371f46329a1",
    "8926": "23a9fcd3c23b93a103c0228128b2dce808323a7a9d15ea9cbb395fdb9f67e37d",
    "3032": "c611103bf720c643a40e128159aabb1607eab97977d0f3483d468a620cd86180",
    "7510": "c22acef088d16e298e47bf58366be413c06f71db84f009e40cf102d1cb25fa25",
    "gpe": "02928ea03d3f99b33ef6107ccef28a30ce580ace676d94de494804fd80a49d65",
}
SRC = {
    "gpe": 'source        "IETF Internet-Draft draft-ietf-nvo3-vxlan-gpe-13, Generic Protocol Extension for VXLAN (VXLAN-GPE), November 2023, section 3.1, https://www.ietf.org/archive/id/draft-ietf-nvo3-vxlan-gpe-13.txt (sha256 %s), IETF Trust (BCP 78); layout restated"' % SHA["gpe"],
    "8926": 'source        "IETF RFC 8926, Geneve: Generic Network Virtualization Encapsulation, November 2020, sections 3.4 and 3.5, https://www.rfc-editor.org/rfc/rfc8926.txt (sha256 %s); layout restated"' % SHA["8926"],
    "3032": 'source        "IETF RFC 3032, MPLS Label Stack Encoding, January 2001, section 2.1, https://www.rfc-editor.org/rfc/rfc3032.txt (sha256 %s); IETF RFC 7510, Encapsulating MPLS in UDP, April 2015, section 3, https://www.rfc-editor.org/rfc/rfc7510.txt (sha256 %s); layout restated"' % (SHA["3032"], SHA["7510"]),
    "7296": 'source        "IETF RFC 7296, Internet Key Exchange Protocol Version 2 (IKEv2), October 2014, section 3, https://www.rfc-editor.org/rfc/rfc7296.txt (sha256 %s); layout restated"' % SHA["7296"],
}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def head(name, comment, sources, uses):
    L = ["# %s" % c for c in comment] + ["format        %s" % name, "version       0.1.0", "distribution  public"]
    L += [SRC[s] for s in sources]
    L += ["uses          %s" % u for u in uses]
    return L + ["wire          bits", "layout        sequential", "bit_order     msb", ""]


def text(L):
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- VXLAN-GPE

def gpe_pack():
    g = "vxlangpe"
    L = head("vxlan-gpe-header", ["VXLAN-GPE header (draft-ietf-nvo3-vxlan-gpe-13 section 3.1): the 8 octets after the outer UDP",
                                  "header. The I bit, the VNI and the last reserved octet are the inet keys of vxlan-header.",
                                  "Public. Written by tools/gen/tunnels-pack.py; do not edit by hand."], ["gpe"], ["inet", g])
    L += [F(g, "reserved_flags", 2), F(g, "version", 2), "field  inet.vxlan_i_flag  1  uint", F(g, "p_flag", 1),
          F(g, "b_flag", 1), F(g, "o_flag", 1), F(g, "reserved", 16), F(g, "next_protocol", 8),
          "field  inet.vxlan_vni  24  uint", "field  inet.vxlan_reserved2  8  uint"]
    return text(L)


GPE_KEYS = [
    ("key", "reserved_flags", "the two reserved flag bits before the version, 0"),
    ("key", "version", "VXLAN-GPE version, 0"),
    ("key", "p_flag", "P bit: the next protocol field is present"),
    ("key", "b_flag", "B bit: ingress-replicated broadcast, unknown unicast or multicast traffic"),
    ("key", "o_flag", "O bit: an OAM packet"),
    ("key", "reserved", "the 16 reserved bits after the flags, 0"),
    ("key", "next_protocol", "the header after VXLAN-GPE, from the LISP-GPE next protocol registry (1 IPv4, 2 IPv6, 3 Ethernet, 4 NSH)"),
]


# ---------------------------------------------------------------- Geneve with options

def geneve_pack():
    g = "geneve"
    data = ["switch  geneve.length"]
    for n in range(32):
        data.append("  case  %d" % n)
        if n:
            data.append("    " + F(g, "data", n * 32, "hex"))
    data.append("end")
    L = head("geneve-options", ["Geneve header (RFC 8926 section 3.4) and its options as type-length-value records (section 3.5).",
                                "The message is the base header and the options, the payload excluded. Public. Written by",
                                "tools/gen/tunnels-pack.py; do not edit by hand."], ["8926"], ["inet", g])
    L += ["field  inet.geneve_version  2  uint", F(g, "opt_len", 6), "field  inet.geneve_control  1  uint",
          "field  inet.geneve_critical  1  uint", "field  inet.geneve_reserved1  6  uint",
          "field  inet.geneve_protocol_type  16  uint", "field  inet.geneve_vni  24  uint",
          "field  inet.geneve_reserved2  8  uint", "group  geneve.options  rest"]
    L += ind(1, [F(g, "option_class", 16), F(g, "option_type", 8), F(g, "option_reserved", 3), F(g, "length", 5)] + data)
    L += ["end"]
    return text(L)


GENEVE_KEYS = [
    ("key", "opt_len", "length of the options in 4-octet words, as on the wire (not computed from the options)"),
    ("list", "options", "the options, in order"),
    ("key", "option_class", "option class: the namespace of the type (IANA Geneve option class registry)"),
    ("key", "option_type", "option type; its high bit is the critical bit"),
    ("key", "option_reserved", "the three reserved bits of the option header, 0"),
    ("key", "length", "length of the option data in 4-octet words, 0 to 31"),
    ("key", "data", "the option data, 4 to 124 octets, as hexadecimal digits"),
]


# ---------------------------------------------------------------- MPLS label stack

def mpls_pack():
    m = "mpls"
    L = head("mpls-label-stack", ["MPLS label stack (RFC 3032 section 2.1; RFC 7510 carries the same stack in UDP): the top entry",
                                  "on the inet keys of mpls-label-entry, then the entries below it. The message is the stack alone.",
                                  "Public. Written by tools/gen/tunnels-pack.py; do not edit by hand."], ["3032"], ["inet", m])
    L += ["field  inet.mpls_label  20  uint", "field  inet.mpls_tc  3  uint", "field  inet.mpls_bottom_of_stack  1  uint",
          "field  inet.mpls_ttl  8  uint", "switch  inet.mpls_bottom_of_stack", "  case  0", "    group  mpls.entries  rest"]
    L += ind(3, [F(m, "label", 20), F(m, "tc", 3), F(m, "bottom_of_stack", 1), F(m, "ttl", 8)])
    L += ["    end", "  else", "end"]
    return text(L)


MPLS_KEYS = [
    ("list", "entries", "the label stack entries below the top entry, in order"),
    ("key", "label", "label value, 20 bits (0-15 reserved)"),
    ("key", "tc", "traffic class, 3 bits"),
    ("key", "bottom_of_stack", "1 for the last entry of the stack"),
    ("key", "ttl", "time to live"),
]


# ---------------------------------------------------------------- IKEv2

I = "ikev2"


def generic(body):
    """One IKEv2 payload: the generic header, then the body inside the extent its length gives."""
    return ([F(I, "next_payload", 8), F(I, "critical", 1), F(I, "payload_reserved", 7), "length  16  bytes  plus  4"]
            + ind(1, body) + ["end"])


def counted_octets(name, lst):
    return ["group  %s.%s  count  @%s" % (I, lst, name), "  " + F(I, "octet", 8), "end"]


def ikev2_message_pack():
    L = head("ikev2-message", ["IKEv2 message (RFC 7296 sections 3.1 and 3.2): the IKE header and the chain of payloads, each",
                               "read as its generic header and its body octets. The bodies are laid out by the ikev2-*",
                               "payload packs. Public. Written by tools/gen/tunnels-pack.py; do not edit by hand."], ["7296"], [I])
    L += [F(I, "spi_i", 64, "hex"), F(I, "spi_r", 64, "hex"), F(I, "first_payload", 8), F(I, "major_version", 4),
          F(I, "minor_version", 4), F(I, "exchange_type", 8), F(I, "flags_reserved_high", 2), F(I, "response", 1),
          F(I, "higher_version", 1), F(I, "initiator", 1), F(I, "flags_reserved_low", 3), F(I, "message_id", 32),
          "length  32  whole", "group  ikev2.payloads  rest"]
    L += ind(1, generic(octets(I, "body")))
    L += ["end"]
    return text(L)


def attribute_list(lst, first, typekey):
    return (["group  %s.%s  rest" % (I, lst), "  " + F(I, first, 1), "  " + F(I, typekey, 15)] +
            ind(1, (["switch  %s.af" % I, "  case  1", "    " + F(I, "attr_value", 16), "  else",
                     "    length  16  bytes"] + ind(3, octets(I, "attr_octets")) + ["    end", "end"])
                   if first == "af" else
                   (["length  16  bytes"] + ind(1, octets(I, "attr_octets")) + ["end"])) + ["end"])


def sa_body():
    transform = ([F(I, "last_substruc", 8), F(I, "substruc_reserved", 8), "length  16  bytes  plus  4"] +
                 ind(1, [F(I, "transform_type", 8), F(I, "transform_reserved", 8), F(I, "transform_id", 16)] +
                     attribute_list("attributes", "af", "attr_type")) + ["end"])
    proposal = ([F(I, "last_substruc", 8), F(I, "substruc_reserved", 8), "length  16  bytes  plus  4"] +
                ind(1, [F(I, "proposal_num", 8), F(I, "protocol_id", 8), "count  spi_size  8", "count  num_transforms  8"] +
                    counted_octets("spi_size", "proposal_spi") +
                    ["group  ikev2.transforms  count  @num_transforms"] + ind(1, transform) + ["end"]) + ["end"])
    return ["group  ikev2.proposals  rest"] + ind(1, proposal) + ["end"]


def ts_body():
    sel = ([F(I, "ts_type", 8), F(I, "ip_protocol", 8), "length  16  bytes  plus  4"] +
           ind(1, ["switch  ikev2.ts_type",
                   "  case  7", "    " + F(I, "start_port", 16), "    " + F(I, "end_port", 16),
                   "    " + F(I, "start_ipv4", 32), "    " + F(I, "end_ipv4", 32),
                   "  case  8", "    " + F(I, "start_port", 16), "    " + F(I, "end_port", 16),
                   "    " + F(I, "start_ipv6", 128, "hex"), "    " + F(I, "end_ipv6", 128, "hex"),
                   "  else"] + ind(2, octets(I, "selector_octets")) + ["end"]) + ["end"])
    return ["count  num_ts  8", F(I, "ts_reserved", 24), "group  ikev2.selectors  count  @num_ts"] + ind(1, sel) + ["end"]


def delete_body():
    case = lambda bits: (["count  num_spis  16", "group  ikev2.spis  count  @num_spis", "  " + F(I, "spi", bits, "hex"), "end"])
    return ([F(I, "protocol_id", 8), F(I, "spi_size_field", 8), "switch  ikev2.spi_size_field",
             "  case  4"] + ind(2, case(32)) + ["  case  8"] + ind(2, case(64)) +
            ["  else", "    " + F(I, "num_spis_field", 16)] + ind(2, octets(I, "spi_octets")) + ["end"])


def eap_body():
    return ([F(I, "eap_code", 8), F(I, "eap_identifier", 8), "switch  ikev2.eap_code", "  case  1,2",
             "    length  16  bytes  plus  4", "      " + F(I, "eap_type", 8)] + ind(3, octets(I, "eap_data")) +
            ["    end", "  else", "    " + F(I, "eap_length", 16), "end"])


BODIES = [
    ("ikev2-sa", "Security Association payload (type 33, section 3.3): proposals, their transforms and the transform attributes", sa_body),
    ("ikev2-ke", "Key Exchange payload (type 34, section 3.4)",
     lambda: [F(I, "dh_group", 16), F(I, "ke_reserved", 16)] + octets(I, "ke_data")),
    ("ikev2-id", "Identification payload (types 35 IDi and 36 IDr, section 3.5)",
     lambda: [F(I, "id_type", 8), F(I, "id_reserved", 24), "switch  ikev2.id_type", "  case  1", "    " + F(I, "id_ipv4", 32),
              "  case  5", "    " + F(I, "id_ipv6", 128, "hex"), "  else"] + ind(2, octets(I, "id_data")) + ["end"]),
    ("ikev2-cert", "Certificate and Certificate Request payloads (types 37 and 38, sections 3.6 and 3.7)",
     lambda: [F(I, "cert_encoding", 8)] + octets(I, "cert_data")),
    ("ikev2-auth", "Authentication payload (type 39, section 3.8)",
     lambda: [F(I, "auth_method", 8), F(I, "auth_reserved", 24)] + octets(I, "auth_data")),
    ("ikev2-notify", "Notify payload (type 41, section 3.10)",
     lambda: [F(I, "protocol_id", 8), "count  spi_size  8", F(I, "notify_type", 16)] + counted_octets("spi_size", "spi_bytes") +
     octets(I, "notify_data")),
    ("ikev2-delete", "Delete payload (type 42, section 3.11)", delete_body),
    ("ikev2-ts", "Traffic Selector payload (types 44 TSi and 45 TSr, section 3.13)", ts_body),
    ("ikev2-cp", "Configuration payload (type 47, section 3.15)",
     lambda: [F(I, "cfg_type", 8), F(I, "cfg_reserved", 24)] + attribute_list("cfg_attributes", "cfg_attr_reserved", "cfg_attr_type")),
    ("ikev2-eap", "EAP payload (type 48, section 3.16): the EAP message header", eap_body),
]


def body_pack(name, what, body):
    L = head(name, ["IKEv2 %s. The message is one payload, its generic header included, as" % what,
                    "ikev2-message holds it. Public. Written by tools/gen/tunnels-pack.py; do not edit by hand."], ["7296"], [I])
    return text(L + generic(body()))


IKEV2_KEYS = [
    ("key", "spi_i", "IKE SA initiator's SPI, 8 octets, as hexadecimal digits"),
    ("key", "spi_r", "IKE SA responder's SPI, 8 octets, as hexadecimal digits (zero in the first message of an initial exchange)"),
    ("key", "first_payload", "the type of the first payload after the header (33 SA ... 48 EAP; 0 none)"),
    ("key", "major_version", "major version, 2"),
    ("key", "minor_version", "minor version, 0"),
    ("key", "exchange_type", "exchange type: 34 IKE_SA_INIT, 35 IKE_AUTH, 36 CREATE_CHILD_SA, 37 INFORMATIONAL"),
    ("key", "flags_reserved_high", "the two reserved bits before R, 0"),
    ("key", "response", "R flag: the message is a response"),
    ("key", "higher_version", "V flag: the sender can speak a higher major version"),
    ("key", "initiator", "I flag: sent by the original initiator of the IKE SA"),
    ("key", "flags_reserved_low", "the three reserved bits after I, 0"),
    ("key", "message_id", "message ID"),
    ("list", "payloads", "ikev2-message: the payloads, in order, each a generic header and body octets"),
    ("list", "body", "ikev2-message: the body of a payload (after the generic header), as octets"),
    ("key", "next_payload", "the type of the next payload (0 for the last; in an Encrypted payload, the first payload inside)"),
    ("key", "critical", "C bit: reject the message when the payload's type is not understood"),
    ("key", "payload_reserved", "the seven reserved bits of the generic header, 0"),
    ("list", "proposals", "SA payload: the proposals, in order"),
    ("key", "last_substruc", "proposal or transform: 0 for the last, 2 (proposal) or 3 (transform) when another follows"),
    ("key", "substruc_reserved", "the reserved octet of a proposal or transform header, 0"),
    ("key", "proposal_num", "proposal number, from 1"),
    ("key", "protocol_id", "protocol: 1 IKE, 2 AH, 3 ESP"),
    ("list", "proposal_spi", "proposal: the sender's SPI, as octets (none in an initial IKE SA negotiation); its size is written from the list"),
    ("list", "transforms", "proposal: the transforms, in order; their number is written from the list"),
    ("key", "transform_type", "transform type: 1 ENCR, 2 PRF, 3 INTEG, 4 D-H group, 5 ESN"),
    ("key", "transform_reserved", "the reserved octet after the transform type, 0"),
    ("key", "transform_id", "transform ID within its type"),
    ("list", "attributes", "transform: the attributes, in order"),
    ("key", "af", "attribute format: 1 type and two-octet value, 0 type, length and value"),
    ("key", "attr_type", "transform attribute type (14 key length in bits)"),
    ("key", "attr_value", "the two-octet value of an attribute in the short form"),
    ("list", "attr_octets", "the value of an attribute in the long form, or of a configuration attribute, as octets"),
    ("key", "dh_group", "KE payload: Diffie-Hellman group number"),
    ("key", "ke_reserved", "KE payload: the 16 reserved bits, 0"),
    ("list", "ke_data", "KE payload: the key exchange data, as octets"),
    ("key", "id_type", "ID payload: 1 IPv4 address, 2 FQDN, 3 RFC 822 address, 5 IPv6 address, 9 DER ASN.1 DN, 10 DER ASN.1 GN, 11 key ID"),
    ("key", "id_reserved", "ID payload: the 24 reserved bits, 0"),
    ("key", "id_ipv4", "ID payload, type 1: the IPv4 address, the 32-bit integer"),
    ("key", "id_ipv6", "ID payload, type 5: the IPv6 address, as hexadecimal digits"),
    ("list", "id_data", "ID payload, other types: the identification data, as octets"),
    ("key", "cert_encoding", "CERT or CERTREQ payload: certificate encoding (4 X.509 signature, 12 hash and URL of X.509 ...)"),
    ("list", "cert_data", "CERT or CERTREQ payload: the certificate data or certification authority, as octets"),
    ("key", "auth_method", "AUTH payload: 1 RSA digital signature, 2 shared key MIC, 3 DSS digital signature"),
    ("key", "auth_reserved", "AUTH payload: the 24 reserved bits, 0"),
    ("list", "auth_data", "AUTH payload: the authentication data, as octets"),
    ("key", "notify_type", "Notify payload: notify message type (below 16384 errors, from 16384 status)"),
    ("list", "spi_bytes", "Notify payload: the SPI, as octets; its size is written from the list"),
    ("list", "notify_data", "Notify payload: the notification data, as octets"),
    ("key", "spi_size_field", "Delete payload: the size of each SPI in octets (0 for an IKE SA)"),
    ("list", "spis", "Delete payload with SPIs of 4 or 8 octets: the SPIs; their number is written from the list"),
    ("key", "spi", "one SPI, as hexadecimal digits"),
    ("key", "num_spis_field", "Delete payload with another SPI size: the number of SPIs, as on the wire"),
    ("list", "spi_octets", "Delete payload with another SPI size: the SPIs, as octets"),
    ("list", "selectors", "TS payload: the traffic selectors; their number is written from the list"),
    ("key", "ts_reserved", "TS payload: the 24 reserved bits, 0"),
    ("key", "ts_type", "traffic selector type: 7 IPv4 address range, 8 IPv6 address range"),
    ("key", "ip_protocol", "traffic selector: IP protocol ID (0 any)"),
    ("key", "start_port", "traffic selector: the lowest port"),
    ("key", "end_port", "traffic selector: the highest port"),
    ("key", "start_ipv4", "traffic selector, type 7: the lowest address, the 32-bit integer"),
    ("key", "end_ipv4", "traffic selector, type 7: the highest address, the 32-bit integer"),
    ("key", "start_ipv6", "traffic selector, type 8: the lowest address, as hexadecimal digits"),
    ("key", "end_ipv6", "traffic selector, type 8: the highest address, as hexadecimal digits"),
    ("list", "selector_octets", "traffic selector of another type: its content after the length, as octets"),
    ("key", "cfg_type", "CP payload: 1 CFG_REQUEST, 2 CFG_REPLY, 3 CFG_SET, 4 CFG_ACK"),
    ("key", "cfg_reserved", "CP payload: the 24 reserved bits, 0"),
    ("list", "cfg_attributes", "CP payload: the configuration attributes, in order"),
    ("key", "cfg_attr_reserved", "configuration attribute: the reserved bit, 0"),
    ("key", "cfg_attr_type", "configuration attribute type (1 INTERNAL_IP4_ADDRESS, 3 INTERNAL_IP4_DNS, 8 INTERNAL_IP6_ADDRESS ...)"),
    ("key", "eap_code", "EAP message code: 1 request, 2 response, 3 success, 4 failure"),
    ("key", "eap_identifier", "EAP message identifier"),
    ("key", "eap_type", "EAP request or response: the method type"),
    ("list", "eap_data", "EAP request or response: the type data, as octets"),
    ("key", "eap_length", "EAP success or failure: the EAP length, as on the wire (4)"),
    ("key", "octet", "one octet"),
]
IKEV2_STRINGS = ["spi_i", "spi_r", "id_ipv6", "spi", "start_ipv6", "end_ipv6"]


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
    out.write("packs/vxlan-gpe-header/pack.def", gpe_pack())
    out.write("packs/geneve-options/pack.def", geneve_pack())
    out.write("packs/mpls-label-stack/pack.def", mpls_pack())
    out.write("packs/ikev2-message/pack.def", ikev2_message_pack())
    for name, what, body in BODIES:
        out.write("packs/%s/pack.def" % name, body_pack(name, what, body))
    hdr = lambda m, what: ["# The %s module: %s. Written by tools/gen/tunnels-pack.py." % (m, what)]
    out.write("model/vxlangpe.def", module("vxlangpe", hdr("vxlangpe", "the VXLAN-GPE header fields not shared with VXLAN"),
                                           'source        "IETF draft-ietf-nvo3-vxlan-gpe-13; restated by goat-transformers"', GPE_KEYS))
    out.write("model/geneve.def", module("geneve", hdr("geneve", "Geneve options (RFC 8926 section 3.5)"),
                                         'source        "IETF RFC 8926; restated by goat-transformers"', GENEVE_KEYS, ["data"]))
    out.write("model/mpls.def", module("mpls", hdr("mpls", "the MPLS label stack entries below the top entry (RFC 3032)"),
                                       'source        "IETF RFC 3032; restated by goat-transformers"', MPLS_KEYS))
    out.write("model/ikev2.def", module("ikev2", hdr("ikev2", "the fields of IKEv2 messages and payloads (RFC 7296)"),
                                        'source        "IETF RFC 7296; restated by goat-transformers"', IKEV2_KEYS, IKEV2_STRINGS))
    return {"tunnels": 4 + len(BODIES) + 4}


def main(argv=None):
    return genio.vector_main("tunnels-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
