# How to process documents

## Upload one or many files

1. Start the app and open <http://127.0.0.1:9578>.
2. Select files under **Scanned PDFs or images**.
3. Select **Process files**.

The app produces Markdown without running structured extraction. To extract fields as well,
enable **Extract structured data** before processing and enter a concrete request, such as:

   ```text
   Extract the customer name, invoice number, invoice date, line items, subtotal, tax, and total.
   ```

The app accepts PDF, PNG, JPEG, TIFF, and WebP. One batch may contain at most 20 files, each
file may be at most 50 MB, and the combined batch may be at most 500 MB.

## Process selected PDF pages

Change **Pages** from **All** to **Range**, then select inclusive
**Start page** and **End page** values. Page numbers start at 1. A range may contain at most 100
pages and cannot exceed the source document's page count. Keep **All** to process the whole
document; an unselected document over 100 pages is rejected.

The same page range applies independently to every file in the submitted batch. A file
whose page count is lower than the highest selected page fails while other uploads continue.
Images are one-page documents: leave the field empty or select page `1`; any higher page fails
preflight validation.

## Improve language recognition

Set **Language hint** to a language expected in the document. Keep `auto` for mixed or unknown
content. The hint guides Terra but does not change the fixed OCR model.

## Control Markdown output

- Enable **Keep repeated headers and footers** when those elements carry business meaning.
- Choose **placeholder**, **off**, or **embed** under **Markdown images**.

Embedded images can make Markdown and ZIP outputs substantially larger. `placeholder` is the
default.

## Generate an annotated PDF

Open **Advanced options** and enable **Generate annotated PDF** before processing. After parsing,
open **Annotated PDF** to inspect the detected line regions and download the PDF. Blue boxes mark
native text, green boxes mark 300-DPI OCR, and red boxes mark 400-DPI repairs. Generated annotated
PDFs are also included in **Download all results (.zip)**.

Annotated PDFs remain available during the active session. Saved history retains Markdown and
JSON, not the annotated PDF, so download it before clearing or restarting the session.

## Work with multiple results

After processing, choose a document from the **Document** selector. Duplicate filenames remain
separate results. Use the result tabs to compare source, annotated PDF, Markdown, JSON, and run
details.

Download each `.md` or `.json` file separately. **Download all results (.zip)** includes every
document with usable Markdown and adds numeric suffixes when sanitized filenames collide.
Use **Copy Markdown source** in the Markdown **Source** tab to place the unrendered Markdown on
the browser clipboard. The Preview tab remains rendered and unchanged.
In **Preview**, use **Copy formatted preview** for rich-text applications such as Word or email,
or **Copy preview as plain text** when formatting is not wanted. Rich copying falls back to plain
text when the browser does not support rich clipboard data.

## Reopen saved results

The app saves derived Markdown, JSON, processing options, filenames, and source hashes under
**Saved history**. Select a record and choose **Load** to reopen it without another model call.
The original PDF or image is not stored, so the Source tab shows a notice for loaded records.

Records expire after 30 days. If retained outputs reach 1 GiB, the app removes the oldest records
first. Choose **Delete** to remove one record immediately.

## Clear local session results

Select **Clear session** in the sidebar. This removes the current in-memory result list and
reruns the UI. It does not delete **Saved history**. Markdown, JSON, and ZIP files already saved
by the browser also remain on disk and must be removed separately.

For controlled output fields, continue with [custom schemas](use-a-custom-schema.md).
