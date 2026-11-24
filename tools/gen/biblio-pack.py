#!/usr/bin/env python3
"""Write the MARC 21 record pack and its module:

- marc21-record: one MARC 21 record in the ISO 2709 exchange structure: the 24-character leader by
  position, the directory entries (tag, field length, starting position), the field terminator that
  ends the directory, and the variable fields as octets. Positions restated from the Library of
  Congress's MARC 21 Format for Bibliographic Data (Leader, Directory, Introduction pages).

CSL-JSON items are written by tools/gen/csl-run.sh (jsonschema2pack), not here.
The vectors are not written here: tools/gen/biblio-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/biblio-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "marc": ('source        "Library of Congress, MARC 21 Format for Bibliographic Data, https://www.loc.gov/marc/bibliographic/bdleader.html, '
             'bddirectory.html and bdintro.html (maintained with Library and Archives Canada; excerpts with credit); positions restated, no text copied"'),
}

LEADER = [("record_length", 5, "00-04 record length: the whole record's length in characters, five digits"),
          ("record_status", 1, "05 record status (a, c, d, n, p)"), ("type_of_record", 1, "06 type of record (a language material, e cartographic, g projected medium ...)"),
          ("bibliographic_level", 1, "07 bibliographic level (a, b, c, d, i, m, s)"), ("type_of_control", 1, "08 type of control (blank, a archival)"),
          ("character_coding_scheme", 1, "09 character coding scheme (blank MARC-8, a UCS/Unicode)"), ("indicator_count", 1, "10 indicator count (2)"),
          ("subfield_code_count", 1, "11 subfield code count (2)"), ("base_address", 5, "12-16 base address of data: the length of the leader and directory, five digits"),
          ("encoding_level", 1, "17 encoding level"), ("descriptive_cataloging_form", 1, "18 descriptive cataloging form"),
          ("multipart_resource_level", 1, "19 multipart resource record level"), ("length_of_field_length", 1, "20 length of the length-of-field portion (4)"),
          ("length_of_starting_position", 1, "21 length of the starting-character-position portion (5)"),
          ("length_of_implementation_portion", 1, "22 length of the implementation-defined portion (0)"), ("undefined", 1, "23 undefined (0)")]


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for t, k, d in keys:
        L.append('list  %-*s  "%s"' % (w, k, d) if t == "list" else 'key   %-*s  %-6s  -  "%s"' % (w, k, t, d))
    return "\n".join(L) + "\n"


def head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", src] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def marc_pack():
    L = head("marc21-record", ["MARC 21 record (ISO 2709 structure): leader, directory, field terminator, variable fields. Written by",
                               "tools/gen/biblio-pack.py; do not edit by hand."], SRC["marc"], ["marc"])
    L += ["field  marc.%s  %d  chars:ascii8" % (k, 8 * n) for k, n, _ in LEADER]
    L += ["group  marc.directory  rest", "  field  marc.entry_first  8  uint", "  switch  marc.entry_first", "    case  30",
          "      group  marc.field_data  rest", "        field  marc.octet  8  uint", "      end", "    else",
          "      field  marc.tag_rest  16  chars:ascii8", "      field  marc.field_length  32  chars:ascii8",
          "      field  marc.starting_position  40  chars:ascii8", "  end", "end"]
    return "\n".join(L) + "\n"


MARC_KEYS = ([("string", k, "leader " + d) for k, _, d in LEADER] +
             [("list", "directory", "the directory entries in order; the last item is the field terminator that ends the directory, holding the variable fields"),
              ("int", "entry_first", "a directory entry's first character code (the tag's first character), or 30 (the field terminator) for the item that holds the variable fields"),
              ("string", "tag_rest", "a directory entry: the tag's second and third characters"),
              ("string", "field_length", "a directory entry: the field's length, four digits"),
              ("string", "starting_position", "a directory entry: the field's starting position relative to the base address, five digits"),
              ("list", "field_data", "the variable fields after the directory, as octets (each ended by 0x1E, the last also by 0x1D)"),
              ("int", "octet", "one octet")])


def build(out):
    out.write("packs/marc21-record/pack.def", marc_pack())
    out.write("model/marc.def", module("marc", ["# The marc module: MARC 21 leader and directory fields. Written by tools/gen/biblio-pack.py."], SRC["marc"], MARC_KEYS))
    return {"biblio": 2}


def main(argv=None):
    return genio.vector_main("biblio-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
