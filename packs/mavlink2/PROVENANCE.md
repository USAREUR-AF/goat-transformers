# Provenance of the MAVLink inputs

- Repository: https://github.com/mavlink/mavlink
- Commit: `12c898d88ce18d24e8caf6338596e98c5005bc97` (head of `master` when fetched, 2026-11-15)
- Fetched from `https://raw.githubusercontent.com/mavlink/mavlink/<commit>/<path>` with curl.

| Local file | Path in the repository | SHA-256 |
|---|---|---|
| `common.xml` | `message_definitions/v1.0/common.xml` | `a4ac8a1144529195af6f948e5b4429bae0bd7b8650472d0ce09fbc5ca7bde7d6` |
| `standard.xml` | `message_definitions/v1.0/standard.xml` | `0c08a5be4a858910ac02111a51551e0b8fa2088675a5ca0a48dfd7792fa94018` |
| `minimal.xml` | `message_definitions/v1.0/minimal.xml` | `7b1e79a1cadedb618042a3f78c09a76ef1f7440df71fa179e647001eeab7475b` |
| `upstream-COPYING.txt` | `COPYING` | `81133ba4d3343a0e627dd0d9582134f956bc9dc82322d369c561249cc2910224` |

`common.xml` includes `standard.xml`, which includes `minimal.xml`. The
generator `tools/gen/mavlink2pack.py` reads the commit from this file and
refuses to run when a file's SHA-256 differs from this table.

## License, as the repository states it

The repository root at this commit has one license file, `COPYING`. It has no
`LICENSE` file. The three XML files carry no license or copyright header.
`README.md` has no license text; it links to `https://mavlink.io/en/#license`.

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
gives them no license of their own. They are part of a repository whose stated
license is LGPL v3, and the MIT exception is worded for output of the
repository's own generator that is embedded in a binary product. The pack here
is produced by a different generator and is data, not a binary product, so the
exception's wording does not plainly cover it.

## What the generated pack takes from the definitions

Message names and ids, field names, field types, array lengths, `units` and
`enum` attribute values, and the base/extension split. Description text is not
copied: key meanings in `model/mavlink.def` are composed by the generator from
those facts.
