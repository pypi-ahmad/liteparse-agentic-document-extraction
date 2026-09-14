from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from liteparse_agentic_document_extraction.evaluation import (
    CURATED_SUITE,
    _report,
    _report_markdown,
    candidate_json,
    corpus_entries,
    run_evaluation,
)
from liteparse_agentic_document_extraction.evaluation_metrics import (
    character_error_rate,
    evaluate_document,
    groundtruth_pages,
    headings,
    tables,
)
from liteparse_agentic_document_extraction.models import (
    AccuracyPolicy,
    LineEvidence,
    ParsedDocument,
    ParsedPage,
    ProcessingIssue,
    RepairReceipt,
)


def test_metrics_parse_markdown_and_html_tables() -> None:
    assert character_error_rate("abc", "axc") == pytest.approx((1, 1 / 3, 2 / 3))
    assert headings("# One\n\n### Three") == [(1, "One"), (3, "Three")]
    assert tables("| A | B |\n|---|---|\n| 1 | 2 |") == [[["A", "B"], ["1", "2"]]]
    assert tables("<table><tr><th>A</th></tr><tr><td>1</td></tr></table>") == [[["A"], ["1"]]]


def test_groundtruth_page_slicing() -> None:
    data = {
        "markdown": "one\ntwo",
        "structure": {
            "children": [
                {"grounding": {"page": 1, "range": {"start": 0, "end": 3}}},
                {"grounding": {"page": 2, "range": {"start": 4, "end": 7}}},
            ]
        },
    }
    assert groundtruth_pages(data, (2,)) == {2: "two"}
    with pytest.raises(ValueError, match="missing selected pages"):
        groundtruth_pages(data, (3,))


def test_corpus_entries_require_exact_complete_suite(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="corpus is incomplete"):
        corpus_entries(tmp_path)
    source = tmp_path / "Original Pdfs"
    truth = tmp_path / "GroundTruths"
    source.mkdir()
    truth.mkdir()
    for stem in CURATED_SUITE:
        (source / f"{stem}.pdf").write_bytes(b"%PDF")
        (truth / f"{stem}.parse.json").write_text(json.dumps({}), encoding="utf-8")
        (truth / f"{stem}.parse.md").write_text("", encoding="utf-8")
    assert len(corpus_entries(tmp_path)) == len(CURATED_SUITE)


def parsed_document() -> ParsedDocument:
    return ParsedDocument(
        markdown="# Title\n\n| A |\n|---|\n| one |",
        pages=(
            ParsedPage(
                1,
                "# Title\n\n| A |\n|---|\n| one |",
                ("p1-l0001",),
                100,
                100,
            ),
        ),
        lines=(LineEvidence("p1-l0001", 1, "one", (10, 10, 30, 20), "ocr_300", 0.9),),
        repairs=(RepairReceipt(1, "r1", (1, 1, 2, 2), "test", 1, 1),),
        issues=(ProcessingIssue("test", "test", "test"),),
        source_page_count=1,
        processed_pages=(1,),
        prompt_template_hashes=(),
    )


def test_evaluate_document_and_candidate_serialization() -> None:
    markdown = "# Title\n\n| A |\n|---|\n| one |"
    reference = {
        "markdown": markdown,
        "structure": {
            "children": [
                {
                    "grounding": {"page": 1, "range": {"start": 0, "end": len(markdown)}},
                    "children": [
                        {
                            "atomic_grounding": [
                                {
                                    "range": {
                                        "start": markdown.index("one"),
                                        "end": len(markdown) - 2,
                                    },
                                    "box": {"xmin": 0.1, "ymin": 0.1, "xmax": 0.3, "ymax": 0.2},
                                }
                            ]
                        }
                    ],
                }
            ]
        },
    }
    result = evaluate_document({1: markdown, 2: "missing"}, reference, parsed_document())
    assert result["pages"][0]["normalized_markdown"]["cer"] == 0
    assert result["pages"][0]["grounding"]["mean_iou"] == pytest.approx(1)
    assert result["pages"][1] == {"page": 2, "status": "failed"}
    assert candidate_json(parsed_document())["repairs"][0]["region_id"] == "r1"


def test_report_contains_accuracy_delta() -> None:
    records = []
    for policy, cer in (("legacy", 0.2), ("accuracy", 0.1)):
        records.append(
            {
                "policy": policy,
                "status": "ok",
                "repairs": 1,
                "repair_disagreements": 0,
                "metrics": {
                    "aggregate": {
                        "normalized_markdown_cer": cer,
                        "table_cell_f1": 0.8,
                        "line_text_f1": 0.9,
                    }
                },
            }
        )
    report = _report(records, (AccuracyPolicy.LEGACY, AccuracyPolicy.ACCURACY))
    assert report["accuracy_minus_legacy"]["normalized_markdown_cer"] == pytest.approx(-0.1)
    assert "| accuracy |" in _report_markdown(report)


def test_run_evaluation_writes_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus = tmp_path / "corpus"
    source = corpus / "Original Pdfs"
    truth = corpus / "GroundTruths"
    source.mkdir(parents=True)
    truth.mkdir()
    for stem, pages in CURATED_SUITE.items():
        markdown = "one"
        data = {
            "markdown": markdown,
            "structure": {
                "children": [
                    {
                        "grounding": {"page": page, "range": {"start": 0, "end": 3}},
                        "children": [],
                    }
                    for page in pages
                ]
            },
        }
        (source / f"{stem}.pdf").write_bytes(b"%PDF")
        (truth / f"{stem}.parse.json").write_text(json.dumps(data), encoding="utf-8")
        (truth / f"{stem}.parse.md").write_text(markdown, encoding="utf-8")

    @contextmanager
    def fake_server():
        yield "http://unused"

    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.evaluation.local_ocr_server", fake_server
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.evaluation.parse_document",
        lambda *_args, **_kwargs: parsed_document(),
    )
    run_dir = run_evaluation(corpus, tmp_path / "runs", (AccuracyPolicy.LEGACY,))
    assert (run_dir / "report.json").is_file()
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "artifacts.zip").is_file()
