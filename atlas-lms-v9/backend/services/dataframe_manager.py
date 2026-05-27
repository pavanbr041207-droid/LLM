"""
services/dataframe_manager.py
Convert detected structured blocks → pandas dataframe → CSV file.
Auto-infer geo scope and column roles.
"""
import io, re, json, os, csv
import pandas as pd
from utils.storage import storage_path, new_id, now

STORAGE = storage_path()

GEO_COLS   = {"district","state","region","city","taluk","mandal","area","location","place","name"}
VALUE_TYPES = {"int64","float64"}

KARNATAKA_DISTRICTS_LC = {
    "bagalkot","ballari","belagavi","bengaluru rural","bengaluru urban","bidar",
    "chamarajanagar","chikkaballapur","chikkamagaluru","chitradurga","dakshina kannada",
    "davanagere","dharwad","gadag","hassan","haveri","kalaburagi","kodagu","kolar",
    "koppal","mandya","mysuru","mysore","raichur","ramanagara","shivamogga","tumakuru",
    "udupi","uttara kannada","vijayanagara","vijayapura","yadgir",
}


def parse_block(block: dict) -> pd.DataFrame | None:
    """Convert a detected block to a pandas DataFrame."""
    t   = block["type"]
    raw = block["raw"]
    try:
        if t == "markdown_table":
            return _parse_md_table(raw)
        elif t in ("csv_block", "csv_plain"):
            return _parse_csv(raw)
        elif t == "json_array":
            return _parse_json(raw)
        elif t == "district_value_pairs":
            return _parse_pairs(block.get("pairs", []))
    except Exception:
        return None
    return None


def _parse_md_table(raw: str) -> pd.DataFrame:
    lines = [l.strip() for l in raw.splitlines() if l.strip() and not re.match(r'^\|[-| :]+\|$', l.strip())]
    headers = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    df = pd.DataFrame(rows)
    return _coerce_numerics(df)


def _parse_csv(raw: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(raw))
    return _coerce_numerics(df)


def _parse_json(raw: str) -> pd.DataFrame:
    data = json.loads(raw)
    df   = pd.DataFrame(data)
    return _coerce_numerics(df)


def _parse_pairs(pairs: list) -> pd.DataFrame:
    rows = [{"district": d, "value": float(v.replace(",",""))} for d,v in pairs]
    return pd.DataFrame(rows)


def _coerce_numerics(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        try:
            converted = pd.to_numeric(df[col].astype(str).str.replace(",",""), errors="coerce")
            if converted.notna().sum() > 0:
                df[col] = converted
        except Exception:
            pass
    return df


def infer_geo_scope(df: pd.DataFrame) -> dict:
    """Infer geography type and scope from dataframe."""
    cols_lc = [c.lower() for c in df.columns]
    geo_col = None
    for col in df.columns:
        if col.lower() in GEO_COLS:
            geo_col = col
            break
    if not geo_col:
        geo_col = df.columns[0]

    scope = "unknown"
    if geo_col:
        sample_vals = df[geo_col].dropna().astype(str).str.lower().tolist()[:5]
        matches = sum(1 for v in sample_vals if v in KARNATAKA_DISTRICTS_LC)
        if matches >= 1:
            scope = "Karnataka"

    value_col = None
    for col in df.columns:
        if col != geo_col and pd.api.types.is_numeric_dtype(df[col]):
            value_col = col
            break

    return {
        "geo_col":   geo_col,
        "value_col": value_col,
        "scope":     scope,
        "row_count": len(df),
        "columns":   list(df.columns),
    }


def save_dataframe(df: pd.DataFrame, session_id: str, label: str = "") -> dict:
    """
    Save dataframe as CSV in storage/datasets/{session_id}/.
    Returns metadata dict with path, columns, geo info.
    """
    ds_dir = os.path.join(STORAGE, "datasets", session_id)
    os.makedirs(ds_dir, exist_ok=True)

    file_id = new_id()
    csv_path = os.path.join(ds_dir, f"{file_id}.csv")
    df.to_csv(csv_path, index=False)

    geo_info = infer_geo_scope(df)
    meta = {
        "id":        file_id,
        "csv_path":  csv_path,
        "label":     label or f"Dataset {now()}",
        "columns":   list(df.columns),
        "rows":      len(df),
        "geo_col":   geo_info["geo_col"],
        "value_col": geo_info["value_col"],
        "geo_scope": geo_info["scope"],
        "timestamp": now(),
    }
    return meta


def load_latest_dataframe(session_id: str) -> tuple[pd.DataFrame | None, dict | None]:
    """Load most recent saved dataframe for session."""
    from services.session_state import get_session_state
    state = get_session_state(session_id)
    ds_meta = state.get("latest_dataset")
    if not ds_meta:
        return None, None
    csv_path = ds_meta.get("csv_path","")
    if not csv_path or not os.path.exists(csv_path):
        return None, None
    try:
        df = pd.read_csv(csv_path)
        return df, ds_meta
    except Exception:
        return None, None
