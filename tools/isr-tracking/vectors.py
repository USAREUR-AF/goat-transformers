#!/usr/bin/env python3
"""vectors.py: conversion vectors of the isr-tracking pack.

Writes, for each kind, one XML document that holds every element the data model
gives that object (model.tsv), with made-up values, in the canonical form of the
xml wire: so a round trip returns it unchanged. The documents follow the rules
pack.md states (elements in model order, `type` as an XML attribute, UUID text
with an optional `gidp` attribute, Shape with `xsi:type`). This program reads the
data model only, not the pack, and imports no engine.

Usage: python3 -I tools/isr-tracking/vectors.py   (from the repository root)
"""
import csv
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "packs", "isr-tracking", "vectors")
INTS = {"UInt", "UnsignedInt", "long", "int", "unsignedByte", "unsignedShort", "byte"}
FLOATS = {"double", "float"}
ARRAYS = {"DoubleArray", "IntegerArray", "unsignedByteArray"}
TIME = "2026-11-19T10:15:30.250Z"
TIME_MS = int(datetime.datetime(2026, 11, 19, 10, 15, 30, 250000, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def load():
    m = {}
    with open(os.path.join(HERE, "model.tsv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader([l for l in f if not l.startswith("#")], delimiter="\t"):
            m.setdefault(r["class"], []).append(r)
    return m


class Doc:
    def __init__(self, model):
        self.m = model
        self.n = 0
        self.shapes = 0
        self.uids = []

    def count(self):
        self.n += 1
        return self.n

    def value(self, t):
        n = self.count()
        if t in INTS:
            return str(n % 200)
        if t in FLOATS:
            return "%d.5" % (n % 500)
        if t in ARRAYS:
            return "%d.5 %d.25 %d" % (n, n + 1, n + 2) if t == "DoubleArray" else "%d %d %d" % (n % 250, (n + 1) % 250, (n + 2) % 250)
        if t == "DateTime":
            return TIME
        if t == "Boolean":
            return "true"
        return "%s-%d" % (t.upper()[:6], n)

    def uuid(self, el, many_index=0):
        n = self.count()
        u = "6f1c2e8a-0b4d-4c3e-9a7f-%012d" % n
        self.uids.append(u)
        attr = ' gidp="%d"' % (n % 90) if n % 2 else ""
        return "<%s%s>%s</%s>" % (el, attr, u, el)

    def obj(self, cls, el, top=False, xsi=None):
        """The element <el> of class cls: attributes first (type, xsi:type), then children."""
        attrs, kids = [], []
        rows = list(self.m.get(cls, []))
        if cls == "Shape":
            self.shapes += 1
            concrete = "Polygon" if self.shapes % 2 else "Ellipsoid"
            attrs.append('xsi:type="%s"' % concrete)
            rows += self.m[concrete]
        for r in rows:
            name, t, mult = r["element"], r["type"], r["mult"].strip("[]")
            many = mult.endswith("*")
            reps = 2 if many and (t not in self.m and t != "Shape" or top) else 1
            if name == "type" and t not in self.m:
                attrs.append('type="%s"' % self.value(t))
                continue
            for _ in range(reps):
                if t == "UUID":
                    kids.append(self.uuid(name))
                elif t in self.m or t == "Shape":
                    if t in self.m and not self.m[t]:
                        continue
                    kids.append(self.obj(t, name))
                else:
                    kids.append("<%s>%s</%s>" % (name, self.value(t), name))
        a = (" " + " ".join(attrs)) if attrs else ""
        return "<%s%s>%s</%s>" % (el, a, "".join(kids), el)


KINDS = [("nits", "NITSRoot", "NITSRoot"), ("message", "message", "TrackMessage"), ("track", "track", "TrackData"),
         ("segment", "segment", "TrackSegment"), ("tp", "tp", "TrackPoint"), ("detection", "detection", "Detection"),
         ("object", "object", "TrackedObject"), ("processedTrack", "processedTrack", "ProcessedTrack"),
         ("trackLinkage", "trackLinkage", "TrackLinkage"), ("motionEvent", "motionEvent", "MotionEvent"),
         ("dynSrcInfo", "dynSrcInfo", "DynamicSourceInformation"), ("sensor", "sensor", "SensorInformation"),
         ("tracker", "tracker", "TrackerInformation"), ("collection", "collection", "CollectionInformation"),
         ("product", "product", "ProductIdentification")]


def vec(name, frm, to, inp, exp, model, ref):
    return {"name": "isr-tracking-" + name, "from": frm, "to": to, "input": inp, "expect": exp, "model": model,
            "source": "synthetic", "reference": ref}


def main():
    model = load()
    out = []
    docs = {}
    for kind, root, cls in KINDS:
        d = Doc(model)
        x = d.obj(cls, root, top=True)
        docs[kind] = (x, d)
        m = {"@kind": kind}
        if kind == "nits":
            m.update({"time_ms": str(TIME_MS), "isrtrack.nitsroot_profile.#": "2", "isrtrack.nitsroot_message.#": "2",
                      "isrtrack.nitsroot_message[0].isrtrack.trackmessage_track.#": "1"})
        elif kind == "message":
            m.update({"time_ms": str(TIME_MS), "isrtrack.trackmessage_track.#": "2"})
        else:
            m["uid"] = d.uids[0]
        out.append(vec(kind + "-roundtrip", "isr-tracking", "isr-tracking", x, x, m,
                       "every element the data model gives a %s, values made up" % cls))
    x, d = docs["track"]
    out.append(vec("track-to-geojson", "isr-tracking", "geojson", x,
                   '{"type":"Feature","geometry":null,"properties":{},"id":"%s"}' % d.uids[0], {"uid": d.uids[0]},
                   "a track as a Feature: its UUID is the id; the model gives no position element of its own"))
    for kind in ("nits", "message"):
        x, _ = docs[kind]
        out.append(vec(kind + "-to-cot", "isr-tracking", "cot-xml", x,
                       '<event version="2.0" type="a-u-X" time="%s" start="%s"><point hae="9999999" ce="9999999" '
                       'le="9999999"/><detail/></event>' % (TIME, TIME), {"time_ms": str(TIME_MS)},
                       "the %s time as the CoT event time" % ("creation" if kind == "nits" else "base")))
    out.append(vec("geojson-to-track", "geojson", "isr-tracking",
                   '{"type":"Feature","geometry":{"type":"Point","coordinates":[11.5,48.25,520]},"properties":{},'
                   '"id":"0f8fad5b-d9cb-469f-a165-70867728950e"}',
                   "<track><uid>0f8fad5b-d9cb-469f-a165-70867728950e</uid></track>",
                   {"uid": "0f8fad5b-d9cb-469f-a165-70867728950e"},
                   "an entity of another format with a uid encodes as a track; its position has no element to go to"))
    os.makedirs(OUT, exist_ok=True)
    for old in os.listdir(OUT):
        if old.endswith(".json"):
            os.remove(os.path.join(OUT, old))
    for i, v in enumerate(out, 1):
        with open(os.path.join(OUT, "%02d-%s.json" % (i, v["name"][13:])), "w", encoding="utf-8") as fh:
            json.dump(v, fh, indent=2)
            fh.write("\n")
    print("isr-tracking: %d vectors" % len(out))


if __name__ == "__main__":
    main()
