# Contributing

Contributions should preserve the application's fixed LiteParse-and-Terra processing contract
and keep changes small, typed, and testable.

## Set up the repository

```powershell
git clone https://github.com/pypi-ahmad/liteparse-agentic-document-extraction.git
cd liteparse-agentic-document-extraction
uv sync --all-groups --locked
```

Use the project-root `.venv` managed by `uv`. Do not commit credentials or create a project
`.env` file. The OpenAI SDK reads `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` from the
process environment.

## Make a change

1. Read [the architecture](docs/codebase/architecture.md) and the relevant module.
2. Add or update focused tests with the behavior change.
3. Keep all model prompts in
   `src/liteparse_agentic_document_extraction/prompt_templates/*.md`.
4. Preserve unrelated work and avoid speculative refactors.
5. Update user or technical documentation when behavior changes.

## Run the quality gate

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build
```

Pytest must retain at least 90% package coverage. The wheel must include the Streamlit UI and
all Markdown prompt templates.

To apply formatting before running the CI-equivalent gate:

```powershell
uv run ruff format .
```

## Live verification

The normal tests mock model calls. Run the credited smoke test only when a change affects the
model, OCR bridge, parsing pipeline, or evidence extraction:

```powershell
uv run python tests/live_smoke.py
```

Success requires nonempty Markdown, structured data, grounded evidence, and no failed status.

## Commit guidance

- Make each commit describe one coherent change.
- Use imperative summaries such as `docs: clarify custom schema usage`.
- Do not commit generated `dist/`, coverage data, caches, or secrets.
- Include the commands run and any remaining risk in the handoff or pull request.
