"""Convert Markdown into safe rich and readable plain clipboard payloads.

MarkdownIt is configured with raw HTML disabled ("html": False), so rendered
output only ever contains tags this module itself understands; that is what
lets _VisibleTextParser assume a fixed, known tag set below.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
_BLOCK_TAGS = {
    "blockquote",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "pre",
    "table",
    "ul",
}


class _VisibleTextParser(HTMLParser):
    """Flatten rendered HTML to plain text with tab/newline table structure.

    table_depth exists because whitespace between tags is meaningful outside
    a table (spacing between inline elements) but is pure formatting noise
    inside one, where cell boundaries are already marked explicitly with
    tabs and newlines below.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self.table_depth += 1
        elif tag == "li":
            self.parts.append("• ")
        elif tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self.parts.append("\t")
        elif tag == "tr":
            # The last cell in a row left a trailing tab separator; turn it
            # into the row's newline instead of appending both.
            if self.parts and self.parts[-1] == "\t":
                self.parts[-1] = "\n"
            else:
                self.parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "table":
            self.table_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.table_depth and not data.strip():
            return
        self.parts.append(data)

    def text(self) -> str:
        value = "".join(self.parts)
        value = re.sub(r"[ \t]+\n", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def clipboard_content(markdown: str) -> tuple[str, str]:
    """Return safe rendered HTML and its visible plain-text equivalent."""
    rich_html = _MARKDOWN.render(markdown)
    parser = _VisibleTextParser()
    parser.feed(rich_html)
    parser.close()
    return rich_html, parser.text()


__all__ = ["clipboard_content"]
