# 300/400-DPI repair strategy

Scanned documents rarely fail uniformly. Rendering every page at 400 DPI would increase image
size and model cost even when most content is easy. The pipeline therefore starts at 300 DPI
and escalates bounded hard regions to 400 DPI.

## Candidate sources

Two signals create repair candidates:

- Terra returns `hard_regions` with pixel bounding boxes and a short reason.
- LiteParse emits a `grid_fallback` block for a table-like region it could not reconstruct
  normally.

Candidates are clamped to the page, merged when overlapping, padded for context, and limited
to 8 per page and 64 per document. Skipped candidates become explicit repair-budget issues.

## Transactional replacement

The 400-DPI crop has its own pixel coordinate system. Repair lines and optional polygons are
mapped back into the full 300-DPI page. A line is accepted only when its center lies inside the
target region.

The replacement is atomic:

1. Map and validate all repair lines without changing the base record.
2. If no valid line remains, return failure and preserve every base line.
3. Otherwise remove base lines centered inside the region.
4. Insert the mapped repair lines in reading order.
5. Record their fingerprints so exported evidence can report `repair_400` provenance.

A valid nonempty 400-DPI repair replaces the region even if its confidence is lower than the
300-DPI line. Resolution and targeted context make the repair pass authoritative; confidence
remains available for downstream review.

## Recovery

Individual repair exceptions are contained and logged. The user receives a bounded
`repair_failed` issue stating that 300-DPI content was retained. If the final parse against the
repaired cache fails, the pipeline clears repair receipts, records `final_parse_failed`, and
returns base Markdown.

This policy favors usable, provenance-rich output over all-or-nothing processing.
