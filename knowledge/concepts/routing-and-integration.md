---
type: Decision Guide
title: Routing and integration
description: Local-first, evidence-preserving routing across LiteParse, LlamaParse, and ADE.
status: draft
generated: { by: okf-skill/0.2, at: 2026-09-02T13:15:46+05:30 }
sources:
  - { id: liteparse-complexity, resource: https://developers.llamaindex.ai/liteparse/guides/complexity/, title: LiteParse document complexity }
  - { id: llamaparse-tiers, resource: https://developers.llamaindex.ai/llamaparse/parse/guides/tiers/, title: LlamaParse tiers }
  - { id: ade-overview, resource: https://docs.landing.ai/ade/ade-overview, title: ADE overview }
---

# Recommended pattern

1. Parse local and simple documents with LiteParse, retaining per-page complexity evidence.
2. Escalate only documents or pages with scans, garbled text, tables, multi-column layout, or dense graphics when policy permits hosted processing.[^liteparse-complexity]
3. Select LlamaParse for versioned hosted parsing and ecosystem fit; select ADE when grounded parse artifacts and schema extraction are central.[^llamaparse-tiers][^ade-overview]
4. Preserve document hash, parser version, page scope, parsed artifact, extraction result, and evidence references through each handoff.
5. Send ambiguous or ungrounded results to review.

This is a routing hypothesis, not a benchmark-backed product ranking.

[^liteparse-complexity]: LiteParse document complexity
[^llamaparse-tiers]: LlamaParse tiers
[^ade-overview]: ADE overview
