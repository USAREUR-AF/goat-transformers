# Pack: etsi-cam

The Cooperative Awareness Message (CAM) of ETSI ITS, as defined by the ASN.1
module `CAM-PDU-Descriptions` of EN 302 637-2 v1.4.1 and the types it imports
from `ITS-Container` of TS 102 894-2 v1.3.1. Public. Both modules are published
by ETSI under BSD-3-Clause (`PROVENANCE.md`). Only the ASN.1 was used: every
type, constraint, extension marker and named number below is read from the two
`.asn` files. The text of the EN and TS documents was not used.

Wire: `bits`, `layout sequential`, `bit_order msb`, `encoding uper`
(`spec/engine-spec.md`, Version 0.19 on Version 0.8). Uses the modules `core`
and `etsicam` (`model/etsicam.def`).

## The message

A message of this pack is one `CAM` value (`ItsPduHeader`, then
`CoopAwareness`) in ASN.1 unaligned PER, padded with zero bits to a whole octet,
as lowercase hex text. It is the CAM alone: the BTP and GeoNetworking headers
that carry it on the air are not part of it, and nor is any security envelope.

`messageID` must be 2 (`cam`): the pack has one kind, `cam`, whose `when`
reads the 8 bits of `messageID`. Any other value (a DENM, `1`, for instance)
is `no-kind`. Encode writes 2.

## Layout, in X.691 order

Every line of `pack.def` follows the ASN.1 component it is written for. The
lengths follow from the constraints (`int:<lb>:<ub>` takes the fewest bits that
hold `ub - lb`).

