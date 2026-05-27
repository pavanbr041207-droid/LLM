"""
services/intent_router.py
Classify user intent before routing to correct pipeline.
No LLM call — pure regex/keyword classification for speed.

Intent categories:
  map_generation        → route to map engine
  dataframe_analysis    → route to dataframe pipeline
  file_analysis         → route to file processor
  image_understanding   → route to vision model
  semantic_search       → route to vector retrieval
  dataset_creation      → route to data extraction
  normal_chat           → route to LLM with context
  reference_previous    → resolve from session state
"""
import re

# ── Map generation intent ────────────────────────────────────────────────────
MAP_PATTERNS = [
    r"generate\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"create\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"make\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"draw\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"show\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"visuali[sz]e\s+(?:this|the|above|that)?",
    r"(?:choropleth|heatmap)",
    r"map\s+(?:this|the|it|above|that)",
    r"show\s+on\s+map",
    r"convert\s+to\s+map",
]

# ── References to previous data ──────────────────────────────────────────────
REFERENCE_PATTERNS = [
    "above data", "previous result", "that data", "this table",
    "use previous", "from above", "above csv", "above table",
    "previous csv", "previous dataset", "latest dataset",
    "those districts", "above districts", "stored data",
]

# ── File/image analysis intent ───────────────────────────────────────────────
IMAGE_PATTERNS = [
    "analyze image", "what is in this image", "describe image",
    "look at this image", "read this image", "ocr", "extract text from",
    "what does this show", "read the chart", "analyze chart",
]
FILE_PATTERNS = [
    "analyze this pdf", "read this pdf", "summarize this document",
    "what is in this file", "analyze this file", "read this excel",
    "analyze this spreadsheet", "extract from document",
]

# ── Semantic search intent ───────────────────────────────────────────────────
SEARCH_PATTERNS = [
    "search for", "find in my documents", "look up", "retrieve",
    "what did we discuss", "what was mentioned", "find previous",
    "recall from project", "search project", "find in files",
]

# ── Dataset creation intent ──────────────────────────────────────────────────
DATASET_PATTERNS = [
    "give me data", "list all districts", "provide data for",
    "show me data", "give data", "list population", "give statistics",
    "provide statistics", "generate dataset", "create dataset",
    "list all", "enumerate", "give all values",
]

# ── Dataframe analysis ────────────────────────────────────────────────────────
ANALYSIS_PATTERNS = [
    "analyze this data", "statistics for", "average of", "maximum",
    "minimum", "correlation", "describe the data", "what is the mean",
    "top 5", "bottom 5", "rank by", "sort by", "filter",
]


def route(user_msg: str, has_file: bool = False,
          has_session_df: bool = False, file_type: str = None) -> dict:
    """
    Classify user intent. Returns:
    {
      intent: str,         # primary intent
      sub_intent: str,     # secondary hint
      confidence: float,
      refs_previous: bool, # references prior data
    }
    """
    msg = user_msg.lower().strip()

    refs_prev = any(ref in msg for ref in REFERENCE_PATTERNS)

    # Priority 1: Image understanding
    if has_file and file_type in ("png","jpg","jpeg","webp","gif"):
        return _r("image_understanding", "vision_model", 0.95, refs_prev)
    if any(p in msg for p in IMAGE_PATTERNS):
        return _r("image_understanding", "vision_model", 0.85, refs_prev)

    # Priority 2: File analysis (PDF, DOCX, XLSX, PPTX)
    if has_file and file_type in ("pdf","docx","xlsx","xls","pptx","txt","md"):
        return _r("file_analysis", file_type, 0.95, refs_prev)
    if any(p in msg for p in FILE_PATTERNS):
        return _r("file_analysis", "document", 0.80, refs_prev)

    # Priority 3: Map generation
    if any(re.search(p, msg) for p in MAP_PATTERNS):
        return _r("map_generation", "choropleth", 0.95, refs_prev)

    # Priority 4: References + has session dataframe → also map if map keywords
    if refs_prev and has_session_df:
        return _r("reference_previous", "session_df", 0.90, True)

    # Priority 5: Semantic search
    if any(p in msg for p in SEARCH_PATTERNS):
        return _r("semantic_search", "vector_retrieval", 0.85, refs_prev)

    # Priority 6: Dataframe analysis
    if any(p in msg for p in ANALYSIS_PATTERNS):
        return _r("dataframe_analysis", "pandas", 0.80, refs_prev)

    # Priority 7: Dataset creation
    if any(p in msg for p in DATASET_PATTERNS):
        return _r("dataset_creation", "llm_extract", 0.75, refs_prev)

    # Default: normal chat
    return _r("normal_chat", "llm", 0.60, refs_prev)


def _r(intent, sub, conf, refs):
    return {
        "intent":        intent,
        "sub_intent":    sub,
        "confidence":    conf,
        "refs_previous": refs,
    }
