#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Run the Recipe Composer scenarios through the Hermes agent.

Hermes exposes an OpenAI-compatible chat-completions API. We feed it the
same system prompt and the same tool schemas (translated from the
agent-neutral tools module) and dispatch tool_calls back to our shared
implementations.

Usage:
    python run_hermes.py                        # all scenarios
    python run_hermes.py weeknight_vegetarian   # one scenario
    HERMES_BASE_URL=http://localhost:8642/v1 python run_hermes.py

Requires:
    - A running Hermes server (default base URL http://localhost:8642/v1)
    - HERMES_API_KEY env var (the bearer token configured on Hermes)
    - `requests` (standard pip install)

Same JSON-lines output shape as run_cuga.py — same verifier — so they can
be compared head-to-head.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

import tools as recipe_tools  # noqa: E402

_PROMPT = (_DIR / "prompt.md").read_text()
_SCENARIOS = json.loads((_DIR / "scenarios.json").read_text())["scenarios"]

def _nemoclaw_sandbox_info(sandbox: str) -> dict:
    """Ask the NemoClaw CLI for a running sandbox's forwarded URL and
    bearer token. Returns {} on any failure so we fall back to plain env."""
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

_BASE_URL = (
    _SBX_INFO.get("forwarded_url")
    or os.environ.get("HERMES_BASE_URL")
    or "http://localhost:8642/v1"
).rstrip("/")
_API_KEY  = (
    _SBX_INFO.get("bearer_token")
    or os.environ.get("HERMES_API_KEY", "")
)
_MODEL    = os.environ.get("HERMES_MODEL", "hermes-3-llama-3.1-8b")
_MAX_TURNS = 12  # tool-call dispatch loop cap per scenario turn


def _dispatch(name: str, args: dict) -> str:
    fn = recipe_tools.TOOLS.get(name)
    if fn is None:
        return json.dumps({"ok": False, "code": "unknown_tool",
                           "error": f"no tool named '{name}'"})
    try:
        return fn(**args)
    except TypeError as e:
        return json.dumps({"ok": False, "code": "bad_args", "error": str(e)})


def _chat(messages: list[dict]) -> dict:
    headers = {"Content-Type": "application/json"}
    if _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"
    resp = requests.post(
        f"{_BASE_URL}/chat/completions",
        headers=headers,
        json={
            "model":       _MODEL,
            "messages":    messages,
            "tools":       recipe_tools.OPENAI_TOOL_SCHEMAS,
            "tool_choice": "auto",
            "temperature": 0.2,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


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


def _run_one(scenario: dict) -> dict:
    thread_id = scenario["thread_id"]
    recipe_tools.reset_session(thread_id)
    started = time.monotonic()
    seen_calls: list[str] = []

    messages: list[dict] = [{"role": "system", "content": _PROMPT}]
    final_text = ""

    for turn in scenario["turns"]:
        messages.append({"role": "user",
                         "content": f"[thread:{thread_id}] {turn}"})
        for _ in range(_MAX_TURNS):
            response = _chat(messages)
            choice = response["choices"][0]["message"]
            messages.append(choice)
            tool_calls = choice.get("tool_calls") or []
            if not tool_calls:
                final_text = choice.get("content") or ""
                break
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = json.loads(tc["function"].get("arguments") or "{}")
                seen_calls.append(fn_name)
                result = _dispatch(fn_name, fn_args)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "content":      result,
                })

    elapsed_ms = int((time.monotonic() - started) * 1000)
    verdict = _verify(scenario, thread_id, seen_calls)
    return {
        "agent":      "hermes",
        "scenario":   scenario["name"],
        "elapsed_ms": elapsed_ms,
        "tool_calls": seen_calls,
        "verdict":    verdict,
        "final_text": final_text[:400],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default=None)
    args = ap.parse_args()

    targets = _SCENARIOS if not args.scenario else [
        s for s in _SCENARIOS if s["name"] == args.scenario
    ]
    if not targets:
        print(f"scenario '{args.scenario}' not found", file=sys.stderr)
        return 2

    exit_code = 0
    for scenario in targets:
        result = _run_one(scenario)
        print(json.dumps(result))
        if not result["verdict"]["ok"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
