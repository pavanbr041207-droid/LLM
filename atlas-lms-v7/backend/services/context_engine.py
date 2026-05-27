"""
services/context_engine.py
Intent detection. Map requests NEVER resolve old CSV/maps.
"""
import re, os
from utils.storage import storage_path, read_json

STORAGE = storage_path()


def detect_intent(message: str, has_csv: bool = False) -> dict:
    msg = message.lower()
    is_map = _is_map_intent(msg)
    return {
        "is_map":             is_map,
        "has_reference":      False,  # DISABLED: never auto-reuse old data for maps
        "needs_execution":    is_map,
        "is_dataset_request": False,
        "force_fresh_map":    is_map,
    }


def _is_map_intent(msg: str) -> bool:
    visual = ["choropleth","map","heatmap","heat map","visualize","plot","choropleat","choroplet"]
    action = ["generate","create","make","draw","render","show"]
    return (
        any(k in msg for k in ["choropleth","choroplet","heat map","heatmap"]) or
        (any(a in msg for a in action) and any(v in msg for v in visual))
    )


def build_context_prompt(user_msg: str, session_id: str,
                         current_csv: str = None, project_id: str = None) -> dict:
    intent = detect_intent(user_msg, has_csv=bool(current_csv))
    return {
        "intent":        intent,
        "csv_path":      current_csv,  # only pass through user-uploaded CSV
        "extra_context": "",
        "resolved":      False,
    }
