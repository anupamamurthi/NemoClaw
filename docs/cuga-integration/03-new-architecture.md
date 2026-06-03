<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# New Architecture — CUGA as a Third Agent

## What changed

The integration is intentionally additive. NemoClaw's agent registry is data-driven, so adding CUGA required **no changes to `src/lib/agent/defs.ts`** itself — just new declarative files and one small change to the CLI branding allowlist.

### Files added

| Path | Purpose |
|------|---------|
| [`agents/cuga/manifest.yaml`](../../agents/cuga/manifest.yaml) | CUGA agent contract — picked up automatically by `listAgents()` |
| [`agents/cuga/policy-permissive.yaml`](../../agents/cuga/policy-permissive.yaml) | Permissive network policy for `shields down` mode |
| [`agents/cuga/Dockerfile.base`](../../agents/cuga/Dockerfile.base) | Base image with Python, uv, CUGA, Playwright/Chromium |
| [`agents/cuga/Dockerfile`](../../agents/cuga/Dockerfile) | Final overlay: hardens, copies generator + start.sh + blueprint |
| [`agents/cuga/start.sh`](../../agents/cuga/start.sh) | Entrypoint that drops privileges and launches `cuga server start` |
| [`agents/cuga/generate-config.ts`](../../agents/cuga/generate-config.ts) | Renders `settings.yaml` + `.env` from `NEMOCLAW_*` build args |
| [`bin/nemocuga.js`](../../bin/nemocuga.js) | Alias launcher that sets `NEMOCLAW_AGENT=cuga` |
| [`examples/recipe-composer/`](../../examples/recipe-composer/) | Runnable comparison example: same workflow, CUGA vs Hermes |
| [`docs/cuga-integration/`](.) | This documentation set |

### Files edited (minimal, surgical)

| Path | Change |
|------|--------|
| [`package.json`](../../package.json) | Registered `nemocuga` in the `bin` map |
| [`src/lib/cli/branding.ts`](../../src/lib/cli/branding.ts) | Added `cuga` → `{display: "NemoCuga", product: "CUGA", uninstallGoodbye: ...}` and `nemocuga` to `KNOWN_CLI_NAMES` |
| [`src/lib/agent/defs.test.ts`](../../src/lib/agent/defs.test.ts) | 5 new tests: CUGA manifest load, picker order, env+flag resolution |
| [`test/cli-oclif-compatibility.test.ts`](../../test/cli-oclif-compatibility.test.ts) | 2 new tests: alias bin appears in usage strings; bin pre-selects the agent |

No other source files were modified.

