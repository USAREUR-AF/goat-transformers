# Pack: goat-processors-system-track

One system track as the goat-processors runner publishes it: one line of its
batched tracks output, a JSON object. It belongs to no external standard. Use
it to convert the runner's tracks to another format, for example ASTERIX
CAT062; split the output into lines with newline framing.

| Model key | Member | Note |
|---|---|---|
| `uid` | `group` | the system track's identifier when fuse makes the tracks |
| `cat062.track_number` | `track_number` | a number 1 to 65535 the track keeps while it lives |
| `time_ms` | `now_ms` | the tick the track describes, epoch ms |
| `lat`, `lon`, `hae`, `course`, `speed_ms` | same names | the fused estimate |

Not mapped: `members` (an array, which the json wire does not carry in
engine-spec 0.5), and `ce`, `hae_from`, `from`, `attributes`, which are
residue and return only when the message goes back to this format.

To write ASTERIX CAT062 the encoder also needs `cat062.sac`, `cat062.sic` and
`track.confirmed`, which the runner does not publish: give them on the command
line (`--set cat062.sac=<n> --set cat062.sic=<n> --set track.confirmed=1`).
`cat062.time_of_day_s` derives from `time_ms`.
