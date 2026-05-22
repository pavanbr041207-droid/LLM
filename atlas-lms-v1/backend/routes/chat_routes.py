"""
routes/chat_routes.py
Anti-hallucination upgrade: MASTER_MAP_PROMPT injected for all map requests.
Dataset signature validation before every map generation.
Context isolation: previous dataset never leaks into new requests.
All existing API contracts preserved.
"""
import os
from flask import Blueprint, request, jsonify
from utils.llm import ask_llm, is_map_request, detect_color, clean_title, MASTER_MAP_PROMPT
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
    return ("You are Atlas AI, a smart friendly AI assistant with semantic memory. "
            "Help with studying, coding, data analysis, and questions. "
            "You can reference previous conversations, CSVs, and maps from memory.")

def _sem_memory():
    try:
        from services.semantic_memory import store_message, store_csv, store_map
        return store_message, store_csv, store_map
    except Exception: return None, None, None

def _ctx_engine():
    try:
        from services.context_engine import build_context_prompt
        return build_context_prompt
    except Exception: return None

def _guard():
    try:
        from middleware.execution_guard import check_execution_guard
        return check_execution_guard
    except Exception: return None

def _meta_gen():
    try:
        from services.metadata_generator import generate_smart_title
        return generate_smart_title
    except Exception: return None

def _retrieval():
    try:
        from services.retrieval_engine import retrieve_csv_context, retrieve_relevant_context
        return retrieve_csv_context, retrieve_relevant_context
    except Exception: return None, None


