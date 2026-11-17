#!/usr/bin/env bash
# Smoke-test the sandbox image with the same flags and account the app uses.
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="${ASSISTANT_SANDBOX_IMAGE:-localhost/assistant-code-sandbox:latest}"
WRAPPER="/usr/local/bin/assistant-sandbox-podman"
SANDBOX_USER="${ASSISTANT_SANDBOX_USER:-sandbox}"

PODMAN=(podman)
if [[ -x "${WRAPPER}" ]] && id "${SANDBOX_USER}" >/dev/null 2>&1 && [[ "$(id -un)" != "${SANDBOX_USER}" ]]; then
  if sudo -n -u "${SANDBOX_USER}" "${WRAPPER}" info >/dev/null 2>&1; then
    PODMAN=(sudo -n -u "${SANDBOX_USER}" "${WRAPPER}")
    echo "Testing as dedicated sandbox account: ${SANDBOX_USER}"
  fi
fi

SCRATCH="$(mktemp -d /tmp/assistant-sandbox-test.XXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT
# The sandbox user must be able to traverse and use the scratch mounts.
chmod 755 "$SCRATCH"
mkdir -p "$SCRATCH/workspace" "$SCRATCH/uploads" "$SCRATCH/outputs"
chmod 777 "$SCRATCH/workspace" "$SCRATCH/outputs"
chmod 755 "$SCRATCH/uploads"

if ! "${PODMAN[@]}" image exists "$IMAGE"; then
  echo "error: image ${IMAGE} is missing; run ./scripts/build-sandbox.sh" >&2
  exit 1
fi

echo "1/5 Running a shell command, Python packages, and writing output files…"
cat > "$SCRATCH/workspace/smoke.py" <<'PY'
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

fig, ax = plt.subplots(figsize=(4, 2.5))
ax.plot(np.arange(10), np.arange(10) ** 2)
fig.tight_layout()
fig.savefig("/mnt/outputs/smoke.png", dpi=100)

pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv("/mnt/outputs/smoke.csv", index=False)
print("python", sys.version.split()[0])
print("numpy", np.__version__, "pandas", pd.__version__)
PY
chmod 644 "$SCRATCH/workspace/smoke.py"
"${PODMAN[@]}" run --rm \
  --pull=never \
  --network=none \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 \
  --memory=768m --memory-swap=768m --cpus=1.0 --pids-limit=128 \
  --userns=keep-id:uid=1000,gid=1000 --user 1000:1000 --init \
  -v "$SCRATCH/workspace:/workspace:rw" \
  -v "$SCRATCH/uploads:/mnt/useruploads:ro" \
  -v "$SCRATCH/outputs:/mnt/outputs:rw" \
  -w /workspace \
  -e HOME=/tmp -e MPLCONFIGDIR=/tmp/matplotlib -e PYTHONUNBUFFERED=1 -e MPLBACKEND=Agg \
  "$IMAGE" sh -lc 'python -I /workspace/smoke.py && node --version && git --version'

test -s "$SCRATCH/outputs/smoke.png"
test -s "$SCRATCH/outputs/smoke.csv"
echo "   wrote smoke.png and smoke.csv"

echo "2/5 Verifying outbound internet access…"
if "${PODMAN[@]}" run --rm --pull=never --dns 1.1.1.1 --dns 9.9.9.9 \
  --cap-drop=ALL --security-opt=no-new-privileges --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
  --userns=keep-id:uid=1000,gid=1000 --user 1000:1000 \
  "$IMAGE" sh -lc 'curl -fsS -m 20 -o /dev/null https://example.com'; then
  echo "   internet reachable"
else
  echo "error: the sandbox could not reach the internet" >&2
  exit 1
fi

echo "3/5 Verifying host/LAN egress is blocked…"
FIREWALL_ACTIVE=0
if systemctl is-active --quiet assistant-sandbox-firewall.service 2>/dev/null; then
  FIREWALL_ACTIVE=1
fi
if [[ "${FIREWALL_ACTIVE}" -eq 1 ]]; then
  cat > "$SCRATCH/workspace/egress.py" <<'PY'
import socket
import struct


def gateway():
    try:
        with open("/proc/net/route", encoding="ascii") as handle:
            next(handle)
            for line in handle:
                fields = line.split()
                if len(fields) > 3 and fields[1] == "00000000":
                    return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except OSError:
        pass
    return None


targets = [(host, 22) for host in [gateway()] if host] + [("169.254.169.254", 80)]
for host, port in targets:
    try:
        with socket.create_connection((host, port), timeout=4):
            raise SystemExit(f"reached private address {host}:{port}")
    except socket.timeout:
        continue
    except OSError as exc:
        # A refusal still proves the packet reached the private host, which
        # means the egress guard is not working.
        if getattr(exc, "errno", None) == 111:
            raise SystemExit(f"private address {host}:{port} refused instead of dropping")
raise SystemExit(0)
PY
  chmod 644 "$SCRATCH/workspace/egress.py"
  if "${PODMAN[@]}" run --rm --pull=never --dns 1.1.1.1 \
    --cap-drop=ALL --security-opt=no-new-privileges --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
    --userns=keep-id:uid=1000,gid=1000 --user 1000:1000 \
    -v "$SCRATCH/workspace:/workspace:ro" -w /workspace \
    "$IMAGE" sh -lc 'python -I /workspace/egress.py'; then
    echo "   private addresses correctly dropped"
  else
    echo "error: the sandbox could reach a private address" >&2
    exit 1
  fi
else
  echo "   egress guard not active (development mode); skipping"
fi

echo "4/5 Verifying the root filesystem is read-only…"
if "${PODMAN[@]}" run --rm --pull=never --network=none --cap-drop=ALL \
  --security-opt=no-new-privileges --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
  --userns=keep-id:uid=1000,gid=1000 --user 1000:1000 \
  "$IMAGE" sh -lc 'if touch /etc/evil 2>/dev/null; then exit 1; fi; exit 0'; then
  echo "   root filesystem correctly read-only"
else
  echo "error: the sandbox could write to the image filesystem" >&2
  exit 1
fi

echo "5/5 Verifying uploads are mounted read-only and outputs writable…"
cat > "$SCRATCH/workspace/probe.py" <<'PY'
from pathlib import Path

Path("/mnt/outputs/probe.txt").write_text("ok", encoding="utf-8")
try:
    Path("/mnt/useruploads/probe.txt").write_text("bad", encoding="utf-8")
except OSError:
    raise SystemExit(0)
raise SystemExit("uploads mount was writable")
PY
chmod 644 "$SCRATCH/workspace/probe.py"
"${PODMAN[@]}" run --rm --pull=never --network=none --cap-drop=ALL \
  --security-opt=no-new-privileges --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
  --userns=keep-id:uid=1000,gid=1000 --user 1000:1000 \
  -v "$SCRATCH/workspace:/workspace:ro" \
  -v "$SCRATCH/uploads:/mnt/useruploads:ro" \
  -v "$SCRATCH/outputs:/mnt/outputs:rw" \
  -w /workspace \
  "$IMAGE" sh -lc 'python -I /workspace/probe.py'
echo "   uploads read-only, outputs writable"

echo
echo "Sandbox OK: ${IMAGE}"
