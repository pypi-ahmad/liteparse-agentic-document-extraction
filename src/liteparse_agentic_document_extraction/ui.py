"""Streamlit interface for agentic document extraction."""

from __future__ import annotations

import streamlit as st

from liteparse_agentic_document_extraction.extraction import validate_user_schema
from liteparse_agentic_document_extraction.models import (
    DocumentArtifact,
    ProcessingOptions,
    RunStatus,
)
from liteparse_agentic_document_extraction.pipeline import (
    artifact_json,
    process_document,
    result_zip,
    safe_stem,
)
from liteparse_agentic_document_extraction.settings import (
    BASE_DPI,
    MAX_BATCH_BYTES,
    MAX_FILES,
    MODEL_ID,
    REASONING_EFFORT,
    REPAIR_DPI,
)
from liteparse_agentic_document_extraction.ui_support import build_page_range, read_schema

st.set_page_config(
    page_title="Agentic document extraction",
    page_icon=":material/document_scanner:",
    layout="wide",
)
st.session_state.setdefault("artifacts", {})


with st.sidebar:
    st.header("Process documents")
    st.caption(
        "Files are sent to the configured OpenAI endpoint for OCR and extraction. "
        "App storage is session-only."
    )
    schema_mode = st.segmented_control(
        "Extraction schema", ["None", "Paste", "Upload"], default="None", key="schema_mode"
    )
    with st.form("processing_options"):
        uploads = st.file_uploader(
            "Scanned PDFs or images",
            type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp"],
            accept_multiple_files=True,
            max_upload_size=50,
            help="Maximum 20 files, 50 MB each, 500 MB per batch, and 100 pages per document.",
        )
        instructions = st.text_area(
            "Extraction instructions",
            placeholder="Example: Extract invoice number, supplier, dates, line items, and totals.",
        )
        pasted_schema = ""
        uploaded_schema = None
        if schema_mode == "Paste":
            pasted_schema = st.text_area("JSON Schema", height=180)
        elif schema_mode == "Upload":
            uploaded_schema = st.file_uploader("JSON Schema file", type=["json"], max_upload_size=1)

        with st.expander("Advanced options"):
            language = st.text_input("Language hint", value="auto")
            page_scope = st.segmented_control(
                "Pages", ["All", "Range"], default="All", key="page_scope"
            )
            start_page = end_page = 1
            if page_scope == "Range":
                with st.container(horizontal=True):
                    start_page = st.number_input(
                        "Start page", min_value=1, value=1, step=1, key="start_page"
                    )
                    end_page = st.number_input(
                        "End page", min_value=1, value=1, step=1, key="end_page"
                    )
            keep_headers = st.toggle("Keep repeated headers and footers", value=False)
            image_mode = st.selectbox("Markdown images", ["placeholder", "off", "embed"])
            st.text_input("Model", value=MODEL_ID, disabled=True)
            st.text_input("Reasoning effort", value=REASONING_EFFORT, disabled=True)
            st.text_input(
                "DPI", value=f"{BASE_DPI} base / {REPAIR_DPI} hard regions", disabled=True
            )

        process = st.form_submit_button(
            "Process files", type="primary", icon=":material/play_arrow:"
        )

    if st.button("Clear session", icon=":material/delete:"):
        st.session_state.artifacts = {}
        st.rerun()

st.title("Agentic document extraction")
st.caption("Layout-aware Markdown and evidence-grounded JSON using LiteParse and GPT-5.6 Terra.")

if process:
    if not uploads:
        st.error("Upload at least one document.")
    elif len(uploads) > MAX_FILES:
        st.error(f"Upload at most {MAX_FILES} files per batch.")
    elif sum(upload.size for upload in uploads) > MAX_BATCH_BYTES:
        st.error("Uploaded batch exceeds 500 MB.")
    else:
        try:
            schema = read_schema(schema_mode or "None", pasted_schema, uploaded_schema)
            validate_user_schema(schema)
            target_pages = build_page_range(page_scope or "All", start_page, end_page)
            options = ProcessingOptions(
                instructions=instructions,
                schema=schema,
                language=language.strip() or "auto",
                target_pages=target_pages,
                keep_headers_footers=keep_headers,
                image_mode=image_mode,
            )
            progress = st.progress(0, text="Starting batch")
            for index, upload in enumerate(uploads, start=1):
                with st.status(f"Processing {upload.name}", expanded=True) as status:
                    status.write("Parsing at 300 DPI, repairing at 400 DPI, then extracting.")
                    artifact = process_document(upload.name, upload.getvalue(), options)
                    st.session_state.artifacts[artifact.artifact_id] = artifact
                    state = "error" if artifact.status is RunStatus.FAILED else "complete"
                    status.update(
                        label=f"{artifact.status.value.title()}: {upload.name}", state=state
                    )
                    if artifact.error:
                        status.write(artifact.error)
                progress.progress(index / len(uploads), text=f"Processed {index} of {len(uploads)}")
        except ValueError as exc:
            st.error(str(exc))

artifacts: dict[str, DocumentArtifact] = st.session_state.artifacts
if not artifacts:
    st.info("Upload one or more documents from sidebar, then select Process files.")
    st.stop()

labels = {
    artifact_id: f"{artifact.source_name} · {artifact.status.value}"
    for artifact_id, artifact in artifacts.items()
}
selected_id = st.selectbox("Document", list(labels), format_func=lambda value: labels[value])
artifact = artifacts[selected_id]

if artifact.error:
    st.error(artifact.error)

source_tab, markdown_tab, json_tab, run_tab = st.tabs(
    ["Source", "Markdown", "JSON", "Run details"], on_change="rerun"
)

if source_tab.open:
    with source_tab:
        if artifact.source_name.lower().endswith(".pdf"):
            st.pdf(artifact.source_bytes, height=800)
        else:
            st.image(artifact.source_bytes, caption=artifact.source_name)

if markdown_tab.open:
    with markdown_tab:
        if artifact.markdown:
            preview_tab, source_code_tab = st.tabs(["Preview", "Source"])
            with preview_tab:
                st.markdown(artifact.markdown)
            with source_code_tab:
                st.code(artifact.markdown, language="markdown", line_numbers=True)
            st.download_button(
                "Download Markdown",
                artifact.markdown,
                file_name=f"{safe_stem(artifact.source_name)}.md",
                mime="text/markdown",
                icon=":material/download:",
                key=f"md-{selected_id}",
            )
        else:
            st.info("No Markdown was produced.")

if json_tab.open:
    with json_tab:
        if artifact.output:
            serialized = artifact_json(artifact)
            st.code(serialized, language="json", line_numbers=True)
            st.download_button(
                "Download JSON",
                serialized,
                file_name=f"{safe_stem(artifact.source_name)}.json",
                mime="application/json",
                icon=":material/download:",
                key=f"json-{selected_id}",
            )
        else:
            st.info("No JSON result was produced.")

if run_tab.open:
    with run_tab:
        document = artifact.output.get("document", {})
        st.json(
            {
                "status": artifact.status.value,
                "source pages": document.get("source_page_count"),
                "processed pages": document.get("processed_pages"),
                "repairs": len(artifact.output.get("repairs", [])),
                "issues": len(artifact.output.get("issues", [])),
                "model": document.get("model"),
                "DPI": f"{BASE_DPI}/{REPAIR_DPI}",
            }
        )

ready = [item for item in artifacts.values() if item.markdown]
if ready:
    st.download_button(
        "Download all results (.zip)",
        result_zip(ready),
        file_name="liteparse-results.zip",
        mime="application/zip",
        icon=":material/folder_zip:",
        key="all-results",
    )
