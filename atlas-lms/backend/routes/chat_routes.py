"""
routes/chat_routes.py
Upgraded: semantic memory + context engine + permission guard + smart titles.
All existing API contracts preserved.
"""
import os
from flask import Blueprint, request, jsonify
from utils.llm import ask_llm, is_map_request, detect_color, clean_title
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

    # Context engine — resolve references like "above csv", "previous map"
    context_result = None
    build_ctx = _ctx_engine()
    if build_ctx:
        try:
            context_result = build_ctx(user_msg, session_id, csv_path, project_id)
            if context_result.get("resolved") and context_result.get("csv_path"):
                csv_path = context_result["csv_path"]
        except Exception: pass

    # Pending color reply
    pk = f"_pend_{session_id}"
    if pk in chat_sessions:
        cmap = detect_color(user_msg)
        if cmap:
            params = chat_sessions.pop(pk)
            return _gen_map(params, cmap, session_id, session_name, project_id)
        reply = "Please type a color: `blue` `green` `red` `purple` `viridis` `plasma` `inferno` `spectral`"
        _add(session_id,"assistant",reply)
        return jsonify({"reply":reply,"mode":"map","waiting_for_color":True,"csv_path":csv_path})

    # Build intent for permission guard
    intent = {}
    if context_result:
        intent = context_result.get("intent",{})
    elif is_map_request(user_msg, csv_path):
        intent = {"needs_execution":True,"is_map":True,"has_reference":False}

    # Build action params for guard
    action_params = {}
    if is_map_request(user_msg, csv_path) and csv_path and os.path.exists(csv_path):
        from utils.map_generator import detect_columns
        dc, vc, _ = detect_columns(csv_path)
        action_params = {"csv_path":csv_path,"district_col":dc or "",
                         "value_col":vc or "","title":clean_title(user_msg) or ""}

    # Permission guard
    guard_fn = _guard()
    if guard_fn and (intent.get("is_map") or intent.get("needs_execution")):
        g = guard_fn(user_msg, session_id, intent, action_params)
        if not g["allowed"]:
            reply = g.get("reply","")
            if reply:
                _add(session_id,"assistant",reply)
                _flush(session_id, session_name, project_id)
                return jsonify({"reply":reply,"mode":"map" if intent.get("is_map") else "chat",
                                "waiting":g.get("waiting",False),"csv_path":csv_path})
        # Restore params from approved pending action
        if g["allowed"] and g.get("params"):
            restored = g["params"]
            if restored.get("csv_path"): csv_path = restored["csv_path"]
            action_params.update(restored)

    # Map mode
    if is_map_request(user_msg, csv_path):
        if csv_path and os.path.exists(csv_path):
            from utils.map_generator import detect_columns
            dc, vc, cols = detect_columns(csv_path)
            if not dc or not vc:
                reply = f"CSV needs 2 columns. Found: {cols}"
                _add(session_id,"assistant",reply)
                return jsonify({"reply":reply,"mode":"map","csv_path":csv_path})

            # Smart title generation
            title = clean_title(user_msg) or f"Karnataka Districts by {vc}"
            gen_title = _meta_gen()
            if gen_title:
                try:
                    meta  = gen_title(csv_path, user_msg, dc, vc)
                    title = meta.get("title") or title
                except Exception: pass

            cmap = detect_color(user_msg) or sidebar_cmap
            if cmap:
                return _gen_map({"csv_path":csv_path,"district_col":dc,
                                 "value_col":vc,"title":title},
                                cmap, session_id, session_name, project_id)

            chat_sessions[pk] = {"csv_path":csv_path,"district_col":dc,
                                  "value_col":vc,"title":title}
            reply = ("What color scheme?\n\n"
                     "**Mono:** `blue` `green` `red` `purple` `orange` `grey` `pink`\n\n"
                     "**Multi:** `viridis` `plasma` `inferno` `magma` `spectral` `turbo`")
            _add(session_id,"assistant",reply)
            return jsonify({"reply":reply,"mode":"map","waiting_for_color":True,"csv_path":csv_path})

        reply = "I can generate a choropleth map! Please upload a CSV or paste district data in the **Map Data** panel."
        _add(session_id,"assistant",reply)
        return jsonify({"reply":reply,"mode":"map","show_sidebar":True})

    # Normal chat with full context injection
    system  = get_system(project_id)
    context = ""

    # Project context (system prompt + memory + docs)
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


def _gen_map(params, colormap, session_id, session_name, project_id):
    import shutil
    from utils.map_generator import generate_map_code, run_map_code
    maps_dir   = os.path.join(STORAGE,"maps")
    output_png = os.path.join(maps_dir,"map_output.png")
    os.makedirs(maps_dir, exist_ok=True)

    code    = generate_map_code(params["csv_path"],params["district_col"],
                                params["value_col"],output_png,params["title"],colormap)
    success, result = run_map_code(code, maps_dir)

    if success:
        map_id   = new_id()
        hist_dir = os.path.join(STORAGE,"history")
        os.makedirs(hist_dir, exist_ok=True)
        shutil.copy2(output_png, os.path.join(hist_dir,f"{map_id}.png"))
        if os.path.exists(params["csv_path"]):
            shutil.copy2(params["csv_path"], os.path.join(hist_dir,f"{map_id}.csv"))
        hf   = os.path.join(hist_dir,"index.json")
        hist = read_json(hf,[])
        hist.insert(0,{"id":map_id,"title":params["title"],"colormap":colormap,
                        "value_col":params["value_col"],"session_id":session_id,
                        "project_id":project_id,"timestamp":now(),
                        "map_file":f"{map_id}.png","csv_file":f"{map_id}.csv"})
        write_json(hf, hist[:50])

        # Store map in semantic memory
        _, _, store_map_fn = _sem_memory()
        if store_map_fn:
            try: store_map_fn(map_id,params["title"],session_id,
                              params.get("csv_path",""),colormap,params.get("value_col",""))
            except Exception: pass

        reply = (f"Map generated!\n\n**Title:** {params['title']}\n"
                 f"**District:** {params['district_col']}  |  "
                 f"**Value:** {params['value_col']}  |  **Color:** {colormap}")
        _add(session_id,"assistant",reply)
        _flush(session_id, session_name, project_id)
        upsert_idx(session_id, session_name, project_id)
        return jsonify({"reply":reply,"mode":"map",
                        "map_url":f"/storage/maps/map_output.png?v={map_id}",
                        "map_id":map_id,"csv_path":params["csv_path"]})

    reply = "Map generation failed."
    _add(session_id,"assistant",reply)
    return jsonify({"reply":reply,"mode":"map","error":result})


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
