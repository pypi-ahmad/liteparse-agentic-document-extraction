---
type: Technology Profile
title: LlamaParse
description: Hosted LlamaIndex parsing with versioned tiers and current LlamaCloud SDKs.
status: draft
generated: { by: okf-skill/0.2, at: 2026-09-02T13:15:46+05:30 }
sources:
  - { id: llamaparse-tiers, resource: https://developers.llamaindex.ai/llamaparse/parse/guides/tiers/, title: LlamaParse Parse v2 tiers }
  - { id: llamaparse-limits, resource: https://developers.llamaindex.ai/llamaparse/general/limitations/, title: LlamaParse limits }
  - { id: legacy-reader, resource: https://github.com/run-llama/llama_index/blob/main/llama-index-integrations/readers/llama-index-readers-llama-parse/README.md, title: Deprecated LlamaParse reader }
---

# Profile

LlamaParse Parse v2 requires a tier and version on every request. Use a published dated version in production; latest is intended for development.[^llamaparse-tiers]

Its tiers are Fast, Cost Effective, Agentic, and Agentic Plus. Fast returns text and spatial text only: Markdown, structured items, and agentic options require a higher tier.[^llamaparse-tiers]

# Constraints

The current documentation lists a 512 MB platform upload limit, 130+ supported formats as a vendor-documented capability, a 35-image-per-page processing cap, and 64 KB extracted-text cap per page.[^llamaparse-limits] Pricing and quotas are volatile.

The supplied llama-parse reader package is explicitly deprecated and unmaintained; use the current LlamaCloud SDK/API rather than copying that integration.[^legacy-reader]

[^llamaparse-tiers]: LlamaParse Parse v2 tiers
[^llamaparse-limits]: LlamaParse limits
[^legacy-reader]: Deprecated LlamaParse reader
