# Security policy

goat-transformers parses messages from untrusted senders: XML, JSON, protobuf and binary bit fields. A defect in a parser or in a load check is a security defect. Security reports are prioritized over feature work.

## Reporting a vulnerability

**Do not open a public issue or pull request to report a vulnerability.**

**[Report a vulnerability privately](https://github.com/USAREUR-AF/goat-transformers/security/advisories/new)**

You can also open the reporting form from this repository's *Security* tab by selecting *Report a vulnerability*.

Reports are private and accessible to repository administrators, organization owners, security managers, the reporter, and collaborators explicitly added to the advisory. Reports remain private until an authorized maintainer publishes the advisory. See [GitHub's advisory permissions](https://docs.github.com/en/code-security/reference/permissions/repository-security-advisory) for details.

Include: a description of the issue and its impact; reproduction steps or a proof of concept (the engine, the pack and the input message); the affected commits; whether you have shared it elsewhere.

## What to expect

| Step | Target |
|---|---|
| Acknowledgement | 3 working days |
| Triage and severity | 7 working days |
| Fix or mitigation for a confirmed high or critical issue | 30 days, with a coordinated disclosure date agreed with you |
| Public advisory | when the fix is released, crediting you unless you prefer otherwise |

## Scope

In scope: the seven engines, the tools and the packs in this repository. Examples: an input message that makes an engine crash, read out of bounds, loop without end or use unbounded memory; a pack or model module that loads when the specification says it must be refused; an engine set to `--max-distribution public` that loads a `controlled` module or pack.

Out of scope: the standards and upstream projects the packs are written from (report those to their publishers, and tell us too if a pack here is affected); a private overlay you do not own.

## Supported versions

Before 1.0, the latest commit on `main` is supported. Fixes are merged to `main`.
