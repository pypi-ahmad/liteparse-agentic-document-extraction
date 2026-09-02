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
| Extraction schema | None | Uses the generic document type and field-list schema. |
| Language hint | `auto` | Guides OCR language recognition. |
| Pages | All | Switch to Range and select inclusive start and end pages. |
| Repeated headers/footers | Off | Includes repeated elements when enabled. |
| Markdown images | `placeholder` | Also supports `off` and `embed`. |

The model, reasoning effort, and 300/400-DPI values are displayed but cannot be changed in the
UI.
