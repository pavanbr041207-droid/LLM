"""
utils/execution_state.py — per-request map execution state.
force_regenerate=True always. No cached map ever served.
Each map gets unique ID + filename → browser never caches old image.
"""
import csv, os, re, shutil
from datetime import datetime
from utils.storage import storage_path, read_json, write_json, new_id, now

STORAGE  = storage_path()
EXEC_DIR = os.path.join(STORAGE, "execution_state")
HIST_DIR = os.path.join(STORAGE, "history")
MAPS_DIR = os.path.join(STORAGE, "maps")


def safe_slug(text: str, fallback: str = "choropleth_map") -> str:
    raw = re.sub(r"[^\w\s-]", "", str(text or "")).strip().lower()
    raw = re.sub(r"[\s-]+", "_", raw)
    return (raw or fallback)[:70]


def request_dir(request_id: str) -> str:
    return os.path.join(EXEC_DIR, request_id)


def create_map_request(session_id: str, user_msg: str, dataset: dict,
                       metadata: dict, colormap: str, source_csv: str = "") -> dict:
    """Always creates a NEW request. Never reuses previous state."""
    request_id = new_id()
    dataset_id = new_id()
    rdir = request_dir(request_id)
    os.makedirs(rdir, exist_ok=True)

    csv_path = os.path.join(rdir, f"{dataset_id}.csv")
    if source_csv and os.path.exists(source_csv):
        shutil.copy2(source_csv, csv_path)
    else:
        rows    = dataset.get("rows", [])
        headers = (list(rows[0].keys()) if rows else
                   [dataset.get("district_col","district"), dataset.get("value_col","value")])
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    output_png = os.path.join(
        rdir,
        f"{safe_slug(metadata.get('export_filename') or metadata.get('title'))}.png"
    )
    state = {
        "request_id":       request_id,
        "dataset_id":       dataset_id,
        "session_id":       session_id,
        "user_prompt":      user_msg,
        "temporary_csv":    csv_path,
        "temporary_output": output_png,
        "source_csv":       source_csv or "",
        "force_regenerate": True,
        "dataset": {
            "district_col":  dataset.get("district_col", "district"),
            "value_col":     dataset.get("value_col", "value"),
            "dataset_label": metadata.get("dataset_label") or dataset.get("dataset_label", ""),
            "source":        dataset.get("source", "uploaded_csv"),
        },
        "metadata":  metadata,
        "colormap":  colormap,
        "timestamp": datetime.now().isoformat(),
        "status":    "ready",
    }
    write_json(os.path.join(rdir, "state.json"), state)
    return state


def load_state(request_id: str) -> dict:
    return read_json(os.path.join(request_dir(request_id), "state.json"), {})


def update_state(request_id: str, **updates) -> dict:
    state = load_state(request_id)
    state.update(updates)
    write_json(os.path.join(request_dir(request_id), "state.json"), state)
    return state


def finalize_map_state(state: dict, map_id: str) -> dict:
    os.makedirs(HIST_DIR, exist_ok=True)
    os.makedirs(MAPS_DIR, exist_ok=True)
    metadata    = state.get("metadata", {})
    export_base = safe_slug(metadata.get("export_filename") or metadata.get("title"))

    hist_png  = os.path.join(HIST_DIR, f"{map_id}.png")
    hist_csv  = os.path.join(HIST_DIR, f"{map_id}.csv")
    hist_json = os.path.join(HIST_DIR, f"{map_id}.json")
    # Unique filename per map_id prevents any browser caching of old image
    map_copy  = os.path.join(MAPS_DIR, f"{map_id}_{export_base}.png")

    shutil.copy2(state["temporary_output"], hist_png)
    shutil.copy2(state["temporary_output"], map_copy)
    shutil.copy2(state["temporary_csv"],    hist_csv)

    snapshot = {
        "request_id":  state["request_id"],
        "dataset_id":  state["dataset_id"],
        "map_id":      map_id,
        "session_id":  state["session_id"],
        "user_prompt": state.get("user_prompt", ""),
        "dataset":     state.get("dataset", {}),
        "colormap":    state.get("colormap", ""),
        "timestamp":   now(),
    }
    write_json(hist_json, snapshot)

    map_url = f"/storage/maps/{os.path.basename(map_copy)}?nocache={map_id}"
    return {
        "snapshot":    snapshot,
        "history_png": hist_png,
        "history_csv": hist_csv,
        "map_copy":    map_copy,
        "map_file":    f"{map_id}.png",
        "csv_file":    f"{map_id}.csv",
        "json_file":   f"{map_id}.json",
        "map_url":     map_url,
    }


def cleanup_request(request_id: str):
    rdir = request_dir(request_id)
    if os.path.exists(rdir):
        shutil.rmtree(rdir, ignore_errors=True)


def latest_map_for_session(session_id: str) -> dict:
    """For metadata/CSV show only. Never used to reuse a map image."""
    hist = read_json(os.path.join(HIST_DIR, "index.json"), [])
    for entry in hist:
        if entry.get("session_id") == session_id:
            return entry
    return hist[0] if hist else {}


def read_map_csv(map_id: str) -> str:
    if not map_id: return ""
    path = os.path.join(HIST_DIR, f"{map_id}.csv")
    if not os.path.exists(path): return ""
    with open(path, encoding="utf-8") as f: return f.read()
