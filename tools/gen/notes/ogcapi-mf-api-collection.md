## What is not carried

A moving feature collection with the API links and counts. Positions (arrays of arrays), the
bounding box (a tuple) and members of several JSON types are not mapped; no shared key is
bound.

The schemas of the API response refer to the MF-JSON Prism schema by its schemas.opengis.net
address; the run reads that file (pinned by SHA-256 in the run script). It states no licence,
so the pack is labelled `LicenseRef-unstated` (REUSE.toml); the response schemas themselves
are under the OGC Software License.
