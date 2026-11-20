#!/usr/bin/env python3
"""Write the vectors of the ogcapi-coverages-coverage pack.

The pack reads one coverage in the JSON encoding of the OGC Coverage Implementation Schema
(CIS) 1.1.1 (OGC 09-146r8), written by hand from the standard's text. This script holds its
own copy of the pack's lines (member path, transform, model key) in the pack's order,
builds every message from values written for these vectors (none is taken from the
standard's example), and works out the canonical output and the decoded values by the
rules of spec/engine-spec.md: the json wire (0.5) and groups (0.7). It reads no pack.def
and calls no goat-transformers engine.

Canonical json (0.5): an object's mapped members in line order, a nested object at the
position of the first line that addresses into it, then that object's residue scalars in
input order; arrays, and anything inside an array that no line maps, are not carried;
items of a group carry no residue (0.7). Numbers: an integer as decimal digits.
A value of the wrong JSON type for its transform is a transform decode failure.

Usage: python3 -I tools/gen/ogcapi-coverages-vectors.py [--out DIR] [--check]
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

PACK = "ogcapi-coverages-coverage"
M = "ogccovcis."
REF = "OGC CIS 1.1.1 (OGC 09-146r8), structure tables of clauses 6 to 8 and the JSON encoding of clause 13"
SOURCE = "derived by tools/gen/ogcapi-coverages-vectors.py from the pack's member list and spec/engine-spec.md; no engine run"

# The pack's lines, in order: (path, transform, key) or (path, None, (list, item lines)).
# Transforms: s string, i int. An item line with path "." is the item itself.
LINES = [
    ("type", "s", "type"), ("id", "s", "id"),
    ("envelope.type", "s", "envelope_type"), ("envelope.srsName", "s", "envelope_srs_name"),
    ("envelope.srsDimension", "i", "envelope_srs_dimension"),
    ("envelope.axisLabels", None, ("envelope_axis_labels", [(".", "s", "envelope_axis_labels_value")])),
    ("envelope.axisExtent", None, ("envelope_axis_extent", [
        ("type", "s", "envelope_axis_extent_type"), ("axisLabel", "s", "envelope_axis_extent_axis_label"),
        ("uomLabel", "s", "envelope_axis_extent_uom_label"), ("lowerBound", "s", "envelope_axis_extent_lower_bound"),
        ("upperBound", "s", "envelope_axis_extent_upper_bound")])),
    ("domainSet.type", "s", "domain_set_type"), ("domainSet.generalGrid.type", "s", "grid_type"),
    ("domainSet.generalGrid.srsName", "s", "grid_srs_name"),
    ("domainSet.generalGrid.axisLabels", None, ("grid_axis_labels", [(".", "s", "grid_axis_labels_value")])),
    ("domainSet.generalGrid.axis", None, ("grid_axis", [
        ("type", "s", "grid_axis_type"), ("axisLabel", "s", "grid_axis_axis_label"),
        ("uomLabel", "s", "grid_axis_uom_label"), ("resolution", "s", "grid_axis_resolution")])),
    ("domainSet.generalGrid.gridLimits.type", "s", "grid_limits_type"),
    ("domainSet.generalGrid.gridLimits.srsName", "s", "grid_limits_srs_name"),
    ("domainSet.generalGrid.gridLimits.indexAxis", None, ("grid_limits_index_axis", [
        ("type", "s", "grid_limits_index_axis_type"), ("axisLabel", "s", "grid_limits_index_axis_axis_label"),
        ("lowerBound", "i", "grid_limits_index_axis_lower_bound"),
        ("upperBound", "i", "grid_limits_index_axis_upper_bound")])),
    ("rangeSet.type", "s", "range_set_type"), ("rangeSet.dataBlock.type", "s", "data_block_type"),
    ("rangeType.type", "s", "range_type_type"),
    ("rangeType.field", None, ("range_type_field", [
        ("type", "s", "range_type_field_type"), ("name", "s", "range_type_field_name"),
        ("definition", "s", "range_type_field_definition"), ("uom.type", "s", "range_type_field_uom_type"),
        ("uom.code", "s", "range_type_field_uom_code")])),
]


def get(obj, path):
    for p in path.split("."):
        if not isinstance(obj, dict) or p not in obj:
            return None
        obj = obj[p]
    return obj


def put(tree, path, value):
    parts = path.split(".")
    for p in parts[:-1]:
        tree = tree.setdefault(p, collections.OrderedDict())
    tree[parts[-1]] = value


def check_type(v, tr):
    if tr == "s" and not isinstance(v, str):
        raise TypeError("transform-decode")
    if tr == "i" and (isinstance(v, bool) or not isinstance(v, int)):
        raise TypeError("transform-decode")
    return v


def canon_lines(obj, lines, model, prefix):
    """The mapped part of one object, as an ordered tree; fills `model`."""
    tree = collections.OrderedDict()
    for path, tr, key in lines:
        v = get(obj, path) if path != "." else obj
        if v is None:
            continue
        if tr is not None:
            put(tree, path, check_type(v, tr))
            model[prefix + M + key] = str(v)
            continue
        lst, items = key
        out = []
        for i, item in enumerate(v):
            ip = "%s%s%s[%d]." % (prefix, M, lst, i)
            if items[0][0] == ".":
                out.append(check_type(item, items[0][1]))
                model[ip + M + items[0][2]] = str(item)
            else:
                out.append(canon_lines(item, items, model, ip))
        put(tree, path, out)
        model["%s%s%s.#" % (prefix, M, lst)] = str(len(v))
    return tree


def residue(src, tree, mapped_paths, base=""):
    """Append the residue scalars of each object (input order) after its mapped members."""
    for k, v in src.items():
        p = base + k
        if isinstance(v, dict):
            if k in tree and isinstance(tree[k], dict):
                residue(v, tree[k], mapped_paths, p + ".")
            continue
        if isinstance(v, list) or v is None or p in mapped_paths:
            continue
        if k not in tree:
            tree[k] = v


def canon(obj):
    model = collections.OrderedDict()
    tree = canon_lines(obj, LINES, model, "")
    residue(obj, tree, {p for p, _, _ in LINES})
    return json.dumps(tree, separators=(",", ":"), ensure_ascii=False), model


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def vec(name, inp, expect=None, model=None, error=None, note=None):
    v = {"name": name, "from": PACK, "to": PACK, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = REF + ("; " + note if note else "")
    return v


def regular_grid():
    """A 2-D regular grid in a lat/long CRS, every mapped member present, written in an order
    of its own, with members the pack does not map."""
    return collections.OrderedDict([
        ("rangeType", {"field": [
            {"uom": {"code": "K", "type": "UnitReference"}, "definition": "https://example.org/def/temperature",
             "name": "surface_temperature", "type": "QuantityType"},
            {"type": "QuantityType", "name": "quality", "definition": "https://example.org/def/quality-flag",
             "uom": {"type": "UnitReference", "code": "1"}}], "type": "DataRecordType"}),
        ("id", "cov-ex-17"),
        ("domainSet", {"generalGrid": {
            "axis": [
                {"axisLabel": "Lat", "type": "RegularAxisType", "lowerBound": "47.5", "upperBound": "48.5",
                 "resolution": "0.25", "uomLabel": "deg"},
                {"type": "RegularAxisType", "axisLabel": "Long", "uomLabel": "deg", "lowerBound": "8",
                 "upperBound": "9", "resolution": "0.5"}],
            "srsName": "http://www.opengis.net/def/crs/EPSG/0/4326", "type": "GeneralGridCoverageType",
            "axisLabels": ["Lat", "Long"],
            "gridLimits": {"indexAxis": [
                {"type": "IndexAxisType", "axisLabel": "i", "lowerBound": 0, "upperBound": 3},
                {"type": "IndexAxisType", "axisLabel": "j", "lowerBound": 0, "upperBound": 1}],
                "srsName": "http://www.opengis.net/def/crs/OGC/0/Index2D", "type": "GridLimitsType"}},
            "type": "DomainSetType"}),
        ("producer", "vector-writer"),
        ("type", "CoverageByDomainAndRangeType"),
        ("envelope", {"srsDimension": 2, "type": "EnvelopeByAxisType", "axisLabels": ["Lat", "Long"],
                      "srsName": "http://www.opengis.net/def/crs/EPSG/0/4326",
                      "axisExtent": [
                          {"axisLabel": "Lat", "uomLabel": "deg", "lowerBound": "47.5", "upperBound": "48.5",
                           "type": "AxisExtentType"},
                          {"type": "AxisExtentType", "axisLabel": "Long", "uomLabel": "deg", "lowerBound": "8",
                           "upperBound": "9"}]}),
        ("rangeSet", {"dataBlock": {"values": [271.5, 272, 273.25, 270, 269.5, 268, 271, 272.5],
                                    "type": "VDataBlockType"}, "type": "RangeSetType"}),
    ])


def index_grid():
    """A 3-D grid of index axes only, no envelope, no grid limits, one range component."""
    return collections.OrderedDict([
        ("type", "CoverageByDomainAndRangeType"), ("id", "cube-3"),
        ("domainSet", {"type": "DomainSetType", "generalGrid": {
            "type": "GeneralGridCoverageType", "srsName": "http://www.opengis.net/def/crs/OGC/0/Index3D",
            "axisLabels": ["i", "j", "k"],
            "axis": [{"type": "IndexAxisType", "axisLabel": "i", "lowerBound": 0, "upperBound": 1},
                     {"type": "IndexAxisType", "axisLabel": "j", "lowerBound": 0, "upperBound": 0},
                     {"type": "IndexAxisType", "axisLabel": "k", "lowerBound": 5, "upperBound": 6}]}}),
        ("rangeSet", {"type": "RangeSetType", "dataBlock": {"type": "VDataBlockType", "values": [1, 2, 3, 4]}}),
        ("rangeType", {"type": "DataRecordType", "field": [{"type": "QuantityType", "name": "count",
                                                            "definition": "https://example.org/def/count",
                                                            "uom": {"type": "UnitReference", "code": "1"}}]}),
    ])


def build_vectors():
    V = collections.OrderedDict()
    cov = regular_grid()
    exp, model = canon(cov)
    V["01-regular-grid-roundtrip"] = vec(
        "regular-grid-roundtrip", js(cov), exp, model,
        note="members in an order of their own become the pack's line order; the top-level member the pack "
             "does not map (producer) is residue after the mapped members; the bounds of a regular axis "
             "(inside the axis array) and the range values (an array) are not carried")
    cov = index_grid()
    exp, model = canon(cov)
    model["@absent"] = [M + "envelope_srs_name", M + "grid_limits_srs_name"]
    V["02-index-grid-roundtrip"] = vec(
        "index-grid-roundtrip", js(cov), exp, model,
        note="no envelope and no grid limits: those objects are not written; an index axis's integer bounds "
             "sit inside the axis array, where no line maps them, and are not carried")
    bad = index_grid()
    bad["envelope"] = {"type": "EnvelopeByAxisType", "srsName": "http://www.opengis.net/def/crs/OGC/0/Index3D",
                       "srsDimension": "3"}
    V["03-srs-dimension-string-error"] = vec(
        "srs-dimension-string-error", js(bad), error="transform-decode",
        note="srsDimension is a positive integer; a JSON string there is the wrong type for `int`")
    bad = regular_grid()
    bad["domainSet"]["generalGrid"]["gridLimits"]["indexAxis"][1]["upperBound"] = 1.5
    V["04-index-bound-fraction-error"] = vec(
        "index-bound-fraction-error", js(bad), error="transform-decode",
        note="an index axis bound is an integer; 1.5 has a fraction")
    return V


def build(out):
    n = 0
    for fn, v in build_vectors().items():
        out.write("packs/%s/vectors/%s.json" % (PACK, fn), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        n += 1
    return {PACK: n}


def main(argv=None):
    return genio.vector_main("ogcapi-coverages-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
