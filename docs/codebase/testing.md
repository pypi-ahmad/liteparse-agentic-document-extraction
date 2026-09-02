# Testing

Run the complete local gate:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build
```

Tests cover validation, transactional repair, evidence invariants, chunk retry/merge behavior,
artifact export, the OCR route, packaged entrypoint, and a headless Streamlit interaction.
`tests/live_smoke.py` is optional because it consumes OpenAI credits; it requires Markdown,
data, and grounded evidence before succeeding.
