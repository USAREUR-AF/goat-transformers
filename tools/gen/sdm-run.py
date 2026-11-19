#!/usr/bin/env python3
"""sdm-run: regenerate the FIWARE Smart Data Models packs, one pack per data model.

Usage: python3 -I tools/gen/sdm-run.py [--check] <sources> <goat-transformers checkout>

With --check nothing is written: every run compares what it would write with the
checkout, all runs are made, and the exit status is 1 when any file differs.

<sources> holds one shallow git checkout per subject repository of
https://github.com/smart-data-models, each at the commit in COMMITS (checked).
For every model in MODELS this runs tools/gen/jsonschema2pack.py on the model's
own `model.yaml` (the model's schema with every reference resolved, so the shared
`common-schema.json` of smart-data-models/data-models, which states no license, is
not read) and writes packs/sdm-<subject>-<model>/ (pack.def, pack.md, vectors,
PROVENANCE.md), model/sdm<model>.def and tools/gen/names/sdm-<subject>-<model>.json.

Form: NGSI key-values (NGSI-v2 `keyValues`, NGSI-LD concise key-values without
@context), the shape `model.yaml` and `schema.json` describe. Wire `json`.
Python 3 standard library only.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio              # noqa: E402  (the directory of this file is put on the path above)
import jsonschema2pack    # noqa: E402

COMMITS = {
    "dataModel.Aeronautics": "58682c9d9d53ee76140b0b2563ece65c9b0a3cfa",
    "dataModel.Device": "eb22fd87a9d89cf68099b0eef1c796969eae5bbf",
    "dataModel.Environment": "2f048407ccc243df67aee7e1b1ca5470092d743e",
    "dataModel.MarineTransport": "4ffb0d8d8c29470e169df9d8c329135ec0806f72",
    "dataModel.PointOfInterest": "7e5e24963a142b9bf6fd15b144a0e24588217608",
    "dataModel.Transportation": "48e0e7ebaaee430f04a47efb27fc38825f79b725",
    "dataModel.UrbanMobility": "81a052c84d275a71489910c4f93eb3b6c80c4830",
    "dataModel.Weather": "803fec05b20cef20abda29cd70f54c3b88e08e3a",
}

# (subject repository, model, where the license is stated):
#   model    the model's own LICENSE.md
#   subject  the subject repository's LICENSE (it covers every model of the subject)
#   schema   the `license` member of the model's schema.json (no LICENSE.md)
MODELS = [
    ("dataModel.Aeronautics", "Aircraft", "model"),
    ("dataModel.Aeronautics", "AircraftModel", "model"),
    ("dataModel.Aeronautics", "Airline", "model"),
    ("dataModel.Aeronautics", "Airport", "model"),
    ("dataModel.Aeronautics", "Flight", "model"),
    ("dataModel.Aeronautics", "FlightNotification", "model"),
    ("dataModel.Device", "Camera", "model"),
    ("dataModel.Device", "Device", "model"),
    ("dataModel.Device", "DeviceMeasurement", "model"),
    ("dataModel.Device", "DeviceModel", "model"),
    ("dataModel.Device", "DeviceOperation", "model"),
    ("dataModel.Device", "Modbus", "model"),
    ("dataModel.Device", "PolarH10", "schema"),
    ("dataModel.Device", "PrivacyObject", "model"),
    ("dataModel.Device", "SenseHat", "schema"),
    ("dataModel.Device", "SmartMeteringObservation", "model"),
    ("dataModel.Device", "UWBAnchor", "schema"),
    ("dataModel.Environment", "AeroAllergenObserved", "model"),
    ("dataModel.Environment", "AirQualityForecast", "model"),
    ("dataModel.Environment", "AirQualityMonitoring", "model"),
    ("dataModel.Environment", "AirQualityObserved", "model"),
    ("dataModel.Environment", "CarbonFootprint", "subject"),
    ("dataModel.Environment", "ElectroMagneticObserved", "model"),
    ("dataModel.Environment", "EnvironmentObserved", "model"),
    ("dataModel.Environment", "FloodMonitoring", "model"),
    ("dataModel.Environment", "IndoorEnvironmentObserved", "model"),
    ("dataModel.Environment", "MosquitoDensity", "model"),
    ("dataModel.Environment", "NightSkyQuality", "subject"),
    ("dataModel.Environment", "NoiseLevelObserved", "model"),
    ("dataModel.Environment", "NoisePollution", "model"),
    ("dataModel.Environment", "NoisePollutionForecast", "model"),
    ("dataModel.Environment", "PhreaticObserved", "model"),
    ("dataModel.Environment", "RainFallRadarObserved", "model"),
    ("dataModel.Environment", "TrafficEnvironmentImpact", "model"),
    ("dataModel.Environment", "TrafficEnvironmentImpactForecast", "model"),
    ("dataModel.Environment", "WaterObserved", "model"),
    ("dataModel.MarineTransport", "Berth", "model"),
    ("dataModel.MarineTransport", "Booking", "model"),
    ("dataModel.MarineTransport", "EdiCodeco", "model"),
    ("dataModel.MarineTransport", "Port", "model"),
    ("dataModel.MarineTransport", "PortAuthority", "model"),
    ("dataModel.MarineTransport", "PortCall", "model"),
    ("dataModel.MarineTransport", "Vessel", "model"),
    ("dataModel.PointOfInterest", "Beach", "model"),
    ("dataModel.PointOfInterest", "Museum", "model"),
    ("dataModel.PointOfInterest", "PointOfInterest", "model"),
    ("dataModel.PointOfInterest", "Store", "model"),
    ("dataModel.Transportation", "APDSObservation", "model"),
    ("dataModel.Transportation", "AnonymousCommuterId", "model"),
    ("dataModel.Transportation", "AnprFlowObserved", "model"),
    ("dataModel.Transportation", "BikeHireDockingStation", "model"),
    ("dataModel.Transportation", "BikeLane", "model"),
    ("dataModel.Transportation", "CityWork", "model"),
    ("dataModel.Transportation", "CrowdFlowObserved", "model"),
    ("dataModel.Transportation", "EVChargingStation", "model"),
    ("dataModel.Transportation", "FareCollectionSystem", "model"),
    ("dataModel.Transportation", "FleetVehicle", "model"),
    ("dataModel.Transportation", "FleetVehicleOperation", "model"),
    ("dataModel.Transportation", "FleetVehicleStatus", "model"),
    ("dataModel.Transportation", "ItemFlowObserved", "model"),
    ("dataModel.Transportation", "RestrictedTrafficArea", "model"),
    ("dataModel.Transportation", "RestrictionException", "model"),
    ("dataModel.Transportation", "Road", "model"),
    ("dataModel.Transportation", "RoadAccident", "model"),
    ("dataModel.Transportation", "RoadSegment", "model"),
    ("dataModel.Transportation", "SpecialRestriction", "model"),
    ("dataModel.Transportation", "TrafficFlowObserved", "model"),
    ("dataModel.Transportation", "TrafficViolation", "model"),
    ("dataModel.Transportation", "TransportStation", "model"),
    ("dataModel.Transportation", "Vehicle", "model"),
    ("dataModel.Transportation", "VehicleFault", "model"),
    ("dataModel.Transportation", "VehicleModel", "model"),
    ("dataModel.UrbanMobility", "ArrivalEstimation", "model"),
    ("dataModel.UrbanMobility", "GtfsAccessPoint", "model"),
    ("dataModel.UrbanMobility", "GtfsAgency", "model"),
    ("dataModel.UrbanMobility", "GtfsCalendarDateRule", "model"),
    ("dataModel.UrbanMobility", "GtfsCalendarRule", "model"),
    ("dataModel.UrbanMobility", "GtfsFrequency", "model"),
    ("dataModel.UrbanMobility", "GtfsRoute", "model"),
    ("dataModel.UrbanMobility", "GtfsService", "model"),
    ("dataModel.UrbanMobility", "GtfsShape", "model"),
    ("dataModel.UrbanMobility", "GtfsStation", "model"),
    ("dataModel.UrbanMobility", "GtfsStop", "model"),
    ("dataModel.UrbanMobility", "GtfsStopTime", "model"),
    ("dataModel.UrbanMobility", "GtfsTransferRule", "model"),
    ("dataModel.UrbanMobility", "GtfsTrip", "model"),
    ("dataModel.UrbanMobility", "PublicTransportRoute", "model"),
    ("dataModel.UrbanMobility", "PublicTransportStop", "model"),
    ("dataModel.UrbanMobility", "TransitManagement", "model"),
    ("dataModel.Weather", "SeaConditions", "model"),
    ("dataModel.Weather", "WeatherAlert", "model"),
    ("dataModel.Weather", "WeatherForecast", "model"),
    ("dataModel.Weather", "WeatherObserved", "model"),
]

# Not generated: no license in the model directory, the subject repository or the
# schema (or no model.yaml). Listed so the skip is a decision, not an omission.
SKIPPED = [
    ("dataModel.MarineTransport", "AisVessel", "no-license"),
    ("dataModel.MarineTransport", "Bollard", "no-license"),
    ("dataModel.MarineTransport", "Company", "no-license"),
    ("dataModel.MarineTransport", "Facility", "no-license"),
    ("dataModel.MarineTransport", "KeyVessel", "no-license"),
    ("dataModel.MarineTransport", "MasterVessel", "no-license"),
    ("dataModel.MarineTransport", "Metocean", "no-license"),
    ("dataModel.MarineTransport", "NavigationSector", "no-license"),
    ("dataModel.MarineTransport", "Operation", "no-license"),
    ("dataModel.MarineTransport", "PortCallEvent", "no-model.yaml"),
    ("dataModel.MarineTransport", "Terminal", "no-license"),
    ("dataModel.MarineTransport", "TrackedManeuver", "no-license"),
    ("dataModel.Transportation", "ElectricVehicleMobility", "no-license"),
    ("dataModel.Transportation", "OriginDestinationFlow", "no-license"),
]

# Shared-key bindings beyond `uid` = `id` (every model: "Unique identifier of the entity").
# time_ms: `dateObserved` where the model states one instant in UTC (format date-time,
# "... ISO8601 UTC format", no interval). course: Vehicle `heading`, stated as the
# direction of travel in degrees clockwise from true north.
TIME_OBSERVED = {"DeviceMeasurement", "AirQualityObserved", "PhreaticObserved", "WaterObserved",
                 "BikeLane", "SeaConditions"}
EXTRA_MAPS = {"Vehicle": ["heading=course"]}

# Conversion vectors from the hand-written geojson vector, for three models.
CROSS = {"Vehicle", "AirQualityObserved", "SeaConditions"}


def kebab(name):
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    return s.lower()


def subject_short(repo):
    return repo.split(".", 1)[1].lower()


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def first_line(path):
    with open(path, encoding="utf-8") as fh:
        for l in fh:
            if l.strip():
                return l.strip().lstrip("# ").strip()
    return ""


def provenance(src, repo, model, how, fmt):
    d = os.path.join(src, repo, model)
    url = "https://github.com/smart-data-models/%s" % repo
    commit = COMMITS[repo]
    rows = [("model.yaml", sha256(os.path.join(d, "model.yaml"))),
            ("schema.json", sha256(os.path.join(d, "schema.json")))]
    if how == "model":
        lic_path = os.path.join(d, "LICENSE.md")
        rows.append(("LICENSE.md", sha256(lic_path)))
        lic = first_line(lic_path)
        if "Creative Commons Attribution 4.0" in lic:
            stmt = ("`%s/LICENSE.md` is the Creative Commons Attribution 4.0 International Public "
                    "License; its first line:\n\n> # Creative Commons Attribution 4.0 International Public License"
                    % model)
        else:
            # the MIT form asks that its notice go with copies: quoted in full
            with open(lic_path, encoding="utf-8") as fh:
                text = fh.read().strip()
            stmt = ("`%s/LICENSE.md` is a permissive license of the MIT form. Its copyright and permission "
                    "notice, which it asks to be included with copies, in full:\n\n%s"
                    % (model, "\n".join("> " + l if l.strip() else ">" for l in text.split("\n"))))
    elif how == "subject":
        lic_path = os.path.join(src, repo, "LICENSE")
        rows.append(("../LICENSE (subject)", sha256(lic_path)))
        stmt = ("The model has no LICENSE.md. The subject repository's `LICENSE` covers every model of "
                "the subject:\n\n> %s" % first_line(lic_path))
    else:
        with open(os.path.join(d, "schema.json"), encoding="utf-8") as fh:
            lic = json.load(fh).get("license")
        stmt = ("The model has no LICENSE.md and the subject repository has no LICENSE. The model's "
                "`schema.json` states its license in its `license` member: `%s` (CC BY 4.0)." % lic)
    out = ["# Provenance of the %s pack\n" % fmt,
           "`tools/gen/sdm-run.py` runs `tools/gen/jsonschema2pack.py` on the model's `model.yaml` and",
           "nothing else. The files are not kept in this repository. Read on 2026-11-19.\n",
           "| | |\n|---|---|",
           "| Document | FIWARE Smart Data Models, subject `%s`, data model `%s` |" % (repo, model),
           "| Publisher | Smart Data Models program (FIWARE Foundation, TM Forum, IUDX, OASC and others) |",
           "| Repository | %s at commit `%s`, directory `%s/` |" % (url, commit, model),
           "| Download | `https://raw.githubusercontent.com/smart-data-models/%s/%s/%s/model.yaml` |"
           % (repo, commit, model), "",
           "| File | SHA-256 | Read by the generator |\n|---|---|---|"]
    for name, h in rows:
        out.append("| `%s` | `%s` | %s |" % (name, h, "yes" if name == "model.yaml" else "no"))
    out += ["", "## License\n", stmt, "",
            "Attribution: the pack is derived from the Smart Data Model `%s` of the subject `%s`; it "
            "restates the model's structure with keys of this project's naming and is not endorsed by "
            "the Smart Data Models program." % (model, repo), ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sdm-run", description=__doc__.split("\n\n")[0])
    ap.add_argument("sources", help="the directory of the subject checkouts")
    ap.add_argument("checkout", help="the goat-transformers checkout to write into")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; compare every pack, module, names file and PROVENANCE.md "
                         "with the checkout and exit 1 when any file differs")
    args = ap.parse_args(argv)
    src, gt = os.path.abspath(args.sources), os.path.abspath(args.checkout)
    gen = os.path.join(gt, "tools", "gen")
    for repo, commit in COMMITS.items():
        got = subprocess.run(["git", "-C", os.path.join(src, repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        if got != commit:
            print("sdm-run: %s is at %s, not %s" % (repo, got, commit), file=sys.stderr)
            return 1
    out = genio.Output(gt, check=args.check)
    status = 0
    for repo, model, how in MODELS:
        fmt = "sdm-%s-%s" % (subject_short(repo), kebab(model))
        module = "sdm" + model.lower()
        my = os.path.join(src, repo, model, "model.yaml")
        lic = "MIT-style (APDS)" if how == "model" and "APDS" in first_line(
            os.path.join(src, repo, model, "LICENSE.md")) else "CC-BY-4.0"
        argv2 = ["--schema", my, "--message", "%s=%s#/%s" % (model, my, model),
                 "--when", "type=%s" % model, "--map", "%s:id=uid" % model,
                 "--format", fmt, "--module", module,
                 "--title", "FIWARE Smart Data Model %s / %s (NGSI key-values)" % (repo, model),
                 "--license", "%s, smart-data-models/%s %s/" % (lic, repo, model),
                 "--source", "https://github.com/smart-data-models/%s at commit %s, %s/model.yaml"
                 % (repo, COMMITS[repo], model),
                 "--out", gt, "--model-dir", os.path.join(gt, "model"),
                 "--names-file", os.path.join(gen, "names", fmt + ".json"),
                 "--notes-file", os.path.join(gen, "notes", "sdm.md")]
        if model in TIME_OBSERVED:
            argv2 += ["--map", "%s:dateObserved=time_ms" % model]
        for m in EXTRA_MAPS.get(model, []):
            argv2 += ["--map", "%s:%s" % (model, m)]
        if model in CROSS:
            argv2 += ["--cross", "%s=%s:input" % (os.path.join(gt, "packs", "geojson", "pack.def"),
                                                 os.path.join(gt, "packs", "geojson", "vectors",
                                                              "01-geojson-to-cot.json"))]
        if args.check:
            argv2.append("--check")
        # the generator in this process: its summary goes to /dev/null, its report to stderr
        with open(os.devnull, "w") as null, contextlib.redirect_stdout(null):
            run = jsonschema2pack.main(argv2)
        if run:
            status = 1
            if not args.check:
                print("sdm-run: %s failed" % fmt, file=sys.stderr)
                return 1
        out.write("packs/%s/PROVENANCE.md" % fmt, provenance(src, repo, model, how, fmt))
        if not args.check:
            print(fmt)
    return max(status, out.report("sdm-run (PROVENANCE.md)"))


if __name__ == "__main__":
    sys.exit(main())
