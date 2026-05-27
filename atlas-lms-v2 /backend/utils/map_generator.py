"""utils/map_generator.py — choropleth map code generator
Generates fresh Python code every call. No caching.
Includes column validation + GeoJSON validation in generated script.
"""
import os, sys, subprocess, tempfile, json
import pandas as pd
from utils.llm import DISTRICT_NAME_MAP

GEOJSON_URLS = [
    "https://raw.githubusercontent.com/inosaint/StatesOfIndia/master/karnataka.geojson",
    "https://raw.githubusercontent.com/shuklaneerajdev/IndiaStateTopojsonFiles/master/Karnataka.geojson",
]


def detect_columns(csv_path):
    try:
        df   = pd.read_csv(csv_path)
        cols = list(df.columns)
        return cols[0], cols[1], cols
    except Exception:
        return None, None, []


def generate_map_code(csv_path, district_col, value_col, output_path,
                      title, colormap, subtitle="", legend_title=""):
    name_map_str = repr(DISTRICT_NAME_MAP)
    urls_str     = repr(GEOJSON_URLS)
    csv_lit      = json.dumps(csv_path)
    output_lit   = json.dumps(output_path)
    dc_lit       = json.dumps(district_col)
    vc_lit       = json.dumps(value_col)
    cmap_lit     = json.dumps(colormap)
    title_lit    = json.dumps(title)
    subtitle_lit = json.dumps(subtitle or "")
    legend_lit   = json.dumps(legend_title or value_col)

    return f'''
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import requests, os, json, sys

CSV_PATH     = {csv_lit}
OUTPUT_PATH  = {output_lit}
DISTRICT_COL = {dc_lit}
VALUE_COL    = {vc_lit}
COLORMAP     = {cmap_lit}
TITLE        = {title_lit}
SUBTITLE     = {subtitle_lit}
LEGEND_TITLE = {legend_lit}
NAME_MAP     = {name_map_str}
URLS         = {urls_str}

# Validate CSV exists and has required columns
if not os.path.exists(CSV_PATH):
    print(f"ERROR: CSV not found: {{CSV_PATH}}", file=sys.stderr); sys.exit(1)

df = pd.read_csv(CSV_PATH)
print(f"CSV columns: {{list(df.columns)}}, rows: {{len(df)}}")

if DISTRICT_COL not in df.columns:
    print(f"ERROR: district column '{{DISTRICT_COL}}' not in {{list(df.columns)}}", file=sys.stderr); sys.exit(1)
if VALUE_COL not in df.columns:
    print(f"ERROR: value column '{{VALUE_COL}}' not in {{list(df.columns)}}", file=sys.stderr); sys.exit(1)
if len(df) == 0:
    print("ERROR: CSV has 0 rows", file=sys.stderr); sys.exit(1)

df[DISTRICT_COL] = df[DISTRICT_COL].astype(str).str.strip().str.lower()
df[DISTRICT_COL] = df[DISTRICT_COL].map(lambda x: NAME_MAP.get(x, x))
df[VALUE_COL]    = pd.to_numeric(df[VALUE_COL], errors="coerce")
df = df.dropna(subset=[VALUE_COL])
print(f"Valid rows after coercion: {{len(df)}}")

if len(df) == 0:
    print("ERROR: No valid numeric rows after coercion", file=sys.stderr); sys.exit(1)

# Load GeoJSON
geojson_path = "/tmp/karnataka_atlas.geojson"
if os.path.exists(geojson_path): os.remove(geojson_path)
geojson_loaded = False
for url in URLS:
    try:
        r = requests.get(url, timeout=20)
        parsed = json.loads(r.text)
        if r.status_code == 200 and "features" in parsed:
            open(geojson_path, "w").write(r.text)
            geojson_loaded = True
            print(f"GeoJSON loaded: {{url}}")
            break
    except Exception as e:
        print(f"GeoJSON URL failed: {{e}}")

if not geojson_loaded:
    print("ERROR: Could not load GeoJSON", file=sys.stderr); sys.exit(1)

gdf = gpd.read_file(geojson_path)
name_col = None
for col in ["NAME_2","district","DISTRICT","name","NAME"]:
    if col in gdf.columns: name_col = col; break
if not name_col:
    for col in gdf.columns:
        if col != "geometry" and gdf[col].dtype == object: name_col = col; break

if not name_col:
    print("ERROR: No name column in GeoJSON", file=sys.stderr); sys.exit(1)

gdf[name_col] = gdf[name_col].astype(str).str.strip().str.lower()
merged  = gdf.merge(df, left_on=name_col, right_on=DISTRICT_COL, how="left")
matched = merged[VALUE_COL].notna().sum()
print(f"Matched {{matched}}/{{len(gdf)}} districts")

# Render map
fig, ax = plt.subplots(1, 1, figsize=(16, 14))
merged[merged[VALUE_COL].isna()].plot(ax=ax, color="#e0e0e0", edgecolor="white", linewidth=0.8)
if matched > 0:
    merged[merged[VALUE_COL].notna()].plot(
        column=VALUE_COL, ax=ax, cmap=COLORMAP,
        edgecolor="white", linewidth=0.8, legend=True,
        legend_kwds={{"label": LEGEND_TITLE, "orientation": "vertical", "shrink": 0.55}}
    )

for idx, row in merged.iterrows():
    try:
        geom = row.geometry
        if geom is None or geom.is_empty: continue
        cx, cy = geom.centroid.x, geom.centroid.y
        label  = str(row[name_col]).title()
        if len(label) > 13: label = label[:11] + "."
        val    = row[VALUE_COL]
        val_str = "" if pd.isna(val) else (
            f"{{val/1e6:.1f}}M" if val>=1e6 else
            f"{{val/1e3:.1f}}K" if val>=1e3 else f"{{val:.1f}}"
        )
        ax.annotate(label, xy=(cx,cy+0.04), ha="center", va="center",
                    fontsize=5.2, fontweight="bold", color="#111",
                    path_effects=[pe.withStroke(linewidth=2.2, foreground="white")])
        if val_str:
            ax.annotate(val_str, xy=(cx,cy-0.06), ha="center", va="center",
                        fontsize=4.8, color="#333",
                        path_effects=[pe.withStroke(linewidth=2, foreground="white")])
    except: pass

ax.set_title(TITLE, fontsize=17, fontweight="bold", pad=22)
if SUBTITLE:
    ax.text(0.5, 0.985, SUBTITLE, transform=ax.transAxes,
            ha="center", va="top", fontsize=9, color="#444")
ax.axis("off")
plt.tight_layout()
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
plt.savefig(OUTPUT_PATH, dpi=180, bbox_inches="tight")
plt.close()
print(f"Map saved: {{OUTPUT_PATH}}")
'''


def run_map_code(code, output_dir):
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir=output_dir)
    tmp.write(code); tmp.close()
    try:
        env = os.environ.copy()
        env["MPLCONFIGDIR"] = output_dir
        result = subprocess.run(
            [sys.executable, tmp.name],
            capture_output=True, text=True, timeout=90, env=env
        )
        if result.returncode == 0: return True, "success"
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Timed out after 90 seconds"
    except Exception as e:
        return False, str(e)
    finally:
        try: os.unlink(tmp.name)
        except: pass
