# Pack: dns-message

A whole DNS message (RFC 1035 section 4.1): the header, the question section, and the answer, authority
and additional sections with their resource records. Wire `bits`, `layout sequential`, most significant
bit first. No kind. One message is one UDP payload (or a TCP message without its 2-octet length prefix).
Written by `tools/gen/inet-more-pack.py`.

`dns-header` (on main) reads the 12-octet header; this pack reads the sections too.

## What is mapped

- **Header** on the `inet` keys of `dns-header` (ID, QR, opcode, AA, TC, RD, RA, Z, RCODE). The four
  section counts are `count` lines, written from the lists.
- **Names** (question name, record owner, NS/CNAME/PTR/MX/SRV target, SOA MNAME and RNAME): each label is
  a 2-bit tag, then for an ordinary label (tag 0) its length and its characters (`chars:ascii8`); a zero
  length ends the name; a compression pointer (tag 3) ends it with the pointer's 14-bit offset, kept as
  a number. Up to 10 labels per name are read.
- **Question**: name, type, class.
- **Resource records**: owner, type, then for OPT (41) the EDNS fields (UDP payload size, extended RCODE,
  version, DO, Z) and the EDNS options (code and data octets); for every other type the class, TTL and
  RDATA in the extent of the RDATA length: A (address as the 32-bit integer), AAAA (hex), NS, CNAME, PTR
  (target name), MX (preference, exchange), TXT (the character strings), SOA (names and the five
  counters), SRV (priority, weight, port, target), CAA (flags, tag, value); other types as octets.

## Shared keys

None of `core` or `track`. The header uses the `inet` keys of `dns-header`; the section counts of
`dns-header` (`inet.dns_qdcount` and the others) are not keys here, because this pack writes them from the
lists.

## Not mapped

- **Following compression pointers**: a pointer names an offset earlier in the message; resolving it is
  a lookup into the message, not a layout. The pointer is kept as its offset, and the labels before it.
  Needed: a reference to an earlier position of the message, or a name transform.
- **The name as one text**: a name is up to 10 label keys (`qname_label1` ...), since a run that ends on
  a value inside an item cannot be a list, and a label's characters need a size a `switch` on the length
  chooses. Labels with octets outside 0x20-0x7E (binary labels) do not decode. Names of more than 10
  labels (reverse IPv6 names have 34) are `no-kind`. Needed: a list that ends at an item whose field has a
  given value, and text whose length a field gives.
- **The pack's size**: each name is ten levels of 63 cases, and records appear in three sections, so the
  generated pack is about 18,600 lines.
- RDATA of other types is octets; EDNS option data is octets.

## Vectors

`tools/gen/inet-more-vectors.py`, without an engine: an A query; a CNAME and A response with compression
pointers; MX and TXT; a name error with SOA; an mDNS-style SRV and AAAA response; a query with EDNS OPT and
a cookie; CAA; an HINFO record as octets; a name of eleven labels (`no-kind`); a cut question
(`malformed-wire`).
