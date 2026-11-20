#!/usr/bin/env python3
"""Hand-derived vectors of the opcua pack, from OPC 10000-6, section 5.2.

Every byte below is written out from the encoding rules, not computed by a codec:

  TypeId          01 00 79 03   NodeId four-byte form: encoding 1, namespace 0, id 889 (0x0379,
                                little-endian), the Default Binary encoding of EUInformation
  encoding byte   01            the body is binary
  length          Int32, little-endian, the bytes of the body
  body            NamespaceUri (String), UnitId (Int32), DisplayName and Description
                  (LocalizedText: a mask byte, 0x01 locale follows, 0x02 text follows)

01: NamespaceUri "a" (01000000 61), UnitId 5 (05000000), DisplayName text "m"
    (02 01000000 6d), Description empty (00): a body of 16 bytes.
02: the same with a null NamespaceUri (length -1, ffffffff) and no display name: the pack reads
    lengths as unsigned, so the decode is malformed-wire.

    python3 -I tools/gen/opcua-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

HEAD = "01007903" + "01"
BODY1 = "0100000061" + "05000000" + "02010000006d" + "00"
BODY2 = "ffffffff" + "05000000" + "00" + "00"


def build(out):
    m = "opcua."
    v1 = {"name": "opcua-eu-information-hand",
          "from": "opcua", "to": "opcua",
          "source": "worked by hand from OPC 10000-6, 5.2 (tools/gen/opcua-vectors.py)",
          "input": HEAD + "10000000" + BODY1, "expect": HEAD + "10000000" + BODY1,
          "model": {"@kind": "eu_information",
                    m + "eu_information_namespace_uri.#": "1",
                    m + "eu_information_namespace_uri[0]." + m + "eu_information_namespace_uri_byte": "97",
                    m + "eu_information_unit_id": "5",
                    m + "eu_information_display_name_text.#": "1",
                    m + "eu_information_display_name_text[0]." + m + "eu_information_display_name_text_byte": "109"}}
    v2 = {"name": "opcua-eu-information-null-string",
          "from": "opcua", "to": "opcua",
          "source": "worked by hand from OPC 10000-6, 5.2 (tools/gen/opcua-vectors.py): a null String has "
                    "length -1, which the pack's count reads as 4294967295 bytes",
          "input": HEAD + "0a000000" + BODY2, "expect_error": "malformed-wire"}
    out.write("packs/opcua/vectors/01-eu-information-hand.json", json.dumps(v1, indent=2) + "\n")
    out.write("packs/opcua/vectors/02-eu-information-null-string.json", json.dumps(v2, indent=2) + "\n")
    return {"opcua": 2}


if __name__ == "__main__":
    sys.exit(genio.vector_main("opcua-vectors", __doc__.split("\n")[0], build))
