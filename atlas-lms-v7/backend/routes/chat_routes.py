"""
routes/chat_routes.py
Fully stateful ChatGPT-like pipeline:
  1. Context manager builds full prompt (history + summary + dataframe)
  2. Map intent? → check session dataframe FIRST → use it directly
  3. References previous data? → use session dataframe
  4. LLM response → response parser auto-detects structured data → saves CSV
  5. Permission gate before any map generation
  6. Project memory isolation
"""
import os
from flask import Blueprint, request, jsonify
from utils.llm import ask_llm, is_map_request, detect_color, clean_title, extract_data_from_llm, infer_topic_geography_metric
from utils.storage import storage_path, read_json, write_json, now, new_id
from utils.csv_handler import parse_pasted, save_csv

chat_bp       = Blueprint("chat", __name__)
STORAGE       = storage_path()
chat_sessions = {}   # in-memory session messages cache

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


@chat_bp.route("/send", methods=["POST","OPTIONS"])
def send():
    if request.method == "OPTIONS": return jsonify({}), 200

    data             = request.json or {}
    user_msg         = data.get("message","")
    csv_path         = data.get("csv_path")
    pasted           = data.get("pasted_data")
    session_id       = data.get("session_id","default")
    session_name     = data.get("session_name","New Chat")
    project_id       = data.get("project_id")
    sidebar_cmap     = data.get("colormap","Blues")
    # File attached with this message (uploaded before send was clicked)
    attached_path    = data.get("attached_file_path")   # server path
    attached_type    = data.get("attached_file_type")   # image|pdf|excel|docx|text|csv
    attached_name    = data.get("attached_file_name","file")

    uploads_dir = os.path.join(STORAGE,"uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    # Handle pasted CSV data
    if pasted:
        csv_path = save_csv(parse_pasted(pasted), uploads_dir)

    # Handle attached CSV — treat as activeCsv
    if attached_path and attached_type == "csv" and os.path.exists(attached_path):
        csv_path = attached_path

    if session_id not in chat_sessions: chat_sessions[session_id] = []
    # Store user message (with file note if attached)
    stored_user_content = user_msg
    if attached_name and attached_type and attached_type != "csv":
        stored_user_content = f"[Attached: {attached_name}]\n{user_msg}" if user_msg else f"[Attached: {attached_name}]"
    chat_sessions[session_id].append({"role":"user","content":stored_user_content})

    # ── Handle non-CSV file attached with message ──────────────────────────
    if attached_path and attached_type and attached_type not in ("csv",) and os.path.exists(attached_path):
        try:
            from services.file_router import route_file
            file_result = route_file(attached_path, new_id(), attached_name,
                                     session_id, project_id, user_msg or "")
            if file_result.get("success"):
                # Build enriched prompt from file result + user message
                file_context = ""
                if attached_type == "image":
                    file_context = file_result.get("text","")
                elif attached_type == "pdf":
                    file_context = file_result.get("preview","") or file_result.get("text","")
                elif attached_type in ("excel","docx","text"):
                    file_context = file_result.get("preview","") or ""

                # If user asked a question, answer it in context of file
                system  = "You are Atlas AI. A file has been shared with you. Answer the user's question based on the file content."
                prompt  = f"File: {attached_name}\nFile content:\n{file_context[:3000]}\n\nUser question: {user_msg}" if user_msg else f"File: {attached_name}\nFile content:\n{file_context[:3000]}\n\nDescribe what you see/read in this file."

                from utils.llm import ask_llm as _ask_llm
                reply = _ask_llm(prompt, system_prompt=system)

                # Auto-detect dataset
                dataset_notice = ""
                dataset_meta   = None
                if file_result.get("has_dataset"):
                    dataset_notice = file_result.get("dataset_notice","")
                    dataset_meta   = file_result.get("dataset_meta")
                    try:
                        from services.session_state import store_dataset
                        if dataset_meta: store_dataset(session_id, dataset_meta)
                    except Exception: pass

                _add(session_id,"assistant",reply)
                _flush(session_id, session_name, project_id)
                upsert_idx(session_id, session_name, project_id)
                resp = {"reply":reply,"mode":"chat","csv_path":None,"clear_csv":True,
                        "clear_attachment":True,"dataset_notice":dataset_notice,
                        "has_dataset":bool(dataset_meta)}
                if dataset_meta: resp["dataset_meta"] = dataset_meta
                return jsonify(resp)
            else:
                # File process failed — tell user clearly
                err = file_result.get("error","Unknown error processing file")
                reply = f"⚠️ Could not process {attached_name}: {err}"
                _add(session_id,"assistant",reply)
                _flush(session_id, session_name, project_id)
                return jsonify({"reply":reply,"mode":"chat","clear_attachment":True})
        except Exception as ex:
            reply = f"⚠️ File processing error: {str(ex)}"
            _add(session_id,"assistant",reply)
            _flush(session_id, session_name, project_id)
            return jsonify({"reply":reply,"mode":"chat","clear_attachment":True})

    # ── STEP 1: Check if user replies YES/NO to pending permission ────────
    try:
        from middleware.execution_guard import check_execution_guard
        from services.permission_manager import get_pending, is_confirmation, is_denial
        pending = get_pending(session_id)
        if pending and pending.get("type") == "map":
            msg_lower = user_msg.lower().strip()
            if is_confirmation(msg_lower) or is_denial(msg_lower):
                guard = check_execution_guard(user_msg, session_id, {"is_map":True}, {})
                if guard.get("denied"):
                    reply = guard["reply"]
                    _add(session_id,"assistant",reply)
                    _flush(session_id, session_name, project_id)
                    upsert_idx(session_id, session_name, project_id)
                    return jsonify({"reply":reply,"mode":"chat","csv_path":None})
                if guard.get("allowed"):
                    orig_msg = pending.get("params",{}).get("user_msg", user_msg)
                    colormap = sidebar_cmap or detect_color(orig_msg) or "Blues"
                    return _route_map(orig_msg, csv_path, colormap,
                                     session_id, session_name, project_id, uploads_dir)
    except Exception:
        pass

    # ── STEP 2: Detect intent ─────────────────────────────────────────────
    from services.map_context_engine import is_map_request as _is_map, references_previous_data
    from services.session_state import has_dataframe

    is_map = _is_map(user_msg) or is_map_request(user_msg, csv_path)
    refs_prev = references_previous_data(user_msg)
    has_df = has_dataframe(session_id)

    # ── STEP 3: If references previous data → load session dataframe ─────
    if refs_prev and has_df and not csv_path:
        try:
            from services.dataframe_manager import load_latest_dataframe
            df, meta = load_latest_dataframe(session_id)
            if df is not None and meta:
                csv_path = meta.get("csv_path")
        except Exception:
            pass

    # ── STEP 4: MAP REQUEST PIPELINE ─────────────────────────────────────
    if is_map:
        colormap = sidebar_cmap or detect_color(user_msg) or "Blues"

        # Permission gate
        try:
            from middleware.execution_guard import check_execution_guard
            guard = check_execution_guard(
                user_msg, session_id,
                {"is_map":True, "needs_execution":True},
                {"user_msg": user_msg}
            )
            if guard.get("denied"):
                reply = guard["reply"]
                _add(session_id,"assistant",reply); _flush(session_id, session_name, project_id)
                upsert_idx(session_id, session_name, project_id)
                return jsonify({"reply":reply,"mode":"chat","csv_path":None,"clear_csv":True})
            if guard.get("waiting"):
                reply = guard["reply"]
                _add(session_id,"assistant",reply); _flush(session_id, session_name, project_id)
                upsert_idx(session_id, session_name, project_id)
                return jsonify({"reply":reply,"mode":"chat","waiting":True,"csv_path":csv_path})
        except Exception:
            pass

        return _route_map(user_msg, csv_path, colormap,
                         session_id, session_name, project_id, uploads_dir)

    # ── STEP 5: NORMAL CHAT with full context + RAG ──────────────────────
    # Intent classification
    try:
        from services.intent_router import route as classify_intent
        from services.session_state import has_dataframe as _has_df
        intent_info = classify_intent(
            user_msg,
            has_file=bool(csv_path),
            has_session_df=_has_df(session_id),
        )
    except Exception:
        intent_info = {"intent": "normal_chat", "refs_previous": False}

    # Semantic retrieval context
    rag_context = ""
    try:
        from services.vector_memory import retrieve_as_context
        rag_context = retrieve_as_context(user_msg, namespace=session_id, top_k=3)
        if project_id:
            proj_ctx = retrieve_as_context(user_msg, namespace=project_id, top_k=2)
            if proj_ctx: rag_context = (rag_context + "\n\n" + proj_ctx).strip()
    except Exception:
        pass

    try:
        from services.context_manager import build_prompt
        system, full_msg = build_prompt(user_msg, session_id, project_id,
                                        extra_system=rag_context)
    except Exception:
        system   = "You are Atlas AI, a smart geographic intelligence assistant."
        full_msg = (rag_context + "\n\n" + user_msg) if rag_context else user_msg

    reply = ask_llm(full_msg, system_prompt=system)

    # ── STEP 6: Parse response — auto-detect structured data ─────────────
    dataset_notice = ""
    dataset_meta   = None
    try:
        from services.response_parser import parse_response
        parsed = parse_response(reply, session_id, user_msg)
        if parsed["has_dataset"]:
            dataset_notice = parsed["dataset_notice"]
            dataset_meta   = parsed["dataset_meta"]
    except Exception:
        pass

    _add(session_id,"assistant",reply)

    # Store both turns in vector memory for future RAG
    try:
        from services.vector_memory import store_conversation_turn
        store_conversation_turn(session_id, "user",      user_msg)
        store_conversation_turn(session_id, "assistant", reply)
        if project_id:
            store_conversation_turn(project_id, "user",      user_msg)
            store_conversation_turn(project_id, "assistant", reply)
    except Exception:
        pass

    _flush(session_id, session_name, project_id)
    upsert_idx(session_id, session_name, project_id)

    response_payload = {
        "reply":          reply,
        "mode":           "chat",
        "csv_path":       csv_path,
        "dataset_notice": dataset_notice,
        "has_dataset":    bool(dataset_meta),
    }
    if dataset_meta:
        response_payload["dataset_meta"] = {
            "rows":      dataset_meta.get("rows",0),
            "columns":   dataset_meta.get("columns",[]),
            "geo_scope": dataset_meta.get("geo_scope",""),
            "label":     dataset_meta.get("label",""),
        }
    return jsonify(response_payload)


def _route_map(user_msg, csv_path, colormap, session_id, session_name, project_id, uploads_dir):
    """
    Route map generation through priority order:
    1. Uploaded CSV (explicit)
    2. Session dataframe (from previous AI output)
    3. Baseline dataset factory (known topics)
    4. LLM data extraction (unknown topics)
    """
    # Priority 1 & 2: CSV from upload or session dataframe
    if csv_path and os.path.exists(csv_path):
        return _pipeline_from_csv(csv_path, user_msg, colormap,
                                   session_id, session_name, project_id)

    # Priority 2: session dataframe (from previous AI response)
    try:
        from services.map_context_engine import get_map_params_from_session
        params = get_map_params_from_session(session_id, user_msg, colormap)
        if params:
            return _pipeline_from_csv(
                params["csv_path"], user_msg, colormap,
                session_id, session_name, project_id,
                title_override=params["title"],
                district_col=params["district_col"],
                value_col=params["value_col"],
            )
    except Exception:
        pass

    # Priority 3: baseline dataset factory
    from services.dataset_factory import generate_dataset, DATA_NOT_AVAILABLE
    dataset = generate_dataset(user_msg)
    if dataset.get("status") == "ok":
        return _pipeline_from_dataset(dataset, user_msg, colormap,
                                       session_id, session_name, project_id)

    # Priority 4: LLM data extraction
    topic, geography, metric_col = infer_topic_geography_metric(user_msg)
    extraction = extract_data_from_llm(topic, geography, metric_col)
    if extraction["status"] == "no_data":
        reply = extraction["reason"]
        _add(session_id,"assistant",reply); _flush(session_id, session_name, project_id)
        upsert_idx(session_id, session_name, project_id)
        return jsonify({"reply":reply,"mode":"chat","csv_path":None})

    fresh_csv = _save_extracted_csv(extraction["csv_text"], uploads_dir)
    if not fresh_csv:
        reply = "⚠️ Failed to save extracted data. Please upload a CSV manually."
        _add(session_id,"assistant",reply); _flush(session_id, session_name, project_id)
        return jsonify({"reply":reply,"mode":"chat"})

    title = f"{geography} District {topic.title()} Distribution"
    return _pipeline_from_csv(
        fresh_csv, user_msg, colormap,
        session_id, session_name, project_id,
        title_override=title,
        district_col=extraction.get("district_col"),
        value_col=extraction.get("value_col"),
    )


def _save_extracted_csv(csv_text, uploads_dir):
    try:
        os.makedirs(uploads_dir, exist_ok=True)
        fpath = os.path.join(uploads_dir, f"llm_{new_id()}.csv")
        with open(fpath,"w",newline="",encoding="utf-8") as f: f.write(csv_text)
        return fpath
    except Exception: return None


def _pipeline_from_dataset(dataset, user_msg, colormap, session_id, session_name, project_id):
    region       = dataset.get("region","Karnataka")
    metric_label = dataset.get("dataset_label","").replace(f"{region} District ","")
    title        = f"{region} District {metric_label} Distribution".strip()
    return _run_map_pipeline(
        source_csv=None, dataset=dataset, user_msg=user_msg, colormap=colormap,
        title=title, subtitle=f"{len(dataset.get('rows',[]))} district records",
        legend_title=metric_label, value_col=dataset.get("value_col","value"),
        district_col=dataset.get("district_col","district"),
        session_id=session_id, session_name=session_name, project_id=project_id,
    )


def _pipeline_from_csv(csv_path, user_msg, colormap, session_id, session_name, project_id,
                        title_override=None, district_col=None, value_col=None):
    from utils.map_generator import detect_columns
    from services.geo_matcher import normalize_dataframe_districts
    import pandas as pd

    if not district_col or not value_col:
        dc, vc, cols = detect_columns(csv_path)
        if not dc or not vc:
            reply = f"⚠️ CSV needs at least 2 columns. Found: {cols}"
            _add(session_id,"assistant",reply); _flush(session_id, session_name, project_id)
            return jsonify({"reply":reply,"mode":"chat","csv_path":None,"clear_csv":True})
        district_col, value_col = dc, vc

    # Apply fuzzy district normalization
    try:
        df = pd.read_csv(csv_path)
        df = normalize_dataframe_districts(df, district_col)
        df.to_csv(csv_path, index=False)
    except Exception: pass

    if title_override:
        title = title_override
    else:
        try:
            from services.metadata_generator import generate_smart_title
            meta  = generate_smart_title(csv_path, user_msg, district_col, value_col)
            title = meta.get("title", clean_title(user_msg) or f"{value_col} by {district_col}")
        except Exception:
            title = clean_title(user_msg) or f"{value_col} by {district_col}"

    dataset = {"district_col":district_col,"value_col":value_col,"source":"uploaded_csv","rows":[]}
    return _run_map_pipeline(
        source_csv=csv_path, dataset=dataset, user_msg=user_msg, colormap=colormap,
        title=title, subtitle="", legend_title=value_col, value_col=value_col,
        district_col=district_col, session_id=session_id,
        session_name=session_name, project_id=project_id,
    )


def _run_map_pipeline(source_csv, dataset, user_msg, colormap, title, subtitle,
                       legend_title, value_col, district_col, session_id, session_name, project_id):
    from utils.map_generator import generate_map_code, run_map_code
    from utils.execution_state import create_map_request, update_state, finalize_map_state, cleanup_request
    from services.session_state import store_map

    metadata = {
        "title":           title,
        "subtitle":        subtitle or "",
        "legend_title":    legend_title or value_col,
        "dataset_label":   f"{district_col} {value_col}",
        "export_filename": title.lower().replace(" ","_")[:50] + ".png",
    }
    state    = create_map_request(session_id, user_msg, dataset, metadata, colormap, source_csv or "")
    maps_dir = os.path.join(STORAGE,"maps")
    os.makedirs(maps_dir, exist_ok=True)
    update_state(state["request_id"], status="executing")

    code    = generate_map_code(
        state["temporary_csv"], district_col, value_col,
        state["temporary_output"], title, colormap,
        subtitle=subtitle or "", legend_title=legend_title or value_col,
    )
    success, result = run_map_code(code, maps_dir)

    if success:
        map_id    = new_id()
        finalized = finalize_map_state(state, map_id)
        store_map(session_id, map_id, title, colormap)

        hf   = os.path.join(STORAGE,"history","index.json")
        hist = read_json(hf,[])
        hist.insert(0,{
            "id":map_id,"title":title,"colormap":colormap,
            "district_col":district_col,"value_col":value_col,
            "session_id":session_id,"project_id":project_id,
            "timestamp":now(),"map_file":finalized["map_file"],
            "csv_file":finalized["csv_file"],"metadata_file":finalized["json_file"],
        })
        write_json(hf, hist[:100])

        # IMPORTANT: store map URL in message content with __MAP__ prefix
        # This allows loadChat() to re-render the map when chat is revisited
        map_url = finalized["map_url"]
        map_msg = f"__MAP__{map_id}::{map_url}"
        _add(session_id,"assistant", map_msg)
        _flush(session_id, session_name, project_id)
        upsert_idx(session_id, session_name, project_id)
        cleanup_request(state["request_id"])
        return jsonify({"reply":"","mode":"map","map_url":map_url,
                        "map_id":map_id,"csv_path":None,"clear_csv":True})

    cleanup_request(state["request_id"])
    reply = f"⚠️ Map generation failed.\n\nError:\n```\n{result[:600]}\n```"
    _add(session_id,"assistant",reply); _flush(session_id, session_name, project_id)
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
    try:
        from services.session_state import clear_session
        clear_session(sid)
    except Exception: pass
    return jsonify({"ok":True})

@chat_bp.route("/session-state/<sid>", methods=["GET"])
def session_state(sid):
    """Frontend polls this to show active dataframe badge."""
    try:
        from services.session_state import get_session_state
        state = get_session_state(sid)
        ds    = state.get("latest_dataset",{})
        return jsonify({
            "has_dataframe":  state.get("has_dataframe", False),
            "dataset_label":  ds.get("label",""),
            "dataset_rows":   ds.get("rows",0),
            "dataset_columns":ds.get("columns",[]),
            "geo_scope":      ds.get("geo_scope",""),
        })
    except Exception:
        return jsonify({"has_dataframe":False})
