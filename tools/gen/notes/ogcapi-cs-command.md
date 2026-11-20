## What is not carried

No shared key is bound: the document is a description or a control message of the
Connected Systems API, not a report of an entity's state. Only the top level is mapped
(`--max-depth 1`): the locator of a member of a Link object (a member named with the suffix
`@link`) joins that name and the member name with a `.`, which the boundary gate reads as an
e-mail address and refuses. The schema objects (SWE Common, JSON or protobuf result and
parameter schemas) and the other nested objects are therefore not mapped either; members of
several JSON types are not mapped (see the table).
