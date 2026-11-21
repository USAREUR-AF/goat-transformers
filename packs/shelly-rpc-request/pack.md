# shelly-rpc-request

A request frame a client sends to a Shelly Gen2 or Gen3 device. Licence `LicenseRef-unstated`:
the documentation states no licence.

## Message convention

One JSON-RPC 2.0 request frame: `jsonrpc` (`2.0`, optional), `id` (a number or text the response
echoes; absent in a notification), `src` (the caller's name, which the response puts in `dst`),
`method` (`<Component>.<Action>`, for example `Switch.Set`, `Cover.GoToPosition`,
`Shelly.GetStatus`) and `params`. This pack maps `params.id` (the component instance) and
`params.on` (the state of `Switch.Set`); other parameters are residue.

## Shared keys

None.

## Raw keys

`jsonrpc`, `src`, `method`, `params.id`, `params.on`, under module `shelly`.

## Not mapped, and why

- `id` may be a number or text, so it is residue.
- `auth` (digest authentication) is an object of text and numbers; it is residue.
- Parameters of other methods (`toggle_after`, `pos`, `brightness` and so on) are residue.
