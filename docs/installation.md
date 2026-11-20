# Installation

Nexus is a self-hosted, single-user application. It runs as one FastAPI process serving a React UI, with an optional dedicated sandbox user for isolated code execution.

## Prerequisites

- Linux (developed on EndeavourOS/Arch) with:
  - Python 3.13+
  - [uv](https://docs.astral.sh/uv/)
  - Node 20+ and npm
- For the sandbox (recommended):
  - rootless Podman
  - `nftables`, `acl`, `e2fsprogs`, `shadow`, `util-linux`
  - systemd
- A [SearXNG](https://searxng.org/) instance (default `http://127.0.0.1:8888`).
- An [NVIDIA NIM](https://build.nvidia.com/) or [OpenRouter](https://openrouter.ai/) API key (at least one).

Install the sandbox host tools on Arch:

```bash
sudo pacman -S podman nftables acl e2fsprogs shadow util-linux
```

## Clone and install

```bash
git clone <this repo> Nexus
cd Nexus

uv sync
npm --prefix web install
npm --prefix web run build
```

## Configure

Copy the example environment file and fill in at least one provider key:

```bash
cp .env.example .env
# edit .env: add a NIM or OpenRouter key
```

See [configuration.md](./configuration.md) for the full list of `ASSISTANT_*` variables.

## Run

```bash
uv run nexus
```

Open <http://127.0.0.1:8848>.

The server binds to loopback by default. To expose it beyond loopback (e.g. for phone or Tailscale access), set `ASSISTANT_HOST=0.0.0.0`:

```bash
ASSISTANT_HOST=0.0.0.0 uv run nexus
```

⚠️ Only do this with `ASSISTANT_PASSWORD` set and preferably behind a reverse proxy with HTTPS.

## Sandbox host setup (recommended)

The sandbox is what makes the `sandbox` tool genuinely useful while keeping your real files out of reach. Run the one-time host setup:

```bash
sudo ./scripts/setup-sandbox-user.sh
```

It creates:

- a dedicated, passwordless `sandbox` account with no login shell;
- a 40 GB ext4 loop image at `/var/lib/nexus-sandbox.img`, mounted at `/srv/nexus-sandbox`;
- `/home/nexus` bind-mounted from that image, owned by you, with narrow ACLs for the sandbox account;
- a root-owned Podman wrapper plus a single sudoers rule, so the app can run containers as `sandbox` but not as root;
- an nftables egress guard that drops sandbox traffic to loopback, LAN, link-local, and metadata addresses while allowing public internet and DNS;
- the sandbox image, built as the sandbox account.

The script is idempotent. It writes an fstab entry for the loop and bind mounts; make sure `/home/nexus` is not already a separately managed mount.

Then restart the app and check:

```bash
curl -s http://127.0.0.1:8848/api/health
./scripts/test-sandbox.sh
```

`/api/health` should report `"mode": "dedicated user sandbox"`.

### How isolation works

See [sandbox.md](./sandbox.md) for the full isolation model, including the nftables guard, Podman wrapper, ACLs, and per-call ephemeral containers.

### Development fallback

Without the setup script, the app falls back to your own rootless Podman and `data/home/` for files. This is convenient for development but does **not** isolate the sandbox from your account. `/api/health` reports `current user (development mode)` in that case.

## First run checklist

1. `uv sync` and `npm --prefix web install && npm --prefix web run build`
2. `cp .env.example .env` and add a NIM or OpenRouter key
3. `uv run nexus` → open <http://127.0.0.1:8848>
4. (Optional) `sudo ./scripts/setup-sandbox-user.sh` → restart → `curl /api/health` → `./scripts/test-sandbox.sh`
