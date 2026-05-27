"""
services/structured_data_detector.py
Detect structured data (CSV, markdown tables, JSON arrays, district-value pairs)
in any LLM response text. Returns detected blocks with type and raw content.
"""
import re, json


# ── Detection patterns ──────────────────────────────────────────────────────

# Markdown table: | col1 | col2 |
_MD_TABLE = re.compile(
    r'(\|[^\n]+\|\n\|[-| :]+\|\n(?:\|[^\n]+\|\n?)+)',
    re.MULTILINE
)

# CSV block: lines with commas (at least 2 rows, consistent column count)
_CSV_LINE = re.compile(r'^[A-Za-z\s\.\-]+,[0-9\.]+\s*$', re.MULTILINE)

# JSON array of objects
_JSON_ARRAY = re.compile(r'(\[\s*\{.*?\}\s*\])', re.DOTALL)

# Explicit ```csv ... ``` code block
_CSV_FENCE = re.compile(r'```(?:csv)?\n(.*?)```', re.DOTALL)

# District-value pairs: "Mysore: 3000000" or "Mysore — 3000000"
_DIST_VALUE = re.compile(
    r'\b([A-Z][a-zA-Z\s\-\.]{2,25})\s*[:\-–—]\s*([0-9][0-9,\.]+)\b'
)

# Geography keywords that hint at geo data
GEO_KEYWORDS = [
    "district","state","taluk","mandal","block","village","city",
    "karnataka","india","bengaluru","mysore","hubli","dharwad","population",
    "rainfall","literacy","gdp","crime","forest","unemployment",
]


def detect(text: str) -> list:
    """
    Scan text for structured data. Returns list of detected blocks:
    [ { type, raw, confidence, rows_hint } ]
    """
    results = []

    # 1. Markdown table
    for m in _MD_TABLE.finditer(text):
        results.append({
            "type":       "markdown_table",
            "raw":        m.group(0).strip(),
            "confidence": 0.95,
            "rows_hint":  m.group(0).count("\n") - 1,
        })

    # 2. Fenced CSV block
    for m in _CSV_FENCE.finditer(text):
        inner = m.group(1).strip()
        rows  = [l for l in inner.splitlines() if l.strip()]
        if len(rows) >= 2:
            results.append({
                "type":       "csv_block",
                "raw":        inner,
                "confidence": 0.98,
                "rows_hint":  len(rows) - 1,
            })

    # 3. Plain CSV lines (if no fenced block found)
    if not any(r["type"] == "csv_block" for r in results):
        csv_lines = _CSV_LINE.findall(text)
        if len(csv_lines) >= 3:
            results.append({
                "type":       "csv_plain",
                "raw":        "\n".join(csv_lines),
                "confidence": 0.80,
                "rows_hint":  len(csv_lines),
            })

    # 4. JSON array
    for m in _JSON_ARRAY.finditer(text):
        raw = m.group(1).strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and len(parsed) >= 2 and isinstance(parsed[0], dict):
                results.append({
                    "type":       "json_array",
                    "raw":        raw,
                    "confidence": 0.92,
                    "rows_hint":  len(parsed),
                })
        except json.JSONDecodeError:
            pass

    # 5. District-value pairs (fallback for unstructured lists)
    if not results:
        pairs = _DIST_VALUE.findall(text)
        if len(pairs) >= 5:
            # Check for geo keywords in text
            has_geo = any(kw in text.lower() for kw in GEO_KEYWORDS)
            results.append({
                "type":       "district_value_pairs",
                "raw":        "\n".join(f"{d},{v.replace(',','')}" for d,v in pairs),
                "confidence": 0.70 if has_geo else 0.50,
                "rows_hint":  len(pairs),
                "pairs":      pairs,
            })

    # Sort by confidence desc
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results


def has_structured_data(text: str) -> bool:
    return len(detect(text)) > 0


def best_block(text: str) -> dict | None:
    blocks = detect(text)
    return blocks[0] if blocks else None
