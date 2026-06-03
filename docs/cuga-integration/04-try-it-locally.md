<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Try It Locally — Dev Setup and Tests

This guide walks through verifying the CUGA integration end-to-end on a local dev machine. It does **not** require an OpenShell host — the integration surface (agent registry, branding, CLI alias) is fully exercisable on macOS or Linux with just Node.

For a real sandboxed run inside OpenShell, see the upstream [Prerequisites](https://docs.nvidia.com/nemoclaw/latest/get-started/prerequisites.html) and [Quickstart](https://docs.nvidia.com/nemoclaw/latest/get-started/quickstart.html); the CUGA agent slots into that same flow with `--agent cuga`.

## Prerequisites

- **Node.js ≥ 24** (`node --version`). The repo enforces this via `scripts/check-node-version.js`.
- **npm ≥ 11** (`npm --version`).
- Git, a working shell, ~2 GB free disk for `node_modules`.
- macOS or Linux is fine for the registry tests. The full `--project cli` suite has ~47 pre-existing test failures on macOS that depend on Linux-only shell tooling (sandbox `start.sh`, iptables, etc.) — these are environmental, not related to CUGA.

## 1. Get the code

```bash
cd /Users/anu/Documents/GitHub/explore
# already cloned if you ran the integration steps:
ls NemoClaw/
# otherwise:
# git clone https://github.com/NVIDIA/NemoClaw.git
cd NemoClaw
```

## 2. Install + build

```bash
npm install --ignore-scripts          # ~12s, 469 packages
npm run build:cli                     # tsc + generate oclif manifest
```

The `--ignore-scripts` flag skips the `prepare` hook (which tries to install pre-commit git hooks via `prek`). You can drop it once you have `prek` installed.

## 3. Smoke-check the registry sees CUGA

```bash
node -e "
const {listAgents, loadAgent, getAgentChoices} = require('./dist/lib/agent/defs');
console.log('agents:', listAgents());
console.log('CUGA display:', loadAgent('cuga').displayName);
console.log('picker order:', getAgentChoices().map(c => c.name));
"
```

Expected output:

```
agents: [ 'cuga', 'hermes', 'openclaw' ]
CUGA display: CUGA
picker order: [ 'openclaw', 'cuga', 'hermes' ]
```

## 4. Smoke-check the `nemocuga` alias

```bash
./bin/nemocuga.js --help 2>&1 | head -5
```

You should see `nemocuga` (not `nemoclaw`) in the usage line. The alias sets `NEMOCLAW_AGENT=cuga` before delegating to the main CLI.

## 5. Run the CUGA-targeted test suites

```bash
# Just the agent registry + CLI alias tests — runs in ~3 seconds
npx vitest run src/lib/agent/defs.test.ts test/cli-oclif-compatibility.test.ts
```

Expected: **23 tests pass** (including 7 new CUGA-specific cases).

Wider safety net — every test file touching agents, branding, onboard, uninstall:

```bash
npx vitest run \
  src/lib/agent/ \
  test/cli-oclif-compatibility.test.ts \
  test/uninstall.test.ts \
  src/commands/onboard.test.ts
```

Expected: **83 tests pass**.

## 6. Optional — run the full CLI test project

```bash
npx vitest run --project cli
```

On macOS, expect roughly **5763 pass / 51 fail / 19 skip**. The failing files (`hermes-start.test.ts`, `install-docker-group-reexec.test.ts`, `nemoclaw-start.test.ts`, `sandbox-provisioning.test.ts`, `ssrf-parity.test.ts`, etc.) all depend on Linux-only shell tooling and are flaky outside an OpenShell host. None of them are in files the CUGA integration touched; the same files fail at the same rate before the integration was added.

## 7. Where to look next

- [`agents/cuga/manifest.yaml`](../../agents/cuga/manifest.yaml) — the contract
- [`agents/cuga/policy-permissive.yaml`](../../agents/cuga/policy-permissive.yaml) — the network policy
- [`bin/nemocuga.js`](../../bin/nemocuga.js) — the alias launcher
- [03-new-architecture.md](./03-new-architecture.md#what-is-not-yet-in-this-integration) — what is still needed to fully onboard CUGA inside an OpenShell sandbox (Dockerfile, start.sh, generate-config.ts)

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `npm install` errors about Node version | Upgrade to Node ≥ 24 (`nvm install 24`) |
| `Cannot find module './dist/...'` from tests | Run `npm run build:cli` — tests import from `dist/` |
| `nemocuga` usage shows `nemoclaw` | Confirm `KNOWN_CLI_NAMES` in `src/lib/cli/branding.ts` includes `nemocuga`, then `npm run build:cli` |
| New CUGA tests fail with `Agent 'cuga' not found` | Confirm `agents/cuga/manifest.yaml` exists and is valid YAML |
