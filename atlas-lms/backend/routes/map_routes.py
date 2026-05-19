"""routes/map_routes.py — CSV upload, map download, history"""
import os, uuid, re
from flask import Blueprint, request, jsonify, send_file
from utils.storage import storage_path, read_json, now

map_bp  = Blueprint("map", __name__)
STORAGE = storage_path()

@map_bp.route("/upload-csv", methods=["POST","OPTIONS"])
def upload_csv():
    if request.method == "OPTIONS": return jsonify({}), 200
    if "file" not in request.files: return jsonify({"error":"No file"}), 400
    file = request.files["file"]
    udir = os.path.join(STORAGE,"uploads")
    os.makedirs(udir, exist_ok=True)
    fp   = os.path.join(udir, f"data_{uuid.uuid4().hex[:8]}.csv")
    file.save(fp)
    with open(fp) as f: lines = f.readlines()
    return jsonify({"message":f"Uploaded: {file.filename}","csv_path":fp,
                    "preview":"".join(lines[:6]),"rows":len(lines)-1})

@map_bp.route("/history", methods=["GET"])
def map_history():
    return jsonify(read_json(os.path.join(STORAGE,"history","index.json"),[]))

@map_bp.route("/download", methods=["GET"])
def download_map():
    fmt    = request.args.get("format","png").lower()
    map_id = request.args.get("id")
    title  = request.args.get("title","choropleth_map")
    src    = (os.path.join(STORAGE,"history",f"{map_id}.png") if map_id
              else os.path.join(STORAGE,"maps","map_output.png"))
    if not os.path.exists(src): return jsonify({"error":"Not found"}), 404
    safe = re.sub(r'[^\w\s-]','',title).strip().replace(' ','_')[:40]
    if fmt == "png":
        return send_file(src, mimetype="image/png", as_attachment=True, download_name=f"{safe}.png")
    import matplotlib.pyplot as plt, matplotlib.image as mpimg
    img = mpimg.imread(src)
    out = os.path.join(STORAGE,"maps",f"out.{fmt}")
    fig,ax = plt.subplots(figsize=(img.shape[1]/100,img.shape[0]/100))
    ax.imshow(img); ax.axis("off"); plt.tight_layout(pad=0)
    if fmt in ("jpeg","jpg"):
        plt.savefig(out,format="jpeg",dpi=150,bbox_inches="tight",quality=95); plt.close()
        return send_file(out,mimetype="image/jpeg",as_attachment=True,download_name=f"{safe}.jpg")
    plt.savefig(out,format="pdf",dpi=150,bbox_inches="tight"); plt.close()
    return send_file(out,mimetype="application/pdf",as_attachment=True,download_name=f"{safe}.pdf")

@map_bp.route("/download-csv", methods=["GET"])
def download_csv():
    map_id = request.args.get("id")
    src    = os.path.join(STORAGE,"history",f"{map_id}.csv") if map_id else None
    if not src or not os.path.exists(src):
        udir  = os.path.join(STORAGE,"uploads")
        files = sorted([f for f in os.listdir(udir) if f.endswith(".csv")],
                       key=lambda f: os.path.getmtime(os.path.join(udir,f)), reverse=True)
        if not files: return jsonify({"error":"No CSV"}), 404
        src = os.path.join(udir, files[0])
    return send_file(src,mimetype="text/csv",as_attachment=True,download_name="district_data.csv")
