"""
services/pdf_processor.py
PDF text extraction using PyMuPDF (fitz) with pdfplumber fallback.
Chunks and stores in vector memory.
"""
import os, re


def extract_text(pdf_path: str) -> dict:
    """
    Extract text from PDF. Returns { success, text, pages, method }.
    Tries PyMuPDF first, then pdfplumber, then pypdf.
    """
    if not os.path.exists(pdf_path):
        return {"success": False, "error": "PDF not found", "text": ""}

    # Method 1: PyMuPDF (fastest, best quality)
    try:
        import fitz  # PyMuPDF
        doc   = fitz.open(pdf_path)
        pages = []
        for page in doc:
            pages.append(page.get_text())
        full_text = "\n\n".join(pages)
        doc.close()
        if full_text.strip():
            return {
                "success": True,
                "text":    full_text,
                "pages":   len(pages),
                "method":  "pymupdf",
                "preview": full_text[:500],
            }
    except ImportError:
        pass
    except Exception:
        pass

    # Method 2: pdfplumber
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: pages.append(t)
        full_text = "\n\n".join(pages)
        if full_text.strip():
            return {
                "success": True,
                "text":    full_text,
                "pages":   len(pages),
                "method":  "pdfplumber",
                "preview": full_text[:500],
            }
    except ImportError:
        pass
    except Exception:
        pass

    # Method 3: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages  = [p.extract_text() or "" for p in reader.pages]
        full_text = "\n\n".join(pages)
        if full_text.strip():
            return {
                "success": True,
                "text":    full_text,
                "pages":   len(pages),
                "method":  "pypdf",
                "preview": full_text[:500],
            }
    except ImportError:
        pass
    except Exception:
        pass

    return {
        "success": False,
        "text":    "",
        "error":   "No PDF library available. Install: pip install PyMuPDF --break-system-packages",
    }


def process_and_store(pdf_path: str, file_id: str, filename: str,
                      project_id: str = None, session_id: str = None) -> dict:
    """
    Extract PDF text, chunk it, store in vector memory.
    Returns metadata for frontend.
    """
    result = extract_text(pdf_path)
    if not result["success"]:
        return result

    text = result["text"]

    # Store in vector memory
    try:
        from services.vector_memory import store_document
        namespace = project_id or session_id or file_id
        store_document(file_id, text, namespace, filename, "pdf")
    except Exception:
        pass

    # Check for tables in PDF
    tables = _extract_tables(text)

    return {
        "success":   True,
        "file_id":   file_id,
        "filename":  filename,
        "pages":     result.get("pages", 0),
        "method":    result.get("method", ""),
        "chars":     len(text),
        "preview":   text[:400],
        "has_tables":len(tables) > 0,
        "tables":    tables[:3],
    }


def _extract_tables(text: str) -> list:
    """Extract CSV-like tables from PDF text."""
    tables = []
    lines  = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r'^[A-Za-z\s]+,\s*[0-9]', line):
            tbl = [line]
            j = i + 1
            while j < len(lines) and re.match(r'^[A-Za-z\s]+,\s*[0-9]', lines[j].strip()):
                tbl.append(lines[j].strip())
                j += 1
            if len(tbl) >= 3:
                tables.append("\n".join(tbl))
            i = j
        else:
            i += 1
    return tables
