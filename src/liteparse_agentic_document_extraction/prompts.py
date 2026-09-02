"""Packaged prompt loading with non-recursive template substitution."""

import re
from hashlib import sha256
from importlib.resources import files

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def load_prompt(name: str, **values: str) -> tuple[str, str]:
    """Render only placeholders declared by the original Markdown template."""
    resource = files("liteparse_agentic_document_extraction.prompt_templates").joinpath(name)
    template = resource.read_text(encoding="utf-8")
    required = set(PLACEHOLDER.findall(template))
    missing = required - values.keys()
    if missing:
        raise ValueError(f"Prompt {name} is missing values for: {', '.join(sorted(missing))}")
    rendered = PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
    return rendered, sha256(template.encode()).hexdigest()