| ASN.1 component | Type and constraint | Line | Bits |
|---|---|---|---|
| header.protocolVersion | INTEGER (0..255) | `int:0:255` | 8 |
| header.messageID | INTEGER (0..255) | `when 8 2` | 8 |
| header.stationID | StationID, INTEGER (0..4294967295) | `int:0:4294967295` | 32 |
| cam.generationDeltaTime | GenerationDeltaTime, INTEGER (0..65535) | `int:0:65535` | 16 |
| camParameters | CamParameters, SEQUENCE with `...`, two OPTIONAL | `ext`, `presence cp 2` | 1 + 2 |
| basicContainer | BasicContainer, SEQUENCE with `...`, none OPTIONAL | `ext` | 1 |
| stationType | StationType, INTEGER (0..255) | `int:0:255` | 8 |
| referencePosition | ReferencePosition, SEQUENCE without `...` | (no line) | 0 |
| latitude | Latitude, INTEGER (-900000000..900000001) | `int:-900000000:900000001` | 31 |
| longitude | Longitude, INTEGER (-1800000000..1800000001) | `int:-1800000000:1800000001` | 32 |
| positionConfidenceEllipse | PosConfidenceEllipse: two SemiAxisLength (0..4095), one HeadingValue (0..3601) | `int:0:4095` twice, `int:0:3601` | 12 + 12 + 12 |
| altitude | Altitude: AltitudeValue (-100000..800001), AltitudeConfidence ENUMERATED of 16, no `...` | `int:-100000:800001`, `enum:16` | 20 + 4 |
| highFrequencyContainer | HighFrequencyContainer, CHOICE of 2 with `...` | `choice 2 ext` | 1 + 1 |
| alt 0 basicVehicleContainerHighFrequency | SEQUENCE without `...`, seven OPTIONAL | `presence hf 7` | 7 |
| heading | Heading: HeadingValue (0..3601), HeadingConfidence (1..127) | `int:0:3601`, `int:1:127` | 12 + 7 |
| speed | Speed: SpeedValue (0..16383), SpeedConfidence (1..127) | `int:0:16383`, `int:1:127` | 14 + 7 |
| driveDirection | DriveDirection, ENUMERATED of 3, no `...` | `enum:3` | 2 |
| vehicleLength | VehicleLengthValue (1..1023), VehicleLengthConfidenceIndication ENUMERATED of 5 | `int:1:1023`, `enum:5` | 10 + 3 |
| vehicleWidth | VehicleWidth, INTEGER (1..62) | `int:1:62` | 6 |
| longitudinalAcceleration | LongitudinalAccelerationValue (-160..161), AccelerationConfidence (0..102) | `int:-160:161`, `int:0:102` | 9 + 7 |
| curvature | CurvatureValue (-1023..1023), CurvatureConfidence ENUMERATED of 8 | `int:-1023:1023`, `enum:8` | 11 + 3 |
| curvatureCalculationMode | ENUMERATED of 3 with `...` | `enum:3:ext` | 1 + 2 |
| yawRate | YawRateValue (-32766..32767), YawRateConfidence ENUMERATED of 9 | `int:-32766:32767`, `enum:9` | 16 + 4 |
| accelerationControl (hf.1) | BIT STRING (SIZE(7)) | `7` | 7 |
| lanePosition (hf.2) | LanePosition, INTEGER (-1..14) | `int:-1:14` | 4 |
| steeringWheelAngle (hf.3) | SteeringWheelAngleValue (-511..512), SteeringWheelAngleConfidence (1..127) | `int:-511:512`, `int:1:127` | 10 + 7 |
| lateralAcceleration (hf.4) | LateralAccelerationValue (-160..161), AccelerationConfidence | `int:-160:161`, `int:0:102` | 9 + 7 |
| verticalAcceleration (hf.5) | VerticalAccelerationValue (-160..161), AccelerationConfidence | `int:-160:161`, `int:0:102` | 9 + 7 |
| performanceClass (hf.6) | PerformanceClass, INTEGER (0..7) | `int:0:7` | 3 |
| cenDsrcTollingZone (hf.7) | CenDsrcTollingZone, SEQUENCE with `...`: Latitude, Longitude, CenDsrcTollingZoneID OPTIONAL (0..134217727) | `ext`, `presence tz 1`, lat, lon, `int:0:134217727` | 1 + 1 + 31 + 32 + 27 |
| alt 1 rsuContainerHighFrequency | RSUContainerHighFrequency, SEQUENCE with `...`, one OPTIONAL | `ext`, `presence rsu 1` | 1 + 1 |
| protectedCommunicationZonesRSU (rsu.1) | SEQUENCE (SIZE(1..16)) OF ProtectedCommunicationZone | `group … size 1 16` | 4, then the items |
| ProtectedCommunicationZone | SEQUENCE with `...`, three OPTIONAL | `ext`, `presence pz 3` | 1 + 3 |
| protectedZoneType | ProtectedZoneType, ENUMERATED: one root value, `...`, one extension value | `enum:1:ext` | 1 + 0 (root) |
| expiryTime (pz.1) | TimestampIts, INTEGER (0..4398046511103) | `int:0:4398046511103` | 42 |
| protectedZoneLatitude, protectedZoneLongitude | Latitude, Longitude | as above | 31 + 32 |
| protectedZoneRadius (pz.2) | ProtectedZoneRadius, INTEGER (1..255, ...) | `int:1:255:ext` | 1 + 8 (root) |
| protectedZoneID (pz.3) | ProtectedZoneID, INTEGER (0..134217727) | `int:0:134217727` | 27 |
| lowFrequencyContainer (cp.1) | LowFrequencyContainer, CHOICE of 1 with `...` | `choice 1 ext` | 1 + 0 |
| alt 0 basicVehicleContainerLowFrequency | SEQUENCE without `...`, none OPTIONAL | (no line) | 0 |
| vehicleRole | VehicleRole, ENUMERATED of 16, no `...` | `enum:16` | 4 |
| exteriorLights | ExteriorLights, BIT STRING (SIZE(8)) | `8` | 8 |
| pathHistory | PathHistory, SEQUENCE (SIZE(0..40)) OF PathPoint | `group … size 0 40` | 6, then the items |
| PathPoint | SEQUENCE without `...`, one OPTIONAL | `presence pp 1` | 1 |
| pathPosition | DeltaReferencePosition: DeltaLatitude (-131071..131072), DeltaLongitude (-131071..131072), DeltaAltitude (-12700..12800) | three `int` | 18 + 18 + 15 |
| pathDeltaTime (pp.1) | PathDeltaTime, INTEGER (1..65535, ...) | `int:1:65535:ext` | 1 + 16 (root) |
| specialVehicleContainer (cp.2) | SpecialVehicleContainer, CHOICE of 7 with `...` | `if cp.2` with no lines | see "Not mapped" |

`BasicVehicleContainerHighFrequency`, `ReferencePosition`, `ItsPduHeader`,
`CoopAwareness`, `CAM`, `BasicVehicleContainerLowFrequency` and `PathPoint`
have no extension marker in these module versions, so they have no `ext`
line. `AltitudeConfidence`, `DriveDirection`, `VehicleLengthConfidenceIndication`,
`CurvatureConfidence`, `YawRateConfidence` and `VehicleRole` are ENUMERATED
without `...`; `CurvatureCalculationMode` and `ProtectedZoneType` have one.
Every ENUMERATED here numbers its root items 0, 1, 2, ... in order, so the
index the pack reads is the item's value. `ProtectedZoneType` has the root
item `permanentCenDsrcTolling (0)` and the extension item
`temporaryCenDsrcTolling (1)`: its extension index 0 decodes to `1 + 0 = 1`,
the item's value.

A BIT STRING of fixed size is a field of that many bits; its first named bit
(bit 0) is the first bit on the wire, the most significant bit of the value.

