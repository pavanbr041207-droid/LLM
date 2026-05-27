"""
services/context_manager.py
Build full ChatGPT-like stateful prompt for every LLM call.

Prompt structure:
  SYSTEM PROMPT
  + PROJECT MEMORY
  + CONVERSATION SUMMARY
  + RECENT MESSAGES (last N)
  + ACTIVE DATAFRAME REFERENCE
  + LATEST USER MESSAGE

Never sends only the latest message — always full context.
"""
import os
from utils.storage import storage_path, read_json, now

STORAGE = storage_path()

CONTEXT_WINDOW  = 10   # recent messages to include
SUMMARY_TRIGGER = 20   # summarize when chat > this many messages


ATLAS_SYSTEM = """You are Atlas AI — a stateful geographic intelligence assistant.

MEMORY RULES:
- You have access to conversation history and a persistent session dataframe.
- When the user says "above data", "those districts", "previous result", "use that data" — 
  ALWAYS use the ACTIVE DATAFRAME provided below. Do NOT ask the user to re-paste.
- When structured data (table, CSV, list of values) appears, acknowledge it has been stored.
- When user asks for a map, check ACTIVE DATAFRAME first. Use it directly.

ANTI-HALLUCINATION:
- Never invent district names or values.
- Always use verified data from conversation or active dataframe.
- If data is unavailable, say so clearly.

DATA CONTINUITY:
- You remember all previous outputs in this conversation.
- Reference previous results naturally: "As I showed earlier..."
"""


def _load_messages(session_id: str) -> list:
    path = os.path.join(STORAGE, "chats", f"{session_id}.json")
    data = read_json(path, {})
    return data.get("messages", [])


def _format_recent(messages: list, n: int = CONTEXT_WINDOW) -> str:
    recent = messages[-n:] if len(messages) > n else messages
    lines = []
    for m in recent:
        role    = "User" if m["role"] == "user" else "Atlas AI"
        content = m.get("content", "")[:800]  # truncate very long messages
        if content.strip():
            lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def _dataframe_context(session_id: str) -> str:
    try:
        from services.session_state import get_session_state
        state  = get_session_state(session_id)
        ds     = state.get("latest_dataset")
        if not ds: return ""
        cols   = ds.get("columns", [])
        rows   = ds.get("rows", 0)
        geo    = ds.get("geo_scope", "unknown")
        gcol   = ds.get("geo_col", "")
        vcol   = ds.get("value_col", "")
        label  = ds.get("label", "")
        path   = ds.get("csv_path","")

        # Read first few rows for inline context
        preview = ""
        if path and os.path.exists(path):
            try:
                import pandas as pd
                df = pd.read_csv(path, nrows=8)
                preview = df.to_csv(index=False)
            except Exception:
                pass

        block = (
            f"\n\n=== ACTIVE DATAFRAME ===\n"
            f"Label: {label}\n"
            f"Geography: {geo}\n"
            f"Columns: {', '.join(cols)}\n"
            f"District column: {gcol} | Value column: {vcol}\n"
            f"Rows: {rows}\n"
        )
        if preview:
            block += f"Preview (first 8 rows):\n{preview}"
        block += "=== END DATAFRAME ===\n"
        return block
    except Exception:
        return ""


def _project_context(project_id: str) -> str:
    if not project_id: return ""
    try:
        path = os.path.join(STORAGE, "projects", f"{project_id}.json")
        proj = read_json(path, {})
        name = proj.get("name","")
        desc = proj.get("description","")
        if name:
            return f"\n\n=== PROJECT CONTEXT ===\nProject: {name}\n{desc}\n=== END PROJECT ===\n"
    except Exception:
        pass
    return ""


def _summary_context(session_id: str) -> str:
    try:
        from services.session_state import get_conversation_summary
        s = get_conversation_summary(session_id)
        if s:
            return f"\n\n=== CONVERSATION SUMMARY ===\n{s}\n=== END SUMMARY ===\n"
    except Exception:
        pass
    return ""


def build_prompt(user_msg: str, session_id: str,
                 project_id: str = None, extra_system: str = "") -> tuple[str, str]:
    """
    Build full stateful prompt.
    Returns (system_prompt, user_message_with_context)
    """
    messages = _load_messages(session_id)

    system  = ATLAS_SYSTEM
    if extra_system:
        system += f"\n\n{extra_system}"

    # Project context
    system += _project_context(project_id)

    # Conversation summary (for long chats)
    summary_ctx = _summary_context(session_id)

    # Active dataframe reference
    df_ctx = _dataframe_context(session_id)

    # Recent message history
    history_ctx = ""
    if messages:
        # Exclude the latest user message (we'll add it separately)
        history = messages[:-1] if messages[-1].get("role") == "user" else messages
        if history:
            history_ctx = f"\n\n=== CONVERSATION HISTORY ===\n{_format_recent(history)}\n=== END HISTORY ===\n"

    # Compose full user-side context
    context = summary_ctx + df_ctx + history_ctx
    full_user_msg = f"{context}\n\nUser (current message): {user_msg}" if context.strip() else user_msg

    # Trigger background summarization if chat is long
    if len(messages) > SUMMARY_TRIGGER and len(messages) % 10 == 0:
        _trigger_summarize(session_id, messages)

    return system, full_user_msg


def _trigger_summarize(session_id: str, messages: list):
    """
    Generate a rolling summary of the conversation.
    Runs as a background update — does not block response.
    """
    try:
        from utils.llm import ask_llm
        from services.session_state import store_summary, get_conversation_summary

        existing = get_conversation_summary(session_id)
        recent   = _format_recent(messages[-20:], n=20)
        prompt   = (
            f"Existing summary:\n{existing}\n\n"
            f"New conversation:\n{recent}\n\n"
            "Write a concise 3-5 sentence summary of what was discussed, "
            "what data was generated, and what maps were created. "
            "Focus on geographic data topics and key findings."
        )
        summary = ask_llm(prompt, system_prompt="You are a conversation summarizer. Be concise.")
        if summary and "❌" not in summary:
            store_summary(session_id, summary)
    except Exception:
        pass
