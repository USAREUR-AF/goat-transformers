## The form

`cisa-kev-catalog` is one whole CISA Known Exploited Vulnerabilities catalog file
(`known_exploited_vulnerabilities.json`): its version, release time, count and the list of
vulnerabilities. `cisa-kev-vulnerability` is one entry of that list on its own.

## Shared keys

- `time_ms` (catalog `dateReleased`): the date and time the catalog was released, in the
  schema's stated form `YYYY-MM-DDTHH:mm:ss.sssZ`.
- `uid` (vulnerability `cveID`): the CVE identifier of the entry.
