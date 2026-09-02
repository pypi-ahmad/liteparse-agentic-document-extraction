---
type: Research Report
title: Agentic document extraction landscape
description: Cited comparison of LiteParse, LlamaParse, and LandingAI ADE for coding agents.
status: draft
generated: { by: okf-skill/0.2, at: 2026-09-02T13:15:46+05:30 }
sources:
  - { id: registry, resource: ../references/source-registry.md, title: Complete source registry }
---

# Executive summary

LiteParse is the local Apache-2.0 baseline, with spatial parsing, OCR options, and per-page complexity signals. LlamaParse is the hosted, versioned-tier option. LandingAI ADE separates grounded Parse from schema-based Extract and exposes current model, job, and data-retention documentation.

Agentic is not a shared implementation standard. LiteParse can be used by an agent but does not claim an agentic model; LlamaParse uses agentic tiers; ADE markets agentic document extraction. Assess their concrete artifacts, limits, evidence, and operational fit instead.

# Key findings

1. LiteParse enables explicit local-first routing through OCR and layout complexity signals.
2. LlamaParse v2 requires tier plus version and recommends pinned dated versions for production.
3. ADE Parse v2 produces the artifact that ADE Extract consumes; v2 is not field-compatible with v1.
4. The requested legacy LlamaParse reader is deprecated and must not be copied as current integration guidance.
5. Pricing, quotas, model aliases, and retention statements are time-sensitive.

# Detailed analysis

Use LiteParse when local processing or simple born-digital documents dominate. Escalate complex layouts under a documented policy. Use LlamaParse where its hosted tiers and LlamaCloud interfaces fit; use ADE where normalized grounding and schema extraction are first-class requirements.

All automated flows should preserve source identity, parser/model version, page scope, parse artifact, extraction result, and evidence. Validate required fields and evidence before downstream action.

# Contrarian views and risks

- No collected source provides a controlled independent comparison across all three products.
- LiteParse warns that heuristic Markdown can degrade on complex layouts.
- LlamaParse Fast cannot output Markdown, and the older reader package is deprecated.
- ADE v2 behavior, limits, and ZDR semantics depend on request path, account, and deployment.
- The supplied Medium post is useful historical context only; it is not authority for current pricing or API behavior.

# Open questions

- Which option meets this project’s measured document corpus and review threshold?
- Which privacy, residency, retention, quota, and SLA terms apply to the intended account?
- What confidence or evidence threshold routes a result to human review?

# Sources

See [the complete source registry](../references/source-registry.md).

# Rerun inputs

workflow: firecrawl-deep-research plus firecrawl-knowledge-base  
topic: LiteParse, LlamaParse, LandingAI ADE, and agentic document extraction  
depth: thorough  
output: OKF reference bundle with snapshots  
note: Firecrawl search/scrape returned HTTP 402. MCP Fetch, GitHub API, and Crawl4AI are approved fallbacks.
