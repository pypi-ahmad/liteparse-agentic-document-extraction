"""Packaged prompt loading with non-recursive template substitution.

Substitution is single-pass: a value inserted for one placeholder is never
itself re-scanned for further {{PLACEHOLDER}} tokens, so caller-supplied
values cannot inject new template variables. Next: ocr_bridge.py and
extraction.py, the two callers that render these templates per request.
"""

import re
from hashlib import sha256
from importlib.resources import files

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def load_prompt(name: str, **values: str) -> tuple[str, str]:
    """Render only placeholders declared by the original Markdown template.

    Extra keyword values with no matching placeholder are silently accepted
    and ignored; only a placeholder with no supplied value raises.
    """
    resource = files("liteparse_agentic_document_extraction.prompt_templates").joinpath(name)
    template = resource.read_text(encoding="utf-8")
    required = set(PLACEHOLDER.findall(template))
    missing = required - values.keys()
    if missing:
        raise ValueError(f"Prompt {name} is missing values for: {', '.join(sorted(missing))}")
    rendered = PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
    # Hash of the on-disk template (not the rendered text) so callers can record
    # exactly which prompt version produced a result, for audit/reproducibility.
    return rendered, sha256(template.encode()).hexdigest()
