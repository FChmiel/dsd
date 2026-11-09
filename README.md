# dsd

Agentic development platform for data scientists: project plans and docs, experiment tracking and benchmarks, wired into Claude Code.

Status: Phase 0 (headless core). See [docs/requirements.md](docs/requirements.md) and [docs/design/phase0-headless-core.md](docs/design/phase0-headless-core.md).

## Install (dev)

```sh
uv sync
uv tool install -e .     # puts `dsd` on your PATH
```

## Use

```sh
cd my-project
dsd init                 # creates .dsd/, docs/plans/main.md, CLAUDE.md block, .mcp.json
dsd info
```

## Develop

```sh
uv run pytest
```
