"""Tests for Markdown-only prompt storage."""

import pytest

from liteparse_agentic_document_extraction.prompts import load_prompt


def test_prompt_loading_and_hashing() -> None:
    prompt, digest = load_prompt("ocr.md", LANGUAGE="en", WIDTH="100", HEIGHT="200")
    assert "100 by 200 pixels" in prompt
    assert "{{" not in prompt
    assert len(digest) == 64


def test_prompt_rejects_unresolved_values() -> None:
    with pytest.raises(ValueError, match="unresolved"):
        load_prompt("extract.md", INSTRUCTIONS="Extract")
