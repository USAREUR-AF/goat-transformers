# goat-transformers (Python)

The Python engine of [goat-transformers](https://github.com/USAREUR-AF/goat-transformers):
it converts messages between formats that are described by data files (packs).
Python 3.9 or later, standard library only.

```
pip install "git+https://github.com/USAREUR-AF/goat-transformers@v0.8.0#subdirectory=engines/python"
```

```python
from goat_transformers import Engine

engine = Engine.from_dir("vendor/goat/packs", packs_only=["cot-xml", "geojson"])
geojson = engine.convert("cot-xml", "geojson", cot_event)   # bytes in, bytes out
```

The package holds the engine. The packs are data: `tools/goat-pkg bundle` in
the repository writes the ones you name, and the model modules they use, to a
directory you vendor or ship as package data. `docs/using.md` in the repository
shows the whole path. `goat-xf-py` is the command-line tool.
