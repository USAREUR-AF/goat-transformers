## IETF YANG data in this pack

The IETF publishes its device and service data models as YANG modules inside RFCs. A
NETCONF or RESTCONF server, or a gNMI target that uses the JSON_IETF encoding, returns the
data of a module as JSON in the form RFC 7951 defines. Each `yang-ietf-*` pack is one such
reply: the object that holds one top-level container of one module, with the augments that
the listed modules add to it (`tools/gen/yang-ietf-run.sh`). Configuration and operational
state share one tree in the operational datastore (RFC 8342), so both are mapped.

How RFC 7951 shapes the message, and so the pack:

- A member name carries the module name (`ietf-interfaces:interfaces`) at the top and
  wherever a node comes from another module than its parent, as an augment does
  (`ietf-ip:ipv4`); every other name is bare.
- A list or leaf-list is a JSON array; the pack reads it as a group, one item per entry.
- 64-bit integers and `decimal64` are JSON strings, so counters such as `in-octets` are
  `string` lines that keep every digit; 8- to 32-bit integers are numbers (`int`).
- An `identityref` value names its module (`iana-if-type:ethernetCsmacd`); it is kept as
  written.
- A leaf of type `empty` is `[null]`, which the json wire does not carry.
- Choices and cases leave no trace on the wire; the nodes of every case are lines, and a
  valid message holds those of one case.

Features (`if-feature`) are all taken as supported; a server that leaves one out simply
sends fewer members. Deprecated top-level containers (`interfaces-state`,
`routing-state`, `modules-state`) are not packs: the RFCs that replaced them moved their
data into the operational tree of the container that is.

**Shared keys.** Only `yang-ietf-system-state` binds one: `clock.current-datetime` is the
device's own reading of the current date and time (RFC 7317 describes it so), which is the
moment the state in the reply holds for, so it is `time_ms` (read with `iso8601_ms`, which
turns an offset into UTC; the text is kept in its raw key too). No tree in this set carries
a geographic position: the geo-location grouping of RFC 9179 is used by no module read
here, and the node coordinates of the TE topology model (RFC 8795) are items of a list.
No node is a stable identifier of the device itself, so `uid` is not bound.
