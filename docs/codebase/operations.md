# Operations

The application is intended for a trusted user's local Windows session, not unattended public
hosting.

## Start and stop

```powershell
uv sync --all-groups --locked
uv run liteparse-ade
```

The default endpoint is <http://127.0.0.1:9578>. Stop it with
<kbd>Ctrl</kbd>+<kbd>C</kbd>. See [run the app](../how-to/run-the-app.md) for port overrides and
launcher behavior.

## Data lifecycle

1. Upload bytes enter Streamlit memory.
2. A temporary source file exists only while `process_document` runs.
3. OCR records remain in a process-local registry for that parse run.
4. The registry is cleared in a `finally` block.
5. Completed artifacts remain in Streamlit session state.
6. **Clear session**, session loss, or process exit removes the application's references.

Files already downloaded through the browser persist at the chosen download location. Session
cleanup cannot delete those copies.

The configured OpenAI endpoint still receives page images and extraction content. Requests set
`store=False`, but operators must evaluate endpoint terms and data-handling requirements for
their documents.

## Capacity and cost controls

File, batch, page, rendered-pixel, repair, chunk, and merge limits bound local memory and model
work. These are application safeguards, not billing guarantees. Cost depends on document size,
hard-region frequency, extraction retries, and the configured endpoint.

## Logs and diagnostics

Provider and parsing exceptions are logged server-side. User-facing artifacts contain bounded
issue codes and messages. When diagnosing failures, record stage, issue code, page, package
version, and model name without copying credentials or sensitive document content.

## Recovery expectations

There is no persistent queue or database. Interrupted work must be resubmitted. Download useful
artifacts before stopping the process. A `partial` result is intentionally downloadable and may
be suitable for human review.

## Upgrade procedure

1. Ensure the working tree is clean.
2. Pull reviewed project changes.
3. Run `uv sync --all-groups --locked`.
4. Run the quality gate in [testing](testing.md).
5. Start the app and process a non-sensitive representative document.
