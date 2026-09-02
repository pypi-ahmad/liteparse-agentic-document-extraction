# Troubleshooting

## The command cannot find `uv`

Install [uv](https://docs.astral.sh/uv/) and open a new PowerShell window. Verify it with:

```powershell
uv --version
```

## `OPENAI_API_KEY` is unavailable

The SDK reads credentials from the process environment. If the key was configured after your
terminal or coding host started, restart that host so it inherits the variable. Do not copy the
key into source, prompts, logs, or a committed `.env` file.

Verify presence safely:

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw "OPENAI_API_KEY is unavailable; restart PowerShell after configuring it."
}
```

## The endpoint rejects authentication or the model

- **Authentication or authorization:** Check key validity and account access. Replace or
  authorize the key through the provider, then restart the process.
- **Connection or DNS:** Check `OPENAI_BASE_URL`. Correct or remove it in Windows user
  environment settings, then restart PowerShell.
- **Model not found:** Check the endpoint model catalog. The endpoint and account must provide
  `gpt-5.6-terra`.
- **Structured output or image input rejected:** Confirm that the endpoint supports the
  Responses API, strict structured output, and image input.

Do not print keys or include them in diagnostics.

## Port 9578 is already in use

Inspect the listener without stopping it:

```powershell
Get-NetTCPConnection -LocalPort 9578 -State Listen
```

Either stop the known owner or use a different port:

```powershell
$env:LITEPARSE_APP_PORT = "9580"
uv run liteparse-ade
```

`launch.cmd` is more aggressive: it forcibly stops any listener on `9578`.

## An upload is rejected immediately

Check that the extension and actual content match. Supported formats are PDF, PNG, JPEG, TIFF,
and WebP. Empty, invalid, or oversized files are rejected before model processing. PDFs must
start with a valid PDF signature.

## A page selection is rejected

Use positive, 1-based numbers such as `1-5,8`. Descending ranges, empty entries, non-numeric
values, more than 100 selected pages, and pages beyond the document are invalid.

## A custom schema is rejected

Confirm that the root and every nested object set `additionalProperties` to `false`, require
all declared properties, and use `null` for optional values. `$ref` is not supported. See the
[custom schema guide](use-a-custom-schema.md).

If the UI says the content is not valid UTF-8 JSON, check the uploaded file's encoding, commas,
quotes, and brackets. If it reports a schema rule, correct the named structural constraint. The
UI displays the local validation message before making model requests. A schema that passes
locally can still use keywords unsupported by the configured Structured Outputs endpoint.

## The result is `partial`

`partial` means Markdown or extracted data remains usable, but at least one stage recorded an
issue. Inspect `stages` and `issues` in the JSON. Typical causes include a failed 400-DPI repair,
a page error, an extraction chunk failure, or evidence that remained invalid after retry.

## Markdown exists but JSON data is missing

Parsing and extraction fail independently. The app deliberately preserves Markdown when Terra
extraction fails. Refine the instructions or schema, process fewer pages, and try again.

## The live smoke test fails

Ensure port `9578` is free and the OpenAI variables are available to the process, then run:

```powershell
uv run python tests/live_smoke.py
```

The test consumes API credits. It fails unless Markdown, data, and grounded evidence are all
present.

## Collect safe diagnostic information

Record the status, stage values, issue codes, page numbers, package version, and model name.
Never include source documents, extracted personal data, API keys, or environment values in a
public issue unless you have reviewed and redacted them.
