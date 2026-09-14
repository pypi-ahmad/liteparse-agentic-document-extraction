"""Tests for rich and plain Markdown clipboard conversion."""

from liteparse_agentic_document_extraction.markdown_clipboard import clipboard_content


def test_clipboard_content_preserves_structure_and_visible_text() -> None:
    markdown = """# Invoice

**Total:** $10

- First
- Second

| Item | Price |
|---|---:|
| Pen | $10 |

`INV-1`

[Portal](https://example.com)
"""

    rich, plain = clipboard_content(markdown)

    assert "<h1>Invoice</h1>" in rich
    assert "<strong>Total:</strong>" in rich
    assert "<table>" in rich
    assert "<code>INV-1</code>" in rich
    assert '<a href="https://example.com">Portal</a>' in rich
    assert "Invoice" in plain
    assert "• First" in plain
    assert "Item\tPrice" in plain
    assert "Portal" in plain
    assert "**" not in plain


def test_clipboard_content_disables_raw_html() -> None:
    rich, plain = clipboard_content('<script>alert("x")</script>')

    assert "<script>" not in rich
    assert "&lt;script&gt;" in rich
    assert '<script>alert("x")</script>' in plain
