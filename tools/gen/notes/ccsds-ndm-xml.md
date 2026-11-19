### Evidence for the shared keys

The two shared keys are bound only in the three messages whose metadata names one object
outside any repeated element: `opm`, `omm` and `apm`. The descriptions of the two metadata
keywords are in the keyword-value Blue Books that NDM/XML encodes (CCSDS 502.0-B-3 tables 3-2
and 4-2, CCSDS 504.0-B-2 table 3-2); the XSD documents neither element.

| Locator | Key | Evidence |
|---|---|---|
| `body/segment/metadata/OBJECT_ID/#text` | `uid` | The keyword holds the identifier of the object the orbit (OPM, OMM) or attitude (APM) data is for; the Blue Books recommend the international designator of the UN Office for Outer Space Affairs index (`YYYY-NNNP{PP}`), which stays the same for the life of the object. `uid` is a stable identifier of the entity, with no unit. When the producer does not know or cannot give the designator the value is `UNKNOWN`; that text then reaches `uid` as it is. |
| `body/segment/metadata/OBJECT_NAME/#text` | `callsign` | The keyword holds the name of the spacecraft the data is for, free text, with `UNKNOWN` when not known. `callsign` is a human-readable name, with no unit. |

Not bound, with the reason:

- The state vector (`X`, `Y`, `Z`, km) and the mean elements are in the frame that
  `REF_FRAME` names (EME2000, ICRF, GCRF, ITRF and others) about the body `CENTER_NAME` names;
  `lat`, `lon` and `hae` are WGS 84 geodetic. No line of a pack can convert a Cartesian
  inertial state to geodetic coordinates (docs/roadmap.md, "Further value functions": frame
  conversions), so no position is bound.
- `EPOCH` is in the time system that `TIME_SYSTEM` names (UTC, TAI, TT, GPS, TDB, MET and
  others) and may be written as a day of year (`YYYY-DDDThh:mm:ss`). `time_ms` is epoch
  milliseconds UTC, and the `iso8601_ms` transform reads calendar dates only. A binding would
  be right only for UTC calendar epochs, and a pack cannot bind a key on a condition of
  another element's value, so `EPOCH` stays a raw key.
- `OBJECT_NAME` and `OBJECT_ID` in `oem`, `aem`, `ocm`, `rdm` and `tdm` lie in a repeated
  `segment` (a group item) or name no single object; in `cdm` there are two objects. A group
  item holds raw keys only.

An entity from another format selects no kind of this pack (every kind's `requires` lists raw
keys), so a conversion into NDM/XML is `no-kind`. That is intended: every message here has
mandatory content (epoch, frame, state) that no other loaded format carries.
