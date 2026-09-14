# Tutorial: process your first scanned document

This tutorial shows how to turn one scanned invoice into Markdown, then optionally extract
structured JSON, starting from a clean checkout.

**Time:** about 10 minutes, plus model processing time  
**Level:** beginner

## Before you begin

You need Windows 11, PowerShell, Git, `uv`, an OpenAI API key available as `OPENAI_API_KEY`,
and a scanned PDF or image. The selected endpoint must provide `gpt-5.6-terra`, image input,
the Responses API, and strict structured output. The file will be sent to that endpoint and
will consume API credits.

Verify that the current PowerShell process inherited the key without displaying it:

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw "OPENAI_API_KEY is unavailable; restart PowerShell after configuring it."
}
```

## 1. Install the application

```powershell
git clone https://github.com/pypi-ahmad/liteparse-agentic-document-extraction.git
cd liteparse-agentic-document-extraction
uv sync --all-groups --locked
```

## 2. Start the application

```powershell
uv run liteparse-ade
```

Open <http://127.0.0.1:9578>. Keep the PowerShell window open while using the app.

## 3. Parse the document

In the left sidebar:

1. Leave **Extract structured data** off.
2. Upload one scanned invoice.
3. Leave the advanced defaults unchanged.
4. Select **Process files**.

The app renders at 300 DPI, retries hard regions at 400 DPI, and reconstructs Markdown. The JSON
artifact records `extraction` as `skipped`, with `data: null` and an empty evidence list.

## 4. Inspect the Markdown

Use the result tabs:

- **Source** confirms that the correct document was processed.
- **Markdown** shows the reconstructed document and its raw Markdown source.
- **JSON** shows stage status, repairs, issues, and optional extracted data.
- **Run details** summarizes pages, status, model, and repair count.

## 5. Optionally extract structured data

To extract fields, enable **Extract structured data**, upload the invoice again, and enter:

```text
Extract the invoice number, supplier, invoice date, currency, and total.
```

Leave **Extraction schema** set to **None**, then select **Process files**. The app parses the
document first and asks Terra for evidence-grounded fields only after Markdown is available.

A successful synthetic result looks like this:

```json
{
  "document_type": "invoice",
  "fields": [
    {
      "name": "invoice_number",
      "value": "INV-7",
      "value_type": "identifier"
    },
    {
      "name": "total",
      "value": "USD 42.00",
      "value_type": "number"
    }
  ]
}
```

Each non-null document value has an evidence entry containing an exact quote and source line
IDs. In the built-in schema, this applies to `document_type` and each `fields/*/value`;
`fields/*/name` and `fields/*/value_type` are structural metadata and need no evidence.

## 6. Download or reopen the outputs

Download the Markdown and JSON individually, or select **Download all results (.zip)**. The
ZIP contains one `.md` and one `.json` file per usable upload. Derived results also appear under
**Saved history** for 30 days. Loading a saved result does not rerun OCR or extraction.

## Checkpoint

You are done when:

- the run status is `complete` or `partial`;
- Markdown is nonempty;
- parsing-only JSON reports extraction as `skipped`; and
- if extraction was enabled, requested document values appear under `data` with evidence;
  built-in field names and value-type labels need no separate evidence.

Next, learn how to [process batches](../how-to/process-documents.md) or
[define a custom schema](../how-to/use-a-custom-schema.md).
