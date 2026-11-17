#!/usr/bin/env bash
#
# One-time host setup for the code sandbox.
#
# Creates:
#   * a dedicated, passwordless `sandbox` user (no login shell, no SSH)
#   * a size-capped ext4 loop filesystem at /var/lib/assistant-sandbox.img
#     mounted at /srv/assistant-sandbox
#   * /home/assistant backed by that filesystem, with the app user owning
#     uploads/outputs and the sandbox user receiving narrow ACL access
#   * a root-owned Podman wrapper plus a narrow sudoers rule so the app can
#     run containers as the sandbox user without giving it the app's secrets
#
# This script is idempotent. Run it with sudo from the project directory:
#
#   sudo ./scripts/setup-sandbox-user.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E bash "${PROJECT_ROOT}/scripts/setup-sandbox-user.sh" "$@"
fi

APP_USER="${SUDO_USER:-${APP_USER:-}}"
if [[ -z "${APP_USER}" || "${APP_USER}" == "root" ]]; then
  echo "error: run this with sudo from your normal user account" >&2
  exit 1
fi
APP_GROUP="$(id -gn "${APP_USER}")"

SANDBOX_USER="${SANDBOX_USER:-sandbox}"
SANDBOX_DISK="${SANDBOX_DISK:-/var/lib/assistant-sandbox.img}"
SANDBOX_MOUNT="${SANDBOX_MOUNT:-/srv/assistant-sandbox}"
SANDBOX_SIZE="${SANDBOX_SIZE:-40G}"
ASSISTANT_HOME="${ASSISTANT_HOME:-/home/assistant}"
WRAPPER="/usr/local/bin/assistant-sandbox-podman"
SUDOERS="/etc/sudoers.d/assistant-sandbox"

