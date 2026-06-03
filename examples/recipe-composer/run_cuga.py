#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Run the Recipe Composer scenarios through the CUGA agent.

Two modes:

    A) IN-PROCESS (default) — imports cuga.sdk.CugaAgent and runs the
       agent in this Python process. Needs `pip install cuga` + an LLM
       provider key. Bypasses NemoClaw entirely.

    B) NEMOCLAW-SANDBOXED — when NEMOCLAW_SANDBOX=<name> is set, the
       runner queries `nemoclaw status` for the sandbox's forwarded URL
       and bearer token, then drives CUGA over its OpenAI-compatible
       /v1/chat/completions endpoint. Requires the sandbox to be up
       (`nemocuga start`) and the workflow's tools to be registered
       server-side via mounted mcp_servers.yaml.

Usage:
    python run_cuga.py                       # all scenarios
    python run_cuga.py weeknight_vegetarian  # one scenario
    python run_cuga.py --provider openai     # in-process LLM provider
    NEMOCLAW_SANDBOX=my-cuga python run_cuga.py   # mode B

Output:
    JSON-lines, one line per scenario — same shape as run_hermes.py so
    `diff <(python run_cuga.py) <(python run_hermes.py)` works.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

import tools as recipe_tools  # noqa: E402

_PROMPT = (_DIR / "prompt.md").read_text()
_SCENARIOS = json.loads((_DIR / "scenarios.json").read_text())["scenarios"]


def _nemoclaw_sandbox_info(sandbox: str) -> dict:
    """Query the NemoClaw CLI for a running sandbox's forwarded URL +
    bearer token. Returns {} if NemoClaw is absent or the sandbox is
    not registered — caller falls back to in-process mode."""
    import shutil, subprocess
    if not shutil.which("nemoclaw"):
        return {}
    try:
        out = subprocess.check_output(
            ["nemoclaw", "status", sandbox, "--json"],
            stderr=subprocess.DEVNULL, timeout=15,
        )
        return json.loads(out)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError):
        return {}


_SANDBOX  = os.environ.get("NEMOCLAW_SANDBOX", "").strip()
_SBX_INFO = _nemoclaw_sandbox_info(_SANDBOX) if _SANDBOX else {}
_HTTP_MODE = bool(_SBX_INFO)


def _wrap_with_langchain():
    """Convert the agent-neutral functions into LangChain tools that
    CugaAgent expects, while keeping the underlying implementation shared."""
    from langchain_core.tools import tool

    wrapped = []
    for name, fn in recipe_tools.TOOLS.items():
        wrapped.append(tool(fn, name_or_callable=name))
    return wrapped


def _make_agent(provider: str | None, model: str | None):
    from cuga.sdk import CugaAgent
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    if model:
        os.environ["LLM_MODEL"] = model
    return CugaAgent(
        tools=_wrap_with_langchain(),
        special_instructions=_PROMPT,
        cuga_folder=str(_DIR / ".cuga-state"),
    )


def _verify(scenario: dict, thread_id: str, tool_calls: list[str]) -> dict:
    exp = scenario["expected"]
    sess = recipe_tools._get_session(thread_id)
    failures: list[str] = []

    for ing in exp.get("pantry_includes", []):
        if ing.lower() not in [p.lower() for p in sess["pantry"]]:
            failures.append(f"pantry missing '{ing}'")
    if "diet" in exp and sess["diet"] != exp["diet"]:
        failures.append(f"diet expected '{exp['diet']}', got '{sess['diet']}'")
    if "allergies" in exp:
        if sorted(sess["allergies"]) != sorted(exp["allergies"]):
            failures.append(f"allergies expected {exp['allergies']}, got {sess['allergies']}")
    if "recipes_saved_min" in exp and len(sess["recipes"]) < exp["recipes_saved_min"]:
        failures.append(f"need ≥{exp['recipes_saved_min']} recipes, got {len(sess['recipes'])}")
    if "recipes_saved_max" in exp and len(sess["recipes"]) > exp["recipes_saved_max"]:
        failures.append(f"need ≤{exp['recipes_saved_max']} recipes, got {len(sess['recipes'])}")
    for blocked in exp.get("no_recipe_uses_any", []):
        for r in sess["recipes"]:
            if blocked.lower() in [u.lower() for u in r.get("uses", [])]:
                failures.append(f"recipe '{r.get('title')}' uses banned '{blocked}'")
    for required in exp.get("must_have_called_tool", []):
        if required not in tool_calls:
            failures.append(f"never called tool '{required}'")

    return {"ok": not failures, "failures": failures}