## How it composes with the existing flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│   user types:    nemoclaw / nemohermes / nemocuga   (or --agent <name>)  │
└─────────────┬────────────────────────────────────────────────────────────┘
              │
              ▼
   bin/nemo*.js  ───►  sets NEMOCLAW_INVOKED_AS + NEMOCLAW_AGENT
              │
              ▼
   src/lib/cli/branding.ts   ───►  picks CLI/display/product strings
              │                     (now knows about cuga / nemocuga)
              ▼
   src/lib/agent/defs.ts     ───►  listAgents() scans agents/*/manifest.yaml
              │                     → ["cuga", "hermes", "openclaw"]
              ▼
   loadAgent("cuga")         ───►  parses agents/cuga/manifest.yaml
              │
              ▼
   onboard / start / stop    ───►  uses health probe (8005), config dir
   sandbox lifecycle               (/sandbox/.cuga), state dirs, policy
                                   (agents/cuga/policy-permissive.yaml)
```

## CUGA-specific manifest decisions

| Field | Value | Why |
|-------|-------|-----|
| `language` | `python` | CUGA is a Python package |
| `install_method` | `pip` | matches CUGA's distribution |
| `health_probe.url` | `http://localhost:8005/health` | CUGA's FastAPI default |
| `forward_ports` | `[8005]` | Same FastAPI app serves UI + API |
| `dashboard.kind` | `ui` | CUGA ships a browser-based chat UI |
| `config.dir` | `/sandbox/.cuga` | mirrors `.openclaw` / `.hermes` siblings |
| `config.format` | `yaml` | CUGA uses `settings.yaml` |
| `state_dirs` | `plans, sessions, knowledge, mcp_servers, workspace, logs, cache, credentials` | Planner plans, Knowledge Engine (Docling) indexes, MCP server configs |
| `device_pairing` | `false` | CUGA uses bearer-token auth (`CUGA_API_KEY`) |
| `messaging_platforms.supported` | `[]` | CUGA's surface is REST/MCP + Web Agent, not native messaging |
| `inference.provider_type` | `custom` | Any OpenAI-compatible base URL (works with OpenShell `inference.local`) |
| `inference.provider_options` | (omitted) | No custom provider-auth plugin needed in onboarding |

## Network policy decisions

The permissive policy opens: NVIDIA inference hosts, GitHub (for skill installs), PyPI (CUGA's package registry), `cuga-project.github.io`, OpenAI and Anthropic API hosts (commonly used through CUGA's API Agent), and a `monitor`-mode wildcard `web_browse` entry covering the Playwright Web Agent's egress to arbitrary sites. In production, the wildcard would be narrowed per workflow.

## Three open design questions the integration documents but does not decide

These are flagged for production hardening — the current integration takes the pragmatic default:

1. **Sub-sandboxing** — CUGA's Code Agent can run Docker/Podman/E2B itself. Inside OpenShell that is nested sandboxing. The cleanest answer is to disable CUGA's sub-sandbox and let OpenShell be the exec environment. This is a CUGA-side config decision, not a NemoClaw code change.
2. **Web Agent browser** — Playwright/Chromium in a headless container needs Xvfb or `--headless=new`. The base blueprint can run headless Chromium; the agent Dockerfile (not yet authored in this integration) would install Chromium and the CUGA browser extension.
3. **Policy layering** — CUGA's own Policies SDK (Intent Guards, Tool Approval) is agent-side; NemoClaw's controls (network, capabilities) are host-side. Keep both; document that NemoClaw is the outer perimeter and CUGA's policies govern in-agent decisions.

## End-to-end wiring shipped in this branch

The branch now includes the full agent-plugin chain so `nemocuga onboard && nemocuga start` actually launches CUGA inside an OpenShell sandbox on a Linux host:

| File | Mirrors | Role |
|------|---------|------|
| [`agents/cuga/Dockerfile.base`](../../agents/cuga/Dockerfile.base) | [`agents/hermes/Dockerfile.base`](../../agents/hermes/Dockerfile.base) | Base image: Debian + Python + uv + CUGA + Playwright/Chromium + sandbox/gateway users + `/sandbox/.cuga/*` tree |
| [`agents/cuga/Dockerfile`](../../agents/cuga/Dockerfile) | [`agents/hermes/Dockerfile`](../../agents/hermes/Dockerfile) | Final overlay: hardens, copies generator + start.sh + blueprint, runs `generate-config.ts` at build time |
| [`agents/cuga/start.sh`](../../agents/cuga/start.sh) | [`agents/hermes/start.sh`](../../agents/hermes/start.sh) (~150 lines vs ~930) | Entrypoint: ulimits, log capture, regenerates settings on demand, repairs state ownership, mints `CUGA_API_KEY`, optional socat port-forward, `gosu`-drops to `sandbox`, `exec cuga server start` |
| [`agents/cuga/generate-config.ts`](../../agents/cuga/generate-config.ts) | [`agents/hermes/generate-config.ts`](../../agents/hermes/generate-config.ts) | Renders `/sandbox/.cuga/settings.yaml` + `.env` from `NEMOCLAW_*` build args (model, provider-key, base URL, API key) |

The `manifest.yaml`'s `gateway_command` now points at `/usr/local/bin/nemoclaw-start`, the canonical name `Dockerfile` copies `start.sh` to.

## Known-to-be-out-of-scope (deferred)

These are *intentional* deferrals, not gaps. Document them so the next iteration knows what wasn't done:

- **`agents/cuga/policy-additions.yaml` (shields-up tightening)** — current branch ships only `policy-permissive.yaml`. A production deploy would narrow the wildcard `web_browse` policy to specific allowed hosts.
- **`agents/cuga/config/*.ts` helper modules** — Hermes split its config rendering across 7 helper files for messaging, build env, managed tool gateways, etc. CUGA's `generate-config.ts` is a single ~100-line file because CUGA has no native messaging adapters; if/when CUGA acquires them, factor the same way.
- **`agents/cuga/plugin/`** — Hermes ships a Python plugin (`agents/hermes/plugin/`) that runs inside the agent process. CUGA does not need one for the basic integration; if a future feature requires in-process hooks, mirror the Hermes layout.
- **CUGA-specific provider auth (`src/lib/cuga-provider-auth.ts`)** — Hermes has one because of its Nous Portal OAuth flow. CUGA uses a plain bearer token to the LLM endpoint, so no equivalent is required.
- **Native `cuga --version`** — current CUGA versions may not implement it; the base image accepts a `[warn]` for now. Either patch upstream or replace with `cuga --help | head -1` parsing.
