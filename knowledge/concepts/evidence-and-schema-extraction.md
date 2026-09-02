---
type: Concept
title: Evidence and schema extraction
description: Grounded parse artifacts and trustworthy typed extraction results.
status: draft
generated: { by: okf-skill/0.2, at: 2026-09-02T13:15:46+05:30 }
sources:
  - { id: ade-overview, resource: https://docs.landing.ai/ade/ade-overview, title: ADE overview }
  - { id: ade-models, resource: https://docs.landing.ai/dpt3/parse-models, title: ADE Parse models }
  - { id: liteparse-repo, resource: https://github.com/run-llama/liteparse, title: LiteParse repository }
---

# Contract

Keep a parsed artifact separate from extracted business fields. Each extracted field should retain document identity, page, available location reference, model or parser version, and confidence when supplied. Missing evidence is a review signal, never a reason to fabricate a value.

ADE documents page-and-coordinate grounding and schema-based extraction after Parse.[^ade-overview] LiteParse exposes spatial JSON and bounding boxes, while its Markdown reconstruction is heuristic.[^liteparse-repo] DPT-3 Verity provides word confidence; DPT-3 Pro prioritizes broader document support.[^ade-models]

[^ade-overview]: ADE overview
[^liteparse-repo]: LiteParse repository
[^ade-models]: ADE Parse models
