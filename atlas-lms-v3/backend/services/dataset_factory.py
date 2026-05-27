"""
services/dataset_factory.py
Dataset preparation for map generation.

KEY RULES:
- For known topics (rainfall/population/literacy/gdp): serve baseline Karnataka data
- For unknown topics (women's population, sex ratio, unemployment, etc.):
  RETURN DATA_NOT_AVAILABLE — never serve wrong/dummy data
- No global state, no caching, every call is isolated
"""
import re
from typing import Dict, List

DATA_NOT_AVAILABLE = "__DATA_NOT_AVAILABLE__"

KARNATAKA_DISTRICTS = [
    "Bagalkot","Ballari","Belagavi","Bengaluru Rural","Bengaluru Urban",
    "Bidar","Chamarajanagar","Chikkaballapur","Chikkamagaluru",
    "Chitradurga","Dakshina Kannada","Davanagere","Dharwad","Gadag",
    "Hassan","Haveri","Kalaburagi","Kodagu","Kolar","Koppal",
    "Mandya","Mysuru","Raichur","Ramanagara","Shivamogga","Tumakuru",
    "Udupi","Uttara Kannada","Vijayanagara","Vijayapura","Yadgir",
]

# Only hard-coded baselines for well-known topics
METRIC_ALIASES = {
    "rainfall": {
        "column": "rainfall_mm","label": "Rainfall (mm)",
        "values": [512,438,782,714,922,690,801,706,1895,612,3740,
                   642,812,596,1048,724,742,2720,688,552,668,781,
                   632,714,1648,708,3890,2480,640,508,702],
    },
    "population": {
        "column": "population","label": "Population",
        "values": [1889752,2452595,4779661,987257,9621551,1703300,
                   1020962,1255104,1137753,1659456,2089649,1946905,
                   1847023,1064570,1776421,1597668,2566326,554519,
                   1536401,1389920,1808680,3001127,1928812,1082636,
                   1752753,2678980,1177361,1437169,1353198,2175102,1174271],
    },
    "literacy": {
        "column": "literacy_rate_percent","label": "Literacy Rate (%)",
        "values": [68.8,67.9,73.5,77.9,87.7,70.5,61.4,70.1,79.2,
                   73.7,88.6,76.3,80.0,75.2,76.1,77.6,65.7,82.6,
                   74.4,68.1,70.4,72.8,60.5,69.2,80.5,75.1,86.2,
                   84.1,67.0,67.2,51.8],
    },
    "gdp": {
        "column": "gdp_index","label": "GDP Index",
        "values": [48,62,74,58,100,44,43,46,63,45,79,54,70,41,
                   57,48,52,61,49,39,56,68,42,51,59,66,72,64,46,47,38],
    },
}

# Topics that must come from LLM query, never from hardcoded fallback
LLM_REQUIRED_TOPICS = {
    "women", "female", "sex ratio", "gender",
    "infant mortality", "child mortality",
    "unemployment", "crime", "forest",
    "agriculture", "yield", "crop",
}


def infer_metric_key(user_msg: str):
    """Returns metric key or None if topic is not in hardcoded baseline."""
    msg = user_msg.lower()
    # LLM-required topics — NEVER use hardcoded data
    if any(k in msg for k in LLM_REQUIRED_TOPICS):
        return None
    if any(k in msg for k in ["rain", "monsoon", "precipitation"]):
        return "rainfall"
    if any(k in msg for k in ["literacy", "education", "literate"]):
        return "literacy"
    if any(k in msg for k in ["gdp", "income", "economic"]):
        return "gdp"
    if any(k in msg for k in ["population", "people", "demographic"]):
        return "population"
    return None  # unknown — must use LLM or upload


def infer_region(user_msg: str) -> str:
    msg = user_msg.lower()
    if "karnataka" in msg: return "Karnataka"
    m = re.search(r"\b(?:of|for|in)\s+([A-Z][A-Za-z\s]+?)(?:\s+district|\s+map|$)", user_msg)
    if m: return m.group(1).strip()
    return "Karnataka"


def generate_dataset(user_msg: str) -> Dict:
    """
    Generate fresh dataset.
    Returns DATA_NOT_AVAILABLE signal if topic is not in baseline.
    Never falls back to wrong data.
    """
    metric_key = infer_metric_key(user_msg)
    if metric_key is None:
        return {
            "status": DATA_NOT_AVAILABLE,
            "reason": (
                "⚠️ **Data Not Available in Baseline**\n\n"
                "This topic requires LLM search or a CSV upload. "
                "Processing via LLM data extraction..."
            ),
        }

    region = infer_region(user_msg)
    metric = METRIC_ALIASES[metric_key]
    rows: List[Dict] = [
        {"district": d, metric["column"]: v}
        for d, v in zip(KARNATAKA_DISTRICTS, metric["values"])
    ]
    return {
        "status":        "ok",
        "region":        region,
        "metric_key":    metric_key,
        "district_col":  "district",
        "value_col":     metric["column"],
        "dataset_label": f"{region} District {metric['label']}",
        "source":        "atlas_internal_baseline",
        "rows":          rows,
    }
