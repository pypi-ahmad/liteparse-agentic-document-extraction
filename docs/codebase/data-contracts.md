# Data contracts

Output JSON uses `schema_version: "2.0"`. Bounding boxes are always
`[x1, y1, x2, y2]` in a top-left, 72-DPI page viewport.

Each evidence record contains a JSON Pointer path, one or more catalog line IDs, and an exact
nonempty quote. Local validation rejects unknown IDs, invalid pointers, absent quotes, missing
leaf coverage, and contradictory run status.

Statuses are terminal:

- `complete`: usable data, no issues.
- `partial`: usable data with one or more issues.
- `failed`: no usable extracted data and at least one issue.