say() { printf '\n\033[1;35m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

for cmd in truncate mkfs.ext4 mount findmnt setfacl getent visudo loginctl useradd usermod; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "error: required command '${cmd}' is missing (Arch: pacman -S e2fsprogs acl util-linux shadow)" >&2
    exit 1
  fi
done

if ! command -v podman >/dev/null 2>&1; then
  echo "error: podman is not installed" >&2
  exit 1
fi

# ---------------------------------------------------------------- filesystem
say "Preparing capped sandbox filesystem ${SANDBOX_DISK} (${SANDBOX_SIZE})"
if [[ ! -f "${SANDBOX_DISK}" ]]; then
  truncate -s "${SANDBOX_SIZE}" "${SANDBOX_DISK}"
  mkfs.ext4 -m 0 -F "${SANDBOX_DISK}" >/dev/null
  echo "created ${SANDBOX_DISK}"
else
  echo "using existing ${SANDBOX_DISK}"
fi

mkdir -p "${SANDBOX_MOUNT}"
if ! mountpoint -q "${SANDBOX_MOUNT}"; then
  mount -o loop,nosuid,nodev,noatime "${SANDBOX_DISK}" "${SANDBOX_MOUNT}"
  echo "mounted ${SANDBOX_DISK} at ${SANDBOX_MOUNT}"
fi

add_fstab() {
  local line="$1"
  grep -qF -- "${line}" /etc/fstab || printf '%s\n' "${line}" >> /etc/fstab
}
add_fstab "${SANDBOX_DISK} ${SANDBOX_MOUNT} ext4 loop,nosuid,nodev,noatime,nofail 0 0"

# --------------------------------------------------------------------- user
say "Creating ${SANDBOX_USER} user"
if ! getent passwd "${SANDBOX_USER}" >/dev/null; then
  NOLOGIN="$(command -v nologin || echo /usr/bin/nologin)"
  useradd -d "${SANDBOX_MOUNT}" -M -s "${NOLOGIN}" "${SANDBOX_USER}"
  echo "created user ${SANDBOX_USER}"
else
  current_home="$(getent passwd "${SANDBOX_USER}" | cut -d: -f6)"
  if [[ "${current_home}" != "${SANDBOX_MOUNT}" ]]; then
    usermod -d "${SANDBOX_MOUNT}" "${SANDBOX_USER}"
    echo "moved ${SANDBOX_USER} home to ${SANDBOX_MOUNT}"
  fi
fi

SANDBOX_UID="$(id -u "${SANDBOX_USER}")"
SANDBOX_GID="$(id -g "${SANDBOX_USER}")"

# Rootless Podman needs subordinate ID ranges for user namespaces.
if ! grep -q "^${SANDBOX_USER}:" /etc/subuid; then
  usermod --add-subuids 200000-265535 "${SANDBOX_USER}"
  echo "allocated subuid range 200000-265535"
fi
if ! grep -q "^${SANDBOX_USER}:" /etc/subgid; then
  usermod --add-subgids 200000-265535 "${SANDBOX_USER}"
  echo "allocated subgid range 200000-265535"
fi

chown "${SANDBOX_USER}:${SANDBOX_USER}" "${SANDBOX_MOUNT}"
chmod 0750 "${SANDBOX_MOUNT}"

if ! loginctl show-user "${SANDBOX_USER}" -p Linger --value 2>/dev/null | grep -q yes; then
  loginctl enable-linger "${SANDBOX_USER}"
  echo "enabled lingering user manager for ${SANDBOX_USER}"
fi

# --------------------------------------------------------------- shared data
say "Preparing ${ASSISTANT_HOME} on the capped filesystem"
mkdir -p "${SANDBOX_MOUNT}/home"
chown "${APP_USER}:${APP_GROUP}" "${SANDBOX_MOUNT}/home"
chmod 0750 "${SANDBOX_MOUNT}/home"

mkdir -p "${ASSISTANT_HOME}"
if ! mountpoint -q "${ASSISTANT_HOME}"; then
  mount --bind "${SANDBOX_MOUNT}/home" "${ASSISTANT_HOME}"
  echo "bind-mounted ${SANDBOX_MOUNT}/home at ${ASSISTANT_HOME}"
fi
add_fstab "${SANDBOX_MOUNT}/home ${ASSISTANT_HOME} none bind,nosuid,nodev,nofail,x-systemd.requires-mounts-for=${SANDBOX_MOUNT} 0 0"

install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0755 \
  "${ASSISTANT_HOME}/useruploads" \
  "${ASSISTANT_HOME}/outputs" \
  "${ASSISTANT_HOME}/.workspaces"

# App owns the files; sandbox can write outputs/workspaces and read uploads.
# Default ACLs make new chat workspaces inherit the same access.
say "Granting ${SANDBOX_USER} narrow access to uploads/outputs"
# The sandbox only needs to traverse the shared root; the bind mounts carry the
# specific uploads/outputs/workspace permissions.
setfacl -m "u:${SANDBOX_USER}:x" "${ASSISTANT_HOME}"
setfacl -R -m "u:${SANDBOX_USER}:rX" "${ASSISTANT_HOME}/useruploads"
find "${ASSISTANT_HOME}/useruploads" -type d -exec setfacl -d -m "u:${SANDBOX_USER}:rX" {} +
# Outputs and workspaces are written by the sandbox as well as the app. Give
# both accounts an explicit named entry so files created by either side stay
# readable/writable by the other regardless of the container umask.
for writable in "${ASSISTANT_HOME}/outputs" "${ASSISTANT_HOME}/.workspaces"; do
  setfacl -R -m "u:${SANDBOX_USER}:rwX" -m "u:${APP_USER}:rwX" "${writable}"
  find "${writable}" -type d -exec setfacl -d -m "u:${SANDBOX_USER}:rwX" -m "u:${APP_USER}:rwX" {} +
done

# ------------------------------------------------------------ app secrets
# The sandbox account must never be able to read the database or API keys even
# if the project is later moved somewhere world-traversable.
say "Restricting app data and environment files"
if [[ -d "${PROJECT_ROOT}/data" ]]; then
  chmod 0700 "${PROJECT_ROOT}/data"
  find "${PROJECT_ROOT}/data" -maxdepth 1 -type f -exec chmod 0600 {} +
fi
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  chmod 0600 "${PROJECT_ROOT}/.env"
fi

# ------------------------------------------------------------------ wrapper
say "Installing root-owned Podman wrapper and sudoers rule"
cat > "${WRAPPER}" <<'WRAPPER_EOF'
#!/bin/sh
# Run Podman as the sandbox account with the environment rootless Podman needs.
# sudo -u can leave HOME pointing at the caller, so derive it from the uid.
set -eu
uid="$(id -u)"
XDG_RUNTIME_DIR="/run/user/${uid}"
HOME="$(getent passwd "${uid}" | cut -d: -f6)"
export XDG_RUNTIME_DIR HOME

if [ -S "${XDG_RUNTIME_DIR}/bus" ]; then
  DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
  export DBUS_SESSION_BUS_ADDRESS
fi

exec /usr/bin/podman "$@"
WRAPPER_EOF
chown root:root "${WRAPPER}"
chmod 0755 "${WRAPPER}"

cat > "${SUDOERS}" <<SUDOERS_EOF
# Generated by Assistant's scripts/setup-sandbox-user.sh
${APP_USER} ALL=(${SANDBOX_USER}) NOPASSWD: ${WRAPPER}
SUDOERS_EOF
chmod 0440 "${SUDOERS}"
visudo -cf "${SUDOERS}" >/dev/null
echo "installed ${SUDOERS}"

# Verify the wrapper works before building anything. Run from / so the sandbox
# account never needs to traverse the app user's 0700 home directory.
if ! (cd / && sudo -u "${SANDBOX_USER}" "${WRAPPER}" info >/dev/null 2>&1); then
  warn "Podman did not answer as ${SANDBOX_USER} yet."
  warn "This is often fixed by logging out/in or rebooting so lingering and cgroups apply."
  warn "Try: sudo -u ${SANDBOX_USER} ${WRAPPER} info"
fi

# ----------------------------------------------------------------- firewall
say "Blocking sandbox access to the host, LAN, and app from inside containers"
if command -v nft >/dev/null 2>&1; then
  cat > /etc/assistant-sandbox-firewall.nft <<NFT_EOF
table inet assistant_sandbox {
  chain output {
    type filter hook output priority 0; policy accept;
    # DNS is the one narrow exception so package managers and git can resolve
    # names. The app itself listens on a high loopback port and stays blocked.
    meta skuid ${SANDBOX_UID} udp dport 53 accept
    meta skuid ${SANDBOX_UID} tcp dport 53 accept
    meta skuid ${SANDBOX_UID} ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 } drop
    meta skuid ${SANDBOX_UID} ip6 daddr { ::1, fc00::/7, fe80::/10, ff00::/8 } drop
  }
}
NFT_EOF
  cat > /usr/local/sbin/assistant-sandbox-firewall <<'NFT_SH'
