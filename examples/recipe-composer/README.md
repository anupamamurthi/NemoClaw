<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Recipe Composer — same workflow, two agents

A small, self-contained CUGA app ported into an agent-neutral shape so it can run through either the **CUGA agent** or the **Hermes agent**.

The original app lives at `cuga-apps/apps/recipe_composer/` (a 500-line FastAPI service that wraps `CugaAgent` and serves a chat UI). The version here strips it back to its essence — a tool catalog + a system prompt + a tiny state store — and provides two thin runners. Same workflow, two runtimes.

## Why this one

- **No external APIs, no auth.** All "knowledge" is static tables in `tools.py` (macros, substitutions, diet blocklist). You can run it offline.
- **Deterministic tools.** Every tool returns JSON; same inputs → same outputs. Makes verification across agents tractable.
- **Small.** 9 tools, ~250 lines of Python, 3 test scenarios.

## Layout

```
examples/recipe-composer/
├── tools.py          # 9 tools, OpenAI-style schemas, per-thread state — pure Python
├── prompt.md         # system prompt the LLM follows
├── scenarios.json    # 3 deterministic transcripts + verification invariants
├── run_cuga.py       # adapter: wraps tools as LangChain @tool, runs through CugaAgent
├── run_hermes.py     # adapter: hits Hermes' OpenAI-compatible /v1/chat/completions
├── test_tools.py     # 20 pure-Python unit tests — no LLM, no agent
└── README.md         # this file
```

`tools.py` is the spec; the two runners are adapters; the vitest harness at [`test/examples-recipe-composer.test.ts`](../../test/examples-recipe-composer.test.ts) drives everything.

## How to run

### Tier 1 — pure-Python tool tests (no LLM, no agent runtime)

Always works. Confirms the workflow's data layer is sound.

```bash
cd /Users/anu/Documents/GitHub/explore/NemoClaw/examples/recipe-composer
python3 test_tools.py
# Ran 20 tests in 0.001s — OK
```

### Tier 2 — the vitest harness (structural + Tier 1, opt-in for agents)

From the NemoClaw root:

```bash
cd /Users/anu/Documents/GitHub/explore/NemoClaw
npx vitest run test/examples-recipe-composer.test.ts
#   13 tests | 11 pass | 2 skipped (the agent runners are opt-in)
```

### Tier 3 — run the CUGA agent end-to-end

Requires CUGA installed and an LLM provider configured.

```bash
pip install cuga langchain langchain-openai     # or your provider of choice
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...

cd examples/recipe-composer
python3 run_cuga.py                      # all 3 scenarios
python3 run_cuga.py weeknight_vegetarian # just one

# To wire it into the vitest harness:
cd /Users/anu/Documents/GitHub/explore/NemoClaw
RUN_CUGA_RUNNER=1 npx vitest run test/examples-recipe-composer.test.ts
```

Output is JSON-lines, one per scenario:

```json
{"agent":"cuga","scenario":"weeknight_vegetarian","elapsed_ms":11420,
 "tool_calls":["add_to_pantry","add_to_pantry","...","save_recipes"],
 "verdict":{"ok":true,"failures":[]},
 "final_text":"Here are three vegetarian dinner ideas tonight: 1) Garlic..."}
```

### Tier 4 — run the Hermes agent end-to-end

Requires a running Hermes server. Its `/v1` endpoint is OpenAI-compatible, so the runner just speaks chat-completions with tools.

```bash
pip install requests
export HERMES_BASE_URL=http://localhost:8642/v1
export HERMES_API_KEY="$(cat ~/.hermes/.env | grep API_SERVER_KEY | cut -d= -f2)"
export HERMES_MODEL=hermes-3-llama-3.1-8b   # whatever model your Hermes instance serves

cd examples/recipe-composer
python3 run_hermes.py                      # all 3 scenarios
python3 run_hermes.py weeknight_vegetarian # just one

# Or via the vitest harness:
cd /Users/anu/Documents/GitHub/explore/NemoClaw
RUN_HERMES_RUNNER=1 npx vitest run test/examples-recipe-composer.test.ts
```

Same output shape — so a `diff <(python3 run_cuga.py ...) <(python3 run_hermes.py ...)` gives you a real apples-to-apples comparison.

### Tier 5 — through NemoClaw sandboxes (Linux + OpenShell required)

**Prerequisites:** an OpenShell-capable Linux host (Brev, EC2, bare-metal). Will not work on macOS — see the troubleshooting section of [04-try-it-locally.md](../../docs/cuga-integration/04-try-it-locally.md).

#### CUGA path (Dockerfile + start.sh + generate-config now in this branch)

```bash
# 1. Onboard the sandbox. Choose your LLM provider + base URL.
nemocuga onboard \
  --model openai/gpt-4o-mini \
  --provider-key custom \
  --inference-base-url https://inference.local/v1

# 2. Mount this example's tools + playbook into the sandbox before start.
mkdir -p ~/.cuga-mounts/recipe-composer
cp examples/recipe-composer/{tools.py,prompt.md,scenarios.json} \
   ~/.cuga-mounts/recipe-composer/
# (and an mcp_servers.yaml that registers tools.py as a Python tool source)

nemocuga start

# 3. Drive the scenarios over the sandbox-forwarded port.
export NEMOCLAW_SANDBOX=<your-sandbox-name>
python3 examples/recipe-composer/run_cuga.py
# [run_cuga] mode: nemoclaw-sandbox (sandbox=..., url=http://localhost:8005)
```

