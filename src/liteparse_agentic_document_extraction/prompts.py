"""Prompt loading and safe template substitution."""

import re
from hashlib import sha256
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(name: str, **values: str) -> tuple[str, str]:
    """Load a Markdown prompt and replace its declared placeholders."""
    path = PROMPT_DIR / name
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    if re.search(r"\{\{[A-Z_]+\}\}", text):
        raise ValueError(f"Prompt {name} contains unresolved placeholders")
    return text, sha256(path.read_bytes()).hexdigest()
