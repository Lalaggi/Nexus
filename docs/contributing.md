# Contributing

Nexus is a self-hosted, single-user AI app built around NVIDIA Nemotron 3.5 VL Super. Contributions are welcome under the Apache 2.0 license.

## Where work is tracked

- [CHANGELOG.md](../CHANGELOG.md) — versioned release notes (Keep a Changelog style).
- [COMPLETED.md](../COMPLETED.md) — implemented features.
- [TODO.md](../TODO.md) — the backlog of planned work.
- [CLEANUP_PLAN.md](../CLEANUP_PLAN.md) — codebase hygiene plan (code splits, backend fixes, testing/tooling).
- [FUTURE_PLANS.md](../FUTURE_PLANS.md) — big features (clarifying questions, provider backend remake).
- [MOBILE_APP_PLANS.md](../MOBILE_APP_PLANS.md) — mobile-app specific plans.

## How to contribute

1. Pick an item from [TODO.md](../TODO.md) (or [CLEANUP_PLAN.md](../CLEANUP_PLAN.md) for hygiene work).
2. Create a branch from `main`.
3. Make your change, following the coding style in [development.md](./development.md).
4. Add or update tests where applicable (`tests/`).
5. Update this documentation if the change affects users (configuration, API, tools, sandbox).
6. Open a pull request (or commit directly if you are the maintainer).

## Documentation standards

This repository follows the documentation standard adopted by the wider ecosystem:

- **README.md** at the root — project front door, quick start, feature overview.
- **CHANGELOG.md** — versioned release notes.
- **COMPLETED.md** — canonical record of implemented features.
- **TODO.md** — planned work / backlog.
- **docs/** — detailed reference and operational guides (installation, configuration, usage, tools, API, sandbox, security, architecture, development, mobile, contributing).

When you ship a user-facing change, update the relevant `docs/` file and the root tracking files.

## License

Apache 2.0 — see [LICENSE](../LICENSE).
