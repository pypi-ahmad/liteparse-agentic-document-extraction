"""Build a visual PDF from LiteParse page screenshots and line evidence.

Purely a rendering step: it trusts LineEvidence.source/bbox as already
correct and only draws over the *base*-DPI screenshots, so a repaired line is
shown at base resolution even though it was re-read at REPAIR_DPI. Next:
repair.py's _line_catalog, which assigns the "source" value used for color.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from typing import Any

from PIL import Image, ImageDraw

from .models import LineEvidence
from .settings import BASE_DPI

# Keep in sync with the legend text in ui.py's annotated-PDF tab.
LINE_COLORS = {
    "native": "#2563eb",
    "ocr_300": "#16a34a",
    "repair_400": "#dc2626",
}


def _draw_line_box(
    draw: ImageDraw.ImageDraw,
    line: LineEvidence,
    scale_x: float,
    scale_y: float,
    default_width: int,
) -> None:
    """Draw a readable outline without covering tightly bounded repair text.

    Repair boxes get a small outward pad and a fixed 1px stroke because
    apply_repair's mapped boxes are tight around the glyphs; the default,
    thicker stroke used elsewhere would otherwise obscure the repaired text.
    """
    x1, y1, x2, y2 = line.bbox
    if line.source == "repair_400":
        padding_x = 2 * scale_x
        padding_y = 2 * scale_y
        box = (
            max(0, x1 * scale_x - padding_x),
            max(0, y1 * scale_y - padding_y),
            x2 * scale_x + padding_x,
            y2 * scale_y + padding_y,
        )
        width = 1
    else:
        box = (x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y)
        width = default_width
    draw.rectangle(box, outline=LINE_COLORS.get(line.source, "#7c3aed"), width=width)


def build_annotated_pdf(
    screenshots: Iterable[Any], pages: Iterable[Any], lines: Iterable[LineEvidence]
) -> bytes:
    """Render processed pages with source-colored line boxes at the base DPI."""
    page_sizes = {page.page_num: (float(page.width), float(page.height)) for page in pages}
    lines_by_page: dict[int, list[LineEvidence]] = {}
    for line in lines:
        lines_by_page.setdefault(line.page, []).append(line)

    images: list[Image.Image] = []
    try:
        for screenshot in sorted(screenshots, key=lambda item: item.page_num):
            page_size = page_sizes.get(screenshot.page_num)
            if page_size is None:
                continue
            with Image.open(io.BytesIO(screenshot.image_bytes)) as source:
                image = source.convert("RGB")
            scale_x = image.width / page_size[0]
            scale_y = image.height / page_size[1]
            draw = ImageDraw.Draw(image)
            width = max(2, round(min(scale_x, scale_y) * 0.75))
            for line in lines_by_page.get(screenshot.page_num, []):
                _draw_line_box(draw, line, scale_x, scale_y, width)
            images.append(image)

        if not images:
            return b""
        output = io.BytesIO()
        images[0].save(
            output,
            format="PDF",
            save_all=True,
            append_images=images[1:],
            resolution=float(BASE_DPI),
        )
        return output.getvalue()
    finally:
        for image in images:
            image.close()
