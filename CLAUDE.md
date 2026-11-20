# CLAUDE.md

[AGENTS.md](AGENTS.md) is the source of truth for this repository: the layout,
the rules, the commands, and what to ask a person before doing. Read it first.
This file adds only what is specific to Claude Code.

## Skills

`.claude/skills/` holds one procedure per task. Use the skill when the request
matches it.

| Skill | Use it when the request is to |
|---|---|
| `add-a-format` | write a pack for a format from its specification |
| `generate-packs-from-a-schema` | produce packs from protobuf files, an XML schema, or a CANboat-style or MAVLink-style definition |
| `convert-a-message` | convert a message, or find out why a conversion fails or drops a value |
| `extend-the-pack-language` | add a rule, a transform, a derive function or a wire type |
| `build-a-minimal-package` | ship only some formats, as a static binary, a library or WebAssembly |
| `write-an-overlay` | support a format whose specification is not public |
| `review-a-pack` | review a pack, as a maintainer or as the owner of the format |

## Subagents

`.claude/agents/` holds the roles the project's method needs. Use them when a
task spans engines or separates authorship from checking.

| Agent | Role |
|---|---|
| `engine-implementer` | implements one specification section in exactly one engine; never reads another engine |
| `pack-author` | writes a pack and its documents from a public specification |
| `vector-deriver` | derives the expected bytes of vectors without an engine |
| `spec-reviewer` | finds ambiguities in the specification and quotes the sentence |

Start one `engine-implementer` per engine, each told its one directory. Do not
pass one engine's code, diff or error analysis to the agent of another engine;
pass the specification section and the failing vector names only.

## Working here

- The master rule: when the task is in `engines/<language>/`, do not read any
  other `engines/` directory, including through search tools.
- For a quick check, load only the packs you need:
  `goat-xf … --packs packs --packs-only a,b` (AGENTS.md, Commands).
- Do not paste the output of `goat-xf matrix` or `tools/goat-pkg plan` into the
  conversation for a catalog format: a single line can be tens of thousands of
  characters. Ask for the pair you need (`goat-xf capability --from a --to b`).
- Run `python3 -I tools/boundary-gate` before proposing a commit.
- Commit and push only when the person asks.
