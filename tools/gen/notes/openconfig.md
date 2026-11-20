## OpenConfig data in this pack

OpenConfig publishes vendor-neutral YANG models for network devices; a device streams or
returns their data over gNMI. In the JSON_IETF encoding that data is the JSON of RFC 7951.
Each `openconfig-*` pack is one such object: one top-level container of one module, with
the augments of the listed modules applied (`tools/gen/openconfig-run.sh`). OpenConfig
puts the intended configuration of a node in its `config` container and the applied
configuration with the counters and status in its `state` container; both are mapped.

How RFC 7951 shapes the message, and so the pack:

- A member name carries the module name (`openconfig-interfaces:interfaces`) at the top
  and wherever a node comes from another module than its parent, as an augment does
  (`openconfig-if-ethernet:ethernet`); every other name is bare.
- A keyed list is a JSON array of entries; the pack reads it as a group. The key leaf at
  the entry's top refers to the one in its `config` container; both are lines.
- 64-bit counters (`oc-yang:counter64`), `timeticks64` and `decimal64` values are JSON
  strings, kept with every digit; 8- to 32-bit integers are numbers (`int`).
- An `identityref` value names its module (`openconfig-platform-types:LINECARD`).
- Unions that mix a number with a string (a port number or a range, a VLAN id or a range)
  have no single type on the wire; they are not mapped and travel as residue.

**Shared keys.** Only `openconfig-system` binds one: `state.current-datetime` is the
system's current date and time as the device reports it, the moment the state in the
message holds for, so it is `time_ms` (read with `iso8601_ms`; the text is kept in its raw
key too). The `timestamp` that gNMI puts on each notification is part of the gNMI
envelope (`gnmi-subscribe-response`), not of this object. No model in this set carries a
geographic position, and no node identifies the device itself, so `uid`, `lat` and `lon`
are not bound.
