# Data contracts

The application separates OCR records, parsed documents, extraction results, and downloadable
artifacts. This keeps provenance and partial success visible across stage boundaries.

## Coordinate contract

All exported boxes use:

```text
[x1, y1, x2, y2]
```

Coordinates are points in a top-left 72-DPI page viewport. OCR provider pixel coordinates are
converted before entering the exported evidence catalog. A `coordinate_space` field accompanies
exported evidence, repairs, and located issues.

## Internal records

| Record | Contract |
|---|---|
| `OcrLine` | Nonempty text, ordered positive box, confidence from 0 to 1, optional polygon. |
| `HardRegion` | Ordered positive box and bounded nonempty reason. |
| `ParsedDocument` | Markdown, pages, line catalog, repairs, issues, page metadata, prompt hashes. |
| `ExtractionResult` | Status, optional data, trusted evidence, issues, prompt hashes. |
| `DocumentArtifact` | Original upload identity plus terminal status, Markdown, JSON, and error. |

## JSON pointers and line IDs

Evidence paths use RFC 6901-style JSON Pointer escaping below `/data`. Object keys escape `~`
as `~0` and `/` as `~1`. Line IDs use `p{page}-l{sequence}`, for example `p3-l0012`.

Evidence may cite multiple lines when a quote spans adjacent catalog entries. The quoted text
must occur after whitespace normalization and case folding.

## Terminal status

| Status | Meaning |
|---|---|
| `complete` | Markdown is usable, optional extraction completed or was skipped, and no issue exists. |
| `partial` | Usable output exists, but at least one stage degraded. |
| `failed` | Parsing produced no usable Markdown. |

The `stages` object explains whether degradation originated in parsing, repair, or extraction.
Consumers should inspect both overall status and issues instead of treating any JSON file as a
guarantee of complete extraction.

Version 2.2 retains `stages.extraction: "skipped"` for parsing-only runs and adds the selected
accuracy policy plus repair verification metadata. These records keep
`data: null` and `evidence: []` rather than introducing a second output shape.

See the [output JSON reference](../reference/output-json.md) for field-level details.
