## Shared keys

None is bound. No OCPP message carries a position. The 1.6 schemas carry no descriptions,
so they state the meaning of no member; the 2.0.1 schemas describe their members, but
their times are times of charging events, meter samples or settings, none stated as the
time a report about an entity is valid, and their identifiers name transactions, EVSEs,
tokens and requests rather than one entity. Every member is a raw key of the pack's own
module.

## The frame

OCPP-J sends each call as a JSON array of the message type, a unique id, the action and
the payload (a result carries no action). The json wire reads one JSON object, so the pack
is the payload alone; the frame is the transport's business.

## Source

The schemas are the Open Charge Alliance's; the Alliance publishes them with the
specification after an account registration. This pack is generated from the copies a
public library carries; see PROVENANCE.md.
