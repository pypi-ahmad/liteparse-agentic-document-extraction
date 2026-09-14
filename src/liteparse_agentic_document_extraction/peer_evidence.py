"""Conservative selection of clearer repeated printed blocks.

Optional evidence source for repair.py, gated behind
ProcessingOptions.experimental_peer_evidence. Only ever supplies a second
*image* as extra context to the same OCR call (see ocr_bridge.call_terra_ocr's
peer_image_bytes) - it never substitutes or votes on text. Deliberately
excludes anything that could legitimately differ between "matching" blocks
(numbers, checkboxes) so a peer can never smuggle another page's differing
answer into this page's repair as if it corroborated it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageFilter, ImageStat

from .consensus import normalized_ocr_text
from .models import BBox
from .ocr_bridge import OcrPageRecord, image_digest


@dataclass(frozen=True, slots=True)
class PeerEvidence:
    """One clearer repeated block supplied as secondary visual evidence."""

    image_bytes: bytes
    source_page: int
    clarity: float


def select_peer_evidence(
    result: Any,
    records: dict[int, OcrPageRecord],
    target_page: int,
    target_region: BBox,
) -> PeerEvidence | None:
    """Return a clearer peer only for stable printed text repeated on three pages."""
    shots = {shot.page_num: shot for shot in result.screenshots}
    pages = {page.page_num: page for page in result.pages}
    target_page_data = pages.get(target_page)
    target_shot = shots.get(target_page)
    target_record = records.get(target_page)
    if target_page_data is None or target_shot is None or target_record is None:
        return None
    target_block = _containing_block(target_page_data, target_shot, target_region)
    if target_block is None:
        return None
    signature = _safe_signature(target_block, target_page_data, target_shot, target_record)
    if not signature:
        return None

    peers: list[tuple[float, int, bytes]] = []
    for page_number, page in pages.items():
        if page_number == target_page or page_number not in shots or page_number not in records:
            continue
        for block in page.blocks or []:
            if block.kind != target_block.kind or block.bbox is None:
                continue
            if _safe_signature(block, page, shots[page_number], records[page_number]) != signature:
                continue
            crop = _crop_block(shots[page_number].image_bytes, page, block)
            peers.append((_clarity(crop), page_number, crop))

    # Require the same text block on at least 3 total pages (2 peers + the
    # target) before trusting repetition as boilerplate, and require the best
    # peer to be at least 5% sharper (Laplacian-edge variance) than the
    # target before it is worth the extra image in the request.
    if len(peers) < 2:
        return None
    target_crop = _crop_block(target_shot.image_bytes, target_page_data, target_block)
    target_clarity = _clarity(target_crop)
    peer_clarity, source_page, peer_image = max(peers)
    if peer_clarity <= target_clarity * 1.05:
        return None
    return PeerEvidence(peer_image, source_page, round(peer_clarity, 4))


def records_by_page(result: Any, run_id: str, registry: Any) -> dict[int, OcrPageRecord]:
    """Resolve base OCR records for the screenshots in a LiteParse result."""
    records: dict[int, OcrPageRecord] = {}
    for shot in result.screenshots:
        record = registry.base_record(run_id, image_digest(shot.image_bytes)[0])
        if record is not None:
            records[shot.page_num] = record
    return records


def _containing_block(page: Any, shot: Any, region: BBox) -> Any | None:
    center_x = (region[0] + region[2]) / 2 / shot.width * page.width
    center_y = (region[1] + region[3]) / 2 / shot.height * page.height
    for block in page.blocks or []:
        box = block.bbox
        if (
            box
            and box.x <= center_x <= box.x + box.width
            and box.y <= center_y <= box.y + box.height
        ):
            return block
    return None


def _safe_signature(block: Any, page: Any, shot: Any, record: OcrPageRecord) -> str:
    """Return a match key, or "" if this block is unsafe to treat as boilerplate.

    Rejects short text, digits, and checkbox glyphs because those are exactly
    the kinds of content that legitimately vary between otherwise-identical
    repeated blocks (form values, page numbers, ticked answers). Two blocks
    only match if their signatures are equal, so this filter is what keeps a
    per-page answer from being mistaken for shared boilerplate.
    """
    text = block.text or "\n".join(block.lines or [])
    signature = normalized_ocr_text(text)
    if len(signature) < 8 or any(char.isdigit() for char in signature):
        return ""
    if any(marker in signature for marker in ("[ ]", "[x]", "[X]", "☐", "☑")):
        return ""
    box = block.bbox
    if box is None:
        return ""
    pixel_box = (
        box.x / page.width * shot.width,
        box.y / page.height * shot.height,
        (box.x + box.width) / page.width * shot.width,
        (box.y + box.height) / page.height * shot.height,
    )
    # Only ever treat machine-printed text as reusable boilerplate; a
    # handwritten or uncertain line inside the block invalidates the match.
    contained = [line for line in record.results if _center_inside(line.bbox, pixel_box)]
    if not contained or any(line.source_kind != "printed" for line in contained):
        return ""
    return signature


def _center_inside(box: list[float], outer: BBox) -> bool:
    center_x = (box[0] + box[2]) / 2
    center_y = (box[1] + box[3]) / 2
    return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]


def _crop_block(image_bytes: bytes, page: Any, block: Any) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        box = block.bbox
        left = max(0, round(box.x / page.width * image.width))
        top = max(0, round(box.y / page.height * image.height))
        right = min(image.width, round((box.x + box.width) / page.width * image.width))
        bottom = min(image.height, round((box.y + box.height) / page.height * image.height))
        output = io.BytesIO()
        image.crop((left, top, right, bottom)).save(output, format="PNG")
    return output.getvalue()


def _clarity(image_bytes: bytes) -> float:
    with Image.open(io.BytesIO(image_bytes)) as image:
        edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
        return float(ImageStat.Stat(edges).var[0])