The runner detects `NEMOCLAW_SANDBOX`, asks `nemoclaw status` for the forwarded URL + bearer token, and drives CUGA over its `/v1/chat/completions` endpoint inside the sandbox.

#### Hermes path (works today; Hermes Dockerfile/start.sh are upstream)

```bash
nemohermes onboard
nemohermes start

export NEMOCLAW_SANDBOX=<your-sandbox-name>
python3 examples/recipe-composer/run_hermes.py
```

#### What you've actually proven with Tier 5

| Layer | Verified |
|---|---|
| Agent registry picks the right `agents/<name>/manifest.yaml` | ✅ |
| Dockerfile.base + Dockerfile build the sandbox image | ✅ |
| `start.sh` drops privileges and launches the agent | ✅ |
| `generate-config.ts` renders agent config from build args | ✅ |
| Health probe at the manifest's URL/port responds | ✅ |
| Network egress policy from `agents/<name>/policy-permissive.yaml` is in force | ✅ |
| LLM calls route through `inference.local` | ✅ |
| The same scenario verdict still passes through the wrapper | ✅ if `verdict.ok == true` in the JSON-lines output |

This is what the integration is ultimately for — running the same workflow under the hardened blueprint with egress policy in effect.

## How the verifier works

`scenarios.json` declares each scenario's user turns and an `expected` block of invariants the final session state must satisfy:

- `pantry_includes` — every named ingredient ended up in the pantry
- `diet` — final diet matches
- `allergies` — exact allergen list
- `recipes_saved_min` / `max` — count bounded
- `no_recipe_uses_any` — no recipe lists any of these in its `uses` (catches diet/allergen leaks)
- `must_have_called_tool` — the named tools were actually invoked at least once

Each runner returns the same `verdict` shape. Failures are listed; an empty list means `ok: true`. The vitest assertion is exactly that.

## How the two agents perform

**Important caveat:** the numbers below are not benchmarks — they are architectural expectations from how each agent is built. Run the scenarios on your own machine + provider to get real numbers. Both runners print `elapsed_ms` and `tool_calls`, which is all you need.

| Dimension | CUGA agent | Hermes agent |
|---|---|---|
| **Calling pattern** | Planner produces an explicit plan first; specialized agents (API/Code/Web/Supervisor) execute steps with structured handoffs | Single OpenAI-compatible chat loop: model decides per-turn whether to emit tool_calls; we dispatch and reply |
| **Tool-call sequencing** | Tends to **batch and group** (calls `add_to_pantry` for every mentioned ingredient before doing anything else; explicitly enumerates compatibility checks per candidate dish) | Tends to **interleave** (may ask one diet question, then plan a dish, then come back for more pantry items) |
| **Determinism per run** | Higher — the plan step constrains downstream choices | Lower — each turn is an independent model call |
| **Token shape** | More upfront planning tokens; fewer per-tool turns | Fewer planning tokens; more per-tool turns |
| **Wall-clock for this scenario** | Slightly slower at small N because of planning overhead; scales better as workflows grow | Faster on short workflows; can balloon if the model loops on tool calls |
| **Failure recovery** | Plan-level retry: if `save_recipes` fails, the Planner re-derives | In-loop self-correction: model sees the error in the next user turn and tries again |
| **What you'd see in `tool_calls`** | Typically: pantry adds (batched) → diet → allergy → `list_pantry` → N× `check_diet_compatibility` → `save_recipes` | Typically: more interleaved, sometimes `list_pantry` called twice, sometimes `check_diet_compatibility` skipped if model "feels confident" |
| **Robustness to ambiguous prompts** | Higher — Planner forces explicit decomposition | Lower — quality tracks the underlying chat model closely |
| **Cost per scenario** | A bit higher (planning + execution) | Lower for short workflows, higher when the model loops |

**Rule of thumb from the scenarios here:**
- For `macro_lookup` (one-shot) — Hermes will be faster and cheaper; CUGA's planning is overhead you don't need.
- For `weeknight_vegetarian` (multi-constraint, multi-tool) — CUGA's verdict pass rate is more reliable; Hermes is faster when it works but more likely to skip the `check_diet_compatibility` step.
- For `keto_minimal_pantry` (similar shape) — same as above.

What matters more than the raw numbers: when you swap a model under each runtime, **CUGA's behavior changes less** because the Planner anchors the flow. **Hermes' behavior changes more** because the model is the flow.

## When to use which (from this example)

- **Pick CUGA** when the workflow has explicit decomposable steps, you want predictable tool sequences, and you'd rather pay upfront planning cost than debug missed steps.
- **Pick Hermes** when the workflow is short, conversational, and you want minimal latency per turn.
- **Pick NemoClaw around either** when you need the hardened sandbox, network egress controls, routed inference, and lifecycle management on top.
