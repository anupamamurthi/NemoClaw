<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# CUGA Integration — Documentation Index

This folder documents the integration that adds [**CUGA**](https://github.com/cuga-project/cuga-agent) as a third supported agent in NemoClaw, alongside the existing OpenClaw (default) and Hermes agents.

| Doc | What it covers |
|-----|----------------|
| [01-overview.md](./01-overview.md) | What CUGA is, why it fits NemoClaw, what each side gains |
| [02-existing-architecture.md](./02-existing-architecture.md) | How NemoClaw works today: blueprint, agent plugin contract, lifecycle CLI, OpenClaw + Hermes |
| [03-new-architecture.md](./03-new-architecture.md) | What changes when CUGA is added — new files, registry behavior, branding, policy |
| [04-try-it-locally.md](./04-try-it-locally.md) | Step-by-step dev setup, build, and how to exercise the CUGA path with tests |
| [examples/recipe-composer/](../../examples/recipe-composer/README.md) | Runnable example — the same small CUGA app driven through both the CUGA agent and the Hermes agent, with deterministic tests and a head-to-head comparison |

The full upstream NemoClaw docs (architecture, security, network policy, CLI commands) remain at <https://docs.nvidia.com/nemoclaw/latest/>.
