# scripts

[![CI](https://github.com/jfudally/scripts/actions/workflows/ci.yml/badge.svg)](https://github.com/jfudally/scripts/actions/workflows/ci.yml)

A collection of useful scripts and small standalone tools. Each lives in its
own subdirectory with its own `Makefile`, `README.md`, and tests, so projects
stay self-contained and can be run independently.

## Projects

| Project | What it does |
| --- | --- |
| [`azure-nsg-ip-updater`](azure-nsg-ip-updater/) | Keeps one or more Azure NSG security rules pointed at this host's current public IPv4 — handy for whitelisting a dynamic residential IP from cron. |

## Layout

```
scripts/
├── pyproject.toml          # uv workspace root (shared .venv lives at ./.venv)
├── .github/workflows/      # CI — runs project test suites via `make test`
└── <project>/              # one directory per script/tool
    ├── Makefile            # canonical entrypoint: make help / test / run / ...
    ├── README.md           # project-specific docs
    ├── src/ + tests/
    └── ...
```

This repo is a [`uv`](https://docs.astral.sh/uv/) workspace: projects share a
single virtual environment at `./.venv` rather than each maintaining its own
interpreter.

## Getting started

Each project is driven through its `Makefile`. From inside a project directory:

```bash
make help      # list available targets
make install   # install dependencies into the shared ../.venv
make test      # run the test suite
make run       # run the tool (see the project README for required config)
```

## Conventions

- **One directory per script/tool**, self-contained with its own docs and tests.
- **`Makefile` is the entrypoint** — humans and CI both invoke `make <target>`.
- **Tests required** — new projects ship with a test suite wired into `make test`.
- **Secrets stay local** — `.env` files are git-ignored; commit only `.env.example`.

## Adding a new script

1. Create a new subdirectory with `src/`, `tests/`, a `Makefile`, and a `README.md`.
2. Wire up `make install` / `make test` following an existing project as a template.
3. Add it to the **Projects** table above and to CI if it should run on push.
