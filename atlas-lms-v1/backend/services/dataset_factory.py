"""
services/dataset_factory.py
Autonomous, deterministic GIS dataset preparation for map requests.

Anti-hallucination upgrade: every generate_dataset call produces a
DATASET_SIGNATURE that chat_routes uses to validate map generation.
Context isolation: no global mutable state; all data is per-call.
"""
import re
from typing import Dict, List

KARNATAKA_DISTRICTS = [
    "Bagalkot", "Ballari", "Belagavi", "Bengaluru Rural", "Bengaluru Urban",
    "Bidar", "Chamarajanagar", "Chikkaballapur", "Chikkamagaluru",
    "Chitradurga", "Dakshina Kannada", "Davanagere", "Dharwad", "Gadag",
    "Hassan", "Haveri", "Kalaburagi", "Kodagu", "Kolar", "Koppal",
    "Mandya", "Mysuru", "Raichur", "Ramanagara", "Shivamogga", "Tumakuru",
    "Udupi", "Uttara Kannada", "Vijayanagara", "Vijayapura", "Yadgir",
]

METRIC_ALIASES = {
    "rainfall": {
        "column": "rainfall",
        "label": "Rainfall",
        "values": [512, 438, 782, 714, 922, 690, 801, 706, 1895, 612, 3740,
                   642, 812, 596, 1048, 724, 742, 2720, 688, 552, 668, 781,
                   632, 714, 1648, 708, 3890, 2480, 640, 508, 702],
    },
    "population": {
        "column": "population",
        "label": "Population",
        "values": [1889752, 2452595, 4779661, 987257, 9621551, 1703300,
                   1020962, 1255104, 1137753, 1659456, 2089649, 1946905,
                   1847023, 1064570, 1776421, 1597668, 2566326, 554519,
                   1536401, 1389920, 1808680, 3001127, 1928812, 1082636,
                   1752753, 2678980, 1177361, 1437169, 1353198, 2175102,
                   1174271],
    },
    "literacy": {
        "column": "literacy_rate",
        "label": "Literacy Rate",
        "values": [68.8, 67.9, 73.5, 77.9, 87.7, 70.5, 61.4, 70.1, 79.2,
                   73.7, 88.6, 76.3, 80.0, 75.2, 76.1, 77.6, 65.7, 82.6,
                   74.4, 68.1, 70.4, 72.8, 60.5, 69.2, 80.5, 75.1, 86.2,
                   84.1, 67.0, 67.2, 51.8],
    },
    "gdp": {
        "column": "gdp_index",
        "label": "GDP Index",
        "values": [48, 62, 74, 58, 100, 44, 43, 46, 63, 45, 79, 54, 70, 41,
                   57, 48, 52, 61, 49, 39, 56, 68, 42, 51, 59, 66, 72, 64,
                   46, 47, 38],
    },
}

DEFAULT_METRIC = "population"


def is_supported_autonomous_region(user_msg: str) -> bool:
    msg = user_msg.lower()
    return "karnataka" in msg or "district" in msg


def infer_metric(user_msg: str) -> str:
    msg = user_msg.lower()
    if any(k in msg for k in ["rain", "monsoon", "precipitation"]):
        return "rainfall"
    if any(k in msg for k in ["literacy", "education"]):
        return "literacy"
    if any(k in msg for k in ["gdp", "income", "economic"]):
        return "gdp"
    if any(k in msg for k in ["population", "people", "demographic"]):
        return "population"
    return DEFAULT_METRIC


def infer_region(user_msg: str) -> str:
    msg = user_msg.lower()
    if "karnataka" in msg:
        return "Karnataka"
    match = re.search(r"\b(?:of|for|in)\s+([A-Z][A-Za-z\s]+?)(?:\s+district|\s+map|$)", user_msg)
    if match:
        return match.group(1).strip()
    return "Karnataka"


def build_dataset_signature(region: str, metric_key: str,
                             district_col: str, value_col: str,
                             source: str) -> Dict:
    """
    Generate a dataset signature for validation and anti-hallucination checks.
    This signature is attached to every dataset and compared before map generation.
    """
    metric = METRIC_ALIASES.get(metric_key, {})
    return {
        "topic": metric.get("label", metric_key.title()),
        "geography": f"{region} Districts",
        "metric_column": value_col,
        "region_column": district_col,
        "metric_key": metric_key,
        "region": region,
        "source": source,
    }


def validate_dataset_signature(signature: Dict, user_msg: str) -> Dict:
    """
    Validate that the user request matches the active dataset signature.
    Returns {"valid": bool, "reason": str}
    """
    if not signature:
        return {"valid": False, "reason": "No active dataset signature found."}

    msg = user_msg.lower()
    region = signature.get("region", "").lower()
    topic  = signature.get("topic", "").lower()

    # Geography mismatch check
    if region and region not in msg:
        # Allow if user doesn't mention any conflicting geography
        conflicting = ["india", "maharashtra", "tamilnadu", "kerala", "andhra"]
        if any(c in msg for c in conflicting if c != region):
            return {
                "valid": False,
                "reason": f"Geography mismatch: active dataset is {signature.get('geography')} "
                          f"but request mentions a different region."
            }

    # Confidence check: topic mismatch (warn, don't hard-block for uploaded CSVs)
    if signature.get("source") == "atlas_internal_baseline":
        metric_key = signature.get("metric_key", "")
        metric_hints = {
            "rainfall":   ["rain", "monsoon", "precipitation", "rainfall"],
            "population": ["population", "people", "demographic"],
            "literacy":   ["literacy", "education", "literate"],
            "gdp":        ["gdp", "income", "economic", "gdp index"],
        }
        hints = metric_hints.get(metric_key, [])
        if hints and not any(h in msg for h in hints + ["map", "choropleth", "visualize", "generate", "create", "show"]):
            return {
                "valid": False,
                "reason": f"Topic mismatch: active dataset is {topic} but request "
                          f"appears to request different data. Please upload a new CSV."
            }

    return {"valid": True, "reason": "Dataset signature validated."}


def generate_dataset(user_msg: str) -> Dict:
    """
    Generate a fresh per-request dataset. No global state, no caching.
    Attaches a dataset_signature for downstream validation.
    """
    metric_key = infer_metric(user_msg)
    region     = infer_region(user_msg)
    metric     = METRIC_ALIASES[metric_key]

    rows: List[Dict] = [
        {"district": district, metric["column"]: value}
        for district, value in zip(KARNATAKA_DISTRICTS, metric["values"])
    ]

    signature = build_dataset_signature(
        region=region,
        metric_key=metric_key,
        district_col="district",
        value_col=metric["column"],
        source="atlas_internal_baseline",
    )

    return {
        "region":           region,
        "metric_key":       metric_key,
        "district_col":     "district",
        "value_col":        metric["column"],
        "dataset_label":    f"{region} District {metric['label']}",
        "source":           "atlas_internal_baseline",
        "rows":             rows,
        "dataset_signature": signature,
    }


def signature_from_csv(csv_path: str, district_col: str,
                       value_col: str, user_msg: str = "") -> Dict:
    """
    Build a dataset signature from an uploaded CSV for validation.
    """
    region = infer_region(user_msg) if user_msg else "Uploaded"
    return build_dataset_signature(
        region=region,
        metric_key=value_col,
        district_col=district_col,
        value_col=value_col,
        source="uploaded_csv",
    )
