"""Tests for Markdown-only prompt storage."""

import pytest

from liteparse_agentic_document_extraction.prompts import load_prompt


def test_prompt_loading_and_hashing() -> None:
    prompt, digest = load_prompt("ocr-user.md", LANGUAGE="en", WIDTH="100", HEIGHT="200")
    assert "100 by 200 pixels" in prompt
    assert "{{" not in prompt
    assert len(digest) == 64


def test_prompt_rejects_missing_values_without_recursive_expansion() -> None:
    with pytest.raises(ValueError, match="missing values"):
        load_prompt("extract-user.md", INSTRUCTIONS="Extract")

    prompt, _ = load_prompt(
        "extract-user.md",
        INSTRUCTIONS="Keep literal {{DOCUMENT}} text",
        SCHEMA_DESCRIPTION="{}",
        DOCUMENT="invoice {{TOTAL}}",
        LINE_CATALOG="line",
        VALIDATION_ERRORS="none",
    )
    assert "Keep literal {{DOCUMENT}} text" in prompt
    assert "invoice {{TOTAL}}" in prompt