## Mapped to shared keys, with the evidence

Each binding rests on the named numbers of the ASN.1 type, which fix the unit
and the direction. Neither module states a datum for `Latitude`,
`Longitude` or `AltitudeValue`; the one datum the ASN.1 names is WGS 84, in
`HeadingValue` (`wgs84North(0)`, `wgs84East(900)`, `wgs84South(1800)`,
`wgs84West(2700)`). `HeadingValue` is also the type of the orientation of the
position's own confidence ellipse (`PosConfidenceEllipse.semiMajorOrientation`),
which places the reference position in the same WGS 84 frame.

| Wire field | Model key | Evidence in the ASN.1 | Note |
|---|---|---|---|
| referencePosition.latitude | `lat` | `Latitude ::= INTEGER {oneMicrodegreeNorth (10), oneMicrodegreeSouth (-10), unavailable(900000001)} (-900000000..900000001)`: 10 is one microdegree, so one step is 1e-7 degree, north positive | `uscale:1/10000000` on the integer. 900000001 (unavailable) decodes as 90.0000001; the datum rests on the WGS 84 frame of `HeadingValue` above |
| referencePosition.longitude | `lon` | `Longitude ::= INTEGER {oneMicrodegreeEast (10), oneMicrodegreeWest (-10), unavailable(1800000001)} (-1800000000..1800000001)`: 1e-7 degree, east positive | `uscale:1/10000000`. 1800000001 (unavailable) decodes as 180.0000001 |
| heading.headingValue | `course` | `HeadingValue ::= INTEGER {wgs84North(0), wgs84East(900), wgs84South(1800), wgs84West(2700), unavailable(3601)} (0..3601)`: 900 steps to the east, so one step is 0.1 degree, clockwise from WGS 84 (true) north | `uscale:1/10`. 3601 (unavailable) decodes as 360.1. The ASN.1 calls it the heading, the orientation of the station; `course` is the direction of travel. They agree when `driveDirection` is `forward` (0); when it is `backward` (1) the direction of travel is the heading plus 180 degrees, and the pack does not correct it |
| speed.speedValue | `speed_ms` | `SpeedValue ::= INTEGER {standstill(0), oneCentimeterPerSec(1), unavailable(16383)} (0..16383)`: one step is 0.01 m/s | `uscale:1/100`. 16383 (unavailable) decodes as 163.83; a speed above 163.82 m/s cannot be written (`transform-encode` above 163.83) |
| header.stationID | `uid` (derived) | `StationID ::= INTEGER(0..4294967295)` | The field is the raw key `etsicam.station_id`. `model/etsicam.def` derives `uid` from it as decimal text (`text_of`), and it from a `uid` that is a decimal number (`parse_int`). A `uid` that is not a number leaves the station ID absent (written 0); a decimal `uid` outside 0..4294967295 is `transform-encode` |

`AltitudeValue` is a raw key, not `hae`: its named number
`referenceEllipsoidSurface(0)` says the zero is the surface of a reference
ellipsoid, and the ASN.1 does not say which. The unit is the centimetre
(`oneCentimeter(1)`).

## Raw keys

Every other component is a key of `model/etsicam.def` holding the integer value
of its ASN.1 type, `unavailable` and `outOfRange` values included. The two
repeated parts are lists: `etsicam.protected_zones` (items: `zone_type`,
`zone_expiry_time`, `zone_latitude`, `zone_longitude`, `zone_radius`,
`zone_id`) and `etsicam.path_history` (items: `delta_latitude`,
`delta_longitude`, `delta_altitude`, `path_delta_time`). The latitude and
longitude of a protected zone, of the tolling zone, and the deltas of the path
history are raw integers, not `lat` and `lon`: they are not the position of
the station.

## Defaults

The pack has a `default` for every mandatory component that the ASN.1 gives
an `unavailable` value, set to that value, so that a message encoded from
another format (GeoJSON with a position only, for instance) says "unavailable"
rather than a false 0: `lat` 90.0000001 and `lon` 180.0000001 (the unavailable
integers), `course` 360.1, `speed_ms` 163.83, and the raw keys of the
confidences, ellipse, altitude, drive direction, vehicle length and width,
accelerations, curvature, yaw rate and their confidences. The confidences of
the optional `steeringWheelAngle`, `lateralAcceleration` and
`verticalAcceleration` have the same default; under ruling 2 of 0.19 a default
does not set a presence bit, so these are written only when the entity holds
the value they belong to. `protocolVersion` defaults to 2; see "To decide".

A key with no default and no value is written as the lower bound of its
constraint (ruling 1 of 0.19): `stationType` 0 (`unknown`),
`generationDeltaTime` 0, `stationID` 0.

