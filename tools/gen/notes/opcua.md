## Notes

The structured DataTypes of namespace 0 describe the information model and the services
themselves: ranges and engineering units, build and server status, endpoint and security
descriptions, PubSub configuration, alarm and audit details. None carries a geographic position,
and none has a DateTime whose meaning is the time a report is valid, so no field is bound to a
shared key: every field is a raw key of module `opcua`, and the pack converts to no other
format. The values convert between this pack and itself, and through the raw keys to any pack
that maps the same keys.

Where the layout comes from: the field names, types, value ranks, optional flags and union flags
of each DataType's `Definition`, the supertype chain (a subtype's fields follow its supertype's),
and the `Default Binary` encoding object of each type, all from `Opc.Ua.NodeSet2.xml`. The
binary encoding rules (byte order, the length prefixes, the NodeId and ExpandedNodeId forms, the
LocalizedText mask, the EncodingMask of optional fields and the SwitchField of unions) are those
of OPC 10000-6, section 5.2, restated here in this repository's own words; the NodeSet holds
names and numbers, not those rules.

`vectors/01-eu-information-hand.json` and `02-eu-information-null-string.json` are worked by
hand from those rules (`tools/gen/opcua-vectors.py`): an EUInformation with a one-byte namespace
URI, a unit id and a display name, and the same with a null namespace URI (length -1), which the
pack refuses as `malformed-wire`.
