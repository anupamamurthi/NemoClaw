<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# CUGA Integration — Overview

## What is CUGA

[CUGA](https://github.com/cuga-project/cuga-agent) is an open-source **generalist agent harness for the enterprise**. Its architecture is composable and centered on specialized reasoning components that collaborate:

- **Planner** — decomposes a user task into a structured execution plan with variable management
- **Code Agent** — executes Python in a sandbox (local, Docker/Podman, or E2B cloud)
- **API Agent** — calls REST APIs via OpenAPI specs and MCP tools
- **Web Agent** — drives browsers via Playwright (with a browser extension)
- **CugaSupervisor** — multi-agent orchestration over the above

Around them: a **Policies SDK** (Intent Guards, Playbooks, Tool Approval gates, Output Formatters), a **Knowledge Engine** (RAG via Docling), and reasoning modes (Fast / Balanced / Accurate).

## What is NemoClaw

NemoClaw is **not** an agent. It is a **host-side reference stack** that runs other agents safely inside NVIDIA OpenShell sandboxes. It provides:

- A **hardened container blueprint** (capability drops, process limits, posture profiles)
- **Routed inference** with provider failover and audit
- **Network egress policy** with allowlists and operator approval flows
- A **lifecycle CLI** (`nemoclaw` / `nemohermes`) for onboarding, start/stop/status, upgrade
- An **agent plugin contract** — each agent declares itself with `agents/<name>/manifest.yaml`

## Why integrate CUGA

CUGA brings a richer agent surface (web + API + code + multi-agent planning) than the existing OpenClaw/Hermes pair. NemoClaw brings the enterprise deployment story CUGA does not have today.

**CUGA gains:** hardened container, audited inference routing, network egress controls, one-CLI install, lifecycle management.

**NemoClaw gains:** an enterprise workflow-automation agent in its catalog — beyond coding/general assistants, into OpenAPI/MCP-driven multi-agent execution.

## What "include CUGA into NemoClaw" means

It is an **agent plugin**, not a merger. After integration:

```bash
# Three ways to select CUGA at runtime, mirroring the Hermes pattern:
nemocuga onboard                     # alias bin
NEMOCLAW_AGENT=cuga nemoclaw onboard # env var
nemoclaw onboard --agent cuga        # flag
```

CUGA appears in the interactive agent picker alongside OpenClaw and Hermes.

See [02-existing-architecture.md](./02-existing-architecture.md) for how NemoClaw is structured today, and [03-new-architecture.md](./03-new-architecture.md) for what the CUGA integration changes.
