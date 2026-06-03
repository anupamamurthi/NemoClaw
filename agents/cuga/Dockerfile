# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# CUGA sandbox image — CUGA + NemoClaw config layer inside OpenShell.
#
# Layers PR-specific code (config generator, startup script, blueprint)
# on top of the pre-built CUGA base image. Mirrors agents/hermes/Dockerfile.

ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/cuga-sandbox-base:latest

# hadolint ignore=DL3006
FROM ${BASE_IMAGE}

# Verify the contract this image promises to the entrypoint.
RUN set -eu; \
    cuga_path="$(command -v cuga 2>/dev/null || true)"; \
    if [ "$cuga_path" != "/usr/local/bin/cuga" ]; then \
        echo "ERROR: expected cuga at /usr/local/bin/cuga, got ${cuga_path:-missing}" >&2; \
        exit 1; \
    fi

# Harden: drop unnecessary build tools and network probes.
RUN (apt-get remove --purge -y gcc gcc-12 g++ g++-12 cpp cpp-12 make \
        netcat-openbsd netcat-traditional ncat 2>/dev/null || true) \
    && apt-get autoremove --purge -y \
    && rm -rf /var/lib/apt/lists/*

# Copy NemoClaw config generator + supporting helpers.
COPY agents/cuga/generate-config.ts /opt/nemoclaw-cuga-config/generate-config.ts
RUN find /opt/nemoclaw-cuga-config -type d -exec chmod 755 {} + \
    && find /opt/nemoclaw-cuga-config -type f -exec chmod 444 {} +

# Copy shared blueprint (sandbox-init, OpenShell glue).
COPY nemoclaw-blueprint/ /opt/nemoclaw-blueprint/
RUN chmod -R a+rX /opt/nemoclaw-blueprint/

# Copy entrypoint.
COPY scripts/lib/sandbox-init.sh /usr/local/lib/nemoclaw/sandbox-init.sh
COPY agents/cuga/start.sh /usr/local/bin/nemoclaw-start
RUN chmod 755 /usr/local/bin/nemoclaw-start /usr/local/lib/nemoclaw/sandbox-init.sh

# Build args for config that varies per deployment. The NemoClaw
# onboard flow renders these into settings.yaml via generate-config.ts.
ARG NEMOCLAW_MODEL=openai/gpt-4o-mini
ARG NEMOCLAW_PROVIDER_KEY=custom
ARG NEMOCLAW_INFERENCE_BASE_URL=https://inference.local/v1
ARG NEMOCLAW_CUGA_API_KEY=""

# Render /sandbox/.cuga/settings.yaml at build time so the file exists
# with the right ownership before the entrypoint drops privileges.
# `tsx` is available in the base via node:22-trixie-slim; we install
# it on demand because the base image deliberately doesn't bake it in.
RUN npm install --global --no-audit --no-fund tsx@4 \
    && NEMOCLAW_MODEL="${NEMOCLAW_MODEL}" \
       NEMOCLAW_PROVIDER_KEY="${NEMOCLAW_PROVIDER_KEY}" \
       NEMOCLAW_INFERENCE_BASE_URL="${NEMOCLAW_INFERENCE_BASE_URL}" \
       NEMOCLAW_CUGA_API_KEY="${NEMOCLAW_CUGA_API_KEY}" \
       tsx /opt/nemoclaw-cuga-config/generate-config.ts \
    && chown -R sandbox:sandbox /sandbox/.cuga/settings.yaml /sandbox/.cuga/.env 2>/dev/null || true \
    && chmod 640 /sandbox/.cuga/settings.yaml /sandbox/.cuga/.env 2>/dev/null || true

# CUGA's FastAPI server listens on 8005; socat in start.sh forwards
# from the published port to the internal one if needed.
EXPOSE 8005

ENTRYPOINT ["/usr/local/bin/nemoclaw-start"]
