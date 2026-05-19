"""utils/map_generator.py — choropleth map code generator"""
import os, sys, subprocess, tempfile
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

def generate_map_code(csv_path, district_col, value_col, output_path, title, colormap):
    name_map_str = str(DISTRICT_NAME_MAP)
    urls_str     = str(GEOJSON_URLS)
    return f'''
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import requests, os, json

CSV_PATH     = r"{csv_path}"
OUTPUT_PATH  = r"{output_path}"
DISTRICT_COL = "{district_col}"
VALUE_COL    = "{value_col}"
COLORMAP     = "{colormap}"
TITLE        = "{title}"
NAME_MAP     = {name_map_str}
URLS         = {urls_str}

df = pd.read_csv(CSV_PATH)
df[DISTRICT_COL] = df[DISTRICT_COL].astype(str).str.strip().str.lower()
df[DISTRICT_COL] = df[DISTRICT_COL].map(lambda x: NAME_MAP.get(x, x))
df[VALUE_COL]    = pd.to_numeric(df[VALUE_COL], errors="coerce")
df = df.dropna(subset=[VALUE_COL])

geojson_path = "/tmp/karnataka_atlas.geojson"
if os.path.exists(geojson_path): os.remove(geojson_path)
for url in URLS:
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and "features" in json.loads(r.text):
            open(geojson_path, "w").write(r.text); break
    except Exception as e:
        print("URL failed:", e)

gdf = gpd.read_file(geojson_path)
name_col = None
for col in ["NAME_2","district","DISTRICT","name","NAME"]:
    if col in gdf.columns: name_col = col; break
if not name_col:
    for col in gdf.columns:
        if col != "geometry" and gdf[col].dtype == object: name_col = col; break

gdf[name_col] = gdf[name_col].astype(str).str.strip().str.lower()
merged = gdf.merge(df, left_on=name_col, right_on=DISTRICT_COL, how="left")
matched = merged[VALUE_COL].notna().sum()
print(f"Matched {{matched}}/{{len(gdf)}}")

fig, ax = plt.subplots(1, 1, figsize=(16, 14))
merged[merged[VALUE_COL].isna()].plot(ax=ax, color="#e0e0e0", edgecolor="white", linewidth=0.8)
if matched > 0:
    merged[merged[VALUE_COL].notna()].plot(
        column=VALUE_COL, ax=ax, cmap=COLORMAP,
        edgecolor="white", linewidth=0.8, legend=True,
        legend_kwds={{"label": VALUE_COL, "orientation": "vertical", "shrink": 0.55}}
    )

for idx, row in merged.iterrows():
    try:
        geom = row.geometry
        if geom is None or geom.is_empty: continue
        cx, cy = geom.centroid.x, geom.centroid.y
        label = str(row[name_col]).title()
        if len(label) > 13: label = label[:11] + "."
        val = row[VALUE_COL]
        val_str = "" if pd.isna(val) else (f"{{val/1e6:.1f}}M" if val>=1e6 else (f"{{val/1e3:.1f}}K" if val>=1e3 else f"{{val:.1f}}"))
        ax.annotate(label, xy=(cx,cy+0.04), ha="center", va="center",
                    fontsize=5.2, fontweight="bold", color="#111",
                    path_effects=[pe.withStroke(linewidth=2.2, foreground="white")])
        if val_str:
            ax.annotate(val_str, xy=(cx,cy-0.06), ha="center", va="center",
                        fontsize=4.8, color="#333",
                        path_effects=[pe.withStroke(linewidth=2, foreground="white")])
    except: pass

ax.set_title(TITLE, fontsize=17, fontweight="bold", pad=18)
ax.axis("off")
plt.tight_layout()
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
plt.savefig(OUTPUT_PATH, dpi=180, bbox_inches="tight")
plt.close()
print("Map saved:", OUTPUT_PATH)
'''

def run_map_code(code, output_dir):
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir=output_dir)
    tmp.write(code); tmp.close()
    try:
        result = subprocess.run([sys.executable, tmp.name],
            capture_output=True, text=True, timeout=90)
        if result.returncode == 0: return True, "success"
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Timed out after 90 seconds"
    except Exception as e:
        return False, str(e)
    finally:
        try: os.unlink(tmp.name)
        except: pass
