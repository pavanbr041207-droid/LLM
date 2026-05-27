"""
services/file_router.py
Detect uploaded file type and route to correct processor.
Returns unified result dict for chat_routes to use.
"""
import os


IMAGE_EXTS = {".png",".jpg",".jpeg",".webp",".gif",".bmp"}
PDF_EXTS   = {".pdf"}
DOCX_EXTS  = {".docx",".doc"}
EXCEL_EXTS = {".xlsx",".xls",".csv"}
TEXT_EXTS  = {".txt",".md",".json"}


def get_file_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTS:  return "image"
    if ext in PDF_EXTS:    return "pdf"
    if ext in DOCX_EXTS:   return "docx"
    if ext in EXCEL_EXTS:  return "excel"
    if ext in TEXT_EXTS:   return "text"
    return "unknown"


def route_file(file_path: str, file_id: str, filename: str,
               session_id: str = None, project_id: str = None,
               user_prompt: str = "") -> dict:
    """
    Route uploaded file to correct processor.
    Returns unified result: { file_type, success, text, preview, has_dataset, ... }
    """
    ftype = get_file_type(filename)
    base  = {
        "file_id":    file_id,
        "filename":   filename,
        "file_type":  ftype,
        "file_path":  file_path,
    }

    if ftype == "image":
        try:
            from services.image_processor import analyze_image, save_image_analysis
            result = analyze_image(file_path, user_prompt)
            if result["success"]:
                save_image_analysis(session_id or file_id, file_path, result)
                # If image contains table data, try to auto-detect dataset
                if result.get("has_table"):
                    try:
                        from services.response_parser import parse_response
                        parsed = parse_response(result["text"], session_id or file_id, user_prompt)
                        result["has_dataset"]  = parsed["has_dataset"]
                        result["dataset_meta"] = parsed.get("dataset_meta")
                        result["dataset_notice"] = parsed.get("dataset_notice","")
                    except Exception: pass
            base.update(result)
            return base
        except Exception as e:
            return {**base, "success": False, "error": str(e)}

    elif ftype == "pdf":
        try:
            from services.pdf_processor import process_and_store
            result = process_and_store(file_path, file_id, filename, project_id, session_id)
            base.update(result)
            # Auto-detect datasets in PDF
            if result.get("success") and result.get("has_tables"):
                for tbl in result.get("tables", [])[:1]:
                    try:
                        from services.response_parser import parse_response
                        parsed = parse_response(tbl, session_id or file_id)
                        if parsed["has_dataset"]:
                            base["has_dataset"]    = True
                            base["dataset_meta"]   = parsed["dataset_meta"]
                            base["dataset_notice"] = parsed["dataset_notice"]
                            break
                    except Exception: pass
            return base
        except Exception as e:
            return {**base, "success": False, "error": str(e)}

    elif ftype == "docx":
        try:
            from services.docx_processor import process_docx
            result = process_docx(file_path, file_id, filename, session_id, project_id)
            base.update(result)
            return base
        except Exception as e:
            return {**base, "success": False, "error": str(e)}

    elif ftype == "excel":
        try:
            from services.excel_processor import process_excel
            result = process_excel(file_path, file_id, filename, session_id, project_id)
            base.update(result)
            base["has_dataset"] = result.get("has_geo", False)
            if base["has_dataset"]:
                base["dataset_notice"] = (
                    f"📊 Spreadsheet loaded — {result.get('best_sheet',{}).get('rows',0)} rows detected. "
                    f"Geographic data found. Say **\"Generate map\"** to visualize."
                )
            return base
        except Exception as e:
            return {**base, "success": False, "error": str(e)}

    elif ftype == "text":
        try:
            with open(file_path, encoding="utf-8") as f:
                text = f.read()
            from services.vector_memory import store_document
            ns = project_id or session_id or file_id
            store_document(file_id, text, ns, filename, "text")
            base.update({
                "success": True,
                "text":    text,
                "preview": text[:400],
                "chars":   len(text),
            })
            return base
        except Exception as e:
            return {**base, "success": False, "error": str(e)}

    return {**base, "success": False, "error": f"Unsupported file type: {ftype}"}
