"""Single source of truth for the local application contract.

Every numeric limit here is enforced somewhere downstream (pipeline.py for
uploads, repair.py for repair budgets, storage.py for history); change a
value here rather than hardcoding a new one at the call site. Next: models.py
for the typed records these limits bound.
"""

import os

APP_HOST = "127.0.0.1"
APP_PORT = int(os.environ.get("LITEPARSE_APP_PORT", "9578"))
# Loopback-only callback the bundled LiteParse instance posts page images to;
# see ocr_bridge.ocr_endpoint, which rejects any non-loopback caller.
OCR_URL = f"http://{APP_HOST}:{APP_PORT}/api/ocr"

MODEL_ID = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
BASE_DPI = 300
REPAIR_DPI = 400
# Below this, repair.py flags a line as a hard-region candidate for a 400-DPI
# reread; it is not a rejection threshold for OCR output itself.
LOW_CONFIDENCE_THRESHOLD = 0.90

MAX_FILES = 20
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_BATCH_BYTES = 500 * 1024 * 1024
MAX_PAGES = 100
MAX_SCHEMA_BYTES = 100 * 1024
MAX_RENDERED_PIXELS = 40_000_000
MAX_REPAIRS_PER_PAGE = 8
MAX_REPAIRS_PER_DOCUMENT = 64
MAX_CHUNK_PAGES = 8
MAX_CHUNK_CHARS = 60_000
MERGE_FAN_IN = 10
OPENAI_TIMEOUT_SECONDS = 180.0

HISTORY_RETENTION_DAYS = 30
MAX_HISTORY_BYTES = 1024**3
HISTORY_LIST_LIMIT = 100
