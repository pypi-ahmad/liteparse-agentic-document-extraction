# How to process documents

## Upload one or many files

1. Start the app and open <http://127.0.0.1:9578>.
2. Select files under **Scanned PDFs or images**.
3. Enter a concrete extraction request, such as:

   ```text
   Extract the customer name, invoice number, invoice date, line items, subtotal, tax, and total.
   ```

4. Select **Process files**.

The app accepts PDF, PNG, JPEG, TIFF, and WebP. One batch may contain at most 20 files, each
file may be at most 50 MB, and the combined batch may be at most 500 MB.

## Process selected PDF pages

Open **Advanced options** and enter pages using comma-separated numbers and inclusive ranges:

```text
1-5,8,12
```

Page numbers start at 1. A selection may contain at most 100 distinct pages and cannot exceed
the source document's page count. Leave the field empty to process the whole document; an
unselected document over 100 pages is rejected.

The same page expression applies independently to every file in the submitted batch. A file
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

## Work with multiple results

After processing, choose a document from the **Document** selector. Duplicate filenames remain
separate results. Use the result tabs to compare source, Markdown, JSON, and run details.

Download each `.md` or `.json` file separately. **Download all results (.zip)** includes every
document with usable Markdown and adds numeric suffixes when sanitized filenames collide.

## Clear local session results

Select **Clear session** in the sidebar. This removes the current in-memory result list and
reruns the UI. Reloading or stopping the app can also discard session state. Markdown, JSON,
and ZIP files already saved by the browser remain on disk and must be removed separately.

For controlled output fields, continue with [custom schemas](use-a-custom-schema.md).