@chat_bp.route("/send", methods=["POST","OPTIONS"])
def send():
    if request.method == "OPTIONS": return jsonify({}), 200

    data         = request.json or {}
    user_msg     = data.get("message","")
    csv_path     = data.get("csv_path")
    pasted       = data.get("pasted_data")
    session_id   = data.get("session_id","default")
    session_name = data.get("session_name","New Chat")
    project_id   = data.get("project_id")
    sidebar_cmap = data.get("colormap")

    uploads_dir = os.path.join(STORAGE,"uploads")
    os.makedirs(uploads_dir, exist_ok=True)

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

    guard_fn = _guard()
    if guard_fn:
        g = guard_fn(user_msg, session_id, {}, {})
        if g.get("denied"):
            params = g.get("params", {})
            if params.get("request_id"):
                try:
                    from utils.execution_state import cleanup_request
                    cleanup_request(params["request_id"])
                except Exception: pass
            reply = g.get("reply","Map generation was cancelled because permission was denied.")
            _add(session_id,"assistant",reply)
            _flush(session_id, session_name, project_id)
            return jsonify({"reply":reply,"mode":"chat","csv_path":None,"clear_csv":True})
        if g.get("allowed") and g.get("params"):
            params = g["params"]
            return _gen_map(params, params.get("colormap") or sidebar_cmap or "Blues",
                            session_id, session_name, project_id)
        if g.get("waiting"):
            reply = g.get("reply","This request requires backend map generation.\nAllow execution?\n[YES] [NO]")
            _add(session_id,"assistant",reply)
            _flush(session_id, session_name, project_id)
            return jsonify({"reply":reply,"mode":"chat","waiting":True,"csv_path":csv_path})

    # Context engine — resolve references like "above csv", "previous map"
    context_result = None
    build_ctx = _ctx_engine()
    if build_ctx:
        try:
            context_result = build_ctx(user_msg, session_id, csv_path, project_id)
            if context_result.get("resolved") and context_result.get("csv_path"):
                csv_path = context_result["csv_path"]
        except Exception: pass

    if _is_csv_snapshot_request(user_msg):
        reply = _csv_snapshot_reply(user_msg, session_id)
        _add(session_id,"assistant",reply)
        _flush(session_id, session_name, project_id)
        return jsonify({"reply":reply,"mode":"chat","csv_path":None,"clear_csv":True})

    intent = {}
    if context_result:
        intent = context_result.get("intent",{})
    elif is_map_request(user_msg, csv_path):
        intent = {"needs_execution":True,"is_map":True,"has_reference":False}

    if is_map_request(user_msg, csv_path) or intent.get("is_map"):
        action_params, err = _prepare_map_request(
            user_msg, csv_path, session_id, sidebar_cmap or detect_color(user_msg) or "Blues"
        )
        if err:
            _add(session_id,"assistant",err)
            _flush(session_id, session_name, project_id)
            return jsonify({"reply":err,"mode":"chat","csv_path":None,"clear_csv":True})

        # ── MASTER PROMPT: validate dataset signature before allowing generation ──
        sig = action_params.get("dataset_signature")
        if sig:
            try:
                from services.dataset_factory import validate_dataset_signature
                validation = validate_dataset_signature(sig, user_msg)
                if not validation["valid"]:
                    err_msg = f"⚠️ Dataset validation failed.\n\n{validation['reason']}\n\nPlease upload the correct CSV or clarify your request."
                    _add(session_id,"assistant",err_msg)
                    _flush(session_id, session_name, project_id)
                    return jsonify({"reply":err_msg,"mode":"chat","csv_path":None,"clear_csv":True})
            except Exception: pass

        intent = {"needs_execution":True,"execution_intent":True,"is_map":True}
        g = guard_fn(user_msg, session_id, intent, action_params) if guard_fn else {"allowed": True}
        if not g["allowed"]:
            reply = g.get("reply","")
            if reply:
                _add(session_id,"assistant",reply)
                _flush(session_id, session_name, project_id)
                return jsonify({"reply":reply,"mode":"chat","waiting":g.get("waiting",False),
                                "csv_path":csv_path})
        return _gen_map(action_params, action_params.get("colormap") or "Blues",
                        session_id, session_name, project_id)

    if intent.get("is_dataset_request"):
        reply = _dataset_reply(user_msg)
        _add(session_id,"assistant",reply)
        _flush(session_id, session_name, project_id)
        upsert_idx(session_id, session_name, project_id)
        return jsonify({"reply":reply,"mode":"chat","csv_path":csv_path})

    # Normal chat with full context injection
    system  = get_system(project_id)
    context = ""

    # Project context
    if project_id:
        try:
            from routes.project_routes import build_project_context
            sys_p, ctx = build_project_context(project_id, user_msg,
                                               chat_sessions.get(session_id,[]))
            if sys_p: system  = sys_p
            if ctx:   context = ctx + "\n\n"
        except Exception: pass

    # Semantic retrieval context
    _, retrieve_rel = _retrieval()
    if retrieve_rel:
        try:
            sem_ctx = retrieve_rel(user_msg, session_id, project_id, top_k=3)
            if sem_ctx: context += sem_ctx + "\n\n"
        except Exception: pass

    # CSV context if loaded
    retrieve_csv, _ = _retrieval()
    if retrieve_csv and csv_path and os.path.exists(csv_path):
        try:
            csv_ctx = retrieve_csv(csv_path, user_msg)
            if csv_ctx: context += csv_ctx + "\n\n"
        except Exception: pass

    # Extra context from context engine
    if context_result and context_result.get("extra_context"):
        context += context_result["extra_context"] + "\n\n"

    reply = ask_llm(context + user_msg, system_prompt=system)
    chat_sessions[session_id].append({"role":"assistant","content":reply})

    if store_msg:
        try: store_msg(session_id,"assistant",reply)
        except Exception: pass

    _flush(session_id, session_name, project_id)
    upsert_idx(session_id, session_name, project_id)
    return jsonify({"reply":reply,"mode":"chat","csv_path":csv_path})


