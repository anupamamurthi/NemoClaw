<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Next steps — for the Claude session on the Linux machine

> **Read [memory.md](./memory.md) first.** This file is a forward-looking task brief; `memory.md` is the full handoff from the previous session (what the user asked for across many turns, the file inventory, known unknowns, gotchas, anti-patterns). Don't skip it.

## Your mission, in one sentence

Prove the CUGA-in-NemoClaw integration actually works end-to-end on a Linux + OpenShell host, then upgrade the `examples/recipe-composer/` demo from "agent-comparison that bypasses NemoClaw" into "agent-comparison that truly runs through NemoClaw."

## Why this exists

The previous session was on macOS. NemoClaw wraps NVIDIA OpenShell, which needs Linux kernel features (Landlock, capability drops via namespaces, iptables egress). So the previous session:

- ✅ Built and tested everything that doesn't need a sandbox (registry, branding, CLI alias, structural tests, pure-Python tool tests)
- ✅ Wrote the full sandbox wiring blind (Dockerfile.base, Dockerfile, start.sh, generate-config.ts) by mirroring Hermes
- ❌ Never actually ran any of it through a sandbox

You are the first session that can. **Verify what the previous session built, and close the loop on what they couldn't.**

## What success looks like

Three concrete deliverables, in order:

1. **`nemocuga onboard && nemocuga start` produces a running sandboxed CUGA** with health probe passing.
2. **All three test tiers pass cleanly** on this Linux host (see "Tasks" below for the exact commands).
3. **The recipe-composer example genuinely runs through NemoClaw** — both runners report `mode: nemoclaw-sandbox` and produce passing verdicts.

When all three are true, commit a follow-up that flips the docs from "*should* work on Linux" to "*verified working on Linux on <date> with <OpenShell version>*."

## Tasks

### Task 1 — Smoke the existing state on this Linux machine

```bash
cd <repo>
node --version    # must be ≥ 24
npm install       # NOT --ignore-scripts this time; prek hooks should install on Linux
npm run build:cli

# Confirm baseline:
npx vitest run src/lib/agent/defs.test.ts \
              test/cli-oclif-compatibility.test.ts \
              test/examples-recipe-composer.test.ts
#   Expect 34/34 pass, 2 skipped (the opt-in agent runners).

python3 examples/recipe-composer/test_tools.py
#   Expect 20/20 pass.
```

If anything here fails on Linux that passed on macOS, **stop and diagnose** — it means something the previous session built doesn't translate. The likely candidates: TypeScript compilation differences, Python 3 version mismatch, missing system packages.

### Task 2 — Verify the previous session's Linux-only assumptions

Before building images, sanity-check the 8 known unknowns enumerated in [memory.md § "Known unknowns / things to verify on Linux"](./memory.md). Fix each one in place:

| Check | What to do if wrong |
|-------|---------------------|
| `cuga --version` works after `pip install cuga` | Patch `agents/cuga/manifest.yaml` `version_command` to `cuga --help \| head -1` or similar |
| `cuga server start --config <path>` is real | Adjust last line of `agents/cuga/start.sh` and `manifest.yaml`'s `gateway_command` description |
| CUGA exposes `/v1/chat/completions` (OpenAI-compatible) | If not, change `run_cuga.py`'s `_run_one_http` to use CUGA's native endpoint (`POST /ask {question, thread_id}` per the original `recipe_composer/main.py`) |
| `nemoclaw status <name> --json` returns `forwarded_url` + `bearer_token` | Update field names in both `run_cuga.py` and `run_hermes.py` `_nemoclaw_sandbox_info()` |
| `npm install -g tsx@4` works inside the image | If it bloats badly, switch to a multi-stage build with a Node compile step |
| Hermes `nemoclaw status` JSON has same field names as CUGA | Should — but cross-check |

Document any fix you make as a sentence in [memory.md](./memory.md) under "Linux verifications" (add the section if absent).

### Task 3 — Build the CUGA sandbox image

```bash
docker build -f agents/cuga/Dockerfile.base \
             -t nemoclaw/cuga-sandbox-base:dev .
# ~10 min first time (Chromium download is the long pole)

docker build -f agents/cuga/Dockerfile \
             --build-arg BASE_IMAGE=nemoclaw/cuga-sandbox-base:dev \
             --build-arg NEMOCLAW_MODEL=openai/gpt-4o-mini \
             -t nemoclaw/cuga-sandbox:dev .
```

If either build fails, fix in the Dockerfile and document the fix in `memory.md`. The previous session wrote these blind; expect 1–2 rounds of iteration.

### Task 4 — Onboard and start

```bash
nemocuga onboard --model openai/gpt-4o-mini \
                 --inference-base-url https://inference.local/v1
nemocuga start
nemocuga status                          # health probe should pass
curl http://localhost:8005/health        # → 200 OK
```

Same for Hermes (works upstream already, treat as control):

```bash
nemohermes onboard && nemohermes start
nemohermes status
```

### Task 5 — Run the recipe-composer through both sandboxes

