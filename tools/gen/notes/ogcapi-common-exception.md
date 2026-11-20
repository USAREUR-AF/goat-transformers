## What is not carried

The problem details object of IETF RFC 7807 that every OGC API returns on an error: `type`,
`title`, `status`, `detail`, `instance`. Every member is mapped to a raw key. No shared key is
bound: the `error` keys of `core` describe a position error, not a request error.
