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
6. Derived Markdown, JSON, and processing metadata are saved to local SQLite history.
7. **Clear session**, session loss, or process exit removes only the in-memory references.
8. Saved records expire after 30 days or are removed earlier to maintain the 1 GiB payload cap.

Files already downloaded through the browser persist at the chosen download location. Session
cleanup cannot delete those copies or SQLite history. Use **Delete** under **Saved history** to
remove a stored result.

The database is `%LOCALAPPDATA%\LiteParseAgenticDocumentExtraction\history.sqlite3`. It contains
derived document content in plaintext but never the original upload or OCR images. Restrict
access to the Windows account and use device encryption when the documents require it.

The configured OpenAI endpoint still receives page images and extraction content. Requests set
`store=False`, but operators must evaluate endpoint terms and data-handling requirements for
their documents.

## Capacity and cost controls

File, batch, page, rendered-pixel, repair, chunk, and merge limits bound local memory and model
work. SQLite history also keeps no more than 1 GiB of retained payload. These are application
safeguards, not billing guarantees. Cost depends on document size, hard-region frequency,
optional extraction retries, and the configured endpoint.

## Logs and diagnostics

Provider and parsing exceptions are logged server-side. User-facing artifacts contain bounded
issue codes and messages. When diagnosing failures, record stage, issue code, page, package
version, and model name without copying credentials or sensitive document content.

## Recovery expectations

There is no persistent processing queue. Interrupted work must be resubmitted. Completed results
can be reopened from SQLite history, but their original source preview is unavailable. A
`partial` result is intentionally downloadable and may be suitable for human review.

## Upgrade procedure

1. Ensure the working tree is clean.
2. Pull reviewed project changes.
3. Run `uv sync --all-groups --locked`.
4. Run the quality gate in [testing](testing.md).
5. Start the app and process a non-sensitive representative document.
