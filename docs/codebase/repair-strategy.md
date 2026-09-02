# Repair strategy

Base OCR always uses 300 DPI. Terra may identify hard regions and LiteParse may report grid
fallback blocks. Overlapping regions are merged, padded, and limited to 8 per page and 64 per
document.

Each candidate is rerendered at 400 DPI. Its OCR coordinates are mapped back into the base
page. Replacement is transactional: no base lines are removed unless the repair contains at
least one valid mapped line. Valid 400-DPI lines replace the region regardless of confidence,
as the higher-resolution pass is authoritative. Failures are recorded and base text survives.