async def _run_one(agent, scenario: dict) -> dict:
    thread_id = scenario["thread_id"]
    recipe_tools.reset_session(thread_id)
    started = time.monotonic()
    seen_calls: list[str] = []

    # Best-effort tool-call tracing — CugaAgent exposes intermediate steps
    # via its callback hooks. If unavailable, we fall back to inferring
    # tool calls from final session state.
    try:
        from langchain_core.callbacks import BaseCallbackHandler

        class _Trace(BaseCallbackHandler):
            def on_tool_start(self, serialized, input_str, **kw):
                seen_calls.append(serialized.get("name", "?"))

        callbacks = [_Trace()]
    except Exception:
        callbacks = None

    final = ""
    for turn in scenario["turns"]:
        augmented = f"[thread:{thread_id}] {turn}"
        result = await agent.invoke(
            augmented, thread_id=thread_id,
            callbacks=callbacks,
        )
        final = str(result)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    verdict = _verify(scenario, thread_id, seen_calls)
    return {
        "agent":      "cuga",
        "scenario":   scenario["name"],
        "elapsed_ms": elapsed_ms,
        "tool_calls": seen_calls,
        "verdict":    verdict,
        "final_text": final[:400],
    }


def _run_one_http(scenario: dict) -> dict:
    """Mode B: drive a NemoClaw-sandboxed CUGA over its OpenAI-compatible
    chat endpoint. Same loop shape as run_hermes.py — kept here so
    `run_cuga.py` is the single CUGA entrypoint regardless of mode."""
    import requests
    base_url = _SBX_INFO["forwarded_url"].rstrip("/")
    api_key  = _SBX_INFO.get("bearer_token", "")
    model    = os.environ.get("CUGA_MODEL", "cuga-default")

    thread_id = scenario["thread_id"]
    recipe_tools.reset_session(thread_id)
    started = time.monotonic()
    seen_calls: list[str] = []
    messages: list[dict] = [{"role": "system", "content": _PROMPT}]
    final_text = ""

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for turn in scenario["turns"]:
        messages.append({"role": "user",
                         "content": f"[thread:{thread_id}] {turn}"})
        for _ in range(12):
            resp = requests.post(
                f"{base_url}/v1/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages,
                      "tools": recipe_tools.OPENAI_TOOL_SCHEMAS,
                      "tool_choice": "auto", "temperature": 0.2},
                timeout=120,
            )
            resp.raise_for_status()
            choice = resp.json()["choices"][0]["message"]
            messages.append(choice)
            tool_calls = choice.get("tool_calls") or []
            if not tool_calls:
                final_text = choice.get("content") or ""
                break
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = json.loads(tc["function"].get("arguments") or "{}")
                seen_calls.append(fn_name)
                fn = recipe_tools.TOOLS.get(fn_name)
                result = (fn(**fn_args) if fn else
                          json.dumps({"ok": False, "code": "unknown_tool",
                                      "error": f"no tool '{fn_name}'"}))
                messages.append({"role": "tool",
                                 "tool_call_id": tc["id"],
                                 "content": result})

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "agent":      "cuga",
        "mode":       "nemoclaw-sandbox",
        "sandbox":    _SANDBOX,
        "scenario":   scenario["name"],
        "elapsed_ms": elapsed_ms,
        "tool_calls": seen_calls,
        "verdict":    _verify(scenario, thread_id, seen_calls),
        "final_text": final_text[:400],
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default=None)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    targets = _SCENARIOS if not args.scenario else [
        s for s in _SCENARIOS if s["name"] == args.scenario
    ]
    if not targets:
        print(f"scenario '{args.scenario}' not found", file=sys.stderr)
        return 2

    if _HTTP_MODE:
        print(f"[run_cuga] mode: nemoclaw-sandbox (sandbox={_SANDBOX}, "
              f"url={_SBX_INFO.get('forwarded_url')})", file=sys.stderr)
        exit_code = 0
        for scenario in targets:
            result = _run_one_http(scenario)
            print(json.dumps(result))
            if not result["verdict"]["ok"]:
                exit_code = 1
        return exit_code

    print("[run_cuga] mode: in-process", file=sys.stderr)
    agent = _make_agent(args.provider, args.model)
    exit_code = 0
    for scenario in targets:
        result = await _run_one(agent, scenario)
        # Tag the mode so head-to-head diffs stay honest.
        result["mode"] = "in-process"
        print(json.dumps(result))
        if not result["verdict"]["ok"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
