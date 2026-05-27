"""
services/session_state.py
Per-session stateful memory store.
Stores: latest_dataset, latest_map_id, geo_scope, conversation_summary.
All data isolated per session_id. Project sessions also isolated.
"""
import os
from utils.storage import storage_path, read_json, write_json, now

STORAGE = storage_path()


def _state_path(session_id: str) -> str:
    d = os.path.join(STORAGE, "session_state")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{session_id}.json")


def get_session_state(session_id: str) -> dict:
    return read_json(_state_path(session_id), {})


def set_session_state(session_id: str, updates: dict):
    state = get_session_state(session_id)
    state.update(updates)
    state["updated"] = now()
    write_json(_state_path(session_id), state)


def store_dataset(session_id: str, ds_meta: dict):
    """Store latest dataset metadata in session."""
    set_session_state(session_id, {
        "latest_dataset":   ds_meta,
        "latest_geo_scope": ds_meta.get("geo_scope","unknown"),
        "latest_columns":   ds_meta.get("columns",[]),
        "latest_geo_col":   ds_meta.get("geo_col"),
        "latest_value_col": ds_meta.get("value_col"),
        "has_dataframe":    True,
    })


def store_map(session_id: str, map_id: str, title: str, colormap: str):
    set_session_state(session_id, {
        "latest_map_id":     map_id,
        "latest_map_title":  title,
        "latest_map_cmap":   colormap,
    })


def store_summary(session_id: str, summary: str):
    set_session_state(session_id, {"conversation_summary": summary})


def get_latest_dataset(session_id: str) -> dict | None:
    return get_session_state(session_id).get("latest_dataset")


def get_conversation_summary(session_id: str) -> str:
    return get_session_state(session_id).get("conversation_summary","")


def has_dataframe(session_id: str) -> bool:
    state = get_session_state(session_id)
    if not state.get("has_dataframe"): return False
    ds = state.get("latest_dataset",{})
    return bool(ds.get("csv_path") and os.path.exists(ds.get("csv_path","")))


def clear_session(session_id: str):
    path = _state_path(session_id)
    if os.path.exists(path): os.remove(path)
