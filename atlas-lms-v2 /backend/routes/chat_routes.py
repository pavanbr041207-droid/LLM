"""
routes/chat_routes.py
Fully automatic map generation pipeline per architecture diagram:
  User request → LLM understanding → Extract topic+geography
  → User uploaded CSV? YES → use it
                       NO  → Query LLM for fresh data
                           → LLM has data? YES → write CSV → run Python → map image
                                          NO  → "Data Not Available" message
No permission prompt. No cached map reuse. Every map = fresh Python execution.
"""
import os, io, csv
from flask import Blueprint, request, jsonify
from utils.llm import (ask_llm, is_map_request, detect_color, clean_title,
                        extract_data_from_llm, infer_topic_geography_metric)
from utils.storage import storage_path, read_json, write_json, now, new_id
from utils.csv_handler import parse_pasted, save_csv

chat_bp       = Blueprint("chat", __name__)
STORAGE       = storage_path()
chat_sessions = {}

def chat_idx():     return os.path.join(STORAGE,"chats","_index.json")
def chat_file(cid): return os.path.join(STORAGE,"chats",f"{cid}.json")
def load_idx():     return read_json(chat_idx(),[])
def save_idx(d):    write_json(chat_idx(),d)

def upsert_idx(sid, name, project_id=None):
    idx = load_idx()
    for c in idx:
        if c["id"]==sid:
            c.update({"name":name,"project_id":project_id,"updated":now()})
            save_idx(idx); return
    idx.insert(0,{"id":sid,"name":name,"project_id":project_id,"created":now(),"updated":now()})
    save_idx(idx)

def get_system(project_id=None):
    if project_id:
        try:
            from routes.project_routes import get_project
            p = get_project(project_id)
            if p and p.get("system_prompt"): return p["system_prompt"]
        except Exception: pass
    return ("You are Atlas AI, a smart AI assistant with geographic map generation capability. "
            "For map requests, you search for data fresh every time and generate maps automatically.")

def _sem_memory():
    try:
        from services.semantic_memory import store_message, store_csv, store_map
        return store_message, store_csv, store_map
    except Exception: return None, None, None

def _meta_gen():
    try:
        from services.metadata_generator import generate_smart_title
        return generate_smart_title
    except Exception: return None


