## Evidence for the shared keys

- `uid` (`jobID`): the identifier of the job, which the schema requires and the API uses in
  the job's path; it names one job for as long as the server keeps it.
- `time_ms` (`updated`): a `date-time`. The recommendation on job status (`REC_job-status`)
  has the server revise `updated` whenever the job's status changes, and the core clause
  notes that it keeps changing while outputs are stored after the job finishes: it is the
  time this status report was last made true, the meaning of `time_ms`. `iso8601_ms` reads
  it (an offset is converted to UTC). `created`, `started` and `finished` are raw keys.