def _prepare_map_request(user_msg, csv_path, session_id, colormap):
    from services.dataset_factory import generate_dataset, signature_from_csv
    from utils.execution_state import create_map_request
    from utils.map_generator import detect_columns

    source_csv = csv_path if csv_path and os.path.exists(csv_path) else ""
    if source_csv:
        dc, vc, cols = detect_columns(source_csv)
        if not dc or not vc:
            return None, f"CSV needs at least 2 columns. Found: {cols}"

        # ── MASTER PROMPT: build signature for uploaded CSV ──────────────
        sig = signature_from_csv(source_csv, dc, vc, user_msg)

        dataset = {
            "district_col":     dc,
            "value_col":        vc,
            "dataset_label":    f"{dc} {vc}",
            "source":           "uploaded_csv",
            "rows":             [],
            "dataset_signature": sig,
        }
        metadata = _metadata_for_csv(source_csv, user_msg, dc, vc)
    else:
        # ── MASTER PROMPT: fresh isolated dataset, no previous data reuse ─
        dataset = generate_dataset(user_msg)
        region = dataset.get("region", "Karnataka")
        metric_label = dataset.get("dataset_label", "").replace(f"{region} District ", "")
        title = f"{region} District {metric_label} Distribution".replace("  ", " ").strip()

        # ── MASTER PROMPT: title MUST reflect current dataset topic ───────
        sig = dataset.get("dataset_signature", {})
        confirmed_topic = sig.get("topic", metric_label)
        title = f"{region} District {confirmed_topic} Distribution"

        metadata = {
            "title":           title,
            "subtitle":        f"{len(dataset.get('rows', []))} district records",
            "legend_title":    metric_label,
            "dataset_label":   dataset.get("dataset_label", title),
            "export_filename": title.lower().replace(" ", "_") + ".png",
            "region":          region,
            "chart_type":      "choropleth",
            "is_geo":          True,
        }

    state = create_map_request(session_id, user_msg, dataset, metadata, colormap, source_csv)
    params = {
        "request_id":        state["request_id"],
        "dataset_id":        state["dataset_id"],
        "csv_path":          state["temporary_csv"],
        "output_png":        state["temporary_output"],
        "district_col":      state["dataset"]["district_col"],
        "value_col":         state["dataset"]["value_col"],
        "title":             metadata.get("title", "Choropleth Map"),
        "subtitle":          metadata.get("subtitle", ""),
        "legend_title":      metadata.get("legend_title", state["dataset"]["value_col"]),
        "dataset_label":     metadata.get("dataset_label", ""),
        "export_filename":   metadata.get("export_filename", ""),
        "colormap":          colormap,
        "dataset_signature": dataset.get("dataset_signature", {}),
    }
    return params, None


def _metadata_for_csv(csv_path, user_msg, district_col, value_col):
    title = clean_title(user_msg) or f"{value_col} Distribution by {district_col}"
    metadata = {
        "title":           title,
        "subtitle":        "",
        "legend_title":    value_col,
        "dataset_label":   f"{district_col} {value_col}",
        "export_filename": title.lower().replace(" ", "_") + ".png",
    }
    gen_title = _meta_gen()
    if gen_title:
        try:
            metadata.update(gen_title(csv_path, user_msg, district_col, value_col))
        except Exception:
            pass
    return metadata


