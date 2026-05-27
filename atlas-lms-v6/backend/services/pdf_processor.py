"""
services/pdf_processor.py
PDF text extraction with 4-method fallback chain.
Methods: PyMuPDF → pdfplumber → pypdf → pypdf2
If all fail: returns install instructions clearly.
"""
import os, re


def extract_text(pdf_path: str) -> dict:
    """
    Extract text from PDF.
    Returns { success, text, pages, method } or { success:False, error }.
    """
    if not os.path.exists(pdf_path):
        return {"success": False, "error": "PDF file not found on server.", "text": ""}

    # ── Method 1: PyMuPDF (best quality) ────────────────────────────────
    try:
        import fitz
        doc   = fitz.open(pdf_path)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        full  = "\n\n".join(p for p in pages if p.strip())
        if full.strip():
            return {"success":True,"text":full,"pages":len(pages),"method":"PyMuPDF","preview":full[:600]}
    except ImportError:
        pass
    except Exception:
        pass

    # ── Method 2: pdfplumber ─────────────────────────────────────────────
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for pg in pdf.pages:
                t = pg.extract_text()
                if t and t.strip(): pages.append(t)
        full = "\n\n".join(pages)
        if full.strip():
            return {"success":True,"text":full,"pages":len(pages),"method":"pdfplumber","preview":full[:600]}
    except ImportError:
        pass
    except Exception:
        pass

    # ── Method 3: pypdf ──────────────────────────────────────────────────
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages  = [p.extract_text() or "" for p in reader.pages]
        full   = "\n\n".join(p for p in pages if p.strip())
        if full.strip():
            return {"success":True,"text":full,"pages":len(pages),"method":"pypdf","preview":full[:600]}
    except ImportError:
        pass
    except Exception:
        pass

    # ── Method 4: PyPDF2 (legacy) ────────────────────────────────────────
    try:
        import PyPDF2
        with open(pdf_path,"rb") as f:
            reader = PyPDF2.PdfReader(f)
            pages  = [p.extract_text() or "" for p in reader.pages]
        full = "\n\n".join(p for p in pages if p.strip())
        if full.strip():
            return {"success":True,"text":full,"pages":len(pages),"method":"PyPDF2","preview":full[:600]}
    except ImportError:
        pass
    except Exception:
        pass

    # ── All methods failed ────────────────────────────────────────────────
    return {
        "success": False,
        "text":    "",
        "error": (
            "No PDF library found. Install one with:\n"
            "  pip install PyMuPDF --break-system-packages\n"
            "OR\n"
            "  pip install pdfplumber --break-system-packages\n"
            "OR\n"
            "  pip install pypdf --break-system-packages"
        ),
    }


def process_and_store(pdf_path: str, file_id: str, filename: str,
                      project_id: str = None, session_id: str = None) -> dict:
    """Extract PDF, chunk, store in vector memory. Returns metadata."""
    result = extract_text(pdf_path)
    if not result["success"]:
        return {
            "success":  False,
            "file_id":  file_id,
            "filename": filename,
            "error":    result.get("error",""),
            "preview":  result.get("error",""),
        }

    text = result["text"]

    # Store in vector memory for RAG
    try:
        from services.vector_memory import store_document
        namespace = project_id or session_id or file_id
        store_document(file_id, text, namespace, filename, "pdf")
    except Exception:
        pass

    tables = _extract_tables(text)

    return {
        "success":    True,
        "file_id":    file_id,
        "filename":   filename,
        "pages":      result.get("pages",0),
        "method":     result.get("method",""),
        "chars":      len(text),
        "text":       text,          # full text for LLM context
        "preview":    text[:600],
        "has_tables": len(tables) > 0,
        "tables":     tables[:3],
    }


def _extract_tables(text: str) -> list:
    tables = []
    lines  = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r'^[A-Za-z][\w\s]+,\s*[\d]', line):
            tbl = [line]
            j   = i + 1
            while j < len(lines) and re.match(r'^[A-Za-z][\w\s]+,\s*[\d]', lines[j].strip()):
                tbl.append(lines[j].strip())
                j += 1
            if len(tbl) >= 3:
                tables.append("\n".join(tbl))
            i = j
        else:
            i += 1
    return tables
