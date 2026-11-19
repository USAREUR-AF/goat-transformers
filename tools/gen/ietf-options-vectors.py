#!/usr/bin/env python3
"""Write the vectors of the packs `dhcpv6-options` and `edns0-options`.

Both are option areas of the `tlv` wire with a 2-octet code and a 2-octet
length (RFC 9915 section 21.1, RFC 6891 section 6.1.2). This script holds its
own copy of the codes it uses and of the sizes RFC 9915 gives the integer
options, builds each options area from values written for these vectors, and
works out the decoded values and the canonical output by the rules of
spec/engine-spec.md 0.13 (line order, residue after mapped items, the first of
a repeated code only). It reads no pack.def and calls no goat-transformers
engine.

Inputs: none. The same run always gives the same bytes. With --check nothing
is written and the exit status is 1 when a committed file differs.

Usage: python3 -I tools/gen/ietf-options-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

# code -> (key, size in octets for an integer option, or None for hex)
DHCPV6 = {1: ("dhcpv6.opt1_clientid", None), 2: ("dhcpv6.opt2_serverid", None), 3: ("dhcpv6.opt3_ia_na", None),
          6: ("dhcpv6.opt6_oro", None), 7: ("dhcpv6.opt7_preference", 1), 8: ("dhcpv6.opt8_elapsed_time", 2),
          14: ("dhcpv6.opt14_rapid_commit", None), 19: ("dhcpv6.opt19_reconf_msg", 1),
          23: ("dhcpv6.opt23_dns_servers", None), 25: ("dhcpv6.opt25_ia_pd", None),
          32: ("dhcpv6.opt32_information_refresh_time", 4), 82: ("dhcpv6.opt82_sol_max_rt", 4),
          150: ("dhcpv6.opt150_ialocator", None)}
EDNS0 = {3: ("edns0.opt3_nsid", None), 8: ("edns0.opt8_edns_client_subnet", None),
         10: ("edns0.opt10_cookie", None), 12: ("edns0.opt12_padding", None),
         15: ("edns0.opt15_extended_dns_error", None)}


def item(code, value_hex):
    v = bytes.fromhex(value_hex)
    return "%04x%04x" % (code, len(v)) + v.hex()


def area(items):
    return "".join(item(c, v) for c, v in items)


def model(table, items):
    """Decoded keys: the first occurrence of each mapped code."""
    m, seen = {}, set()
    for code, v in items:
        if code in table and code not in seen:
            seen.add(code)
            key, size = table[code]
            if size is None:
                m[key] = v
            elif v:
                m[key] = str(int(v, 16))
    return m


def canonical(table, items):
    """What encode writes: mapped codes in ascending code order (the order of the
    pack's lines), each once; then the codes no line maps, in input order."""
    mapped, rest, seen = {}, [], set()
    for code, v in items:
        if code in table:
            if code not in seen:
                seen.add(code)
                mapped[code] = v
        else:
            rest.append((code, v))
    return area(sorted(mapped.items()) + rest)


REF6 = "RFC 9915 section 21 (option format and the sizes of the integer options); %s; written by tools/gen/ietf-options-vectors.py"
REFE = "RFC 6891 section 6.1.2 (option format); %s; written by tools/gen/ietf-options-vectors.py"


def vec(pack, name, inp, expect=None, model=None, ref="", error=None):
    v = {"name": name, "from": pack, "to": pack, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model is not None:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = ref
    return v


def dhcpv6():
    p, T, out = "dhcpv6-options", DHCPV6, []
    duid = "000100012f1e2d3c001122334455"            # DUID-LLT, written for these vectors
    ia_na = "0000000a" + "00000e10" + "00001518"      # IAID 10, T1 3600, T2 5400, no nested options
    solicit = [(1, duid), (3, ia_na), (6, "00170018"), (8, "0000"), (14, "")]
    s = area(solicit)
    out.append(vec(p, "solicit-options-round-trip", s, s, model(T, solicit),
                   REF6 % "client identifier, IA_NA (its 12 fixed octets as hex), option request for codes 23 and 24, "
                          "elapsed time 0, rapid commit (empty: the empty string under hex)"))
    reply = [(1, duid), (2, "0001000127a1b2c3aabbccddeeff"), (7, "ff"), (23, "20010db8000000000000000000000053"),
             (32, "00015180"), (82, "00000e10")]
    r = area(reply)
    out.append(vec(p, "reply-options-integers", r, r, model(T, reply),
                   REF6 % "preference 255 (1 octet), information refresh time 86400 s and SOL_MAX_RT 3600 s (4 "
                          "octets each), one DNS server address as hex"))
    shuffled = [(8, "0064"), (1, duid), (6, "0017")]
    out.append(vec(p, "options-written-in-code-order", area(shuffled), canonical(T, shuffled), model(T, shuffled),
                   REF6 % "the input's order is not kept: encode writes the mapped options in the order of the "
                          "pack's lines, ascending code; elapsed time 100 (one second)"))
    two = [(1, duid), (3, ia_na), (3, "0000000b00000e1000001518"), (25, "0000000c0000000000000000")]
    out.append(vec(p, "repeated-option-only-the-first", area(two), canonical(T, two), model(T, two),
                   REF6 % "two IA_NA options: the first is read and written, the second is not carried "
                          "(engine-spec 0.13, Locators); IA_PD as hex"))
    unknown = [(1, duid), (65000, "cafe"), (150, "01")]
    out.append(vec(p, "unregistered-code-kept-as-residue", area(unknown), canonical(T, unknown),
                   model(T, unknown),
                   REF6 % "code 65000 is not in the registry and has no line: it is residue and is written back "
                          "after the mapped options; code 150 is mapped as hex"))
    cut = area([(1, duid)])[:-4]
    out.append(vec(p, "option-longer-than-the-area", cut, error="malformed-wire",
                   ref="the client identifier states 14 octets and the input ends two octets early "
                       "(engine-spec 0.13, Reading a message, step 3)"))
    out.append(vec(p, "empty-options-area", "", "", {},
                   ref="an empty input is an empty set; it encodes to nothing (engine-spec 0.13, step 3)"))
    return p, out


def edns0():
    p, T, out = "edns0-options", EDNS0, []
    q = [(3, ""), (10, "24a1c4d5e6f70809")]
    s = area(q)
    out.append(vec(p, "query-nsid-and-client-cookie", s, s, model(T, q),
                   REFE % "a query asking for the name server identifier (empty value) and carrying an 8-octet "
                          "client cookie (code 10)"))
    resp = [(3, "6e73312e6578616d706c65"), (10, "24a1c4d5e6f708090011223344556677"), (12, "00" * 6),
            (15, "0012")]
    r = area(resp)
    out.append(vec(p, "response-options", r, r, model(T, resp),
                   REFE % "an NSID, a client and server cookie, six octets of padding and an extended DNS error "
                          "with info-code 18 and no text, each as hex"))
    sub = [(8, "0001180020010db8"), (65001, "aa")]
    out.append(vec(p, "unregistered-code-kept-as-residue", area(sub), canonical(T, sub), model(T, sub),
                   REFE % "a client-subnet option as hex, and an unassigned code kept as residue"))
    out.append(vec(p, "option-longer-than-the-rdata", area([(10, "24a1c4d5e6f70809")])[:-2], error="malformed-wire",
                   ref="the cookie states 8 octets and the input holds 7 (engine-spec 0.13, step 3)"))
    return p, out


def build(out):
    written = {}
    for make in (dhcpv6, edns0):
        pack, vecs = make()
        assert len({v["name"] for v in vecs}) == len(vecs)
        names = set()
        for i, v in enumerate(vecs, 1):
            rel = "packs/%s/vectors/%02d-%s.json" % (pack, i, v["name"])
            names.add(rel.rsplit("/", 1)[1])
            out.write(rel, json.dumps(v, indent=2) + "\n")
        for old in out.listdir("packs/%s/vectors" % pack):
            if old not in names:
                out.remove("packs/%s/vectors/%s" % (pack, old))
        written[pack] = len(vecs)
    return written


def main(argv=None):
    return genio.vector_main("ietf-options-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
