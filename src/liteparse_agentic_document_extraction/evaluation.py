"""Credited A/B evaluation against LandingAI ADE reference artifacts.

Standalone CLI (liteparse-ade-eval), not imported by the app. Spends real
OpenAI API credits and writes OCR'd document text to local disk under
--output-root; see main()'s --acknowledge-sensitive-output gate. Next:
evaluation_metrics.py for how scores are computed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import threading
import zipfile
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

from .evaluation_metrics import evaluate_document, groundtruth_pages
from .models import AccuracyPolicy, ParsedDocument, ProcessingOptions
from .ocr_bridge import ocr_endpoint
from .repair import parse_document

CURATED_SUITE: dict[str, tuple[int, ...]] = {
    "Masked Amerigroup_1": (1, 2),
    "Masked BadgeCare Plus_1": (1, 2),
    "Masked_Amerigroup_RealSolutions_1": (1, 2, 3, 4, 5),
    "Masked_Amerigroup_RealSolutions_2": (1, 2, 3),
    "PublicWaterMassMailing": (4, 5),
}


def corpus_entries(corpus_root: Path) -> list[tuple[str, Path, Path, Path, tuple[int, ...]]]:
    """Resolve the fixed suite by exact stem; fail before spending credits if incomplete."""
    sources = corpus_root / "Original Pdfs"
    truths = corpus_root / "GroundTruths"
    entries = []
    missing = []
    for stem, pages in CURATED_SUITE.items():
        source = sources / f"{stem}.pdf"
        truth_json = truths / f"{stem}.parse.json"
        truth_markdown = truths / f"{stem}.parse.md"
        absent = [path for path in (source, truth_json, truth_markdown) if not path.is_file()]
        if absent:
            missing.extend(absent)
        else:
            entries.append((stem, source, truth_json, truth_markdown, pages))
    if missing:
        names = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Evaluation corpus is incomplete:\n{names}")
    return entries


@contextmanager
def local_ocr_server() -> Any:
    """Serve the private OCR callback in-process so its run registry is shared.

    Boots its own ephemeral server rather than pointing at a running app
    instance because ocr_bridge.REGISTRY is an in-memory, per-process
    singleton; parse_document's run_id would be meaningless to a different
    process. Binding port 0 picks any free loopback port.
    """
    app = Starlette(routes=[Route("/api/ocr", ocr_endpoint, methods=["POST"])])
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/api/ocr"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def candidate_json(document: ParsedDocument) -> dict[str, Any]:
    return {
        "markdown": document.markdown,
        "pages": [asdict(page) for page in document.pages],
        "lines": [asdict(line) for line in document.lines],
        "repairs": [asdict(repair) for repair in document.repairs],
        "issues": [asdict(issue) for issue in document.issues],
        "processed_pages": list(document.processed_pages),
    }


def run_evaluation(
    corpus_root: Path,
    output_root: Path,
    policies: tuple[AccuracyPolicy, ...],
) -> Path:
    entries = corpus_entries(corpus_root)
    identity = json.dumps({"suite": CURATED_SUITE, "policies": policies}, default=list)
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:8]
    run_dir = output_root / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{suffix}"
    run_dir.mkdir(parents=True)
    results: list[dict[str, Any]] = []
    with local_ocr_server() as ocr_url:
        for policy in policies:
            for stem, source, truth_json_path, truth_md_path, pages in entries:
                print(f"[{policy.value}] {stem}: pages {pages}", flush=True)
                truth_json = json.loads(truth_json_path.read_text(encoding="utf-8"))
                truth_md = truth_md_path.read_text(encoding="utf-8")
                # Sanity check that the two reference files for this document
                # have not drifted apart, since groundtruth_pages() below
                # slices character ranges out of truth_json's markdown field.
                if truth_json.get("markdown") != truth_md:
                    raise ValueError(f"Reference Markdown mismatch for {stem}")
                reference_pages = groundtruth_pages(truth_json, pages)
                target = run_dir / policy.value / stem
                target.mkdir(parents=True)
                record: dict[str, Any] = {"policy": policy.value, "document": stem}
                try:
                    document = parse_document(
                        source,
                        ProcessingOptions(
                            target_pages=",".join(str(page) for page in pages),
                            accuracy_policy=policy,
                        ),
                        list(pages),
                        ocr_url=ocr_url,
                    )
                    metrics = evaluate_document(reference_pages, truth_json, document)
                    record.update(
                        status="ok",
                        metrics=metrics,
                        repairs=len(document.repairs),
                        repair_disagreements=sum(
                            issue.code == "repair_disagreement" for issue in document.issues
                        ),
                    )
                    (target / "candidate.md").write_text(document.markdown, encoding="utf-8")
                    _write_json(target / "candidate.json", candidate_json(document))
                    _write_json(target / "metrics.json", metrics)
                except Exception as error:
                    record.update(status="failed", error=f"{type(error).__name__}: {error}")
                    print(f"  failed: {record['error']}", flush=True)
                results.append(record)
    report = _report(results, policies)
    _write_json(run_dir / "report.json", report)
    (run_dir / "report.md").write_text(_report_markdown(report), encoding="utf-8")
    with zipfile.ZipFile(run_dir / "artifacts.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in run_dir.rglob("*"):
            if path.is_file() and path.name != "artifacts.zip":
                archive.write(path, path.relative_to(run_dir))
    return run_dir


def _report(records: list[dict[str, Any]], policies: tuple[AccuracyPolicy, ...]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    keys = ("normalized_markdown_cer", "table_cell_f1", "line_text_f1")
    for policy in policies:
        successful = [
            item for item in records if item["policy"] == policy.value and item["status"] == "ok"
        ]
        summary[policy.value] = {
            "successful_documents": len(successful),
            "failed_documents": sum(
                item["policy"] == policy.value and item["status"] != "ok" for item in records
            ),
            **{
                key: sum(item["metrics"]["aggregate"][key] for item in successful)
                / max(1, len(successful))
                for key in keys
            },
            "repairs": sum(item.get("repairs", 0) for item in successful),
            "repair_disagreements": sum(item.get("repair_disagreements", 0) for item in successful),
        }
    delta = {}
    if AccuracyPolicy.LEGACY.value in summary and AccuracyPolicy.ACCURACY.value in summary:
        delta = {
            key: summary[AccuracyPolicy.ACCURACY.value][key]
            - summary[AccuracyPolicy.LEGACY.value][key]
            for key in keys
        }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "suite": {key: list(value) for key, value in CURATED_SUITE.items()},
        "summary": summary,
        "accuracy_minus_legacy": delta,
        "documents": records,
    }


def _report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Accuracy evaluation",
        "",
        "| Policy | Success | CER | Table F1 | Line F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for policy, values in report["summary"].items():
        lines.append(
            f"| {policy} | {values['successful_documents']} | "
            f"{values['normalized_markdown_cer']:.4f} | {values['table_cell_f1']:.4f} | "
            f"{values['line_text_f1']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evaluation/runs"))
    parser.add_argument(
        "--policies",
        nargs="+",
        choices=[policy.value for policy in AccuracyPolicy],
        default=[AccuracyPolicy.LEGACY.value, AccuracyPolicy.ACCURACY.value],
    )
    parser.add_argument(
        "--acknowledge-sensitive-output",
        action="store_true",
        help="Confirm that OCR artifacts may contain sensitive source text.",
    )
    return parser


def main() -> None:
    # Candidate Markdown/JSON written under --output-root can contain the
    # full OCR'd text of real scanned documents; require an explicit opt-in
    # before writing it to disk (see the gitignored evaluation/runs/ note in
    # the project README).
    args = build_parser().parse_args()
    if not args.acknowledge_sensitive_output:
        raise SystemExit("Refusing to write OCR artifacts without --acknowledge-sensitive-output")
    run_dir = run_evaluation(
        args.corpus_root,
        args.output_root,
        tuple(AccuracyPolicy(value) for value in args.policies),
    )
    print(f"Evaluation written to {run_dir}")


if __name__ == "__main__":
    main()
