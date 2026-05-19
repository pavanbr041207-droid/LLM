"""
services/metadata_generator.py
Generates intelligent titles for maps/charts from CSV structure.
Never copies user prompt directly.
"""
import os, re
import pandas as pd
from utils.llm import ask_llm


# ── Chart type detection ──
def detect_chart_type(df: pd.DataFrame, user_msg: str = "") -> str:
    """Infer best chart type from data structure."""
    cols     = list(df.columns)
    msg      = user_msg.lower()
    num_cols = df.select_dtypes(include="number").columns.tolist()
    str_cols = df.select_dtypes(include="object").columns.tolist()

    # Explicit override from user message
    if "pie" in msg:      return "pie"
    if "bar" in msg:      return "bar"
    if "line" in msg:     return "line"
    if "scatter" in msg:  return "scatter"
    if any(k in msg for k in ["map","choropleth","district","state","region"]):
        return "choropleth"

    # Infer from data
    if len(str_cols) >= 1 and len(num_cols) == 1:
        if len(df) <= 10:  return "pie"
        return "bar"
    if len(num_cols) >= 2:
        return "scatter"
    # Check for time-series
    for col in str_cols:
        if any(t in col.lower() for t in ["year","date","month","time","period"]):
            return "line"
    return "bar"


def detect_geography(df: pd.DataFrame) -> bool:
    """Detect if data is geographic (district/state level)."""
    geo_keywords = ["district","state","taluk","city","village","region",
                    "country","zone","block","mandal","province"]
    for col in df.columns:
        if any(k in col.lower() for k in geo_keywords):
            return True
    # Check values
    for col in df.select_dtypes(include="object").columns:
        sample = " ".join(df[col].astype(str).head(5).tolist()).lower()
        if any(k in sample for k in ["bangalore","mysore","karnataka","india","delhi"]):
            return True
    return False


def generate_smart_title(csv_path: str, user_msg: str = "",
                          district_col: str = "", value_col: str = "") -> dict:
    """
    Generate professional title, axis labels, and subtitle.
    Returns: {title, x_label, y_label, subtitle, chart_type}
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return _fallback_title(value_col, district_col)

    chart_type = detect_chart_type(df, user_msg)
    is_geo     = detect_geography(df)

    # Determine column roles
    num_cols = df.select_dtypes(include="number").columns.tolist()
    str_cols = df.select_dtypes(include="object").columns.tolist()

    x_col = district_col or (str_cols[0] if str_cols else df.columns[0])
    y_col = value_col    or (num_cols[0] if num_cols else (df.columns[1] if len(df.columns) > 1 else df.columns[0]))

    # Clean column names for display
    x_label = _clean_col(x_col)
    y_label = _clean_col(y_col)

    # Ask LLM for a professional title (short prompt, fast)
    prompt = (
        f"Generate a professional, concise chart title (max 8 words) for a "
        f"{'choropleth map' if is_geo else chart_type + ' chart'} showing "
        f"'{y_label}' by '{x_label}'. "
        f"Do NOT copy the user's exact words. Return ONLY the title, nothing else."
    )
    raw_title = ask_llm(prompt).strip().strip('"\'').strip()

    # Validate — if LLM gave something reasonable use it, else fallback
    if raw_title and 3 <= len(raw_title) <= 80 and "\n" not in raw_title:
        title = raw_title
    else:
        title = _fallback_title_str(y_label, x_label, is_geo)

    # Subtitle from data stats
    try:
        vmin = df[y_col].min()
        vmax = df[y_col].max()
        subtitle = f"Range: {_fmt_num(vmin)} — {_fmt_num(vmax)} · {len(df)} records"
    except Exception:
        subtitle = f"{len(df)} records"

    return {
        "title":      title,
        "x_label":    x_label,
        "y_label":    y_label,
        "subtitle":   subtitle,
        "chart_type": chart_type,
        "is_geo":     is_geo,
    }


def _clean_col(col: str) -> str:
    """Convert column name to readable label."""
    col = str(col).replace("_"," ").replace("-"," ")
    return col.title().strip()


def _fmt_num(val) -> str:
    try:
        v = float(val)
        if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
        if v >= 1_000:     return f"{v/1_000:.1f}K"
        return f"{v:.1f}"
    except Exception:
        return str(val)


def _fallback_title_str(y_label: str, x_label: str, is_geo: bool) -> str:
    if is_geo:
        return f"{y_label} Distribution by {x_label}"
    return f"{y_label} by {x_label}"


def _fallback_title(value_col: str, district_col: str) -> dict:
    y = _clean_col(value_col or "Value")
    x = _clean_col(district_col or "Category")
    return {
        "title":      f"{y} Distribution by {x}",
        "x_label":    x,
        "y_label":    y,
        "subtitle":   "",
        "chart_type": "choropleth",
        "is_geo":     True,
    }
