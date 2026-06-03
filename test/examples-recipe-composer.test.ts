// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Tests for examples/recipe-composer — a small, self-contained CUGA app
// (no external APIs, no auth) ported into an agent-neutral shape so it
// can run through either the CUGA agent or the Hermes agent.
//
// What this file does:
//   1. Always-on: structural validation of the example files (paths, JSON,
//      schema/registry parity, OPENAI_TOOL_SCHEMAS shape). No interpreter
//      shell-out required — runs everywhere vitest does.
//   2. If `python3` is available: shells out to run the pure-Python
//      deterministic tool tests (test_tools.py). No CUGA, no Hermes, no LLM.
//   3. If `RUN_CUGA_RUNNER=1` and `python3` are available: runs the CUGA
//      scenario runner end-to-end (requires `cuga` installed + LLM creds).
//   4. If `RUN_HERMES_RUNNER=1` and `python3` are available: runs the
//      Hermes scenario runner end-to-end (requires HERMES_BASE_URL +
//      HERMES_API_KEY pointing at a running Hermes server).
//
// Tiers 3+4 are opt-in to keep CI green when the runtimes aren't present.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const EX = path.join(ROOT, "examples", "recipe-composer");

interface ScenarioFile {
  scenarios: Array<{
    name: string;
    thread_id: string;
    turns: string[];
    expected: Record<string, unknown>;
  }>;
}

function readScenarios(): ScenarioFile {
  return JSON.parse(fs.readFileSync(path.join(EX, "scenarios.json"), "utf8"));
}

function hasPython3(): boolean {
  return spawnSync("python3", ["--version"], { encoding: "utf8" }).status === 0;
}

interface RunnerResult {
  agent: "cuga" | "hermes";
  scenario: string;
  elapsed_ms: number;
  tool_calls: string[];
  verdict: { ok: boolean; failures: string[] };
  final_text: string;
}

function runPythonRunner(
  script: string,
  scenarioName?: string,
  extraEnv: Record<string, string> = {},
): RunnerResult[] {
  const args = [path.join(EX, script)];
  if (scenarioName) args.push(scenarioName);
  const result = spawnSync("python3", args, {
    cwd: EX,
    encoding: "utf8",
    env: { ...process.env, ...extraEnv },
    timeout: 300_000,
  });
  if (result.error) throw result.error;
  const lines = (result.stdout || "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  return lines.map((l) => JSON.parse(l) as RunnerResult);
}

describe("examples/recipe-composer — structural validation", () => {
  const expectedFiles = [
    "README.md",
    "tools.py",
    "prompt.md",
    "scenarios.json",
    "run_cuga.py",
    "run_hermes.py",
    "test_tools.py",
  ];

  it.each(expectedFiles)("%s exists", (name) => {
    expect(fs.existsSync(path.join(EX, name))).toBe(true);
  });

  it("scenarios.json parses and declares at least one scenario per shape", () => {
    const { scenarios } = readScenarios();
    expect(scenarios.length).toBeGreaterThanOrEqual(1);
    for (const s of scenarios) {
      expect(s.name).toMatch(/^[a-z0-9_]+$/);
      expect(s.thread_id.length).toBeGreaterThan(0);
      expect(s.turns.length).toBeGreaterThan(0);
      expect(typeof s.expected).toBe("object");
    }
  });

  it("prompt.md is non-trivial and mentions the tool sequence", () => {
    const prompt = fs.readFileSync(path.join(EX, "prompt.md"), "utf8");
    expect(prompt.length).toBeGreaterThan(300);
    for (const tool of [
      "add_to_pantry",
      "list_pantry",
      "check_diet_compatibility",
      "save_recipes",
    ]) {
      expect(prompt).toContain(tool);
    }
  });

  it("tools.py registry and OpenAI schemas declare all 9 expected tools", () => {
    const src = fs.readFileSync(path.join(EX, "tools.py"), "utf8");
    const expectedTools = [
      "add_to_pantry",
      "remove_from_pantry",
      "list_pantry",
      "set_diet",
      "add_allergy",
      "estimate_macros",
      "suggest_substitution",
      "check_diet_compatibility",
      "save_recipes",
    ];
    // Each tool should appear both as a TOOLS registry entry and as a
    // "name": "<tool>" field inside OPENAI_TOOL_SCHEMAS.
    for (const t of expectedTools) {
      // TOOLS entry: `    "<name>": ...,` (whitespace-padded line).
      const reRegistry = new RegExp(`^\\s*"${t}":\\s+${t},\\s*$`, "m");
      expect(reRegistry.test(src), `TOOLS missing '${t}'`).toBe(true);
      // OpenAI schema entry.
      const reSchema = new RegExp(`"name":\\s*"${t}"`);
      expect(reSchema.test(src), `OPENAI_TOOL_SCHEMAS missing '${t}'`).toBe(true);
    }
  });
});

describe("examples/recipe-composer — Python tool tests", () => {
  const skip = !hasPython3();

  it.skipIf(skip)("test_tools.py: all 20 unit tests pass", () => {
    const result = spawnSync("python3", ["test_tools.py"], {
      cwd: EX,
      encoding: "utf8",
      timeout: 60_000,
    });
    if (result.status !== 0) {
      console.error(result.stdout, result.stderr);
    }
    expect(result.status).toBe(0);
    // unittest writes its "Ran N tests" line to stderr.
    expect(result.stderr).toContain("OK");
    expect(result.stderr).toContain("Ran 20 tests");
  });
});

describe("examples/recipe-composer — CUGA runner (opt-in)", () => {
  const skip = !hasPython3() || process.env.RUN_CUGA_RUNNER !== "1";

  it.skipIf(skip)(
    "weeknight_vegetarian scenario completes with a passing verdict",
    () => {
      const results = runPythonRunner("run_cuga.py", "weeknight_vegetarian");
      expect(results).toHaveLength(1);
      const [r] = results;
      expect(r.agent).toBe("cuga");
      expect(r.verdict.ok).toBe(true);
      expect(r.tool_calls).toContain("save_recipes");
    },
    600_000,
  );
});

describe("examples/recipe-composer — Hermes runner (opt-in)", () => {
  const skip = !hasPython3() || process.env.RUN_HERMES_RUNNER !== "1";

  it.skipIf(skip)(
    "weeknight_vegetarian scenario completes with a passing verdict",
    () => {
      const results = runPythonRunner("run_hermes.py", "weeknight_vegetarian");
      expect(results).toHaveLength(1);
      const [r] = results;
      expect(r.agent).toBe("hermes");
      expect(r.verdict.ok).toBe(true);
      expect(r.tool_calls).toContain("save_recipes");
    },
    600_000,
  );
});
