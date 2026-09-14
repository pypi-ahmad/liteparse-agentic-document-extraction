# 300/400-DPI repair strategy

Scanned documents rarely fail uniformly. Rendering every page at 400 DPI would increase image
size and model cost even when most content is easy. The pipeline therefore starts at 300 DPI
and escalates bounded hard regions to 400 DPI.

## Candidate sources

Four signals create repair candidates in accuracy mode:

- Terra returns `hard_regions` with pixel bounding boxes and a short reason.
- LiteParse emits a `grid_fallback` block for a table-like region it could not reconstruct
  normally.
- Terra assigns a line confidence below `0.90`.
- OCR text contains a conservative anomaly marker or damaged-character pattern.

Candidates are clamped to the page, merged when overlapping, padded for context, and limited
to 8 per page and 64 per document. Skipped candidates become explicit repair-budget issues.

## Transactional replacement

The 400-DPI crop has its own pixel coordinate system. Repair lines and optional polygons are
mapped back into the full 300-DPI page. A line is accepted only when its center lies inside the
target region.

Accuracy mode reads every 400-DPI crop twice independently. Matching text and overlapping boxes
form consensus. A third read is made only when the first two disagree, and every accepted line
must then have a two-of-three majority. If any line remains unresolved, the entire repair is
rejected and the original 300-DPI region is kept.

The accepted replacement is atomic:

1. Map and validate all repair lines without changing the base record.
2. If no valid line remains, return failure and preserve every base line.
3. Otherwise remove base lines centered inside the region.
4. Insert the mapped repair lines in reading order.
5. Record their fingerprints so exported evidence can report `repair_400` provenance.

Legacy mode retains the former single-read behavior for controlled A/B evaluation. Accuracy mode
is the application default.

Experimental peer evidence can provide a clearer repeated instance from another page to the
repair call. It is off by default and only considers repeated printed text that excludes digits
and checkbox-like markers; at least three page occurrences are required.

## Recovery

Individual repair exceptions are contained and logged. The user receives a bounded
`repair_failed` issue stating that 300-DPI content was retained. Consensus rejection instead
records `repair_disagreement`. If the final parse against the
repaired cache fails, the pipeline clears repair receipts, records `final_parse_failed`, and
returns base Markdown.

This policy favors usable, provenance-rich output over all-or-nothing processing.
