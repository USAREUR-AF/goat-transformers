# Pack: goat-processors-report

The report that the goat-processors runner reads from the fabric, UDP or a
file: one JSON object whose members are shared-model keys under their model
names. `time_ms` is an integer, epoch milliseconds. It belongs to no external
standard.

`track.source_id` is written as the member `source_id` of a nested `track`
object, because a JSON member name holding `.` is not addressable (engine-spec
0.5). The runner reads a nested object as dotted keys.

| Model key | Member | Note |
|---|---|---|
| `track.source_id` | `track.source_id` (nested) | which source reported the track; usually set on the command line (`--set track.source_id=<source>`) |
| `uid`, `type`, `callsign` | same names | strings |
| `time_ms`, `stale_ms` | same names | integers, epoch ms |
| `lat`, `lon`, `hae`, `ce`, `course`, `speed_ms` | same names | numbers; `hae` is the model key unchanged, metres above the WGS 84 ellipsoid; the source calls `ce` a one-sigma horizontal error, while the model key states no sigma |
| `time_error_ms`, `time_state` | same names | time quality of the stamping clock |
| `radar.rcs_m2` | `radar.rcs_m2` (nested) | the radar cross section in square metres, as the reporting radar measured it; the runner carries it to the system track, per source |

Not mapped: every other model key. A message decoded from another format
keeps only these keys.
