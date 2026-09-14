"""Streamlit interface for agentic document extraction.

Streamlit executes this whole file top-to-bottom on every rerun (a page
load, a widget interaction, or an explicit st.rerun()); there is no
persistent app object, so all cross-rerun state lives in st.session_state.
Excluded from coverage (pyproject.toml) - see tests/test_streamlit_app.py,
which drives it through Streamlit's AppTest harness instead. Next:
pipeline.py, which this script calls for every document.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from liteparse_agentic_document_extraction.extraction import validate_user_schema
from liteparse_agentic_document_extraction.markdown_clipboard import clipboard_content
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
    HISTORY_LIST_LIMIT,
    MAX_BATCH_BYTES,
    MAX_FILES,
    MODEL_ID,
    REASONING_EFFORT,
    REPAIR_DPI,
)
from liteparse_agentic_document_extraction.storage import HistoryError, HistoryStore
from liteparse_agentic_document_extraction.ui_components import (
    clipboard_button,
    copy_markdown_button,
)
from liteparse_agentic_document_extraction.ui_support import build_page_range, read_schema


# Streamlit on_click callbacks: these run once, before Streamlit reruns the
# rest of this script, so session_state changes made here are already in
# effect by the time the widgets below are recreated on that rerun.
def _load_saved_result(store: HistoryStore, artifact_id: str) -> None:
    try:
        saved = store.load(artifact_id)
    except HistoryError as exc:
        st.session_state.history_notice = ("warning", str(exc))
        return
    if saved is None:
        st.session_state.history_notice = ("warning", "Saved result no longer exists.")
        return
    st.session_state.artifacts[artifact_id] = saved.artifact
    st.session_state.selected_artifact_id = artifact_id


def _delete_saved_result(store: HistoryStore, artifact_id: str) -> None:
    try:
        deleted = store.delete(artifact_id)
    except HistoryError as exc:
        st.session_state.history_notice = ("warning", str(exc))
        return
    if not deleted:
        st.session_state.history_notice = ("warning", "Saved result no longer exists.")
        return
    st.session_state.artifacts.pop(artifact_id, None)
    if st.session_state.get("selected_artifact_id") == artifact_id:
        st.session_state.pop("selected_artifact_id", None)
    st.session_state.history_notice = ("success", "Saved result deleted.")


st.set_page_config(
    page_title="Agentic document extraction",
    page_icon=":material/document_scanner:",
    layout="wide",
)
st.session_state.setdefault("artifacts", {})

history_store: HistoryStore | None = None
history_error: str | None = None
try:
    history_store = HistoryStore.default()
except HistoryError as exc:
    history_error = str(exc)


with st.sidebar:
    st.header("Process documents")
    st.caption(
        "Files are sent to the configured OpenAI endpoint for OCR. Structured extraction runs "
        "only when enabled. Derived outputs are saved locally for 30 days; source files are not."
    )
    extract_data = st.toggle("Extract structured data", value=False, key="extract_data")
    schema_mode = "None"
    if extract_data:
        schema_mode = st.segmented_control(
            "Extraction schema", ["None", "Paste", "Upload"], default="None", key="schema_mode"
        )
    page_scope = st.segmented_control("Pages", ["All", "Range"], default="All", key="page_scope")
    with st.form("processing_options"):
        uploads = st.file_uploader(
            "Scanned PDFs or images",
            type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp"],
            accept_multiple_files=True,
            max_upload_size=50,
            help="Maximum 20 files, 50 MB each, 500 MB per batch, and 100 pages per document.",
        )
        instructions = ""
        pasted_schema = ""
        uploaded_schema = None
        if extract_data:
            instructions = st.text_area(
                "Extraction instructions",
                placeholder=(
                    "Example: Extract invoice number, supplier, dates, line items, and totals."
                ),
            )
            if schema_mode == "Paste":
                pasted_schema = st.text_area("JSON Schema", height=180)
            elif schema_mode == "Upload":
                uploaded_schema = st.file_uploader(
                    "JSON Schema file", type=["json"], max_upload_size=1
                )

        with st.expander("Advanced options"):
            language = st.text_input("Language hint", value="auto")
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
            generate_annotated_pdf = st.toggle("Generate annotated PDF", value=False)
            experimental_peer_evidence = st.toggle(
                "Experimental peer evidence",
                value=False,
                help=(
                    "Use only clearer printed blocks repeated consistently on at least three pages."
                ),
            )
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
st.caption("Layout-aware Markdown with optional evidence-grounded JSON using LiteParse and Terra.")

if process:
    if not uploads:
        st.error("Upload at least one document.")
    elif len(uploads) > MAX_FILES:
        st.error(f"Upload at most {MAX_FILES} files per batch.")
    elif sum(upload.size for upload in uploads) > MAX_BATCH_BYTES:
        st.error("Uploaded batch exceeds 500 MB.")
    else:
        try:
            schema = None
            if extract_data:
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
                extract_data=extract_data,
                generate_annotated_pdf=generate_annotated_pdf,
                experimental_peer_evidence=experimental_peer_evidence,
            )
            progress = st.progress(0, text="Starting batch")
            for index, upload in enumerate(uploads, start=1):
                with st.status(f"Processing {upload.name}", expanded=True) as status:
                    stage_message = "Parsing at 300 DPI and repairing hard regions at 400 DPI."
                    if extract_data:
                        stage_message += " Structured extraction follows parsing."
                    status.write(stage_message)
                    artifact = process_document(upload.name, upload.getvalue(), options)
                    st.session_state.artifacts[artifact.artifact_id] = artifact
                    st.session_state.selected_artifact_id = artifact.artifact_id
                    # A history-save failure is shown inline but does not
                    # remove the just-computed result from this session or
                    # stop the rest of the batch.
                    if history_store is not None:
                        try:
                            history_store.save(artifact, options)
                        except HistoryError as exc:
                            status.write(str(exc))
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

history_summaries = []
if history_store is not None:
    try:
        history_summaries = history_store.list_recent(limit=HISTORY_LIST_LIMIT)
    except HistoryError as exc:
        history_error = str(exc)

with st.sidebar, st.expander("Saved history"):
    history_notice = st.session_state.pop("history_notice", None)
    if history_notice:
        notice_kind, notice_text = history_notice
        if notice_kind == "success":
            st.success(notice_text)
        else:
            st.warning(notice_text)
    if history_error:
        st.warning(history_error)
    elif not history_summaries:
        st.caption("No saved results yet.")
    else:
        history_labels = {
            item.artifact_id: (
                f"{item.source_name} · {item.status.value} · "
                f"{datetime.fromtimestamp(item.created_at, UTC):%Y-%m-%d %H:%M} UTC"
            )
            for item in history_summaries
        }
        saved_id = st.selectbox(
            "Saved result",
            list(history_labels),
            format_func=lambda value: history_labels[value],
            key="saved_history_id",
        )
        selected_summary = next(item for item in history_summaries if item.artifact_id == saved_id)
        st.caption(
            f"Expires {datetime.fromtimestamp(selected_summary.expires_at, UTC):%Y-%m-%d}. "
            f"Stored output: {selected_summary.retained_bytes / 1024:.1f} KiB."
        )
        assert history_store is not None
        with st.container(horizontal=True):
            st.button(
                "Load",
                icon=":material/history:",
                key="load-saved-result",
                on_click=_load_saved_result,
                args=(history_store, saved_id),
            )
            st.button(
                "Delete",
                icon=":material/delete:",
                key="delete-saved-result",
                on_click=_delete_saved_result,
                args=(history_store, saved_id),
            )

if not artifacts:
    st.info("Upload documents to process, or load a result from saved history.")
    st.stop()

labels = {
    artifact_id: f"{artifact.source_name} · {artifact.status.value}"
    for artifact_id, artifact in artifacts.items()
}
if st.session_state.get("selected_artifact_id") not in labels:
    st.session_state.selected_artifact_id = list(labels)[-1]
selected_id = st.selectbox(
    "Document",
    list(labels),
    format_func=lambda value: labels[value],
    key="selected_artifact_id",
)
artifact = artifacts[selected_id]

if artifact.error:
    st.error(artifact.error)

source_tab, annotated_tab, markdown_tab, json_tab, run_tab = st.tabs(
    ["Source", "Annotated PDF", "Markdown", "JSON", "Run details"], on_change="rerun"
)

# `.open` is true only for the currently visible tab; each block below only
# does its (sometimes non-trivial, e.g. clipboard rendering) work when its
# tab is actually the one on screen.
if source_tab.open:
    with source_tab:
        if not artifact.source_bytes:
            st.info("The original source file was not saved with this historical result.")
        elif artifact.source_name.lower().endswith(".pdf"):
            st.pdf(artifact.source_bytes, height=800)
        else:
            st.image(artifact.source_bytes, caption=artifact.source_name)

if annotated_tab.open:
    with annotated_tab:
        if artifact.annotated_pdf:
            st.pdf(artifact.annotated_pdf, height=800)
            st.download_button(
                "Download annotated PDF",
                artifact.annotated_pdf,
                file_name=f"{safe_stem(artifact.source_name)}.annotated.pdf",
                mime="application/pdf",
                icon=":material/download:",
                key=f"annotated-{selected_id}",
            )
            st.caption("Blue: native text · Green: 300-DPI OCR · Red: 400-DPI repair")
        else:
            st.info(
                "No annotated PDF is available. Enable it in Advanced options and process again."
            )

if markdown_tab.open:
    with markdown_tab:
        if artifact.markdown:
            preview_tab, source_code_tab = st.tabs(["Preview", "Source"])
            with preview_tab:
                rich_html, plain_text = clipboard_content(artifact.markdown)
                with st.container(horizontal=True):
                    clipboard_button(
                        "Copy formatted preview",
                        plain_text,
                        rich_html=rich_html,
                        key=f"copy-rich-preview-{selected_id}",
                    )
                    clipboard_button(
                        "Copy preview as plain text",
                        plain_text,
                        key=f"copy-plain-preview-{selected_id}",
                    )
                st.markdown(artifact.markdown)
            with source_code_tab:
                copy_markdown_button(artifact.markdown, key=f"copy-markdown-{selected_id}")
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
