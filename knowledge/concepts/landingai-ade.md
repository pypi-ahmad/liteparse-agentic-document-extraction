---
type: Technology Profile
title: LandingAI ADE
description: Grounded Parse and schema-based Extract APIs for agentic document extraction.
status: draft
generated: { by: okf-skill/0.2, at: 2026-09-02T13:15:46+05:30 }
sources:
  - { id: ade-overview, resource: https://docs.landing.ai/ade/ade-overview, title: ADE overview }
  - { id: ade-models, resource: https://docs.landing.ai/dpt3/parse-models, title: ADE Parse models }
  - { id: ade-rate-limits, resource: https://docs.landing.ai/dpt3/rate-limits, title: ADE rate limits }
  - { id: ade-zdr, resource: https://docs.landing.ai/ade/zdr, title: ADE Zero Data Retention }
---

# Profile

ADE provides Parse, Extract, Classify, Section, and Split. Parse returns structured Markdown and hierarchical data; Extract maps parsed content to a schema.[^ade-overview]

Parse v2 uses DPT-3 Pro by default and offers DPT-3 Verity for born-digital text. They differ in document coverage, formatting, grounding granularity, and confidence behavior; retain the returned model version.[^ade-models]

# Constraints

Parse v2 is not field-compatible with v1. Its synchronous limit is 50 MiB; asynchronous jobs accept PDF files up to 1 GiB and images up to 50 MiB, with up to 6,000 PDF pages.[^ade-rate-limits] Zero Data Retention is an account and deployment setting with specific result-retrieval behavior, not a blanket default.[^ade-zdr]

[^ade-overview]: ADE overview
[^ade-models]: ADE Parse models
[^ade-rate-limits]: ADE rate limits
[^ade-zdr]: ADE Zero Data Retention
