# Python internals reference

The package is an application, not a versioned Python SDK. Only the `liteparse-ade` console
entrypoint is a supported public interface. The module-level names below are documented for
contributors and tests and may change without a compatibility release.

## Modules

| Module | Responsibility |
|---|---|
| `server` | Compose the Streamlit script and private Starlette OCR route. |
| `ui` | Render upload, options, previews, and downloads. |
| `pipeline` | Validate uploads and coordinate parsing, optional extraction, and export. |
| `repair` | Run LiteParse and apply bounded 400-DPI hard-region repair. |
| `annotations` | Render optional 300-DPI PDFs with color-coded line boxes. |
| `ocr_bridge` | Validate private OCR requests, call Terra, and cache run-scoped OCR. |
| `extraction` | Validate schemas, chunk documents, call Terra, ground evidence, and merge. |
| `models` | Define application records and structured OCR response models. |
| `settings` | Hold fixed resource and model settings. |
| `prompts` | Load packaged Markdown templates and substitute placeholders once. |
| `storage` | Persist derived artifacts in bounded, expiring SQLite history. |

## Coordinator interfaces

| Callable | Inputs | Result or error behavior |
|---|---|---|
| `process_document` | Filename, bytes, options | Returns an artifact and preserves Markdown after extraction failure. |
| `validate_upload` | Filename and bytes | Returns normalized extension or raises `ValueError`. |
| `parse_target_pages` | Range string or `None` | Returns sorted page numbers or raises `ValueError`. |
| `artifact_json` | `DocumentArtifact` | Returns indented UTF-8 JSON text. |
| `result_zip` | Iterable of artifacts | Returns ZIP bytes with collision-safe filenames. |

## History interfaces

| Callable or class | Purpose |
|---|---|
| `HistoryStore` | Own the SQLite path, schema, retention, capacity, and record operations. |
| `HistoryStore.save` | Store derived output and options without source bytes. |
| `HistoryStore.list_recent` | Return bounded newest-first metadata for the UI. |
| `HistoryStore.load` | Restore an artifact with `source_bytes=b""`. |
| `HistoryStore.delete` | Delete one record by generated artifact ID. |
| `default_database_path` | Resolve the per-user `%LOCALAPPDATA%` database path. |

## Extraction interfaces

| Callable | Purpose |
|---|---|
| `validate_user_schema` | Enforce the supported strict JSON Schema subset. |
| `generic_data_schema` | Return the default document type and field-list schema. |
| `extraction_schema` | Wrap a data schema in the status/evidence/issues envelope. |
| `validate_extraction` | Return validation errors and trusted evidence. |
| `extract_document` | Run chunk extraction, retry, and hierarchical merge. |

## Parsing and OCR interfaces

| Callable or class | Purpose and failure behavior |
|---|---|
| `Region` | Describe one hard region in base-page screenshot pixels. |
| `merge_regions` | Merge nearby same-page regions and return reading-order candidates. |
| `padded_crop` | Convert a pixel box to LiteParse fractional crop values with padding. |
| `apply_repair` | Map repair lines and replace the base region atomically; returns removed/added counts. |
| `parse_document` | Run preflight, base parse, bounded repair, final parse, and catalog creation. |
| `OcrPageRecord` | Hold one cached page image digest, geometry, OCR, regions, and prompt hashes. |
| `RunCache` | Hold base and repair records for one active parse run. |
| `OcrRegistry` | Create, query, and delete thread-safe process-local run caches. |
| `get_openai_client` | Construct the environment-configured SDK client with timeout and retries. |
| `image_digest` | Validate image pixels and return SHA-256 digest, width, and height. |
| `call_terra_ocr` | Request structured OCR and bounded hard regions from Terra. |

`ocr_endpoint` is deliberately excluded from supported interfaces. It validates loopback,
content length, run ID, stage, and image body for LiteParse's private callback.

## Data models

| Model | Purpose |
|---|---|
| `RunStatus` | Overall `complete`, `partial`, or `failed` state. |
| `OcrStage` | Internal `base`, `repair`, or `final` OCR pass. |
| `OcrLine` | Validated text, box, confidence, and optional polygon. |
| `HardRegion` | Validated box and reason requesting targeted repair. |
| `OcrOutput` | Terra structured OCR response containing lines and regions. |
| `ProcessingOptions` | Extraction flag, instructions, schema, language, pages, repeated elements, and image mode. |
| `ProcessingIssue` | Stage failure with optional page, box, and data path. |
| `LineEvidence` | Stable line ID, page, text, box, OCR source, and confidence. |
| `RepairReceipt` | Applied region, reason, and replaced/added counts. |
| `ParsedPage` | Page Markdown and its line IDs. |
| `ParsedDocument` | Markdown, pages, lines, repairs, issues, provenance, and page metadata. |
| `ExtractionResult` | Status, optional data, trusted evidence, issues, and prompt hashes. |
| `DocumentArtifact` | Upload identity, terminal status, Markdown, JSON, and safe error. |

`ExtractionChunk` is a contributor-facing record for one bounded set of pages or oversized-page
segment.

## Private OCR route

`POST /api/ocr` is an in-process integration contract for LiteParse. It requires an active,
unguessable run ID and accepts only loopback requests. It is not a supported external API.
Run state is process-local and removed when document parsing finishes.

## Prompt contract

All model instructions live under `prompt_templates/` as Markdown. Developer and user prompts
are separate. The loader performs a single placeholder substitution pass, so replacement text
containing `{{...}}` is not recursively interpreted.

`load_prompt(name, **values)` returns rendered text and the SHA-256 hash of the original
template. `build_page_range(scope, start_page, end_page)` converts the UI selection to
LiteParse syntax, while `read_schema(mode, pasted, uploaded)` parses and size-checks the UI's
optional schema. They raise ordinary file, JSON, or `ValueError` exceptions for callers.
