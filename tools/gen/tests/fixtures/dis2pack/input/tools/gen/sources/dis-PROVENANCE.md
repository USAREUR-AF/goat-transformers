# Provenance of the DIS inputs

| Fact | Value |
|---|---|
| layouts | https://github.com/open-dis/xmlpg, fixture, commit `0123456789abcdef0123456789abcdef01234567` |
| xmlpg archive | `https://codeload.github.com/open-dis/xmlpg/tar.gz/0123456789abcdef0123456789abcdef01234567` |
| PDU types | https://github.com/open-dis/open-dis-python, fixture, commit `89abcdef0123456789abcdef0123456789abcdef` |
| open-dis-python archive | `https://codeload.github.com/open-dis/open-dis-python/tar.gz/89abcdef0123456789abcdef0123456789abcdef` |

The xmlpg README calls `DIS2012.xml` the original specification file of Open
DIS, no longer maintained, with corrections made in the generated libraries.
The generator takes the layouts from it, the PDU type numbers from the class
annotations of open-dis-python, and reads both as data (an XML tree and a
Python syntax tree); it runs neither. No IEEE document was read.

## Files

| Path | SHA-256 |
|---|---|
| `xmlpg/LICENSE.md` | `b2a0a12fbd2438c797130305a0f8995b9269d4adc5ab3816623683ad614a858e` |
| `xmlpg/DIS2012.xml` | `d7533e01c95e41721199389d48a1568a68bd05628d7d67d85c2e293c8b6e1d08` |
| `opendis/LICENSE` | `b2a0a12fbd2438c797130305a0f8995b9269d4adc5ab3816623683ad614a858e` |
| `opendis/opendis/dis7.py` | `6afade999efa7636670bb4d39bd1678c49a58b623c642f29ed580b3ca7237fd9` |
| `opendis/opendis/PduFactory.py` | `3efe9f509547162843bc856ff88d16bbe08c49ff79949d1ac0524ad6c56b4f0f` |

## xmlpg LICENSE.md

```
Fixture license text for the dis2pack tests: the files under this directory
were written for the tests of this repository and are covered by its license.
```

## open-dis-python LICENSE

```
Fixture license text for the dis2pack tests: the files under this directory
were written for the tests of this repository and are covered by its license.
```
