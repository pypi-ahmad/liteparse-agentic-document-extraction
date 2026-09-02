# LiteParse agentic document extraction

Local Streamlit app that turns scanned PDFs and images into layout-aware Markdown and
evidence-grounded JSON. LiteParse owns document layout reconstruction. GPT-5.6 Terra owns
OCR, hard-region inspection, and schema extraction.

## Setup and cloning

```powershell
git clone https://github.com/pypi-ahmad/liteparse-agentic-document-extraction.git
cd liteparse-agentic-document-extraction
uv sync --all-groups
```

Repository: <https://github.com/pypi-ahmad/liteparse-agentic-document-extraction>

## Run

Requirements: Windows, uv, and `OPENAI_API_KEY` in process environment. The OpenAI SDK also
uses `OPENAI_BASE_URL` when configured.

```powershell
uv sync --all-groups
uv run python asgi_app.py
```

Open <http://127.0.0.1:8501>.

The app keeps uploads and outputs only in current Streamlit session and temporary directories.
Model requests use `store=False`. Files are still sent to configured OpenAI endpoint for OCR
and extraction.

## Fixed processing contract

- GPT-5.6 Terra, medium reasoning, original image detail
- 300 DPI base rendering
- Automatic 400 DPI rerender for hard regions
- Maximum 20 files, 50 MB each, 100 processed pages per document
- PDF, PNG, JPEG, TIFF, and WebP inputs

All model instructions live in Markdown under `prompts/`.

## Verify

```powershell
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Optional synthetic live check (uses OpenAI API credits):

```powershell
uv run python tests/live_smoke.py
```
