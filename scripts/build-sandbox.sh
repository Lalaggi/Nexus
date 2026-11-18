#!/usr/bin/env bash
# Build the rootless Podman image used by the sandbox tool.
#
# After scripts/setup-sandbox-user.sh this builds as the dedicated `sandbox`
# user, so images and layers live on its capped filesystem. Before setup (or
# on a development machine) it falls back to the current user's Podman.
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="${ASSISTANT_SANDBOX_IMAGE:-localhost/nexus-code-sandbox:latest}"
CONTAINERFILE="${1:-sandbox/Containerfile}"
WRAPPER="/usr/local/bin/nexus-sandbox-podman"
SANDBOX_USER="${ASSISTANT_SANDBOX_USER:-sandbox}"

PODMAN=(podman)
SANDBOX_MODE=0
if [[ -x "${WRAPPER}" ]] && id "${SANDBOX_USER}" >/dev/null 2>&1 && [[ "$(id -un)" != "${SANDBOX_USER}" ]]; then
  if sudo -n -u "${SANDBOX_USER}" "${WRAPPER}" info >/dev/null 2>&1; then
    PODMAN=(sudo -n -u "${SANDBOX_USER}" "${WRAPPER}")
    SANDBOX_MODE=1
    echo "Using dedicated sandbox account: ${SANDBOX_USER}"
  fi
fi

if ! command -v podman >/dev/null 2>&1; then
  echo "error: podman is not installed" >&2
  exit 1
fi

BUILD_CONTEXT="sandbox"
CLEANUP=""
if [[ "${SANDBOX_MODE}" -eq 1 ]]; then
  # The project may live in a 0700 home the sandbox account cannot read.
  CLEANUP="$(mktemp -d /tmp/nexus-sandbox-build.XXXXXX)"
  chmod 755 "${CLEANUP}"
  cp "${CONTAINERFILE}" "${CLEANUP}/Containerfile"
  chmod 644 "${CLEANUP}/Containerfile"
  BUILD_CONTEXT="${CLEANUP}"
  CONTAINERFILE="${CLEANUP}/Containerfile"
  trap 'rm -rf "${CLEANUP}"' EXIT
fi

echo "Building ${IMAGE} from ${CONTAINERFILE} (first build downloads ~500 MB)…"
"${PODMAN[@]}" build \
  --tag "${IMAGE}" \
  --file "${CONTAINERFILE}" \
  "${BUILD_CONTEXT}/"

echo
echo "Built ${IMAGE}."
echo "Verify it with: ./scripts/test-sandbox.sh"
