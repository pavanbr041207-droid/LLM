"""
services/context_engine.py
Intent detection + context retrieval pipeline.
Sits between user input and LLM call.
"""
import re
from utils.storage import storage_path, read_json
import os

STORAGE = storage_path()

# ── Intent patterns ──
REFERENCE_PATTERNS = [
    r"above csv", r"previous csv", r"last csv", r"that csv",
    r"use csv", r"same csv", r"earlier csv", r"last uploaded",
    r"previous map", r"last map", r"that map", r"above map",
    r"earlier map", r"same map", r"the map", r"previous graph",
    r"second image", r"first image", r"last image",
    r"use above", r"from earlier", r"previous data",
    r"continue previous", r"update.*map", r"change.*color",
    r"convert.*chart", r"same data", r"that data",
]

EXECUTION_PATTERNS = [
    r"generate.*map", r"create.*map", r"make.*map",
    r"generate.*graph", r"create.*graph", r"plot.*",
    r"run.*code", r"execute.*", r"visualize.*",
    r"draw.*chart", r"show.*chart",
]

UPDATE_PATTERNS = [
    r"update.*map", r"change.*color.*map", r"convert.*map",
    r"make.*same.*graph", r"horizontal.*graph",
    r"same.*but", r"previous.*but",
]


def detect_intent(message: str) -> dict:
    """
    Analyze user message and return intent flags.
    Returns dict with: has_reference, needs_execution, is_update, is_map
    """
    msg = message.lower()
    return {
        "has_reference":   any(re.search(p, msg) for p in REFERENCE_PATTERNS),
        "needs_execution": any(re.search(p, msg) for p in EXECUTION_PATTERNS),
        "is_update":       any(re.search(p, msg) for p in UPDATE_PATTERNS),
        "is_map":          _is_map_intent(msg),
        "is_csv_ref":      any(r in msg for r in ["above csv","previous csv","last csv","that csv","same csv","use csv"]),
        "is_map_ref":      any(r in msg for r in ["previous map","last map","that map","above map","same map"]),
        "is_color_change": any(r in msg for r in ["change color","blue","green","red","purple","viridis","plasma"]),
    }


def _is_map_intent(msg: str) -> bool:
    map_kws = ["choropleth","map","district","generate map","create map","literacy","population"]
    return any(k in msg for k in map_kws)


def get_session_context(session_id: str, limit: int = 6) -> str:
    """Load recent messages from session for context injection."""
    cf = os.path.join(STORAGE, "chats", f"{session_id}.json")
    data = read_json(cf, {})
    msgs = data.get("messages", [])[-limit:]
    if not msgs: return ""
    lines = []
    for m in msgs:
        role    = m.get("role","").upper()
        content = m.get("content","")[:300]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def get_last_csv_in_session(session_id: str) -> str:
    """Find the most recent CSV path used in this session from chat history."""
    uploads = os.path.join(STORAGE, "uploads")
    if not os.path.exists(uploads): return None
    # Get all CSV files sorted by modification time
    csvs = sorted(
        [f for f in os.listdir(uploads) if f.endswith(".csv")],
        key=lambda f: os.path.getmtime(os.path.join(uploads, f)),
        reverse=True
    )
    if csvs:
        return os.path.join(uploads, csvs[0])
    return None


def get_last_map_in_session(session_id: str) -> dict:
    """Find the most recent map generated in this or any session."""
    hist_file = os.path.join(STORAGE, "history", "index.json")
    history   = read_json(hist_file, [])
    # Prefer current session, fallback to latest
    for h in history:
        if h.get("session_id") == session_id:
            return h
    return history[0] if history else None


def build_context_prompt(user_msg: str, session_id: str,
                         current_csv: str = None, project_id: str = None) -> dict:
    """
    Full context pipeline:
    1. Detect intent
    2. Resolve references
    3. Retrieve semantic context
    4. Return enriched context dict
    """
    intent  = detect_intent(user_msg)
    result  = {
        "intent":       intent,
        "csv_path":     current_csv,
        "map_meta":     None,
        "extra_context": "",
        "resolved":     False,
    }

    # ── Reference resolution ──
    if intent["has_reference"]:
        try:
            from services.semantic_memory import resolve_reference
            resolved = resolve_reference(user_msg, session_id, current_csv)
            if resolved.get("csv_path") and resolved["csv_path"] != current_csv:
                result["csv_path"]     = resolved["csv_path"]
                result["extra_context"] += resolved.get("context","")
                result["resolved"]     = True
            if resolved.get("map_id"):
                result["map_meta"]     = resolved.get("map_meta")
                result["extra_context"] += resolved.get("context","")
                result["resolved"]     = True
            if resolved.get("semantic_context"):
                result["extra_context"] += "\n" + resolved["semantic_context"]
        except Exception as e:
            pass

    # ── Auto-resolve last CSV if map requested but no CSV given ──
    if intent["is_map"] and not result["csv_path"]:
        last = get_last_csv_in_session(session_id)
        if last:
            result["csv_path"]      = last
            result["extra_context"] += f"\n[Auto-retrieved last CSV: {os.path.basename(last)}]"
            result["resolved"]      = True

    # ── Session history context ──
    hist = get_session_context(session_id, limit=4)
    if hist:
        result["session_history"] = hist

    return result
