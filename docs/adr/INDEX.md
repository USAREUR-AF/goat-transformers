# Architecture decision records

| ADR | Title | Status |
|---|---|---|
| [0001](0001-data-driven-packs-independent-engines.md) | Data-driven packs and independent per-language engines | Accepted |
| [0002](0002-shared-model-pivot-measured-fidelity.md) | Shared-model pivot, measured fidelity, pair overrides | Accepted |
| [0005](0005-time-hygiene-in-core.md) | Time hygiene in core, on two axes, never invented | Proposed |

A new record starts from [TEMPLATE.md](TEMPLATE.md). A change to `model/core.def`
or `model/track.def` needs one; `tools/model-governance.py` checks it on every
pull request.
