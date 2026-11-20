## What is not carried

The moving features response (a feature collection of moving features). As in
`ogcapi-mf-api-feature`, positions, `id` and open members are not mapped and no shared key is
bound; `links`, `timeStamp`, `numberMatched` and `numberReturned` are.

The schemas of the API response refer to the MF-JSON Prism schema by its schemas.opengis.net
address; the run reads that file (pinned by SHA-256 in the run script). It states no licence,
so the pack is labelled `LicenseRef-unstated` (REUSE.toml); the response schemas themselves
are under the OGC Software License.
