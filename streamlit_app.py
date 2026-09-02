"""Streamlit user interface for agentic document extraction."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

from liteparse_agentic_document_extraction.models import (
    BASE_DPI,
    MODEL_ID,
    REASONING_EFFORT,
    REPAIR_DPI,
    DocumentArtifact,
    ProcessingOptions,
    RunStatus,
)
from liteparse_agentic_document_extraction.pipeline import (
    MAX_FILES,
    artifact_json,
    process_document,
    result_zip,
    safe_stem,
    validate_user_schema,
)

st.set_page_config(
    page_title="Agentic document extraction", page_icon=":material/document_scanner:", layout="wide"
)
st.session_state.setdefault("artifacts", {})


def read_schema(mode: str, pasted: str, uploaded: Any) -> dict[str, Any] | None:
    """Read the selected optional JSON Schema input."""
    if mode == "None":
        return None
    raw = pasted if mode == "Paste" else uploaded.getvalue().decode("utf-8") if uploaded else ""
    if not raw.strip():
        raise ValueError("Selected schema mode requires JSON Schema content")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON Schema must be a JSON object")
    return parsed


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
            help="Maximum 20 files, 50 MB each, and 100 processed pages per document.",
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
            uploaded_schema = st.file_uploader("JSON Schema file", type=["json"])

        with st.expander("Advanced options"):
            language = st.text_input("Language hint", value="auto")
            target_pages = st.text_input("Pages", placeholder="All pages, or 1-5,8")
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
    else:
        try:
            schema = read_schema(schema_mode or "None", pasted_schema, uploaded_schema)
            validate_user_schema(schema)
            options = ProcessingOptions(
                instructions=instructions,
                schema=schema,
                language=language.strip() or "auto",
                target_pages=target_pages.strip() or None,
                keep_headers_footers=keep_headers,
                image_mode=image_mode,
            )
            progress = st.progress(0, text="Starting batch")
            for index, upload in enumerate(uploads, start=1):
                with st.status(f"Processing {upload.name}", expanded=True) as status:
                    status.write(
                        "Parsing at 300 DPI, repairing hard regions at 400 DPI, then extracting."
                    )
                    artifact = process_document(upload.name, upload.getvalue(), options)
                    st.session_state.artifacts[artifact.source_hash] = artifact
                    if artifact.status == RunStatus.FAILED:
                        status.update(label=f"Failed: {upload.name}", state="error")
                        status.write(artifact.error or "Processing failed")
                    else:
                        status.update(label=f"Ready: {upload.name}", state="complete")
                progress.progress(index / len(uploads), text=f"Processed {index} of {len(uploads)}")
        except (ValueError, json.JSONDecodeError) as exc:
            st.error(str(exc))

artifacts: dict[str, DocumentArtifact] = st.session_state.artifacts
if not artifacts:
    st.info("Upload one or more documents from sidebar, then select Process files.")
    st.stop()

labels = {
    digest: f"{artifact.source_name} · {artifact.status.value}"
    for digest, artifact in artifacts.items()
}
selected_hash = st.selectbox(
    "Document",
    list(labels),
    format_func=lambda digest: labels[digest],
)
artifact = artifacts[selected_hash]

if artifact.status == RunStatus.FAILED:
    st.error(artifact.error or "Processing failed")
    st.stop()

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
            key=f"md-{selected_hash}",
        )

if json_tab.open:
    with json_tab:
        serialized = artifact_json(artifact)
        st.code(serialized, language="json", line_numbers=True)
        st.download_button(
            "Download JSON",
            serialized,
            file_name=f"{safe_stem(artifact.source_name)}.json",
            mime="application/json",
            icon=":material/download:",
            key=f"json-{selected_hash}",
        )

if run_tab.open:
    with run_tab:
        document = artifact.output.get("document", {})
        st.json(
            {
                "status": artifact.status.value,
                "pages": document.get("page_count"),
                "repairs": len(artifact.output.get("repairs", [])),
                "issues": len(artifact.output.get("issues", [])),
                "model": document.get("model"),
                "DPI": f"{BASE_DPI}/{REPAIR_DPI}",
            }
        )

ready = [
    item for item in artifacts.values() if item.status in {RunStatus.COMPLETE, RunStatus.PARTIAL}
]
if ready:
    st.download_button(
        "Download all results (.zip)",
        result_zip(ready),
        file_name="liteparse-results.zip",
        mime="application/zip",
        icon=":material/folder_zip:",
        key="all-results",
    )
