# Provenance of the overture-connector pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/overture-run.sh`) reads the files below and nothing
else. They are not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | Overture Maps schema, feature type `connector` (theme `transportation`), JSON Schema in YAML |
| Publisher | Overture Maps Foundation |
| Repository | https://github.com/OvertureMaps/schema at tag `v2.0.0`, commit `cb69ac3a3d31daa05f72a505af4f3234f191e77b` |
| Download | `https://raw.githubusercontent.com/OvertureMaps/schema/cb69ac3a3d31daa05f72a505af4f3234f191e77b/schema/transportation/connector.yaml` |

| File | SHA-256 |
|---|---|
| `schema/defs.yaml` | `261b18599053af7221c3e2626a0bfb4dff504e19a0ea7643818f60034c755871` |
| `schema/transportation/connector.yaml` | `a2c15330c05b0077641d7f1a58b710d78d7dd3b8e135c5ad40f4d2b0dc75ebb9` |

## License

The repository's `LICENSE` is the Creative Commons Attribution 4.0 International Public License (CC BY 4.0); its title lines: (SHA-256 of `LICENSE`: `0caef66f639ab192462d6d7a8f2c65c53f8b238179ac5ed94abf437040839e3e`)

> Attribution 4.0 International
> Creative Commons Attribution 4.0 International Public License

The schema files under `schema/` are covered by that `LICENSE`. The Python packages under `packages/` declare the MIT license in their `pyproject.toml`; they are not read. Overture's map data carries its own licenses, which do not apply here: only the schema is used. Attribution: the pack is derived from the Overture Maps schema (CC BY 4.0), restated with keys of this project's naming.

The pack restates the schema's structure (member names, types, nesting) with keys of this
project's naming. It is not endorsed by the publisher.
