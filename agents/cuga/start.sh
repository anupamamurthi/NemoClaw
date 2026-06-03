#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# NemoClaw sandbox entrypoint for CUGA.
#
# Smaller sibling of agents/hermes/start.sh — same shape, fewer special
# cases (CUGA has no native messaging, no device pairing, no SQLite
# online-backup runtime layer). The big things this script does:
#
#   1. Capture stdout/stderr to /tmp/nemoclaw-start.log for diagnosis.
#   2. Source the shared sandbox-init.sh library (proxy env, common helpers).
#   3. Verify settings.yaml exists; rerun generate-config.ts if missing.
#   4. Repair ownership/permissions on the writable state tree.
#   5. Generate or rotate CUGA_API_KEY into /sandbox/.cuga/.env.
#   6. Drop from root to `sandbox` user via gosu and exec `cuga server start`.
#
# CUGA's FastAPI server listens on 0.0.0.0:8005, exposing GET /health
# (used by NemoClaw's health probe) and the chat UI at /.

set -euo pipefail

# ── Source shared sandbox initialisation library ─────────────────
_SANDBOX_INIT="/usr/local/lib/nemoclaw/sandbox-init.sh"
if [ ! -f "$_SANDBOX_INIT" ]; then
  _SANDBOX_INIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../scripts/lib/sandbox-init.sh"
fi
# shellcheck source=scripts/lib/sandbox-init.sh
# shellcheck disable=SC1090
source "$_SANDBOX_INIT"

# Harden: cap process count to slow fork bombs.
if ! ulimit -Su 512 2>/dev/null; then
  echo "[SECURITY] Could not set soft nproc limit" >&2
fi
if ! ulimit -Hu 512 2>/dev/null; then
  echo "[SECURITY] Could not set hard nproc limit" >&2
fi

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ── Stdout/stderr capture for early-failure diagnosis ────────────
_START_LOG="/tmp/nemoclaw-start.log"
: > "$_START_LOG"
chmod 600 "$_START_LOG"
exec > >(tee -a "$_START_LOG") 2> >(tee -a "$_START_LOG" >&2)

echo "[start] CUGA sandbox entrypoint starting at $(date -u +%FT%TZ)"

# ── Constants ────────────────────────────────────────────────────
CUGA_HOME="${CUGA_HOME:-/sandbox/.cuga}"
SETTINGS_PATH="${CUGA_HOME}/settings.yaml"
ENV_PATH="${CUGA_HOME}/.env"
RUNTIME_DIR="${CUGA_HOME}/runtime"
PUBLIC_PORT="${CUGA_PUBLIC_PORT:-8005}"
INTERNAL_PORT="${CUGA_INTERNAL_PORT:-8005}"

# ── Verify / regenerate settings.yaml ────────────────────────────
if [ ! -f "$SETTINGS_PATH" ]; then
  echo "[start] settings.yaml missing; regenerating from NEMOCLAW_* env"
  if command -v tsx >/dev/null 2>&1 && [ -f /opt/nemoclaw-cuga-config/generate-config.ts ]; then
    tsx /opt/nemoclaw-cuga-config/generate-config.ts
  else
    echo "[start] FATAL: generate-config.ts not present and no settings.yaml" >&2
    exit 1
  fi
fi

# ── Ownership repair on mutable state tree ───────────────────────
# OpenShell mounts volumes that may come back owned by root after a
# rebuild. The sandbox user has to own everything writable.
if [ "$(id -u)" -eq 0 ]; then
  for d in plans sessions knowledge mcp_servers playbooks workspace logs cache credentials; do
    if [ -d "${CUGA_HOME}/${d}" ]; then
      chown -R sandbox:sandbox "${CUGA_HOME}/${d}" 2>/dev/null || true
      chmod 770 "${CUGA_HOME}/${d}" 2>/dev/null || true
    fi
  done
  mkdir -p "$RUNTIME_DIR"
  chown gateway:sandbox "$RUNTIME_DIR"
  chmod 2770 "$RUNTIME_DIR"
fi

# ── Generate / load CUGA_API_KEY ─────────────────────────────────
# If .env has an empty CUGA_API_KEY, generate a fresh one on first boot
# and persist it. Subsequent boots reuse the persisted key.
if [ -f "$ENV_PATH" ]; then
  # shellcheck disable=SC1090
  CUGA_API_KEY_LINE="$(grep -E '^CUGA_API_KEY=' "$ENV_PATH" || true)"
  CUGA_API_KEY="${CUGA_API_KEY_LINE#CUGA_API_KEY=}"
fi
if [ -z "${CUGA_API_KEY:-}" ]; then
  CUGA_API_KEY="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)"
  echo "[start] generated new CUGA_API_KEY (40 chars)"
  if [ "$(id -u)" -eq 0 ]; then
    printf 'CUGA_API_KEY=%s\n' "$CUGA_API_KEY" > "$ENV_PATH"
    chown sandbox:sandbox "$ENV_PATH"
    chmod 640 "$ENV_PATH"
  fi
fi
export CUGA_API_KEY

# ── Write runtime proxy env for interactive sessions ─────────────
# Mirror the Hermes pattern so `openshell sandbox connect` shells get
# the correct CUGA_HOME and proxy variables.
PROXY_ENV_FILE="/tmp/nemoclaw-proxy-env.sh"
if [ "$(id -u)" -eq 0 ]; then
  {
    echo "# Runtime env for CUGA sandbox — written by start.sh"
    echo "export CUGA_HOME=${CUGA_HOME}"
    echo "export PATH=/usr/local/bin:/opt/cuga/.venv/bin:\${PATH}"
    [ -n "${HTTPS_PROXY:-}" ] && echo "export HTTPS_PROXY=${HTTPS_PROXY}"
    [ -n "${HTTP_PROXY:-}" ]  && echo "export HTTP_PROXY=${HTTP_PROXY}"
    [ -n "${NO_PROXY:-}" ]    && echo "export NO_PROXY=${NO_PROXY}"
  } > "$PROXY_ENV_FILE"
  chown root:root "$PROXY_ENV_FILE"
  chmod 444 "$PROXY_ENV_FILE"
fi

# ── Optional public-port forwarder ───────────────────────────────
# When the published port differs from CUGA's internal bind port,
# launch socat to bridge them. Mirrors the Hermes/OpenClaw pattern.
if [ "$PUBLIC_PORT" != "$INTERNAL_PORT" ]; then
  echo "[start] forwarding :${PUBLIC_PORT} -> :${INTERNAL_PORT} via socat"
  socat -d "TCP-LISTEN:${PUBLIC_PORT},reuseaddr,fork" \
          "TCP:127.0.0.1:${INTERNAL_PORT}" &
  SOCAT_PID=$!
  echo "$SOCAT_PID" > "${RUNTIME_DIR}/socat.pid"
fi

# ── Hand off to CUGA, dropping privileges if we're root ──────────
CUGA_CMD=(/usr/local/bin/cuga server start --config "$SETTINGS_PATH")

echo "[start] launching: ${CUGA_CMD[*]}"
if [ "$(id -u)" -eq 0 ]; then
  exec gosu sandbox env \
    CUGA_HOME="$CUGA_HOME" \
    CUGA_API_KEY="$CUGA_API_KEY" \
    PATH="/usr/local/bin:/opt/cuga/.venv/bin:${PATH}" \
    "${CUGA_CMD[@]}"
else
  exec "${CUGA_CMD[@]}"
fi
