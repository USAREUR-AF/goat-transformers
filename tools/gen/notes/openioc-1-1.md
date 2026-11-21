## The form

One message is one OpenIOC 1.1 document: the `OpenIOC` root in the default namespace
`http://openioc.org/schemas/OpenIOC_1.1` (no prefix), with its metadata, criteria and
parameters. The schema's indicators nest without limit (an `Indicator` holds items and
further indicators); the generator reads them to its depth limit, and deeper indicators
are not read.

## Licence

The header comment of `schemas/ioc.xsd` states "Copyright 2013 Mandiant Corporation.
Licensed under the Apache 2.0 license", and the repository's `LICENSE` is the Apache License
2.0. (The generator's source line says no file carries a statement because it looks for a
US distribution statement; the Apache statement is in the file's header comment.)

## Shared keys

- `uid` (`@id` of `OpenIOC`): the identifier of the indicator of compromise document.
