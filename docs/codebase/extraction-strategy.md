# Extraction strategy

Documents are split at 8 pages or 60,000 rendered characters. Oversized individual pages are
split by evidence lines, with Markdown slicing as a lossless fallback when no catalog lines
exist. Terra gets separate developer and user prompts from packaged Markdown files.

Each response is checked against the requested schema and the local evidence catalog. Invalid
responses receive one retry with validation feedback. Multiple chunk results are merged in
groups of 10 until one result remains. A failed chunk or merge becomes a partial issue instead
of hiding successful work.
