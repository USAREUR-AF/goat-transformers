#!/usr/bin/env python3
"""biblio-vectors: write the vectors of marc21-record.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of:
- the Library of Congress MARC 21 pages: a record is the 24-character leader (record length at 00-04,
  the codes at 05-11, the base address of data at 12-16, codes at 17-19, the entry map 4500 at 20-23),
  the directory of 12-character entries (tag 3, field length 4, starting position 5), a field
  terminator 0x1E, the variable fields each ended by 0x1E, and the record terminator 0x1D; the record
  length counts the whole record, the base address the leader and directory with its terminator.

Inputs: records built here from values chosen here; the bibliographic data is invented. The MARC
lengths and positions are computed here. `expect` of a round trip is the input. `model` holds values
that were packed.

Usage: python3 -I tools/gen/biblio-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/biblio-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_M = "the Library of Congress MARC 21 Leader, Directory and Introduction pages"


def vec(pack, name, inp, model=None, error=None, ref="", note=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


def marc(leader_codes, fields):
    """leader_codes: the 19 code characters at 05-11 and 17-23; fields: [(tag, data without terminator)]."""
    directory, data, pos = b"", b"", 0
    for tag, body in fields:
        f = body + b"\x1e"
        directory += tag.encode() + b"%04d" % len(f) + b"%05d" % pos
        data += f
        pos += len(f)
    data += b"\x1d"
    base = 24 + len(directory) + 1
    total = base + len(data)
    c = leader_codes
    leader = b"%05d" % total + c[0:7].encode() + b"%05d" % base + c[7:14].encode()
    assert len(leader) == 24
    return leader + directory + b"\x1e" + data


def marc_vectors():
    P = "marc21-record"
    out = []
    a = marc("nam a22" + " a 4500", [("001", b"ex0000001"), ("008", b"240115s2024    xxu           000 0 eng d"),
                                       ("245", b"10\x1faA study of example data /\x1fcJane Doe.")])
    out.append(("01-book-record-roundtrip.json", vec(P, "book-record-roundtrip", a,
                {"marc.record_length": "%05d" % len(a), "marc.record_status": "n", "marc.type_of_record": "a", "marc.bibliographic_level": "m",
                 "marc.character_coding_scheme": "a", "marc.indicator_count": "2", "marc.base_address": "%05d" % (24 + 36 + 1),
                 "marc.length_of_field_length": "4", "marc.directory.#": "4", "marc.directory[0].marc.entry_first": "48",
                 "marc.directory[0].marc.tag_rest": "01", "marc.directory[0].marc.field_length": "0010",
                 "marc.directory[0].marc.starting_position": "00000", "marc.directory[3].marc.entry_first": "30"},
                ref=R_M, note="an invented Unicode monograph record with fields 001, 008 and 245; lengths and positions computed")))
    b = marc("cem a22" + "1i 4500", [("001", b"ex0000002"), ("034", b"1 \x1faa\x1fb24000")])
    out.append(("02-map-record-roundtrip.json", vec(P, "map-record-roundtrip", b,
                {"marc.record_status": "c", "marc.type_of_record": "e", "marc.encoding_level": "1", "marc.directory.#": "3"},
                ref=R_M, note="a corrected cartographic record with two fields")))
    out.append(("03-cut-leader-is-malformed.json", vec(P, "cut-leader-is-malformed", a[:20], error="malformed-wire",
                ref=R_M, note="20 of the 24 leader characters")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (marc_vectors(),):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("biblio-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
