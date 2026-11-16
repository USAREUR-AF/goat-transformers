# Provenance of the schema sources

`tools/gen/xsd2pack.py` (run script `tools/gen/xsd2pack-run.sh`) reads the files
below and nothing else, and refuses a set when any file it is given does not
carry "Distribution Statement A" in its first 6000 bytes. Each file is an
unmodified copy of the publisher's file. The files are not kept in this
repository; `sources/<set>/` below is a directory under the path the run script
is given.

## UCI 2.6 (`sources/uci/`)

| | |
|---|---|
| Document | Universal Command and Control Interface (UCI) Standard, version 2.6, schema version `002.6.0` |
| Publisher | U.S. Air Force |
| Repository | https://github.com/open-arsenal/uci at commit `78eb61b6112c8bffa40820c33124b57787fc5bd9` |
| Archive | `UCI Release Documentation - UCI Schema/03_UCI-STD-002_Rev6_UCI_Schema_v2_6-CDRL.zip`, 1051186 bytes, SHA-256 `073dafd85f0a1cf2f1668f75a73aca6a5af28895e0b4645186ed7b23014c145e` |

Files in the archive:

| File | Bytes | SHA-256 | Read by the generator |
|---|---|---|---|
| `UCI_MessageDefinitions_v2_6_0.xsd` | 8152675 | `af54ce724c4fe869c8208c86985c0b768d74d581691e21d66c88bb6cfe59955b` | yes |
| `UCI_SecurityMarkings_v2_6_0.xsd` | 335380 | `ee6e58d5db9fd80d526bc964b8244ec296d106301640d34c3cb2c5c00b710b88` | yes (`xs:include` of the first) |
| `UCI_Versioning_v2_6_0.xsd` | 2282 | `952b5a0d8308787eadf8f4fe5917f5a82a23984595da0791c8f4c47da622b87c` | no: it imports the message definitions and declares the `version` annotation attribute the schema puts on its own declarations; no message contains it |

Statement, in the first `xs:documentation` of each of the three files (line 8):

> Distribution Statement A. Approved for public release: distribution is unlimited.

Not read from the archive: `README_DISCLAIMER.txt`, `VDD.txt`.

## A-GRA 6.0a (`sources/a-gra/`)

| | |
|---|---|
| Document | Autonomy Government Reference Architecture (A-GRA), release 6.0a, schema version `006.0.ASK` |
| Publisher | U.S. Air Force |
| Repository | https://github.com/open-arsenal/a-gra at commit `aaabf2cd5c341002e6c62d1448460b55b5634931`, directory `Schema/` (two files; both read) |
| Download | `https://raw.githubusercontent.com/open-arsenal/a-gra/aaabf2cd5c341002e6c62d1448460b55b5634931/Schema/<name>` |

| File | Bytes | SHA-256 | Read by the generator |
|---|---|---|---|
| `A-GRA_MessageDefinitions_v6_0_a.xsd` | 8866855 | `9efa174eda548bf27c8ca4afaaba12c6dca4cc259d799bcc4a098df968cfc38d` | yes |
| `A-GRA_SecurityMarkings_v6_0_a.xsd` | 187161 | `27cf46befc3d3383de3ce7e584724abfe274faa5b4d8a710033b80109f604f20` | yes |

Statement, in the first `xs:documentation` of each file (line 7 and line 8):

> Distribution Statement A. Approved for public release: distribution is unlimited.

The message definitions file has `xs:include schemaLocation="A-GRA_SecurityMarkings_v6_0.xsd"`.
The release holds that file as `A-GRA_SecurityMarkings_v6_0_a.xsd`; no file named
`A-GRA_SecurityMarkings_v6_0.xsd` is in the directory. The generator is told so
with `--alias`. Both files declare schema version `006.0.ASK` and the same
target namespace.

## ISA IPL 4.7 XML (`sources/isa-xml/`)

| | |
|---|---|
| Document | Integrated Sensor Architecture (ISA) schema set 6.0.13, IPL 4.7 XML schema `ipl-4.7-6.0.13.xsd` (ISA IPL Format 6.0) |
| Obtained | from the publisher; there is no public download address |

| File | Bytes | SHA-256 | Read by the generator |
|---|---|---|---|
| `ipl-4.7-6.0.13.xsd` | 232475 | `02bfacd8213437640c18a36078a3b4803bdcfdbb37f154e42e80e79c81c4f741` | yes |

Statement, in the comment that opens the file (line 3):

> Distribution Statement A. Approved for Public Release. Distribution is Unlimited.

The file has no `xs:import` and no `xs:include`.
