# Processing flow

This page traces one uploaded file from validation to downloadable output.

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit UI
    participant P as Pipeline
    participant L as LiteParse/Repair
    participant O as OCR bridge
    participant T as GPT-5.6 Terra
    participant E as Extraction

    User->>UI: Upload file and options
    UI->>P: process_document(name, bytes, options)
    P->>P: Validate file and pages
    P->>L: Parse temporary source
    L->>L: Preflight and render at 300 DPI
    L->>O: POST page image with active run ID
    O->>T: Structured OCR request
    T-->>O: Lines and hard regions
    O-->>L: LiteParse OCR response
    opt Hard regions
        L->>L: Rerender bounded crop at 400 DPI
        L->>O: OCR repair image
        O->>T: Structured OCR request
        T-->>O: Repair lines
        L->>L: Transactionally replace region
    end
    L-->>P: Markdown, lines, repairs, issues
    opt Structured extraction enabled
        P->>P: Validate extraction schema
        P->>E: Extract parsed document
        E->>T: Bounded schema request
        T-->>E: Data, evidence, issues
        E->>E: Validate schema, quotes, and line IDs
        opt More than one chunk
            E->>T: Hierarchically merge groups
        end
        E-->>P: Validated extraction result
    end
    P-->>UI: Document artifact
    UI->>UI: Save derived output to SQLite
    UI-->>User: Preview and download
```

## Stage behavior

1. **Validation:** Check extension, content signature, size, and page expression before model
   work begins. Validate a schema only when extraction is enabled.
2. **Preflight:** Read the document's page count without OCR. Reject an invalid selection or an
   unselected document over 100 pages.
3. **Base parse:** LiteParse renders and calls the private OCR route at 300 DPI.
4. **Repair:** Merge Terra hard regions with LiteParse grid-fallback blocks, enforce budgets,
   and rerender accepted crops at 400 DPI.
5. **Final parse:** If any repair succeeded, parse again against the amended OCR cache.
6. **Catalog:** Convert page text items into stable line IDs and 72-DPI top-left coordinates.
7. **Extraction:** When enabled, process bounded chunks and validate every non-null value against
   cited text. Otherwise mark the stage `skipped`.
8. **Export:** Combine stage outcomes, provenance, evidence, repairs, and issues into JSON v2.2.
9. **History:** Store the derived artifact and options in bounded SQLite history without source
   bytes.

## Failure preservation

- Invalid input returns a failed artifact before creating temporary work.
- Empty or invalid repair OCR leaves the original 300-DPI region unchanged.
- A final repaired parse failure falls back to the original base Markdown.
- A failed extraction chunk or merge records an issue and preserves successful chunks.
- A total extraction failure still leaves source and Markdown available when parsing succeeded.
- A SQLite failure leaves the current session result available and shows a safe warning.
