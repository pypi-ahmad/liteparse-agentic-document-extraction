# Testing and validation

## Local quality gate

Run from the repository root:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build
```

Pytest includes package coverage and fails below 90%. CI runs the same checks on Windows for
pushes to `main` and pull requests.

## Test layers

| Layer | What it proves |
|---|---|
| Models and validation | Boxes, schemas, page ranges, uploads, statuses, and evidence invariants. |
| OCR bridge | Cache isolation, request contract, bounds, errors, and transactional repair. |
| Pipeline | Partial-success behavior, JSON provenance, safe names, and ZIP collisions. |
| Extraction | Chunk preservation, retries, evidence trust, and merge failure handling. |
| Streamlit | Initial render, empty-submit feedback, and session clearing. |
| Packaging | Console delegation, packaged UI, and Markdown prompts. |

## Optional credited smoke test

```powershell
uv run python tests/live_smoke.py
```

The script starts a temporary OCR route on port `9578`, generates a 300-DPI invoice image, and
runs the real pipeline against Terra. It consumes API credits. Success requires:

- a non-failed status;
- nonempty Markdown;
- non-null extracted data; and
- at least one grounded evidence item.

The current verified fixture reads `Invoice INV-7` and `Total USD 42.00`. Model-dependent text
may vary, but the acceptance invariants must remain stable.

## Documentation validation

Documentation changes should additionally verify relative links, parse JSON examples, check
referenced paths, and run `git diff --check`. Keep examples aligned with source constants and
tests; do not copy draft research claims into runtime documentation without verification.
