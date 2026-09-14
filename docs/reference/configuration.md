# Configuration reference

## Runtime environment

| Name | Required | Purpose |
|---|---:|---|
| `OPENAI_API_KEY` | Yes | Authenticates the OpenAI SDK. |
| `OPENAI_BASE_URL` | No | Selects the configured OpenAI-compatible endpoint. |
| `LITEPARSE_APP_PORT` | No | Overrides port `9578` for `uv run liteparse-ade`. |

The app binds to `127.0.0.1`; it is not configured as a remote multi-user service.

## Fixed model settings

| Setting | Value |
|---|---|
| Model | `gpt-5.6-terra` |
| Reasoning effort | `medium` |
| Image detail | Original |
| Request storage | Disabled with `store=False` |
| OpenAI timeout | 180 seconds |
| SDK retries | 2 |

## Processing limits

| Resource | Limit |
|---|---:|
| Files per batch | 20 |
| Bytes per file | 50 MB |
| Bytes per batch | 500 MB |
| Processed pages per document | 100 |
| Uploaded schema | 100 KB |
| Rendered page image | 40,000,000 pixels |
| Repairs per page | 8 |
| Repairs per document | 64 |
| Extraction chunk | 8 pages or 60,000 rendered characters |
| Merge group | 10 partial results |
| Saved-history retention | 30 days |
| Saved-history payload | 1 GiB |
| Saved-history selector | 100 newest records |

## Supported inputs

| Format | Extensions |
|---|---|
| PDF | `.pdf` |
| PNG | `.png` |
| JPEG | `.jpg`, `.jpeg` |
| TIFF | `.tif`, `.tiff` |
| WebP | `.webp` |

## UI options

| Option | Default | Effect |
|---|---|---|
| Extract structured data | Off | Enables instructions, schema selection, and field extraction. |
| Extraction schema | None | Uses the generic field-list schema when extraction is enabled. |
| Language hint | `auto` | Guides OCR language recognition. |
| Pages | All | Switch to Range and select inclusive start and end pages. |
| Repeated headers/footers | Off | Includes repeated elements when enabled. |
| Generate annotated PDF | Off | Draws color-coded line boxes on 300-DPI processed pages. |
| Markdown images | `placeholder` | Also supports `off` and `embed`. |
| Experimental peer evidence | Off | Adds a safer repeated printed region to difficult OCR calls. |

The model, reasoning effort, and 300/400-DPI values are displayed but cannot be changed in the
UI.

Accuracy mode is fixed as the default. It sends two independent 400-DPI reads for each difficult
region and sends a third only when the first pair disagrees. The evaluator can select legacy mode
for comparison; the normal UI does not expose the policy switch.

## Local history

SQLite history is stored at
`%LOCALAPPDATA%\LiteParseAgenticDocumentExtraction\history.sqlite3`. The location, 30-day
retention, and 1 GiB retained-output cap are fixed. The database stores derived Markdown and
JSON plus processing metadata. It does not store the original uploaded file or OCR images.
