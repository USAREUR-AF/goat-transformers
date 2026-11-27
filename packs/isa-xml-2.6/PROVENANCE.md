# Provenance of the schema sources

`tools/gen/xsd2pack.py` (run script `tools/gen/xsd2pack-run.sh`) reads the file
below and nothing else, and refuses a set when any file it is given does not
carry "Distribution Statement A" in its first 6000 bytes. The file is an
unmodified copy of the publisher's file. It is not kept in this repository;
`sources/isa-xml/` below is a directory under the path the run script is given.

## ISA IPL 2.6 XML (`sources/isa-xml/`)

| | |
|---|---|
| Document | Integrated Sensor Architecture (ISA) schema set 6.0.13, IPL 2.6 XML schema `ipl-2.6-6.0.13.xsd` (ISA IPL Format 6.0) |
| Obtained | from the publisher, in the ISA 6.0.13 schema set of the `isa-xml` pack (whose IPL 4.7 file is the same set's); there is no public download address |

| File | Bytes | SHA-256 | Read by the generator |
|---|---|---|---|
| `ipl-2.6-6.0.13.xsd` | 85843 | `0f101dbf4aa956d2ceb66a9ca142b619acac27ed377d0b6af44b6d19c437ef2e` | yes |

Statement, in the comment that opens the file (line 3):

> Distribution Statement A. Approved for Public Release. Distribution is Unlimited.

The file has no `xs:import` and no `xs:include`, and carries no license text and no
copyright line.