#!/bin/sh
set -eu
nft delete table inet assistant_sandbox 2>/dev/null || true
exec nft -f /etc/assistant-sandbox-firewall.nft
NFT_SH
  chmod 0755 /usr/local/sbin/assistant-sandbox-firewall

  cat > /etc/systemd/system/assistant-sandbox-firewall.service <<'UNIT_EOF'
[Unit]
Description=Assistant sandbox egress guard
Documentation=file:///etc/assistant-sandbox-firewall.nft
After=network-pre.target
Wants=network-pre.target
Before=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/assistant-sandbox-firewall
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT_EOF
  systemctl daemon-reload
  systemctl enable --now assistant-sandbox-firewall.service
  echo "installed and applied the nftables egress guard"
else
  warn "nft is not installed; sandbox containers will not have LAN/host egress blocked."
  warn "Install nftables and re-run this script."
fi

# --------------------------------------------------------------------- image
say "Building the sandbox image as ${SANDBOX_USER}"
# The project may live in a 0700 home that the sandbox account cannot read, so
# copy the (tiny) build context onto the sandbox filesystem first.
BUILD_DIR="${SANDBOX_MOUNT}/build"
install -d -o "${SANDBOX_USER}" -g "${SANDBOX_USER}" -m 0755 "${BUILD_DIR}"
install -o "${SANDBOX_USER}" -g "${SANDBOX_USER}" -m 0644 \
  "${PROJECT_ROOT}/sandbox/Containerfile" "${BUILD_DIR}/Containerfile"
(cd / && sudo -u "${SANDBOX_USER}" "${WRAPPER}" build \
  --tag "localhost/assistant-code-sandbox:latest" \
  --file "${BUILD_DIR}/Containerfile" \
  "${BUILD_DIR}")

say "Running the sandbox smoke test as ${SANDBOX_USER}"
(cd / && sudo -u "${SANDBOX_USER}" "${WRAPPER}" image inspect localhost/assistant-code-sandbox:latest >/dev/null)

cat <<EOF

Sandbox host setup complete.

  sandbox user:     ${SANDBOX_USER} (uid ${SANDBOX_UID})
  capped storage:   ${SANDBOX_MOUNT} (${SANDBOX_SIZE} max)
  shared data:      ${ASSISTANT_HOME} (bind-mounted from ${SANDBOX_MOUNT}/home)
  outputs:          ${ASSISTANT_HOME}/outputs
  uploads:          ${ASSISTANT_HOME}/useruploads

The app auto-detects the wrapper. Start it and check Settings → Code sandbox,
or run: curl -s http://127.0.0.1:8848/api/health

If the app was already running, restart it. To remove the per-call containers:
  sudo -u ${SANDBOX_USER} ${WRAPPER} ps -a

EOF
