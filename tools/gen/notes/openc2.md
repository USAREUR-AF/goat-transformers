## The form

One message is one OpenC2 Command or one OpenC2 Response, the JSON object the
language specification serializes; the schemas' top-level wrapper (an object with a member
`openc2_command` or `openc2_response`, used to validate either) is not a message. The kind
is chosen by a member only that message has: `action` for a Command, `status` for a
Response. The schemas come from the TC Open Repository `oasis-open/openc2-custom-aps`
(Apache-2.0), directory `Schema-Template/v1.1/JSON-Schema`; they restate the data types of
the OpenC2 Language Specification 1.1 (`oc2ls`) and of the Stateless Packet Filtering
actuator profile 1.1 (`oc2slpf`). The packs restate the schemas' structure only; the
specifications' text, which the OASIS IPR policy covers, is not used.

## Evidence for the shared keys

- `uid` (`command_id`, Command only): the schema names it the identifier of this Command,
  a string of up to 36 non-space characters; a Response refers to the Command by it. It is
  the message's own identifier.

Not bound:

- Times. `args.start_time` and `args.stop_time` are when the Command is to begin and end,
  not the time of the message; the schema's `Date-Time` type is an integer and states no
  unit. The message itself carries no time stamp.
- `target` and `actuator` hold exactly one member each in a valid message (`maxProperties`
  1), its name chosen from a list. Every choice is a line of its own; the json wire has no
  rule for "exactly one of these members", so the pack does not check it, and the generated
  vectors hold every member at once (a document the schema would refuse, but one the wire
  round-trips).
- The `results` of a Response and actuator-specific arguments (`args.slpf`) are mapped as
  the schema gives them; a member whose names are data is not mapped.
