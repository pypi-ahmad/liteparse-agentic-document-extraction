---
type: Technology Profile
title: LiteParse
description: Local Apache-2.0 parser with spatial output, OCR options, and complexity routing.
status: draft
generated: { by: okf-skill/0.2, at: 2026-09-02T13:15:46+05:30 }
sources:
  - { id: liteparse-product, resource: https://www.llamaindex.ai/liteparse, title: LiteParse product page }
  - { id: liteparse-repo, resource: https://github.com/run-llama/liteparse, title: LiteParse repository }
  - { id: liteparse-complexity, resource: https://developers.llamaindex.ai/liteparse/guides/complexity/, title: LiteParse document complexity }
---

# Profile

LiteParse is an Apache-2.0 local parser with a Rust/PDFium core, optional OCR, and CLI, Python, Node/TypeScript, Rust, and WASM interfaces. Its repository documents text, JSON, Markdown, screenshots, bounding boxes, layout blocks, images, annotations, and form-field extraction.[^liteparse-repo]

Use it for local or simple documents. Its per-page complexity result exposes OCR and layout reasons to support explicit escalation.[^liteparse-complexity]

# Constraints

Markdown reconstruction is heuristic and rule-based. The project calls out dense tables, multi-column layouts, scans, charts, and handwriting as difficult cases.[^liteparse-repo] Office conversion may depend on LibreOffice, and HTTP OCR is not automatically local.

[^liteparse-product]: LiteParse product page
[^liteparse-repo]: LiteParse repository
[^liteparse-complexity]: LiteParse document complexity