```bash
# CUGA path
export NEMOCLAW_SANDBOX=<your-cuga-sandbox-name>
python3 examples/recipe-composer/run_cuga.py
# Expect: "[run_cuga] mode: nemoclaw-sandbox (sandbox=..., url=http://localhost:8005)"
# Then JSON-lines verdicts with verdict.ok == true

# Hermes path
export NEMOCLAW_SANDBOX=<your-hermes-sandbox-name>
python3 examples/recipe-composer/run_hermes.py

# Wire them into the vitest harness:
RUN_CUGA_RUNNER=1 RUN_HERMES_RUNNER=1 \
  npx vitest run test/examples-recipe-composer.test.ts
# Expect 13/13 pass (no skips).

# Side-by-side comparison:
diff <(NEMOCLAW_SANDBOX=cuga-sbx   python3 examples/recipe-composer/run_cuga.py | jq -S .) \
     <(NEMOCLAW_SANDBOX=hermes-sbx python3 examples/recipe-composer/run_hermes.py | jq -S .)
```

### Task 6 — Make the example *truly* use NemoClaw (the upgrade)

Today the runners can hit a sandboxed agent (good), but the *workflow* itself isn't NemoClaw-aware. To close that loop:

1. **Author `examples/recipe-composer/mcp_servers.yaml`** that registers `tools.py` as an MCP/Python tool source CUGA can load server-side. (Deferred in the previous session because CUGA's MCP config format varies by version — pick the one your installed CUGA actually supports.)
2. **Document the mount recipe** in [examples/recipe-composer/README.md](./examples/recipe-composer/README.md) Tier 5: `nemocuga onboard --mount ./tools.py:/sandbox/.cuga/playbooks/recipe-composer/tools.py --mount ./prompt.md:... --mount ./mcp_servers.yaml:/sandbox/.cuga/mcp_servers.yaml`.
3. **Add an opt-in vitest case** that asserts the sandboxed CUGA *actually loaded* the workflow's tools — call `GET <forwarded-url>/v1/tools` (or whatever CUGA's tool-list endpoint is) and verify the 9 tool names from `tools.py` appear.
4. **Tighten `agents/cuga/policy-permissive.yaml`** for this specific example: drop the wildcard `web_browse` since the recipe-composer needs zero external HTTPS. That makes it a real demo of the "egress allowlist narrows to just what the workflow needs" property.
5. **Add a new tier to the README**: "Tier 6 — verify the egress policy is enforced." Try to `curl https://example.com` from inside the sandbox; expect connection refused. This makes the NemoClaw value-add visible, not theoretical.

### Task 7 — Capture what changed

Once tasks 1–6 are done:

1. Update [memory.md](./memory.md) — add a "Linux verifications" section listing what worked, what needed fixing, what surprised you.
2. Update [docs/cuga-integration/04-try-it-locally.md](./docs/cuga-integration/04-try-it-locally.md) — the "tested on" line should now include Linux.
3. Update [docs/cuga-integration/03-new-architecture.md § "Known-to-be-out-of-scope (deferred)"](./docs/cuga-integration/03-new-architecture.md#known-to-be-out-of-scope-deferred) — strike through anything you closed.
4. Commit. Push.

## Anti-patterns (lessons the previous session learned the hard way)

The user pushed back on these. Don't repeat them.

- **Don't claim tests "pass" when they were skipped.** Always report explicitly: "N passed, M skipped (gated on env X)". The user caught this and was unhappy.
- **Don't fabricate benchmark numbers.** The CUGA-vs-Hermes comparison in the example README is *architectural expectations*, not benchmarks. When you have real numbers from this Linux run, add them as a separate "Measured on <date> with <model>" subsection — don't overwrite the architectural table.
- **Don't add agent-specific `if (agent === "cuga") { ... }` branches in `src/lib/agent/defs.ts`.** The registry is data-driven. The whole point. The only TS edit the previous session made was in `src/lib/cli/branding.ts` for the CLI name allowlist — that's the bar.
- **Don't collapse the multi-agent CUGA design to a single CugaAgent** (from existing memory `feedback_ouroboros_multi_agent.md`). If something fails inside CUGA, fix the orchestration, not the agent topology.
- **Don't break anything outside the repo working directory.**

## When you get stuck

In rough priority order:

1. Re-read the relevant section of [memory.md](./memory.md) — odds are the previous session flagged exactly what you're hitting.
2. Look at how Hermes solves the same problem. `agents/hermes/` is the working reference; `agents/cuga/` is a mirror with simplifications. If something works for Hermes and not CUGA, the diff between the two files usually points at the cause.
3. The 8 failing macOS-only test files (see `memory.md` § "Test status") should pass on Linux. If they don't, that's a Linux setup issue, not a code issue.
4. The user (Anupama) has deep CUGA expertise. If a CUGA-specific question blocks you for more than 15 minutes, surface it — don't guess.

## Definition of done

- `nemocuga start` brings up a healthy sandboxed CUGA (`curl /health` returns 200)
- `RUN_CUGA_RUNNER=1 RUN_HERMES_RUNNER=1 npx vitest run test/examples-recipe-composer.test.ts` → 13/13 pass
- `diff <(run_cuga ...) <(run_hermes ...)` is a meaningful comparison (not "both errored")
- Example README's Tier 5 has been promoted from "Linux + OpenShell required" to "Linux verified on <date>"
- `mcp_servers.yaml` exists and the sandboxed CUGA actually loads the recipe-composer tools server-side
- `memory.md` has a "Linux verifications" section with what worked, what you fixed, and any surprises
- A clean commit on the branch with a message that summarizes the verification + the example upgrade

Good hunting.
