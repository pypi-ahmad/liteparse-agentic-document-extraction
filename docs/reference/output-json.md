# Output JSON reference

Every processed artifact uses `schema_version` `2.0`.

## Top-level fields

| Field | Meaning |
|---|---|
| `schema_version` | Output contract version. |
| `status` | Overall `complete`, `partial`, or `failed` state. |
| `stages` | Separate parsing, repair, and extraction outcomes. |
| `document` | Source identity, pages, versions, model, DPI, and prompt hashes. |
| `data` | Generic or user-schema extraction result; may be `null`. |
| `evidence` | Grounding for non-null extracted leaves. |
| `repairs` | Successfully applied 400-DPI replacements. |
| `issues` | Bounded failures or ambiguities retained with the result. |

## Status invariants

- `complete`: usable Markdown, extraction is complete, and no issue exists.
- `partial`: usable Markdown or data remains, but extraction or another stage has issues.
- `failed`: no usable Markdown was produced.

Extraction model responses use a stricter internal invariant: `failed` requires `data: null` and
at least one issue; `partial` requires usable data and at least one issue.

## Evidence

Each evidence object has:

- `path`: JSON Pointer to one non-null leaf below `/data`;
- `line_ids`: stable IDs such as `p1-l0001`;
- `quote`: exact nonempty text found across the cited lines; and
- `sources`: expanded page, text, bounding box, OCR source, and confidence information.

Local validation rejects unknown paths or IDs, quotes absent from cited text, evidence pointing
to non-leaf or null values, and non-null values without valid evidence. In the generic schema,
field names and value-type labels are metadata and do not require their own evidence.

## Coordinates

Every `bbox` is `[x1, y1, x2, y2]` in `viewport_points_top_left_72dpi` coordinates. The origin
is the page's top-left corner. `x2` and `y2` are the lower-right position, not width and height.

## Repairs and issues

A repair records page, region ID, box, reason, replaced line count, and added line count. Only
valid nonempty mapped 400-DPI OCR can create a repair receipt.

An issue contains `code`, `message`, `stage`, and optional page, box, path, and coordinate-space
fields. Issue messages are bounded and avoid exposing provider exception details in the UI.

## Abridged example

```json
{
  "schema_version": "2.0",
  "status": "complete",
  "stages": {
    "parsing": "complete",
    "repair": "complete",
    "extraction": "complete"
  },
  "document": {
    "source_name": "synthetic-invoice.png",
    "processed_pages": [1],
    "model": "gpt-5.6-terra",
    "reasoning_effort": "medium",
    "base_dpi": 300,
    "repair_dpi": 400
  },
  "data": {
    "document_type": "invoice",
    "fields": [
      {
        "name": "invoice_number",
        "value": "INV-7",
        "value_type": "identifier"
      }
    ]
  },
  "evidence": [
    {
      "path": "/data/document_type",
      "line_ids": ["p1-l0001"],
      "quote": "Invoice",
      "sources": [
        {
          "id": "p1-l0001",
          "page": 1,
          "text": "Invoice INV-7",
          "bbox": [48.0, 72.0, 270.0, 112.0],
          "source": "ocr_300",
          "confidence": 0.99,
          "coordinate_space": "viewport_points_top_left_72dpi"
        }
      ]
    },
    {
      "path": "/data/fields/0/value",
      "line_ids": ["p1-l0001"],
      "quote": "INV-7",
      "sources": [
        {
          "id": "p1-l0001",
          "page": 1,
          "text": "Invoice INV-7",
          "bbox": [48.0, 72.0, 270.0, 112.0],
          "source": "ocr_300",
          "confidence": 0.99,
          "coordinate_space": "viewport_points_top_left_72dpi"
        }
      ]
    }
  ],
  "repairs": [],
  "issues": []
}
```

The example is abridged and omits generated identifiers, versions, and prompt hashes.
