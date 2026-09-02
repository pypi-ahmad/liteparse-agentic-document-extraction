---
type: Concept
title: Document processing fundamentals
description: OCR, parsing, extraction, and agent orchestration in document workflows.
status: draft
generated: { by: okf-skill/0.2, at: 2026-09-02T13:15:46+05:30 }
sources:
  - { id: liteparse-complexity, resource: https://developers.llamaindex.ai/liteparse/guides/complexity/, title: LiteParse document complexity }
  - { id: ade-overview, resource: https://docs.landing.ai/ade/ade-overview, title: ADE overview }
---

# Core distinctions

OCR transcribes pixels. Parsing reconstructs readable structure, layout, tables, and media. Extraction maps parsed content to a requested schema. Orchestration selects tools or tiers, scopes work, validates evidence, and escalates failures.

LiteParse explicitly separates OCR need from layout complexity, allowing a born-digital multi-column page to be routed to a heavier layout path without OCR.[^liteparse-complexity] ADE separates Parse from schema-based Extract.[^ade-overview]

[^liteparse-complexity]: LiteParse document complexity
[^ade-overview]: ADE overview
