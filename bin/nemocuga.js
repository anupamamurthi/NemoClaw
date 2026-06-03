#!/usr/bin/env node
// @ts-nocheck
// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// NemoCuga — alias for NemoClaw with the CUGA agent pre-selected.
process.env.NEMOCLAW_AGENT = "cuga";
process.env.NEMOCLAW_INVOKED_AS = "nemocuga";
module.exports = require("../dist/nemoclaw");