## Choosing the high-frequency container on encode

Encode writes the first `alt` in line order that has content (0.19, CHOICE):
`basicVehicleContainerHighFrequency` when the entity holds any of its keys,
else `rsuContainerHighFrequency` when it holds `etsicam.protected_zones`,
else `basicVehicleContainerHighFrequency` with its defaults. This reads
"content" as a present key or a non-empty list, not a default (ruling 22 of
0.8, ruling 2 of 0.19). A reading in which defaults count as content would
write every roadside-unit CAM as a vehicle container; a vector pins it.

## Not mapped, and what decode does

| Part | Why | Decode | Encode |
|---|---|---|---|
| specialVehicleContainer (CHOICE of seven containers) | Out of the scope of this version. Six of its seven alternatives could be stated by the 0.19 lines; `RoadWorksContainerBasic.closedLanes.drivingLaneStatus` is `DrivingLaneStatus ::= BIT STRING (SIZE (1..13))`, a BIT STRING of variable size, which has no locator in 0.19 (it could be imitated by a `group … size 1 13` of 1-bit items) | With the presence bit `cp.2` set, decode reads nothing for it: the `if cp.2` block has no lines. It is the last root component of CamParameters, so every key before it is read correctly and the rest of the input is ignored (ruling 9 of 0.8). Exception: when the CamParameters extension bit is also 1, decode reads the extension-addition bitmap at the position of the container, which gives `malformed-wire` or skips bits that are not additions. v1.4.1 defines no addition to CamParameters, so a v1.4.1 sender writes that bit 0 | The presence bit is written 0; a same-format round trip of a message with the container is not exact |
| Extension alternatives of HighFrequencyContainer and LowFrequencyContainer | v1.4.1 defines none; the engine skips them (0.19, CHOICE) | skipped; no key | not written |
| Extension additions of CamParameters, BasicContainer, CenDsrcTollingZone, RSUContainerHighFrequency, ProtectedCommunicationZone | v1.4.1 defines none; the engine skips them (0.19, extension markers) | skipped; no key | not written |
| Extension values of CurvatureCalculationMode and ProtectedZoneType | read as `n + index` (0.19) | `3` and above; `2` and above | written in the extension form |
| `unavailable` and `outOfRange` values on `lat`, `lon`, `course`, `speed_ms` | the pack language has no way to state "this wire value means absent" | they decode as the out-of-range numbers above (for example `lat` 90.0000001) | the defaults write them |
| generationDeltaTime to `time_ms` | `GenerationDeltaTime` is a time modulo 65536 ms of `TimestampIts`, whose zero is `utcStartOf2004`; no derive function takes a remainder or the 2004 epoch, and the ASN.1 does not say how leap seconds are counted | raw key `etsicam.generation_delta_time` | `time_ms` is not written |
| positionConfidenceEllipse to `ce`, altitudeConfidence to `le` | the ASN.1 gives the axes in centimetres and the confidence as classes, without the confidence level, and `ce` is a circular error | raw keys | not written |
| altitude to `hae` | the ellipsoid is not named in the ASN.1 | raw key | `hae` is not written |
| messageID | read by the kind's `when` | no key | 2 |
| CAM of other versions (TS 103 900) | another ASN.1 module, another layout | not this pack | |

## Places where the 0.19 rules could not state the ASN.1

Within the parts this pack maps, none: every constraint of the components
listed under "Layout" has a 0.19 locator. Ruling 17 of 0.19 (extensible SIZE,
extensible semi-constrained INTEGER, FROM constraints, fragmented lengths) does
not arise here. Outside them:

- `DrivingLaneStatus ::= BIT STRING (SIZE (1..13))` (in specialVehicleContainer):
  a BIT STRING of variable size has no locator. Candidate addition:
  `bitstring:<lb>:<ub>`, the bit count as a constrained whole number then the
  bits.
- A wire value that the ASN.1 names `unavailable` cannot be decoded as an
  absent key. Candidate addition: a per-field sentinel that maps one wire value
  to absent on decode and absent to it on encode.

## To decide

- The `lat`/`lon` binding: the WGS 84 datum is not stated by the ASN.1 of
  `Latitude` and `Longitude`; it is taken from the WGS 84 frame of
  `HeadingValue`, which orients the position's confidence ellipse.
- `heading` bound to `course`, which differs when the vehicle drives backwards.
- `protocolVersion` default 2: the ASN.1 says only `INTEGER (0..255)`. 2 is
  the `version (2)` arc of the module identifier of `CAM-PDU-Descriptions`;
  that it is the value v1.4.1 senders write is not stated in the ASN.1.
- The reverse derive `parse_int uid`, which makes a decimal `uid` above
  4294967295 a `transform-encode` failure rather than a station ID of 0.
