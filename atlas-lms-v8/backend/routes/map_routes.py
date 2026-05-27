"""routes/map_routes.py — CSV upload, map download, manual generation, history"""
import os, uuid, re
from flask import Blueprint, request, jsonify, send_file
from utils.storage import storage_path, read_json, write_json, now, new_id

map_bp  = Blueprint("map", __name__)
STORAGE = storage_path()


@map_bp.route("/upload-csv", methods=["POST","OPTIONS"])
def upload_csv():
    if request.method == "OPTIONS": return jsonify({}), 200
    if "file" not in request.files: return jsonify({"error":"No file uploaded"}), 400
    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error":"Only .csv files are supported"}), 400
    udir = os.path.join(STORAGE,"uploads")
    os.makedirs(udir, exist_ok=True)
    fp = os.path.join(udir, f"data_{uuid.uuid4().hex[:8]}.csv")
    file.save(fp)
    with open(fp, encoding="utf-8") as f: lines = f.readlines()
    return jsonify({
        "message":  f"Uploaded: {file.filename}",
        "csv_path": fp,
        "preview":  "".join(lines[:6]),
        "rows":     max(0, len(lines)-1),
    })


@map_bp.route("/generate-from-upload", methods=["POST","OPTIONS"])
def generate_from_upload():
    """
    Manual generation: CSV path + colormap + title → fresh map.
    Always runs Python code fresh. Never serves cached image.
    """
    if request.method == "OPTIONS": return jsonify({}), 200
    data       = request.json or {}
    csv_path   = data.get("csv_path","")
    colormap   = data.get("colormap","Blues")
    title      = data.get("title","").strip() or "Choropleth Map"
    session_id = data.get("session_id","manual_gen")

    if not csv_path or not os.path.exists(csv_path):
        return jsonify({"error":"CSV file not found. Please upload first."}), 400

    from utils.map_generator import detect_columns, generate_map_code, run_map_code
    from utils.execution_state import create_map_request, update_state, finalize_map_state, cleanup_request

    dc, vc, cols = detect_columns(csv_path)
    if not dc or not vc:
        return jsonify({"error":f"CSV needs at least 2 columns. Found: {cols}"}), 400

    if title == "Choropleth Map":
        title = f"{vc.replace('_',' ').title()} by {dc.replace('_',' ').title()}"

    metadata = {
        "title":           title,
        "subtitle":        "",
        "legend_title":    vc,
        "dataset_label":   f"{dc} {vc}",
        "export_filename": title.lower().replace(" ","_")[:50] + ".png",
    }
    dataset = {"district_col":dc,"value_col":vc,"source":"manual_upload","rows":[]}
    state   = create_map_request(session_id, "Manual: "+title, dataset, metadata, colormap, csv_path)

    maps_dir = os.path.join(STORAGE,"maps")
    os.makedirs(maps_dir, exist_ok=True)
    update_state(state["request_id"], status="executing")

    code    = generate_map_code(
        state["temporary_csv"], dc, vc,
        state["temporary_output"], title, colormap,
        legend_title=vc,
    )
    success, result = run_map_code(code, maps_dir)

    if success:
        map_id    = new_id()
        finalized = finalize_map_state(state, map_id)
        hf   = os.path.join(STORAGE,"history","index.json")
        hist = read_json(hf,[])
        hist.insert(0,{
            "id":           map_id,
            "title":        title,
            "colormap":     colormap,
            "district_col": dc,
            "value_col":    vc,
            "session_id":   session_id,
            "project_id":   None,
            "timestamp":    now(),
            "map_file":     finalized["map_file"],
            "csv_file":     finalized["csv_file"],
            "metadata_file":finalized["json_file"],
        })
        write_json(hf, hist[:100])
        cleanup_request(state["request_id"])
        return jsonify({"ok":True,"map_id":map_id,"map_url":finalized["map_url"],"title":title})

    cleanup_request(state["request_id"])
    return jsonify({"error": result[:600]}), 500


@map_bp.route("/history", methods=["GET"])
def map_history():
    return jsonify(read_json(os.path.join(STORAGE,"history","index.json"),[]))


@map_bp.route("/download", methods=["GET"])
def download_map():
    fmt    = request.args.get("format","png").lower()
    map_id = request.args.get("id","").strip()
    title  = request.args.get("title","choropleth_map")

    if not map_id:
        return jsonify({"error":"map_id is required. No fallback served."}), 400

    src = os.path.join(STORAGE,"history",f"{map_id}.png")
    if not os.path.exists(src):
        maps_dir = os.path.join(STORAGE,"maps")
        candidates = [f for f in os.listdir(maps_dir) if f.startswith(map_id)] if os.path.exists(maps_dir) else []
        if candidates:
            src = os.path.join(maps_dir, candidates[0])
        else:
            return jsonify({"error":f"Map {map_id} not found. Please regenerate."}), 404

    safe = re.sub(r'[^\w\s-]','',title).strip().replace(' ','_')[:40]
    if fmt == "png":
        return send_file(src, mimetype="image/png", as_attachment=True, download_name=f"{safe}.png")

    import matplotlib.pyplot as plt, matplotlib.image as mpimg
    img = mpimg.imread(src)
    out = os.path.join(STORAGE,"maps",f"export_{map_id}.{fmt}")
    fig,ax = plt.subplots(figsize=(img.shape[1]/100, img.shape[0]/100))
    ax.imshow(img); ax.axis("off"); plt.tight_layout(pad=0)
    if fmt in ("jpeg","jpg"):
        plt.savefig(out,format="jpeg",dpi=150,bbox_inches="tight",quality=95)
        plt.close()
        return send_file(out, mimetype="image/jpeg", as_attachment=True, download_name=f"{safe}.jpg")
    plt.savefig(out,format="pdf",dpi=150,bbox_inches="tight")
    plt.close()
    return send_file(out, mimetype="application/pdf", as_attachment=True, download_name=f"{safe}.pdf")


@map_bp.route("/download-csv", methods=["GET"])
def download_csv():
    map_id = request.args.get("id","").strip()
    if not map_id:
        return jsonify({"error":"map_id required"}), 400
    src = os.path.join(STORAGE,"history",f"{map_id}.csv")
    if not os.path.exists(src):
        return jsonify({"error":"No CSV snapshot found for this map"}), 404
    return send_file(src, mimetype="text/csv", as_attachment=True,
                     download_name=f"{map_id}_data.csv")
