---
type: Evaluation Guide
title: Evaluation and claims
description: How to assess document-processing quality without treating vendor positioning as proof.
status: draft
generated: { by: okf-skill/0.2, at: 2026-09-02T13:15:46+05:30 }
sources:
  - { id: liteparse-repo, resource: https://github.com/run-llama/liteparse, title: LiteParse repository }
  - { id: llamaparse-product, resource: https://www.llamaindex.ai/llamaparse, title: LlamaParse product page }
  - { id: ade-overview, resource: https://docs.landing.ai/ade/ade-overview, title: ADE overview }
---

# Rule

First-party documentation is evidence of documented interfaces, limits, and workflows. Quality, speed, scale, and benchmark statements remain vendor claims unless accompanied by a reproducible dataset, metric, version, configuration, cost, and baseline.

No inspected source provides an independent controlled LiteParse-versus-LlamaParse-versus-ADE benchmark. Use an internal corpus covering native PDFs, scans, multi-column pages, tables, forms, handwriting, figures, and multilingual content. Measure reading order, transcription, table structure, field accuracy, evidence coverage, latency, failure rate, and cost.

[^liteparse-repo]: LiteParse repository
[^llamaparse-product]: LlamaParse product page
[^ade-overview]: ADE overview