def _gen_map(params, colormap, session_id, session_name, project_id):
    from utils.map_generator import generate_map_code, run_map_code
    from utils.execution_state import load_state, update_state, finalize_map_state, cleanup_request

    request_id = params.get("request_id")
    state = load_state(request_id) if request_id else {}
    maps_dir = os.path.dirname(params.get("output_png") or state.get("temporary_output") or os.path.join(STORAGE, "maps"))
    os.makedirs(maps_dir, exist_ok=True)
    output_png = params.get("output_png") or state.get("temporary_output")

    if request_id:
        update_state(request_id, status="executing")

    # ── MASTER PROMPT: pass dataset_signature into generated code ─────────
    code = generate_map_code(
        params["csv_path"], params["district_col"], params["value_col"],
        output_png, params["title"], colormap,
        subtitle=params.get("subtitle", ""),
        legend_title=params.get("legend_title", params["value_col"]),
        dataset_signature=params.get("dataset_signature"),
    )
    success, result = run_map_code(code, maps_dir)

    if success:
        map_id = new_id()
        if request_id:
            state = update_state(request_id, status="completed", map_id=map_id)
        else:
            state = {
                "request_id":       new_id(),
                "dataset_id":       new_id(),
                "session_id":       session_id,
                "temporary_csv":    params["csv_path"],
                "temporary_output": output_png,
                "metadata":         params,
                "dataset":          {"district_col": params["district_col"], "value_col": params["value_col"]},
                "colormap":         colormap,
            }
        finalized = finalize_map_state(state, map_id)

        hf   = os.path.join(STORAGE,"history","index.json")
        hist = read_json(hf,[])
        hist.insert(0,{
            "id":               map_id,
            "request_id":       state.get("request_id"),
            "dataset_id":       state.get("dataset_id"),
            "title":            params["title"],
            "subtitle":         params.get("subtitle", ""),
            "legend_title":     params.get("legend_title", params["value_col"]),
            "dataset_label":    params.get("dataset_label", ""),
            "export_filename":  params.get("export_filename", ""),
            "colormap":         colormap,
            "district_col":     params["district_col"],
            "value_col":        params["value_col"],
            "dataset_signature":params.get("dataset_signature", {}),
            "session_id":       session_id,
            "project_id":       project_id,
            "timestamp":        now(),
            "map_file":         finalized["map_file"],
            "csv_file":         finalized["csv_file"],
            "metadata_file":    finalized["json_file"],
        })
        write_json(hf, hist[:100])

        _, _, store_map_fn = _sem_memory()
        if store_map_fn:
            try: store_map_fn(map_id, params["title"], session_id,
                              finalized["history_csv"], colormap, params.get("value_col",""))
            except Exception: pass

        reply = ""
        _add(session_id,"assistant",reply)
        _flush(session_id, session_name, project_id)
        upsert_idx(session_id, session_name, project_id)
        if request_id:
            cleanup_request(request_id)
        return jsonify({"reply":reply,"mode":"map",
                        "map_url":finalized["map_url"],
                        "map_id":map_id,"csv_path":None,"clear_csv":True})

    if request_id:
        update_state(request_id, status="failed", error=result)
        cleanup_request(request_id)
    reply = "Map generation failed."
    _add(session_id,"assistant",reply)
    return jsonify({"reply":reply,"mode":"map","error":result,"csv_path":None,"clear_csv":True})


def _is_csv_snapshot_request(user_msg):
    msg = user_msg.lower()
    return "csv" in msg and any(k in msg for k in ["used", "previous map", "this map", "last map", "that map", "show"])


def _csv_snapshot_reply(user_msg, session_id):
    from utils.execution_state import latest_map_for_session, read_map_csv
    entry    = latest_map_for_session(session_id)
    csv_text = read_map_csv(entry.get("id")) if entry else ""
    if not csv_text:
        return "No map CSV snapshot is available for this chat yet."
    title = entry.get("title", "previous map")
    return f"CSV used for {title}:\n\n```csv\n{csv_text.strip()}\n```"


def _dataset_reply(user_msg):
    try:
        from services.dataset_factory import generate_dataset
        dataset = generate_dataset(user_msg)
        rows    = dataset.get("rows", [])
        if not rows:
            return "I couldn't prepare a dataset for that request."
        district_col = dataset.get("district_col", "district")
        value_col    = dataset.get("value_col", "value")
        preview = rows[:12]
        lines   = [f"| {district_col} | {value_col} |", "|---|---:|"]
        lines  += [f"| {r[district_col]} | {r[value_col]} |" for r in preview]
        if len(rows) > len(preview):
            lines.append(f"| ... | {len(rows) - len(preview)} more records |")
        return f"{dataset.get('dataset_label','Dataset')}\n\n" + "\n".join(lines)
    except Exception:
        return ask_llm(user_msg, system_prompt=get_system())


def _add(sid, role, content):
    if sid not in chat_sessions: chat_sessions[sid] = []
    msgs = chat_sessions[sid]
    if not msgs or msgs[-1]["content"] != content:
        msgs.append({"role":role,"content":content})

def _flush(sid, name, project_id=None):
    write_json(chat_file(sid),{"id":sid,"name":name,"project_id":project_id,
                               "timestamp":now(),"messages":chat_sessions.get(sid,[])})

@chat_bp.route("/list",      methods=["GET"])
def list_chats(): return jsonify(load_idx()[:40])

@chat_bp.route("/recent",    methods=["GET"])
def recent_chats():
    return jsonify([c for c in load_idx() if not c.get("project_id")][:30])

@chat_bp.route("/get/<sid>", methods=["GET"])
def get_chat(sid): return jsonify(read_json(chat_file(sid),{"messages":[]}))

@chat_bp.route("/search",    methods=["GET"])
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