@chat_bp.route("/send", methods=["POST","OPTIONS"])
def send():
    if request.method == "OPTIONS": return jsonify({}), 200

    data         = request.json or {}
    user_msg     = data.get("message","")
    csv_path     = data.get("csv_path")        # only from explicit user upload
    pasted       = data.get("pasted_data")
    session_id   = data.get("session_id","default")
    session_name = data.get("session_name","New Chat")
    project_id   = data.get("project_id")
    sidebar_cmap = data.get("colormap","Blues")

    uploads_dir = os.path.join(STORAGE,"uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    # Handle pasted CSV data
    if pasted:
        csv_path = save_csv(parse_pasted(pasted), uploads_dir)
        _, store_csv_fn, _ = _sem_memory()
        if store_csv_fn:
            try: store_csv_fn(csv_path, session_id, preview=pasted[:300])
            except Exception: pass

    if session_id not in chat_sessions: chat_sessions[session_id] = []
    chat_sessions[session_id].append({"role":"user","content":user_msg})

    store_msg, _, _ = _sem_memory()
    if store_msg:
        try: store_msg(session_id,"user",user_msg,
                       attachments={"csv_path":csv_path} if csv_path else {})
        except Exception: pass

    # ── PIPELINE: MAP REQUEST ────────────────────────────────────────────────
    if is_map_request(user_msg, csv_path):
        colormap = sidebar_cmap or detect_color(user_msg) or "Blues"

        # ── BRANCH A: User uploaded a CSV — use it directly ─────────────────
        if csv_path and os.path.exists(csv_path):
            return _pipeline_from_csv(
                csv_path, user_msg, colormap,
                session_id, session_name, project_id
            )

        # ── BRANCH B: No CSV — check baseline dataset factory first ─────────
        from services.dataset_factory import generate_dataset, DATA_NOT_AVAILABLE
        dataset = generate_dataset(user_msg)

        if dataset.get("status") == "ok":
            # Known topic with baseline data — write fresh CSV and generate map
            return _pipeline_from_dataset(
                dataset, user_msg, colormap,
                session_id, session_name, project_id
            )

        # ── BRANCH C: Unknown topic — query LLM for fresh data ──────────────
        topic, geography, metric_col = infer_topic_geography_metric(user_msg)
        extraction = extract_data_from_llm(topic, geography, metric_col)

        if extraction["status"] == "no_data":
            # LLM has no data — return clear "not available" message
            reply = extraction["reason"]
            _add(session_id,"assistant",reply)
            _flush(session_id, session_name, project_id)
            upsert_idx(session_id, session_name, project_id)
            return jsonify({"reply":reply,"mode":"chat","csv_path":None})

        # LLM returned data — save fresh CSV and generate map
        fresh_csv = _save_extracted_csv(extraction["csv_text"], uploads_dir)
        if not fresh_csv:
            reply = "⚠️ Failed to save extracted data to CSV. Please upload a CSV manually."
            _add(session_id,"assistant",reply)
            _flush(session_id, session_name, project_id)
            return jsonify({"reply":reply,"mode":"chat"})

        title = f"{geography} District {topic.title()} Distribution"
        return _pipeline_from_csv(
            fresh_csv, user_msg, colormap,
            session_id, session_name, project_id,
            title_override=title,
            district_col=extraction.get("district_col"),
            value_col=extraction.get("value_col"),
        )

    # ── NORMAL CHAT ──────────────────────────────────────────────────────────
    system  = get_system(project_id)
    context = ""
    if project_id:
        try:
            from routes.project_routes import build_project_context
            sys_p, ctx = build_project_context(project_id, user_msg,
                                               chat_sessions.get(session_id,[]))
            if sys_p: system  = sys_p
            if ctx:   context = ctx + "\n\n"
        except Exception: pass

    reply = ask_llm(context + user_msg, system_prompt=system)
    _add(session_id,"assistant",reply)
    if store_msg:
        try: store_msg(session_id,"assistant",reply)
        except Exception: pass
    _flush(session_id, session_name, project_id)
    upsert_idx(session_id, session_name, project_id)
    return jsonify({"reply":reply,"mode":"chat","csv_path":csv_path})


# ─── Pipeline helpers ────────────────────────────────────────────────────────

def _save_extracted_csv(csv_text: str, uploads_dir: str) -> str:
    """Save LLM-extracted CSV to a fresh unique file."""
    try:
        os.makedirs(uploads_dir, exist_ok=True)
        fpath = os.path.join(uploads_dir, f"llm_{new_id()}.csv")
        with open(fpath, "w", newline="", encoding="utf-8") as f:
            f.write(csv_text)
        return fpath
    except Exception:
        return None


def _pipeline_from_dataset(dataset: dict, user_msg: str, colormap: str,
                            session_id: str, session_name: str, project_id) -> object:
    """Run map generation from an atlas baseline dataset dict."""
    region       = dataset.get("region", "Karnataka")
    metric_label = dataset.get("dataset_label", "").replace(f"{region} District ", "")
    title        = f"{region} District {metric_label} Distribution".strip()

    return _run_map_pipeline(
        source_csv=None,
        dataset=dataset,
        user_msg=user_msg,
        colormap=colormap,
        title=title,
        subtitle=f"{len(dataset.get('rows',[]))} district records",
        legend_title=metric_label,
        value_col=dataset.get("value_col","value"),
        district_col=dataset.get("district_col","district"),
        session_id=session_id,
        session_name=session_name,
        project_id=project_id,
    )


def _pipeline_from_csv(csv_path: str, user_msg: str, colormap: str,
                        session_id: str, session_name: str, project_id,
                        title_override: str = None,
                        district_col: str = None, value_col: str = None) -> object:
    """Run map generation from a CSV file (uploaded or LLM-extracted)."""
    from utils.map_generator import detect_columns

    if not district_col or not value_col:
        dc, vc, cols = detect_columns(csv_path)
        if not dc or not vc:
            reply = f"⚠️ CSV needs at least 2 columns. Found: {cols}"
            return jsonify({"reply":reply,"mode":"chat","csv_path":None,"clear_csv":True})
        district_col, value_col = dc, vc

    if title_override:
        title = title_override
    else:
        gen_title = _meta_gen()
        if gen_title:
            try:
                meta  = gen_title(csv_path, user_msg, district_col, value_col)
                title = meta.get("title", clean_title(user_msg) or f"{value_col} by {district_col}")
            except Exception:
                title = clean_title(user_msg) or f"{value_col} by {district_col}"
        else:
            title = clean_title(user_msg) or f"{value_col} by {district_col}"

    dataset = {
        "district_col": district_col,
        "value_col":    value_col,
        "source":       "uploaded_csv",
        "rows":         [],
    }
    return _run_map_pipeline(
        source_csv=csv_path,
        dataset=dataset,
        user_msg=user_msg,
        colormap=colormap,
        title=title,
        subtitle="",
        legend_title=value_col,
        value_col=value_col,
        district_col=district_col,
        session_id=session_id,
        session_name=session_name,
        project_id=project_id,
    )


def _run_map_pipeline(source_csv, dataset, user_msg, colormap, title, subtitle,
                       legend_title, value_col, district_col,
                       session_id, session_name, project_id) -> object:
    """
    Core map execution pipeline.
    Always runs fresh Python code. Never serves a cached image.
    """
    from utils.map_generator import generate_map_code, run_map_code
    from utils.execution_state import create_map_request, update_state, finalize_map_state, cleanup_request

    metadata = {
        "title":           title,
        "subtitle":        subtitle or "",
        "legend_title":    legend_title or value_col,
        "dataset_label":   f"{district_col} {value_col}",
        "export_filename": title.lower().replace(" ","_")[:50] + ".png",
    }

    state = create_map_request(session_id, user_msg, dataset, metadata, colormap, source_csv or "")
    maps_dir = os.path.join(STORAGE,"maps")
    os.makedirs(maps_dir, exist_ok=True)
    update_state(state["request_id"], status="executing")

    # Generate fresh Python code and run it
    code = generate_map_code(
        state["temporary_csv"],
        district_col, value_col,
        state["temporary_output"],
        title, colormap,
        subtitle=subtitle or "",
        legend_title=legend_title or value_col,
    )
    success, result = run_map_code(code, maps_dir)

    if success:
        map_id    = new_id()
        finalized = finalize_map_state(state, map_id)

        # Update history index
        hf   = os.path.join(STORAGE,"history","index.json")
        hist = read_json(hf,[])
        hist.insert(0,{
            "id":           map_id,
            "title":        title,
            "colormap":     colormap,
            "district_col": district_col,
            "value_col":    value_col,
            "session_id":   session_id,
            "project_id":   project_id,
            "timestamp":    now(),
            "map_file":     finalized["map_file"],
            "csv_file":     finalized["csv_file"],
            "metadata_file":finalized["json_file"],
        })
        write_json(hf, hist[:100])

        _, _, store_map_fn = _sem_memory()
        if store_map_fn:
            try: store_map_fn(map_id, title, session_id,
                              finalized["history_csv"], colormap, value_col)
            except Exception: pass

        _add(session_id,"assistant","")
        _flush(session_id, session_name, project_id)
        upsert_idx(session_id, session_name, project_id)
        cleanup_request(state["request_id"])
        return jsonify({
            "reply":     "",
            "mode":      "map",
            "map_url":   finalized["map_url"],
            "map_id":    map_id,
            "csv_path":  None,
            "clear_csv": True,
        })

    cleanup_request(state["request_id"])
    reply = f"⚠️ Map generation failed.\n\nError:\n```\n{result[:600]}\n```"
    _add(session_id,"assistant",reply)
    _flush(session_id, session_name, project_id)
    return jsonify({"reply":reply,"mode":"map","error":result,"csv_path":None,"clear_csv":True})


def _add(sid, role, content):
    if sid not in chat_sessions: chat_sessions[sid] = []
    msgs = chat_sessions[sid]
    if not msgs or msgs[-1]["content"] != content:
        msgs.append({"role":role,"content":content})

def _flush(sid, name, project_id=None):
    write_json(chat_file(sid),{"id":sid,"name":name,"project_id":project_id,
                               "timestamp":now(),"messages":chat_sessions.get(sid,[])})


@chat_bp.route("/list",         methods=["GET"])
def list_chats(): return jsonify(load_idx()[:40])

@chat_bp.route("/recent",       methods=["GET"])
def recent_chats():
    return jsonify([c for c in load_idx() if not c.get("project_id")][:30])

@chat_bp.route("/get/<sid>",    methods=["GET"])
def get_chat(sid): return jsonify(read_json(chat_file(sid),{"messages":[]}))

@chat_bp.route("/search",       methods=["GET"])
def search_chats():
    q = request.args.get("q","").lower()
    results = []
    for c in load_idx():
        if q in c.get("name","").lower(): results.append(c); continue
        d = read_json(chat_file(c["id"]),{})
        if q in " ".join(m.get("content","") for m in d.get("messages",[])).lower():
            results.append(c)
    return jsonify(results[:20])

@chat_bp.route("/delete/<sid>", methods=["DELETE","OPTIONS"])
def delete_chat(sid):
    if request.method == "OPTIONS": return jsonify({}), 200
    save_idx([c for c in load_idx() if c["id"]!=sid])
    cf = chat_file(sid)
    if os.path.exists(cf): os.remove(cf)
    if sid in chat_sessions: del chat_sessions[sid]
    return jsonify({"ok":True})
