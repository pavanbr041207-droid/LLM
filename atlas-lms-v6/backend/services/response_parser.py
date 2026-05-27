"""
services/response_parser.py
Post-process every LLM response:
1. Detect structured data
2. Convert to dataframe
3. Save CSV automatically
4. Update session state
Returns enriched response dict.
"""
from services.structured_data_detector import best_block
from services.dataframe_manager import parse_block, save_dataframe, infer_geo_scope
from services.session_state import store_dataset
from utils.storage import now


def parse_response(response_text: str, session_id: str,
                   user_msg: str = "") -> dict:
    """
    Parse LLM response. Detect structured data and auto-save.
    Returns:
    {
      text: str,               # original response
      has_dataset: bool,
      dataset_meta: dict|None, # if data detected
      dataset_notice: str,     # message to show user
    }
    """
    result = {
        "text":           response_text,
        "has_dataset":    False,
        "dataset_meta":   None,
        "dataset_notice": "",
    }

    try:
        block = best_block(response_text)
        if not block or block["confidence"] < 0.65:
            return result

        df = parse_block(block)
        if df is None or len(df) < 2:
            return result

        # Require at least 2 columns
        if len(df.columns) < 2:
            return result

        geo_info = infer_geo_scope(df)
        label    = _infer_label(user_msg, geo_info)

        # Save to disk
        meta = save_dataframe(df, session_id, label=label)
        meta.update({
            "geo_scope": geo_info["scope"],
            "geo_col":   geo_info["geo_col"],
            "value_col": geo_info["value_col"],
        })

        # Persist to session state
        store_dataset(session_id, meta)

        notice = (
            f"📊 **Dataset detected and saved** — {meta['rows']} rows, "
            f"columns: {', '.join(meta['columns'])}. "
            f"Geography: {geo_info['scope']}. "
            f"You can now say **\"Generate map\"** to visualize this data."
        )

        result["has_dataset"]    = True
        result["dataset_meta"]   = meta
        result["dataset_notice"] = notice

    except Exception:
        pass

    return result


def _infer_label(user_msg: str, geo_info: dict) -> str:
    import re
    msg  = user_msg.lower()
    gcol = geo_info.get("geo_col","")
    vcol = geo_info.get("value_col","") or ""
    scope = geo_info.get("scope","")

    metric = vcol.replace("_"," ").title() if vcol else ""

    # Try to extract from user message
    m = re.search(r"(?:give|show|list|provide)\s+(.+?)(?:\s+(?:for|of|in)|$)", msg)
    if m:
        topic = m.group(1).strip().title()
        return f"{scope} {topic}" if scope else topic

    return f"{scope} {metric} Dataset".strip() if (scope or metric) else f"Dataset {now()}"
