# Tutorial: Process your first scanned document

This tutorial takes a new user from a clean checkout to Markdown and structured JSON from one
scanned invoice.

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

## 3. Configure the extraction

In the left sidebar:

1. Leave **Extraction schema** set to **None**.
2. Upload one scanned invoice.
3. Enter this instruction:

   ```text
   Extract the invoice number, supplier, invoice date, currency, and total.
   ```

4. Leave the advanced defaults unchanged.
5. Select **Process files**.

The app renders at 300 DPI, retries hard regions at 400 DPI, reconstructs Markdown, and asks
Terra for evidence-grounded fields.

## 4. Inspect the result

Use the four result tabs:

- **Source** confirms that the correct document was processed.
- **Markdown** shows the reconstructed document and its raw Markdown source.
- **JSON** shows extracted fields, evidence, repairs, and issues.
- **Run details** summarizes pages, status, model, and repair count.

A successful synthetic result resembles:

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

Each non-null value has an evidence entry containing an exact quote and source line IDs.

## 5. Download the outputs

Download the Markdown and JSON individually, or select **Download all results (.zip)**. The
ZIP contains one `.md` and one `.json` file per usable upload.

## Checkpoint

You have succeeded when:

- the run status is `complete` or `partial`;
- Markdown is nonempty;
- the requested values appear under `data`; and
- every non-null value has evidence.

Next, learn how to [process batches](../how-to/process-documents.md) or
[define a custom schema](../how-to/use-a-custom-schema.md).
