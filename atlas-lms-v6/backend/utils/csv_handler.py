"""utils/csv_handler.py — CSV parsing for pasted and uploaded data"""
import csv, re, os, uuid

def parse_pasted(text):
    rows = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line: continue
        if "\t" in line:
            parts = line.split("\t")
        elif "," in line:
            parts = next(csv.reader([line]))
        else:
            parts = re.split(r"\s{2,}", line)
        rows.append([p.strip() for p in parts])
    return rows

def save_csv(rows, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    filename = f"pasted_{uuid.uuid4().hex[:8]}.csv"
    filepath = os.path.join(data_dir, filename)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return filepath
