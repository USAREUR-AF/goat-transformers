# Pack: canonical-track-v2

Canonical Track v2, the track contract of the public repository
`USAREUR-AF/open-billie` (`schemas/canonical-track-v2.schema.json`). Public. One
JSON object per track, on the `json` wire.

| Schema member | Model key |
|---|---|
| `trackId` | `uid` |
| `sourceId`, `trackGeneration` | `track.source_id`, `track.generation` |
| `testData`, `headerSimulated`, `simulated`, `confirmed`, `coasting`, `finalUpdate` | `track.test_data`, `track.header_simulated`, `track.simulated`, `track.confirmed`, `track.coasting`, `track.final_update` (1 for `true`, 0 for `false`, absent when the member is absent) |
| `observedAt` | `time_ms` |
| `position.latitudeDeg`, `.longitudeDeg`, `.altitudeM` | `lat`, `lon`, `hae` |
| `velocity.eastMps`, `.northMps`, `.upMps` | `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms` |
| `classification` | `track.class`, and `type` through the table `class-cot` |
| `confidence` | `track.confidence` |
| `positionUncertainty.sigmaEastM`, `.sigmaNorthM`, `.sigmaUpM` | `track.sigma_east_m`, `track.sigma_north_m`, `track.sigma_up_m` |
| `identifiers` (array) | the list `track.identifiers`; each element's `scheme` and `value` are the item keys `track.id_scheme` and `track.id_value` |

`apiVersion` and `kind` are constants. A message whose `apiVersion` is not
`billie.dev/track-v2` or whose `kind` is not `Track` is refused with `no-kind`;
both are written on encode.

The `identifiers` array is a group (engine-spec Version 0.7): each element is
one item of the list `track.identifiers`, in order. An empty array is a list
that is present and empty and is written back as `[]`; a message with no
`identifiers` member has no list and writes none. A member of an element other
than `scheme` and `value` is dropped. The array is written after
`positionUncertainty`. A format that maps `track.identifiers`
(`demo-track-json` does) receives the list; the pack does not check that the
schemes are distinct.

The kind requires the model keys of the schema's required members: `uid`,
`track.source_id`, `track.generation`, `time_ms`, `lat`, `lon`. A conversion
from a format that cannot supply all six is refused with `no-kind`.

`classification` fills two keys. `track.class` holds the word as written.
`type` holds the CoT type the table `class-cot` gives it:

| `classification` | `type` |
|---|---|
| `unknown`, `clutter`, `other` | `a-u-X` |
| `fixed-wing-aircraft` | `a-u-A-M-F` |
| `rotary-wing-aircraft` | `a-u-A-M-H` |
| `uas` | `a-u-A-M-F-Q` |
| `balloon` | `a-u-A-M-L` |
| `bird` | `a-u-A` |
| `vehicle` | `a-u-G-E-V` |

On encode the `track.class` line comes first, so an entity that has the class
writes it. An entity that has only `type` writes the class its type maps to;
`a-u-X` writes `unknown`. A `type` the table does not hold is written as it is,
which is not a word of the schema's vocabulary.

The model module `track` derives `course`, `speed_ms`, `ce` and `le` from the
velocity and the position uncertainty (`model/track.def`), so a conversion to a
format that maps those keys carries them.

`observedAt` is written with the `Z` designator and read with `Z` or an offset.
The pack does not check the schema's ranges, string lengths or the
`classification` vocabulary.
