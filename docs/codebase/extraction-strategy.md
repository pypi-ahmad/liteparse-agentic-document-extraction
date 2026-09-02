# Evidence-grounded extraction

Extraction converts parsed content into either the built-in field-list schema or a strict schema
supplied by the user. Model output is accepted only after local structural and evidence checks.

## Chunking

A request contains at most 8 pages or 60,000 rendered characters. Page groups remain intact
where possible. An oversized page is divided by catalog lines; if no lines exist, its Markdown
is sliced without discarding content.

Each chunk contains Markdown plus a catalog row for every available line:

```text
p1-l0001 | p1 | [72.0, 144.0, 240.0, 160.0] | Invoice INV-7
```

## Model contract

Terra must return:

- `status`: `complete`, `partial`, or `failed`;
- `data`: the requested object or `null`;
- `evidence`: JSON Pointer, line IDs, and exact quote for extracted values; and
- `issues`: typed missing, ambiguous, conflicting, illegible, or unsupported conditions.

Developer and user instructions are separate packaged Markdown prompts. Requests use
`gpt-5.6-terra`, medium reasoning, and `store=False`.

## Local validation

The validator checks the entire response envelope and user data schema. For each evidence item
it resolves the JSON Pointer, verifies every line ID, normalizes whitespace, and confirms that
the quote occurs in the cited text. Every non-null data leaf needs valid evidence, except generic
field-name and value-type metadata.

Status must agree with data and issues. Invalid output is retried once with concise validation
feedback. After the retry, only trusted evidence survives; status becomes `partial` when usable
data remains and `failed` otherwise.

## Hierarchical merge

When extraction produces multiple chunk results, groups of at most 10 are merged. The merge
receives the partial JSON and only the evidence lines those partials cited. Groups are repeatedly
merged until one result remains.

A failed merge retains the first usable result in its group and adds an
`extraction_merge_failed` issue. Any issue prevents an overall `complete` status.
