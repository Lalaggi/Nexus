# Sandbox

The sandbox is an isolated Linux container for code execution. It is what makes the `sandbox` tool genuinely useful while keeping your real files, home directory, API keys, and LAN out of reach.

## Modes

`/api/health` reports the sandbox mode:

- `dedicated user sandbox` — the recommended mode. A dedicated `sandbox` user runs containers through a root-owned Podman wrapper, with a size-capped ext4 loop filesystem, narrow ACLs, and an nftables egress guard. Set up with `sudo ./scripts/setup-sandbox-user.sh`.
- `current user (development mode)` — fallback. The app uses your own rootless Podman and `data/home/` for files. Convenient for development but does **not** isolate the sandbox from your account.

## What setup-sandbox-user.sh creates

Run `sudo ./scripts/setup-sandbox-user.sh`. It creates:

1. A dedicated, passwordless `sandbox` account (no login shell, no SSH).
2. A 40 GB ext4 loop image at `/var/lib/nexus-sandbox.img`, mounted at `/srv/nexus-sandbox` (with an fstab entry).
3. `/home/nexus` bind-mounted from that image, owned by you, with narrow ACLs for the sandbox account.
4. A root-owned Podman wrapper at `/usr/local/bin/nexus-sandbox-podman` plus a sudoers rule so the app can run containers as `sandbox` but not as root.
5. An nftables egress guard (`/etc/nexus-sandbox-firewall.nft`, systemd service `nexus-sandbox-firewall`) that drops sandbox traffic to loopback, LAN, link-local, and metadata addresses while allowing public internet and DNS.
6. The sandbox image (`localhost/nexus-code-sandbox:latest`), built as the sandbox account from `sandbox/Containerfile`.

The script is idempotent.

## Per-call isolation

Each `sandbox` call is an ephemeral container (`--rm`):

- Read-only root filesystem (`--read-only`), dropped capabilities (`--cap-drop=ALL`), `no-new-privileges`, `--init`.
- Memory/CPU/PID limits: `--memory=768m`, `--cpus=1.0`, `--pids-limit=128`, `--ulimit nofile=256:256`.
- User namespaces: `--userns=keep-id` maps the dedicated host sandbox account onto the container's UID 1000, so bind-mounted files belong to the sandbox account and never to your main home.
- No host home, no app database, no API keys baked into the image.
- Mounts (per chat):
  - `/workspace` — read-write scratch, persists for this conversation
  - `/mnt/useruploads` — read-only uploads
  - `/mnt/outputs` — read-write, user-visible outputs
- Outbound internet allowed; private ranges dropped by nftables keyed on the sandbox UID.

## Persistent Python packages

Each container is fresh (`--rm`), so packages installed into the container's site-packages vanish when it exits. Instead, `/workspace/.python-packages` is mounted and on `PYTHONPATH`/`PIP_TARGET`, so pip installs survive across sandbox calls. Before every run, `sitecustomize.py` and `usercustomize.py` are removed from that directory and the user site is disabled, so a file dropped by one turn cannot silently execute in later turns.

> A maliciously named module could still shadow a future import; the container limits blast radius per call, not confidentiality across turns in the same chat.

## Outputs and links

The model writes anything the user should see to `/mnt/outputs` and links it as `[name](file:///mnt/outputs/name)`. New/updated files in outputs are reported in the tool result with `file://` links. Active content (HTML, SVG, XML, JavaScript) is served as `text/plain` with a sandbox CSP rather than rendered on the app origin.

## Rebuilding the sandbox image

After editing `sandbox/Containerfile`:

```bash
./scripts/build-sandbox.sh
./scripts/test-sandbox.sh
```

## Network isolation

The sandbox runs on the default Podman bridge network (`podman`, subnet `10.88.0.0/16`) with outbound internet and DNS allowed. Classical container escape vectors (capabilities, seccomp, mount propagation, container sockets) are all blocked, but **LAN access from inside the container is not blocked at the host network layer** on this system.

### Why host-level network isolation isn't available

Rootless Podman on this system uses slirp4netns/pasta for networking, which NATs container traffic to the host's IP. This means:

- **Bridge networks can't be created** — rootless Podman lacks `CAP_NET_ADMIN`, and the `br_netfilter` kernel module isn't loaded.
- **Source-IP iptables matching doesn't work** — container traffic appears to come from the host's IP, not the container's IP.
- **`--uid-owner` iptables matching doesn't work** — the kernel lacks the `xt_owner` module.

Full LAN isolation would require host network configuration (nftables rules, a dedicated bridge, or `--network=none`) which is outside the scope of `sandbox.py`.

### App-layer defenses (what `sandbox.py` does)

Two pre-flight checks run before any command reaches the container:

1. **Private IP blocker** (`sandbox_block_private_ips`, default `true`) — rejects commands containing raw private IP literals (`192.168.x.x`, `10.x.x.x`, `127.0.0.1`, `169.254.x.x`, `0.0.0.0`, IPv6 link-local/multicast, etc.). Stops naive commands like `curl http://192.168.50.1`.

2. **Network reconnaissance blocker** — rejects commands containing patterns that reveal network topology or host internals (`ip route`, `ip addr`, `/proc/net/*`, `ifconfig`, `netstat`, `ss`, `/proc/1/mountinfo`, etc.). Stops a model from deriving the gateway IP programmatically to bypass the IP blocker.

These are defense-in-depth, not a perimeter. A determined model can still bypass them via obfuscation, DNS rebinding, or connecting through a public proxy.

### If you need stronger network isolation

- **`ASSISTANT_SANDBOX_NETWORK=false`** — disables all outbound network access inside the sandbox (`--network=none`). Public internet, curl, git clone, etc. won't work, but LAN access is impossible.
- **Host-level firewall** — nftables/iptables rules on the host keyed on the sandbox user's UID or the Podman bridge interface. Requires root and kernel modules that may not be available.
- **Guest VLAN** — put the sandbox host on a separate VLAN with no LAN access. Requires router support.

## Security boundaries

- The sandbox protects your home directory and keys from the model's code, not the app process from you. The app user can still read its own data and the encryption key.
- This is a single-user app by design. Do not share one instance between people who should not see each other's conversations; run a separate instance per person.
