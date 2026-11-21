#!/usr/bin/env python3
"""Write the health data packs and their modules:

- hl7v2-segment: one HL7 version 2 segment line on the text wire, fields split at '|': MSH (fields 2
  to 21; MSH-1 is the separator itself), PID (fields 1 to 39) and OBX (fields 1 to 19), each field as
  its text with the component, repetition and escape characters left in it. Field numbers and names
  restated from hl7apy (hl7apy/v2_5/fields.py, segments.py), for version 2.5.
- dicom-part10: a DICOM Part 10 file in the explicit VR little-endian encoding: the 128-octet
  preamble, the "DICM" prefix and the data elements (group, element, VR, the 16- or 32-bit length by
  VR, the value as octets). Restated from pydicom (filereader.py, valuerep.py).

The vectors are not written here: tools/gen/health-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/health-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

HA = "c57adca03c77e549031867b36a6d5703611af8cd"
PD = "6c8881341bee6b438b4cbd0e1a5391774d7919e6"
SRC = {
    "hl7": ('source        "hl7apy, https://github.com/crs4/hl7apy at commit %s, hl7apy/v2_5/fields.py and segments.py (MIT License, '
            'Copyright (c) 2012-2018 CRS4); field numbers and names restated, no code copied; the HL7 v2.5 standard not used"' % HA),
    "dcm": ('source        "pydicom, https://github.com/pydicom/pydicom at commit %s, src/pydicom/filereader.py and valuerep.py (MIT License, '
            'Copyright (c) 2008-2020 Darcy Mason and pydicom contributors); layout restated, no code copied; DICOM PS3.5 and PS3.10 '
            'not used"' % PD),
}

MSH = ["field_separator", "encoding_characters", "sending_application", "sending_facility", "receiving_application", "receiving_facility",
       "date_time_of_message", "security", "message_type", "message_control_id", "processing_id", "version_id", "sequence_number",
       "continuation_pointer", "accept_acknowledgment_type", "application_acknowledgment_type", "country_code", "character_set",
       "principal_language_of_message", "alternate_character_set_handling_scheme", "message_profile_identifier"]
PID = ["set_id_pid", "patient_id", "patient_identifier_list", "alternate_patient_id_pid", "patient_name", "mother_s_maiden_name",
       "date_time_of_birth", "administrative_sex", "patient_alias", "race", "patient_address", "county_code", "phone_number_home",
       "phone_number_business", "primary_language", "marital_status", "religion", "patient_account_number", "ssn_number_patient",
       "driver_s_license_number_patient", "mother_s_identifier", "ethnic_group", "birth_place", "multiple_birth_indicator", "birth_order",
       "citizenship", "veterans_military_status", "nationality", "patient_death_date_and_time", "patient_death_indicator",
       "identity_unknown_indicator", "identity_reliability_code", "last_update_date_time", "last_update_facility", "species_code",
       "breed_code", "strain", "production_class_code", "tribal_citizenship"]
OBX = ["set_id_obx", "value_type", "observation_identifier", "observation_sub_id", "observation_value", "units", "references_range",
       "abnormal_flags", "probability", "nature_of_abnormal_test", "observation_result_status", "effective_date_of_reference_range",
       "user_defined_access_checks", "date_time_of_the_observation", "producer_s_id", "responsible_observer", "observation_method",
       "equipment_instance_identifier", "date_time_of_the_analysis"]


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for t, k, d in keys:
        L.append('list  %-*s  "%s"' % (w, k, d) if t == "list" else 'key   %-*s  %-6s  -  "%s"' % (w, k, t, d))
    return "\n".join(L) + "\n"


def hl7_pack():
    L = ["# One HL7 v2 segment line (MSH, PID or OBX), its fields split at '|'. Written by tools/gen/health-pack.py; do not edit by hand.",
         "format        hl7v2-segment", "version       0.1.0", "distribution  public", SRC["hl7"], "uses          hl7v2",
         "wire          text", 'delimiter     "|"', ""]
    L += ["kind  msh", "when  0  MSH"] + ["field  hl7v2.msh_%d_%s  %d  string  optional" % (n, name, n - 1) for n, name in enumerate(MSH, 1) if n >= 2] + [""]
    L += ["kind  pid", "when  0  PID"] + ["field  hl7v2.pid_%d_%s  %d  string  optional" % (n, name, n) for n, name in enumerate(PID, 1)] + [""]
    L += ["kind  obx", "when  0  OBX"] + ["field  hl7v2.obx_%d_%s  %d  string  optional" % (n, name, n) for n, name in enumerate(OBX, 1)]
    return "\n".join(L) + "\n"


def hl7_keys():
    keys = []
    for seg, names, start in (("msh", MSH, 2), ("pid", PID, 1), ("obx", OBX, 1)):
        for n, name in enumerate(names, 1):
            if n < start:
                continue
            keys.append(("string", "%s_%d_%s" % (seg, n, name), "%s-%d %s: the field's text (components, repetitions and escapes as sent)"
                         % (seg.upper(), n, name.replace("_", " "))))
    return keys


def dicom_pack():
    short = "AE,AS,AT,CS,DA,DS,DT,FL,FD,IS,LO,LT,PN,SH,SL,SS,ST,TM,UI,UL,US"
    L = ["# DICOM Part 10 file, explicit VR little endian: preamble, DICM, data elements. Written by tools/gen/health-pack.py;",
         "# do not edit by hand.", "format        dicom-part10", "version       0.1.0", "distribution  public", SRC["dcm"],
         "uses          dicom", "wire          bits", "layout        sequential", "bit_order     lsb", "",
         "field  dicom.preamble  1024  hex", "kind  part10", "when  32  1296255300",
         "group  dicom.elements  rest", "  field  dicom.group  16  uint", "  field  dicom.element  16  uint",
         "  field  dicom.vr  16  chars:ascii8", "  switch  dicom.vr", "    case  %s" % short,
         "      length  16  bytes", "        group  dicom.value  rest", "          field  dicom.octet  8  uint", "        end", "      end",
         "    else", "      field  dicom.reserved  16  uint", "      length  32  bytes", "        group  dicom.value  rest",
         "          field  dicom.octet  8  uint", "        end", "      end", "  end", "end"]
    return "\n".join(L) + "\n"


DICOM_KEYS = [
    ("string", "preamble", "the 128-octet preamble, as hexadecimal digits (each octet's low digit first under the little-endian bit order)"),
    ("list", "elements", "the data elements, in file order"),
    ("int", "group", "data element tag: group number"), ("int", "element", "data element tag: element number"),
    ("string", "vr", "value representation, two letters (AE ... UV)"),
    ("int", "reserved", "the two reserved octets before a 32-bit length (OB, OD, OF, OL, OV, OW, SQ, SV, UC, UN, UR, UT, UV)"),
    ("list", "value", "the value field, as octets (its length is written from the list)"),
    ("int", "octet", "one octet"),
]


def build(out):
    out.write("packs/hl7v2-segment/pack.def", hl7_pack())
    out.write("packs/dicom-part10/pack.def", dicom_pack())
    out.write("model/hl7v2.def", module("hl7v2", ["# The hl7v2 module: HL7 v2.5 MSH, PID and OBX fields. Written by tools/gen/health-pack.py."], SRC["hl7"], hl7_keys()))
    out.write("model/dicom.def", module("dicom", ["# The dicom module: DICOM Part 10 file fields. Written by tools/gen/health-pack.py."], SRC["dcm"], DICOM_KEYS))
    return {"health": 4}


def main(argv=None):
    return genio.vector_main("health-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
