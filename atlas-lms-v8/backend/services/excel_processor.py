"""
services/excel_processor.py
Excel/CSV analysis: sheet detection, geo-column inference, auto-dataframe.
"""
import os
import pandas as pd


def process_excel(file_path: str, file_id: str, filename: str,
                  session_id: str = None, project_id: str = None) -> dict:
    """
    Load Excel/CSV, detect geo columns, auto-store as session dataframe.
    Returns metadata for frontend.
    """
    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext == ".csv":
            df = pd.read_csv(file_path)
            sheets = {"Sheet1": df}
        elif ext in (".xlsx", ".xls"):
            xf = pd.ExcelFile(file_path)
            sheets = {name: xf.parse(name) for name in xf.sheet_names}
        else:
            return {"success": False, "error": f"Unsupported format: {ext}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    results = []
    best_df = None
    best_meta = None

    for sheet_name, df in sheets.items():
        if df.empty: continue
        df = _coerce(df)
        geo_col, value_col, geo_scope = _infer_geo(df)
        meta = {
            "sheet":     sheet_name,
            "rows":      len(df),
            "columns":   list(df.columns),
            "geo_col":   geo_col,
            "value_col": value_col,
            "geo_scope": geo_scope,
            "preview":   df.head(5).to_csv(index=False),
        }
        results.append(meta)
        if geo_col and value_col and best_df is None:
            best_df   = df
            best_meta = meta

    # Auto-store best geo sheet in session
    if best_df is not None and session_id:
        try:
            from services.dataframe_manager import save_dataframe
            from services.session_state import store_dataset
            saved = save_dataframe(best_df, session_id,
                                   label=f"{filename} — {best_meta['sheet']}")
            saved.update({
                "geo_scope": best_meta["geo_scope"],
                "geo_col":   best_meta["geo_col"],
                "value_col": best_meta["value_col"],
            })
            store_dataset(session_id, saved)
        except Exception:
            pass

    return {
        "success":   True,
        "file_id":   file_id,
        "filename":  filename,
        "ext":       ext,
        "sheets":    results,
        "has_geo":   best_df is not None,
        "best_sheet":best_meta,
        "auto_stored":best_df is not None,
    }


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        try:
            converted = pd.to_numeric(df[col].astype(str).str.replace(",",""), errors="coerce")
            # Only replace column if at least some values converted successfully
            if converted.notna().sum() > 0:
                df[col] = converted
        except Exception:
            pass
    return df


GEO_WORDS = {"district","state","region","city","taluk","area","location","name","place"}
KA_DISTRICTS_LC = {
    "bagalkot","ballari","belagavi","bengaluru rural","bengaluru urban",
    "bidar","chamarajanagar","chikkaballapur","chikkamagaluru","chitradurga",
    "dakshina kannada","davanagere","dharwad","gadag","hassan","haveri",
    "kalaburagi","kodagu","kolar","koppal","mandya","mysuru","mysore",
    "raichur","ramanagara","shivamogga","tumakuru","udupi","uttara kannada",
    "vijayanagara","vijayapura","yadgir",
}


def _infer_geo(df: pd.DataFrame):
    geo_col = value_col = None
    geo_scope = "unknown"

    for col in df.columns:
        if col.lower() in GEO_WORDS:
            geo_col = col; break
    if not geo_col:
        for col in df.columns:
            if df[col].dtype == object:
                sample = df[col].dropna().astype(str).str.lower().tolist()[:5]
                if any(v in KA_DISTRICTS_LC for v in sample):
                    geo_col = col
                    geo_scope = "Karnataka"
                    break

    if geo_col:
        sample = df[geo_col].dropna().astype(str).str.lower().tolist()[:5]
        if any(v in KA_DISTRICTS_LC for v in sample):
            geo_scope = "Karnataka"
        for col in df.columns:
            if col != geo_col and pd.api.types.is_numeric_dtype(df[col]):
                value_col = col; break

    return geo_col, value_col, geo_scope
