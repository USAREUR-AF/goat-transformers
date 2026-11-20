## What is not carried

The temporal properties of one moving feature. The response is close to hollow: the
`temporalProperties` member is either the Prism form (objects keyed by property name, with
tuple-shaped values) or a list of temporal properties, and the generator reads that choice
as a tuple, so it is not mapped. Only the links, `timeStamp`, `numberMatched` and
`numberReturned` are. Read a single property with `ogcapi-mf-api-tproperty`. No shared key is
bound.

The schemas of the API response refer to the MF-JSON Prism schema by its schemas.opengis.net
address; the run reads that file (pinned by SHA-256 in the run script). It states no licence,
so the pack is labelled `LicenseRef-unstated` (REUSE.toml); the response schemas themselves
are under the OGC Software License.
