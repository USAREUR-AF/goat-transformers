## The form

One message is one OSV (Open Source Vulnerability) entry in the OSV schema's JSON form.

## Shared keys

- `uid` (`id`): the entry's identifier, unique within its database prefix (the schema's id
  format).
- `time_ms` (`modified`): the time the entry was last modified. The OSV schema says this is
  the field by which, of two entries with the same id, the newer is chosen, so it is the
  time the entry as written is valid; its pattern always ends in `Z`.
