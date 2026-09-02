# OCR page

Image dimensions: {{WIDTH}} by {{HEIGHT}} pixels.
Language hint: {{LANGUAGE}}.

For each visible line, return exact text, `[x1, y1, x2, y2]` pixel bounds, confidence
from 0 to 1, and a polygon only when rotation makes it useful. Return `hard_regions`
for clipped or tiny text, handwriting, dense tables, overlapping marks, blur, or
uncertain reading order. Keep regions tight. Return empty arrays when appropriate.
