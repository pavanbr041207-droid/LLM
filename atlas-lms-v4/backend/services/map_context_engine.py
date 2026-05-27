"""
services/map_context_engine.py
Intelligent map routing:
- Detects map intent in user message
- Checks session for stored dataframe FIRST
- If dataframe exists → use it directly (no LLM re-generation)
- If not → fall back to LLM data extraction or baseline
"""
import re

MAP_INTENTS = [
    r"generate\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"create\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"make\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"draw\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"show\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"plot\s+(?:a\s+)?(?:choropleth|map|heatmap)",
    r"visuali[sz]e\s+(?:this|the|above|that)?\s*(?:data|dataset|table)?",
    r"convert\s+(?:this|the|above|that)?\s*(?:data|table|result)\s+to\s+(?:a\s+)?map",
    r"(?:choropleth|heatmap)",
    r"show\s+(?:on\s+)?(?:a\s+)?map",
    r"map\s+(?:this|the|above|that|it)",
    r"generate\s+map",
    r"create\s+map",
]

REFERENCE_INTENTS = [
    "above data", "those districts", "previous result", "use that",
    "that data", "previous data", "above table", "previous table",
    "use previous", "above csv", "that csv", "use above",
    "previous csv", "previous dataset", "latest dataset",
    "stored data", "saved data",
]


def is_map_request(user_msg: str) -> bool:
    msg = user_msg.lower()
    return any(re.search(p, msg) for p in MAP_INTENTS)


def references_previous_data(user_msg: str) -> bool:
    msg = user_msg.lower()
    return any(ref in msg for ref in REFERENCE_INTENTS)


def should_use_session_dataframe(user_msg: str, session_id: str) -> bool:
    """
    Returns True if:
    1. User is making a map request AND session has a dataframe, OR
    2. User references previous data AND session has a dataframe
    """
    try:
        from services.session_state import has_dataframe
        if not has_dataframe(session_id): return False
        return is_map_request(user_msg) or references_previous_data(user_msg)
    except Exception:
        return False


def get_map_params_from_session(session_id: str, user_msg: str, colormap: str = "Blues") -> dict | None:
    """
    Build map generation params directly from session dataframe.
    Returns params dict ready for _run_map_pipeline, or None if not available.
    """
    try:
        from services.dataframe_manager import load_latest_dataframe
        from services.geo_matcher import normalize_dataframe_districts

        df, meta = load_latest_dataframe(session_id)
        if df is None or meta is None: return None

        district_col = meta.get("geo_col")
        value_col    = meta.get("value_col")
        if not district_col or not value_col: return None

        # Normalize district names via fuzzy matching
        df = normalize_dataframe_districts(df, district_col)

        # Save normalized version back
        import os
        norm_path = meta["csv_path"].replace(".csv", "_normalized.csv")
        df.to_csv(norm_path, index=False)

        geo_scope = meta.get("geo_scope", "Karnataka")
        vcol_label = value_col.replace("_"," ").title()
        title     = _infer_title(user_msg, geo_scope, vcol_label)

        return {
            "csv_path":    norm_path,
            "district_col": district_col,
            "value_col":   value_col,
            "title":       title,
            "colormap":    colormap,
            "source":      "session_dataframe",
            "meta":        meta,
        }
    except Exception:
        return None


def _infer_title(user_msg: str, geo_scope: str, metric: str) -> str:
    msg = user_msg.lower()
    # Try to extract explicit title from user message
    m = re.search(r"(?:for|of)\s+(.+?)(?:\s+(?:in|of|district)|$)", msg)
    if m:
        topic = m.group(1).strip().title()
        return f"{geo_scope} District {topic} Distribution"
    return f"{geo_scope} District {metric} Distribution"
