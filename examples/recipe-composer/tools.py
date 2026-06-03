# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Agent-neutral tool definitions for the Recipe Composer example.

These 9 tools form the workflow. They have no dependency on any agent
framework — they are plain Python functions returning JSON strings. The
companion runner files (run_cuga.py, run_hermes.py) adapt them for each
agent runtime, and OPENAI_TOOL_SCHEMAS at the bottom gives the
OpenAI-style function schema for use with Hermes (or any OpenAI-compatible
tool-calling API).

State (pantry, diet, allergies, last recipes) is per-thread and lives in
the module-level _sessions dict — same shape as the original CUGA app.
"""
from __future__ import annotations

import json
from typing import Any

# ── Static lookup tables (the inline "knowledge base") ──────────────────
_MACROS_PER_100G: dict[str, dict[str, float]] = {
    "chicken breast":   {"calories": 165, "protein": 31,  "carbs": 0,   "fat": 3.6},
    "ground beef":      {"calories": 250, "protein": 26,  "carbs": 0,   "fat": 17},
    "salmon":           {"calories": 208, "protein": 20,  "carbs": 0,   "fat": 13},
    "tofu":             {"calories":  76, "protein": 8,   "carbs": 1.9, "fat": 4.8},
    "egg":              {"calories": 155, "protein": 13,  "carbs": 1.1, "fat": 11},
    "rice":             {"calories": 130, "protein": 2.7, "carbs": 28,  "fat": 0.3},
    "pasta":            {"calories": 158, "protein": 5.8, "carbs": 31,  "fat": 0.9},
    "bread":            {"calories": 265, "protein": 9.0, "carbs": 49,  "fat": 3.2},
    "potato":           {"calories":  77, "protein": 2.0, "carbs": 17,  "fat": 0.1},
    "broccoli":         {"calories":  34, "protein": 2.8, "carbs": 7,   "fat": 0.4},
    "spinach":          {"calories":  23, "protein": 2.9, "carbs": 3.6, "fat": 0.4},
    "tomato":           {"calories":  18, "protein": 0.9, "carbs": 3.9, "fat": 0.2},
    "onion":            {"calories":  40, "protein": 1.1, "carbs": 9.3, "fat": 0.1},
    "garlic":           {"calories": 149, "protein": 6.4, "carbs": 33,  "fat": 0.5},
    "olive oil":        {"calories": 884, "protein": 0,   "carbs": 0,   "fat": 100},
    "butter":           {"calories": 717, "protein": 0.9, "carbs": 0.1, "fat": 81},
    "cheese":           {"calories": 402, "protein": 25,  "carbs": 1.3, "fat": 33},
    "milk":             {"calories":  42, "protein": 3.4, "carbs": 5.0, "fat": 1.0},
    "lentils":          {"calories": 116, "protein": 9,   "carbs": 20,  "fat": 0.4},
    "chickpeas":        {"calories": 164, "protein": 8.9, "carbs": 27,  "fat": 2.6},
    "quinoa":           {"calories": 120, "protein": 4.4, "carbs": 21,  "fat": 1.9},
    "almonds":          {"calories": 579, "protein": 21,  "carbs": 22,  "fat": 50},
    "peanut butter":    {"calories": 588, "protein": 25,  "carbs": 20,  "fat": 50},
    "avocado":          {"calories": 160, "protein": 2.0, "carbs": 9,   "fat": 15},
    "banana":           {"calories":  89, "protein": 1.1, "carbs": 23,  "fat": 0.3},
    "lemon":            {"calories":  29, "protein": 1.1, "carbs": 9,   "fat": 0.3},
}

_SUBSTITUTIONS: dict[str, list[tuple[str, str]]] = {
    "butter":      [("olive oil", "1:1 in savory cooking"),
                    ("avocado",   "1:1 in baking (mashed)")],
    "milk":        [("almonds",   "blend with water for almond milk")],
    "egg":         [("banana",    "1/2 banana per egg in baking"),
                    ("tofu",      "soft tofu for scrambles")],
    "rice":        [("quinoa",    "1:1 swap, more protein"),
                    ("lentils",   "earthier base, similar cook time")],
    "pasta":       [("quinoa",    "gluten-free base"),
                    ("rice",      "if you need a starch")],
    "bread":       [("rice",      "as a base for the same toppings")],
    "ground beef": [("lentils",   "1:1 in stews/sauces"),
                    ("tofu",      "crumbled, for tacos/bolognese")],
    "chicken breast": [("tofu",   "marinate and pan-fry"),
                       ("chickpeas", "for chicken-salad-style dishes")],
}

_DIET_BLOCKLIST: dict[str, set[str]] = {
    "vegetarian":   {"chicken breast", "ground beef", "salmon"},
    "vegan":        {"chicken breast", "ground beef", "salmon",
                     "egg", "milk", "cheese", "butter"},
    "pescatarian":  {"chicken breast", "ground beef"},
    "gluten-free":  {"pasta", "bread"},
    "dairy-free":   {"milk", "cheese", "butter"},
    "keto":         {"rice", "pasta", "bread", "potato", "banana"},
}


# ── Session store ────────────────────────────────────────────────────────
_sessions: dict[str, dict[str, Any]] = {}


def _get_session(thread_id: str) -> dict[str, Any]:
    if thread_id not in _sessions:
        _sessions[thread_id] = {
            "pantry":    [],
            "diet":      "",
            "allergies": [],
            "recipes":   [],
        }
    return _sessions[thread_id]


def reset_session(thread_id: str) -> None:
    """Test helper — clear state for a given thread."""
    _sessions.pop(thread_id, None)


def _append_unique(lst: list[str], value: str) -> None:
    if value and value.lower() not in [v.lower() for v in lst]:
        lst.append(value)


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data})


def _err(code: str, msg: str) -> str:
    return json.dumps({"ok": False, "code": code, "error": msg})


# ── The 9 tools ──────────────────────────────────────────────────────────
def add_to_pantry(thread_id: str, ingredient: str) -> str:
    if not ingredient:
        return _err("bad_input", "ingredient is empty")
    s = _get_session(thread_id)
    norm = ingredient.strip().lower()
    _append_unique(s["pantry"], norm)
    return _ok({"added": norm, "pantry_size": len(s["pantry"])})


def remove_from_pantry(thread_id: str, ingredient: str) -> str:
    s = _get_session(thread_id)
    target = (ingredient or "").strip().lower()
    before = len(s["pantry"])
    s["pantry"] = [i for i in s["pantry"] if i.lower() != target]
    return _ok({"removed": before != len(s["pantry"]), "pantry_size": len(s["pantry"])})


def list_pantry(thread_id: str) -> str:
    s = _get_session(thread_id)
    return _ok({
        "pantry":    s["pantry"],
        "count":     len(s["pantry"]),
        "diet":      s["diet"] or "no preference",
        "allergies": s["allergies"],
    })


def set_diet(thread_id: str, diet: str) -> str:
    s = _get_session(thread_id)
    d = (diet or "").strip().lower()
    if d in ("", "omnivore", "none"):
        s["diet"] = ""
        return _ok({"diet": "no preference"})
    if d not in _DIET_BLOCKLIST:
        return _err("bad_input",
                    f"unknown diet '{d}'. Valid: " +
                    ", ".join(_DIET_BLOCKLIST) + ", omnivore")
    s["diet"] = d
    return _ok({"diet": d})


def add_allergy(thread_id: str, ingredient: str) -> str:
    s = _get_session(thread_id)
    norm = (ingredient or "").strip().lower()
    if not norm:
        return _err("bad_input", "ingredient is empty")
    _append_unique(s["allergies"], norm)
    return _ok({"allergies": s["allergies"]})


def estimate_macros(ingredient: str, grams: int = 100) -> str:
    key = (ingredient or "").strip().lower()
    if key not in _MACROS_PER_100G:
        sample = ", ".join(sorted(_MACROS_PER_100G)[:6])
        return _err("not_found", f"no macro data for '{key}'. Try: {sample}…")
    per100 = _MACROS_PER_100G[key]
    scale = grams / 100.0
    return _ok({
        "ingredient": key, "grams": grams,
        "calories":   round(per100["calories"] * scale, 1),
        "protein_g":  round(per100["protein"]  * scale, 1),
        "carbs_g":    round(per100["carbs"]    * scale, 1),
        "fat_g":      round(per100["fat"]      * scale, 1),
    })


def suggest_substitution(ingredient: str) -> str:
    key = (ingredient or "").strip().lower()
    subs = _SUBSTITUTIONS.get(key, [])
    if not subs:
        return _ok({"ingredient": key, "substitutes": [],
                    "note": "No standard substitutions on file."})
    return _ok({"ingredient": key,
                "substitutes": [{"name": s, "why": w} for s, w in subs]})


def check_diet_compatibility(thread_id: str, ingredients_csv: str) -> str:
    s = _get_session(thread_id)
    items = [i.strip().lower() for i in (ingredients_csv or "").split(",") if i.strip()]
    if not items:
        return _err("bad_input", "ingredients_csv is empty")
    blocked_diet = []
    if s["diet"] in _DIET_BLOCKLIST:
        blocked_diet = [i for i in items if i in _DIET_BLOCKLIST[s["diet"]]]
    blocked_allergy = [i for i in items if i in s["allergies"]]
    return _ok({
        "diet":              s["diet"] or "no preference",
        "blocked_by_diet":   blocked_diet,
        "blocked_by_allergy": blocked_allergy,
        "compatible":        not (blocked_diet or blocked_allergy),
    })


def save_recipes(thread_id: str, recipes_json: str) -> str:
    s = _get_session(thread_id)
    try:
        recipes = json.loads(recipes_json)
    except json.JSONDecodeError as e:
        return _err("bad_input", f"invalid JSON: {e}")
    if not isinstance(recipes, list):
        return _err("bad_input", "recipes_json must be a JSON array")
    s["recipes"] = recipes
    return _ok({"saved": len(recipes)})


# ── Registry helpers used by the runners ────────────────────────────────
TOOLS: dict[str, Any] = {
    "add_to_pantry":            add_to_pantry,
    "remove_from_pantry":       remove_from_pantry,
    "list_pantry":              list_pantry,
    "set_diet":                 set_diet,
    "add_allergy":              add_allergy,
    "estimate_macros":          estimate_macros,
    "suggest_substitution":     suggest_substitution,
    "check_diet_compatibility": check_diet_compatibility,
    "save_recipes":             save_recipes,
}


def _str_param(desc: str) -> dict:
    return {"type": "string", "description": desc}


# OpenAI-style function schemas — used by run_hermes.py and any other
# OpenAI-compatible tool-calling client.
OPENAI_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "add_to_pantry",
        "description": "Add an ingredient to the user's pantry for this session.",
        "parameters": {"type": "object",
            "properties": {"thread_id":  _str_param("Current session/thread ID."),
                           "ingredient": _str_param("Ingredient name, lowercase singular.")},
            "required": ["thread_id", "ingredient"]}}},
    {"type": "function", "function": {
        "name": "remove_from_pantry",
        "description": "Remove an ingredient from the user's pantry.",
        "parameters": {"type": "object",
            "properties": {"thread_id":  _str_param("Current session/thread ID."),
                           "ingredient": _str_param("Ingredient to remove.")},
            "required": ["thread_id", "ingredient"]}}},
    {"type": "function", "function": {
        "name": "list_pantry",
        "description": "List the user's current pantry plus their diet and allergies.",
        "parameters": {"type": "object",
            "properties": {"thread_id": _str_param("Current session/thread ID.")},
            "required": ["thread_id"]}}},
    {"type": "function", "function": {
        "name": "set_diet",
        "description": "Save the user's dietary preference for this session.",
        "parameters": {"type": "object",
            "properties": {"thread_id": _str_param("Current session/thread ID."),
                           "diet": _str_param("vegetarian | vegan | pescatarian | "
                                              "gluten-free | dairy-free | keto | omnivore")},
            "required": ["thread_id", "diet"]}}},
    {"type": "function", "function": {
        "name": "add_allergy",
        "description": "Mark an ingredient the user cannot eat.",
        "parameters": {"type": "object",
            "properties": {"thread_id":  _str_param("Current session/thread ID."),
                           "ingredient": _str_param("Allergen ingredient name.")},
            "required": ["thread_id", "ingredient"]}}},
    {"type": "function", "function": {
        "name": "estimate_macros",
        "description": "Static lookup of rough macros (kcal, protein/carbs/fat) for one ingredient.",
        "parameters": {"type": "object",
            "properties": {"ingredient": _str_param("Ingredient name."),
                           "grams":      {"type": "integer",
                                          "description": "Portion size in grams (default 100)."}},
            "required": ["ingredient"]}}},
    {"type": "function", "function": {
        "name": "suggest_substitution",
        "description": "Suggest pantry-friendly substitutions for a missing ingredient.",
        "parameters": {"type": "object",
            "properties": {"ingredient": _str_param("Ingredient to substitute.")},
            "required": ["ingredient"]}}},
    {"type": "function", "function": {
        "name": "check_diet_compatibility",
        "description": "Check whether a CSV list of ingredients is allowed under the user's diet + allergies.",
        "parameters": {"type": "object",
            "properties": {"thread_id":       _str_param("Current session/thread ID."),
                           "ingredients_csv": _str_param("Comma-separated ingredient names.")},
            "required": ["thread_id", "ingredients_csv"]}}},
    {"type": "function", "function": {
        "name": "save_recipes",
        "description": "Persist the structured recipe suggestions for this thread.",
        "parameters": {"type": "object",
            "properties": {"thread_id":    _str_param("Current session/thread ID."),
                           "recipes_json": _str_param("JSON array of recipe objects "
                                                      "(title, time_minutes, difficulty, "
                                                      "uses, missing, calories_est, why, steps).")},
            "required": ["thread_id", "recipes_json"]}}},
]
