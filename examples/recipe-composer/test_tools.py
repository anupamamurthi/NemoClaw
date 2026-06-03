#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Pure-Python deterministic tests for the Recipe Composer tools.

These tests do NOT require CUGA, Hermes, or any LLM — they exercise the
tool implementations directly. They give us a fast smoke test that the
workflow's data layer is sound regardless of which agent runtime is wired
on top of it.

Run:
    python test_tools.py             # exits 0 if all pass
    python -m unittest test_tools    # also works

The companion vitest test (test/examples-recipe-composer.test.ts) shells
out to this file when python3 is available.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

import tools as T  # noqa: E402


def _parse(s: str) -> dict:
    return json.loads(s)


class RecipeComposerTools(unittest.TestCase):

    def setUp(self):
        self.tid = "t-test"
        T.reset_session(self.tid)

    # ── pantry ──────────────────────────────────────────────────────────
    def test_add_to_pantry_normalizes_and_dedupes(self):
        T.add_to_pantry(self.tid, "Chicken Breast")
        r = _parse(T.add_to_pantry(self.tid, "chicken breast"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["pantry_size"], 1)

    def test_add_to_pantry_rejects_empty(self):
        r = _parse(T.add_to_pantry(self.tid, ""))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "bad_input")

    def test_remove_from_pantry(self):
        T.add_to_pantry(self.tid, "rice")
        r = _parse(T.remove_from_pantry(self.tid, "RICE"))
        self.assertTrue(r["data"]["removed"])
        self.assertEqual(r["data"]["pantry_size"], 0)

    def test_list_pantry_shape(self):
        T.add_to_pantry(self.tid, "tofu")
        r = _parse(T.list_pantry(self.tid))
        self.assertEqual(r["data"]["count"], 1)
        self.assertIn("tofu", r["data"]["pantry"])
        self.assertEqual(r["data"]["diet"], "no preference")

    # ── diet / allergies ────────────────────────────────────────────────
    def test_set_diet_known_value(self):
        r = _parse(T.set_diet(self.tid, "vegetarian"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["diet"], "vegetarian")

    def test_set_diet_unknown_rejected(self):
        r = _parse(T.set_diet(self.tid, "carnivore"))
        self.assertFalse(r["ok"])

    def test_set_diet_omnivore_clears(self):
        T.set_diet(self.tid, "vegan")
        r = _parse(T.set_diet(self.tid, "omnivore"))
        self.assertEqual(r["data"]["diet"], "no preference")

    def test_add_allergy(self):
        T.add_allergy(self.tid, "almonds")
        T.add_allergy(self.tid, "ALMONDS")
        r = _parse(T.list_pantry(self.tid))
        self.assertEqual(r["data"]["allergies"], ["almonds"])

    # ── macros / substitutions ──────────────────────────────────────────
    def test_estimate_macros_chicken_200g(self):
        r = _parse(T.estimate_macros("chicken breast", 200))
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["protein_g"], 62.0)
        self.assertEqual(r["data"]["calories"], 330.0)

    def test_estimate_macros_unknown(self):
        r = _parse(T.estimate_macros("dragonfruit"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "not_found")

    def test_suggest_substitution_known(self):
        r = _parse(T.suggest_substitution("butter"))
        names = [s["name"] for s in r["data"]["substitutes"]]
        self.assertIn("olive oil", names)

    def test_suggest_substitution_unknown_returns_ok_empty(self):
        r = _parse(T.suggest_substitution("zucchini"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["substitutes"], [])

    # ── diet compatibility ─────────────────────────────────────────────
    def test_check_diet_blocks_chicken_for_vegetarian(self):
        T.set_diet(self.tid, "vegetarian")
        r = _parse(T.check_diet_compatibility(self.tid,
                                              "chicken breast, broccoli, rice"))
        self.assertFalse(r["data"]["compatible"])
        self.assertIn("chicken breast", r["data"]["blocked_by_diet"])

    def test_check_diet_blocks_allergens(self):
        T.add_allergy(self.tid, "almonds")
        r = _parse(T.check_diet_compatibility(self.tid, "almonds, oats"))
        self.assertIn("almonds", r["data"]["blocked_by_allergy"])

    def test_check_diet_compatible_path(self):
        T.set_diet(self.tid, "vegan")
        r = _parse(T.check_diet_compatibility(self.tid, "lentils, rice, tomato"))
        self.assertTrue(r["data"]["compatible"])

    # ── save_recipes ────────────────────────────────────────────────────
    def test_save_recipes_happy_path(self):
        payload = json.dumps([
            {"title": "Lentil bowl", "time_minutes": 25, "difficulty": "easy",
             "uses": ["lentils", "rice"], "missing": [], "calories_est": 600,
             "why": "Uses pantry only", "steps": ["cook lentils", "serve"]},
        ])
        r = _parse(T.save_recipes(self.tid, payload))
        self.assertEqual(r["data"]["saved"], 1)

    def test_save_recipes_rejects_non_array(self):
        r = _parse(T.save_recipes(self.tid, '{"title": "x"}'))
        self.assertFalse(r["ok"])

    def test_save_recipes_rejects_invalid_json(self):
        r = _parse(T.save_recipes(self.tid, "not json"))
        self.assertFalse(r["ok"])

    # ── registry / schemas ──────────────────────────────────────────────
    def test_tool_registry_has_nine_tools(self):
        self.assertEqual(len(T.TOOLS), 9)

    def test_openai_schemas_match_registry(self):
        schema_names = {s["function"]["name"] for s in T.OPENAI_TOOL_SCHEMAS}
        self.assertEqual(schema_names, set(T.TOOLS.keys()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
