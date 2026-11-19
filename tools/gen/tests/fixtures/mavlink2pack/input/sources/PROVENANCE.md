# Provenance of the test inputs

These three files are written for the tests of `tools/gen/mavlink2pack.py`.
They are not copies of the MAVLink definitions and belong to no commit of the
MAVLink repository; the commit below is a placeholder of the right shape.

- Commit: `0123456789abcdef0123456789abcdef01234567`

| Local file | Path | SHA-256 |
|---|---|---|
| `common.xml` | `tools/gen/tests/fixtures/mavlink2pack/input/sources/common.xml` | `b50a50b9ab48d854dec20418c31ce0eea3d2a314bfa8217377a4510c339eb89a` |
| `standard.xml` | `tools/gen/tests/fixtures/mavlink2pack/input/sources/standard.xml` | `64150ec2955fe49fbbc4280220cb01d6de912510cc8a0d211d880f20be2717bb` |
| `minimal.xml` | `tools/gen/tests/fixtures/mavlink2pack/input/sources/minimal.xml` | `49c856c4a3dc2293392f95f67ac0edcb79f74e61e7363394977433a337b4bc65` |

`common.xml` includes `standard.xml`, which includes `minimal.xml`. The
generator refuses a file whose SHA-256 differs from this table. After an edit
of a file, write its new value here: `shasum -a 256 <file>` or
`python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`.
