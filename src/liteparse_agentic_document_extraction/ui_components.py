"""Small browser-side controls that Streamlit does not provide natively.

The JS below writes component data into Blob objects for the Clipboard API
(navigator.clipboard.write/writeText), never into innerHTML, so
attacker-controlled Markdown rendered to plain text/HTML here cannot execute
as script in the browser.
"""

from __future__ import annotations

import streamlit as st

_COPY_MARKDOWN = st.components.v2.component(
    "copy_markdown_source",
    html='<button id="copy" type="button"></button>',
    css="""
button {
  appearance: none;
  background: var(--st-secondary-background-color);
  border: 1px solid color-mix(in srgb, var(--st-text-color) 20%, transparent);
  border-radius: var(--st-button-border-radius);
  color: var(--st-text-color);
  cursor: pointer;
  font: inherit;
  padding: 0.45rem 0.8rem;
}
button:hover { border-color: var(--st-primary-color); }
button:focus-visible { outline: 2px solid var(--st-primary-color); outline-offset: 2px; }
""",
    js="""
export default function(component) {
  const { data, parentElement } = component;
  const button = parentElement.querySelector("#copy");
  if (!button) return;
  button.textContent = data?.label ?? "Copy";

  // Three-tier fallback: rich HTML+text clipboard write, then plain-text-only
  // write (older browsers or no html payload), then a visible failure label
  // if the Clipboard API itself is unavailable or denied.
  button.onclick = async () => {
    try {
      if (data?.html && window.ClipboardItem && navigator.clipboard.write) {
        await navigator.clipboard.write([new ClipboardItem({
          "text/html": new Blob([data.html], {type: "text/html"}),
          "text/plain": new Blob([data.text ?? ""], {type: "text/plain"}),
        })]);
        button.textContent = "Copied";
      } else {
        await navigator.clipboard.writeText(data?.text ?? "");
        button.textContent = data?.html ? "Copied as plain text" : "Copied";
      }
    } catch {
      try {
        await navigator.clipboard.writeText(data?.text ?? "");
        button.textContent = "Copied as plain text";
      } catch {
        button.textContent = "Copy failed";
      }
    }
  };
}
""",
)


def copy_markdown_button(markdown: str, *, key: str) -> None:
    """Render a button that copies trusted component data to the browser clipboard."""
    clipboard_button("Copy Markdown source", markdown, key=key)


def clipboard_button(label: str, text: str, *, key: str, rich_html: str | None = None) -> None:
    """Render a browser clipboard button with an optional rich HTML payload."""
    _COPY_MARKDOWN(data={"label": label, "text": text, "html": rich_html}, key=key)


__all__ = ["clipboard_button", "copy_markdown_button"]
