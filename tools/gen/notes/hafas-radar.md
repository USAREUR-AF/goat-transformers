## The message

The whole result of hafas-client's `radar()`: the list of movements and
`realtimeDataUpdatedAt` (UNIX seconds, the latest moment the realtime data of the response
were updated). No shared key is bound: the result holds many vehicles; read one with
`hafas-movement`. `realtimeDataUpdatedAt` is not the time of any one position.
