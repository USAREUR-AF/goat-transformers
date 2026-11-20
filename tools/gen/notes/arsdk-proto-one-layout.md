
## One layout

This feature's `Event` has a `oneof` member that cannot be a kind (a scalar, or
a message whose only field is a `map`), so the run makes the envelope one kind
(`--one-layout`): every member's fields are lines of it, each at its own field
number, and decode keeps whichever member the message holds.
