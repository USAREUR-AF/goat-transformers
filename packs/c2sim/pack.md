# Pack: c2sim

C2SIM position report: one C2SIM `Message` whose body is a `ReportBody`
holding a `PositionReportContent`. C2SIM (Command and Control Systems -
Simulation Systems Interoperation) is SISO-STD-019-2020, adopted by NATO as
STANAG 4856. Public. Written from `C2SIM_SMX_LOX.xsd`, the schema the OpenC2SIM
project derives from the C2SIM Core, Standard Military Extension and Land
Operations Extension ontologies (namespace
`http://www.sisostds.org/schemas/C2SIM/1.1`, MIT License; PROVENANCE.md).
Wire `xml`.

Uses the modules `core` and `c2sim` (`model/c2sim.def`).

## What is mapped

One kind, `position-report`. It holds when the root is `Message` in the 1.1
namespace and the report's time of observation is an `IsoDateTime`. The
lines follow the element order of the schema's sequences, so an encoded
message has its elements in schema order.

| Element | Key | Note |
|---|---|---|
| `C2SIMHeader/CommunicativeActTypeCode` | `c2sim.communicative_act` | |
| `C2SIMHeader/ConversationID` | `c2sim.conversation_id` | a UUID |
| `C2SIMHeader/FromSendingSystem` | `c2sim.from_sending_system` | |
| `C2SIMHeader/InReplyToMessageID` | `c2sim.in_reply_to_message_id` | optional |
| `C2SIMHeader/MessageID` | `c2sim.message_id` | a UUID |
| `C2SIMHeader/Protocol`, `ProtocolVersion` | `c2sim.protocol`, `c2sim.protocol_version` | text as the sender writes it |
| `C2SIMHeader/ReplyToSystem` | `c2sim.reply_to_system` | optional |
| `C2SIMHeader/SecurityClassificationCode` | `c2sim.security_classification` | optional; passed through, never chosen by a conversion |
| `C2SIMHeader/SendingTime/IsoDateTime` | `c2sim.sending_time` | optional; the text |
| `C2SIMHeader/ToReceivingSystem` | `c2sim.to_receiving_system` | |
| `ReportBody/FromSender`, `ToReceiver` | `c2sim.from_sender`, `c2sim.to_receiver` | UUIDs |
| `PositionReportContent/TimeOfObservation/DateTime/IsoDateTime` | `time_ms` | below |
| `PositionReportContent/HeadingAngle` | `c2sim.heading_deg` | degrees, north is zero |
| `Location/GeodeticCoordinate/AltitudeAGL` | `c2sim.altitude_agl_m` | metres above ground level |
| `Location/GeodeticCoordinate/AltitudeMSL` | `c2sim.altitude_msl_m` | metres above mean sea level |
| `Location/GeodeticCoordinate/Latitude`, `Longitude` | `lat`, `lon` | degrees |
| `PositionReportContent/Speed` | `speed_ms` | metres per second |
| `PositionReportContent/SubjectEntity` | `uid` | the UUID of the entity whose position is reported |
| `ReportBody/ReportID` | `c2sim.report_id` | a UUID |
| `ReportBody/ReportingEntity` | `c2sim.reporting_entity` | a UUID |

The paths in the table are under `Message/MessageBody/DomainMessageBody/` for
the report body and its content.

### The time of observation

The schema's `IsoDateTime` pattern is `YYYY-MM-DDTHH:MM:SSZ`: whole seconds,
no fraction. The locator is bound to `time_ms` through `iso8601_s`
(engine-spec 0.12), which reads a time as `iso8601_ms` does and writes it to
the whole second: a track observed at `12:30:00.750Z` is written
`12:30:00Z`.

### Keys not bound to the shared model

- `AltitudeMSL` is height above mean sea level and `hae` is height above the
  WGS 84 ellipsoid; the two differ by the geoid height, which the message does
  not carry. `AltitudeAGL` is height above ground. Neither is written as
  `hae`, and a `hae` is not written as either.
- `HeadingAngle` is a heading. The schema does not say it is the direction of
  travel, so it is not bound to `course`, and no velocity is derived from it.

## Converting to this pack

The schema requires the header's `CommunicativeActTypeCode`,
`ConversationID`, `FromSendingSystem`, `MessageID`, `Protocol`,
`ProtocolVersion` and `ToReceivingSystem`, and the report's `FromSender`,
`ToReceiver`, `TimeOfObservation`, `ReportID` and `ReportingEntity`. A track
from another format holds none of them, so the kind `requires` each of the
corresponding keys, with `uid`, `lat` and `lon`. The caller supplies them as
context (`--set`, a vector's `context`): the sending system assigns its
message and report identifiers. The time of observation is the entity's
`time_ms`. An entity without them fails with `no-kind`.

The schema types `SubjectEntity` and the identifiers above as UUIDs. The pack
writes the text it is given; a `uid` that is not a UUID gives a message the
schema refuses.

## What is not mapped

A child element no line maps is not carried (engine-spec ruling 6 of 0.1.1):

| Element | Why |
|---|---|
| `C2SIMHeader/AuthorizationHeader` | a structure of its own; not needed for a position |
| `ReportContentGroup/Duration` | optional; a duration, not an instant |
| `PositionReportContent/EntityHealthStatus` | repeated, a choice of three structures (operational status, resources, strength) |
| `Location/RelativeLocation` | a position relative to another entity: decode gives no `lat` or `lon` from it, and the element is not carried |
| `TimeOfObservation/RelativeTime`, `SimulationTime` | no absolute instant; such a report is `no-kind` |
| `Name` in a `DateTime` | optional label |
| every other report content (`ObservationReportContent`, `TaskStatus`) and every other message body (orders, plans, initialization) | outside this pack |

A report holding more than one `ReportContent` is read for its first; the
rest are not carried.

## Vectors

| Vector | What it checks |
|---|---|
| `01-position-report-roundtrip` | every mapped element; decimals in shortest form |
| `02-required-only-roundtrip` | only the required elements and a location |
| `03-to-canonical-track-v2` | to a canonical track, with `sourceId` and `trackGeneration` from context |
| `04-to-canonical-track-v2-without-context` | `no-kind` without them |
| `05-to-cot-xml` | to CoT, with `stale` and `how` from context |
| `06-simulation-time-is-no-kind` | a time of observation as `SimulationTime` |
| `07-other-namespace-is-no-kind` | the 1.0 namespace |
| `08-entity-health-status-is-not-carried` | an unmapped element is dropped |
| `canonical-track-v2/43-to-c2sim-position-report-with-context` | from a canonical track, with the header and report identifiers from context and the time from `observedAt`; speed derived from the velocity |
| `canonical-track-v2/45-to-c2sim-time-with-a-fraction` | an `observedAt` with milliseconds is written to the whole second |
| `canonical-track-v2/44-to-c2sim-without-context` | `no-kind` without them |

Every C2SIM input and expected message validates against the schema
(`xmllint --schema`), except the input of vector 07, which is in a namespace
the schema does not declare.
