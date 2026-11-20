# Documentation

Welcome to the Nexus documentation. Nexus is a self-hosted, single-user ChatGPT replacement that works with any model on NVIDIA NIM or OpenRouter (**Nemotron 3.5 VL Super** enabled by default).

## Getting started

| Document | For |
|----------|-----|
| [README.md](../README.md) | Project overview, features, quick start |
| [installation.md](./installation.md) | Step-by-step install, sandbox host setup, first run |
| [configuration.md](./configuration.md) | All `ASSISTANT_*` environment variables |
| [usage.md](./usage.md) | Features, tools, chat model, files & links |

## Reference

| Document | For |
|----------|-----|
| [tools.md](./tools.md) | Built-in tool reference (schemas, arguments, behavior) |
| [api.md](./api.md) | HTTP API endpoints and SSE stream events |
| [sandbox.md](./sandbox.md) | Sandbox isolation, nftables guard, Podman wrapper |
| [security.md](./security.md) | Security model, encryption, boundaries |
| [architecture.md](./architecture.md) | Architecture and data flow |

## Operations

| Document | For |
|----------|-----|
| [development.md](./development.md) | Backend/frontend development, tests, linting |
| [mobile.md](./mobile.md) | Capacitor Android app build and first run |
| [contributing.md](./contributing.md) | How to contribute, cleanup plan, coding style |

## Project tracking

| Document | For |
|----------|-----|
| [CHANGELOG.md](../CHANGELOG.md) | Versioned release notes |
| [COMPLETED.md](../COMPLETED.md) | Implemented features |
| [TODO.md](../TODO.md) | Backlog and planned work |

## How this documentation is organized

This documentation follows the structure adopted by the wider ecosystem:

- **README.md** at the repo root — the project's front door: what it is, quick start, and pointers to everything else.
- **CHANGELOG.md** — versioned, human-readable release notes (Keep a Changelog style).
- **COMPLETED.md** — a canonical record of implemented features.
- **TODO.md** — the backlog of planned work.
- **docs/** — detailed reference and operational guides.
