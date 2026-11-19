# Provenance of pack mavlink2-uavionix

- Repository: https://github.com/mavlink/mavlink
- Commit: `12c898d88ce18d24e8caf6338596e98c5005bc97` (the commit of pack `mavlink2`; fetched again and read on 2026-11-19)
- Fetched from `https://raw.githubusercontent.com/mavlink/mavlink/<commit>/<path>` with curl.
- Date read: 2026-11-19

| Local file | Path in the repository | SHA-256 |
|---|---|---|
| `uAvionix.xml` | `message_definitions/v1.0/uAvionix.xml` | `bd9adf101205744270be9b5fc7205d1c73e365a619435fffc2623958069da516` |
| `common.xml` | `message_definitions/v1.0/common.xml` | `a4ac8a1144529195af6f948e5b4429bae0bd7b8650472d0ce09fbc5ca7bde7d6` |
| `standard.xml` | `message_definitions/v1.0/standard.xml` | `0c08a5be4a858910ac02111a51551e0b8fa2088675a5ca0a48dfd7792fa94018` |
| `minimal.xml` | `message_definitions/v1.0/minimal.xml` | `7b1e79a1cadedb618042a3f78c09a76ef1f7440df71fa179e647001eeab7475b` |
| `upstream-COPYING.txt` | `COPYING` | `81133ba4d3343a0e627dd0d9582134f956bc9dc82322d369c561249cc2910224` |

`uAvionix.xml` is the dialect; the other files are its include closure (`common.xml`, `standard.xml`, `minimal.xml`).
The generator reads them only to check that every message id and name of the
whole set is unique; their messages are not in this pack.
`tools/gen/mavlink2pack.py --dialect uAvionix` reads the commit from this file and
refuses to run when a file's SHA-256 differs from this table.

## Check values

The generator holds the CRC_EXTRA and full payload length of every message of
`uAvionix.xml`, as stated by the C headers that the MAVLink project generates from the
definitions, and stops when its own computation differs. They were taken from
https://github.com/mavlink/c_library_v2 at commit `43e9923f0e8301b9a93c1e2e04f3b82e356d8ad8`
(headers generated from mavlink commit `a3451f1b1629871a4a37f6c8bc9da149e39baaf7`),
file `uAvionix/uAvionix.h`, macro `MAVLINK_MESSAGE_CRCS`, SHA-256
`a4e6203af43ca516137491d8d13ef5c764625d2f0c8bbf178bae0902fb8a6659`. Only those integers are used; they are
values of the protocol that the generator also derives from the XML. That
repository has no license file of its own; it is output of the MAVLink
generator, which `COPYING` (below) puts under its MIT exception.

## License, as the repository states it

The repository root at this commit has one license file, `COPYING`. It has no
`LICENSE` file. `README.md` has no license text; it links to
`https://mavlink.io/en/#license`.

`COPYING` (kept here as `upstream-COPYING.txt`) states, in this order:

1. "This repository contains the generator for the MAVLink protocol. The
   generator itself is (L)GPL v3 licensed, while the generated code is subject
   to different licenses:"
2. "Exception to the (L)GPL v.3: As an exception, if you use this Software to
   compile your source code and portions of this Software, including messages
   ("the generator output"), are embedded into the binary product as a result,
   you may redistribute such product and such product is hereby licensed under
   the following MIT license:" followed by the MIT permission text, written for
   "the generated software (the "Generated Software")".
3. The full text of the GNU Lesser General Public License, version 3.

`COPYING` does not name the XML message definitions as a separate work and
gives them no license of their own; they are part of a repository whose stated
license is LGPL v3, as for pack `mavlink2`.

## Header of the dialect file

`uAvionix.xml` carries no license, copyright, distribution or other restriction
statement. Its header holds comments giving the contributor (uAvionix), its web address, contact e-mail addresses and the id range 10001 to 10049. Contact
addresses are not reproduced here.

## What the generated pack takes from the definitions

Message names and ids, field names, field types, array lengths, `units`, `enum`
and `invalid` attribute values, the base/extension split, and the `wip` and
`deprecated` markers. Description text is not copied: key meanings in
`model/mavlinkuavionix.def` are composed by the generator from those facts, and the
position notes in `pack.md` are written in this project's words.
