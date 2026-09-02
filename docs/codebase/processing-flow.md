# Processing flow

1. Validate extension, signature, size, page selection, and optional schema.
2. Render and OCR selected pages at 300 DPI through LiteParse.
3. Combine Terra hard-region reports with LiteParse grid-fallback regions.
4. Rerender bounded regions at 400 DPI; apply only valid, nonempty mapped OCR lines.
5. Reparse with repaired OCR cache and produce layout-aware Markdown.
6. Build stable line IDs and 72-DPI top-left evidence boxes.
7. Extract bounded chunks with Terra and validate every non-null leaf against quoted lines.
8. Merge chunk results hierarchically and return complete, partial, or failed output.

A failed repair retains 300-DPI content. A failed extraction retains source and Markdown.
