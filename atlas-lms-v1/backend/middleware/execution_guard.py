"""
middleware/execution_guard.py
Intercepts execution requests and enforces permission flow.
"""
from services.permission_manager import (
    requires_permission, is_confirmation, is_denial,
    store_pending, get_pending, clear_pending, permission_prompt
)


def check_execution_guard(user_msg: str, session_id: str,
                           intent: dict, action_params: dict) -> dict:
    """
    Main guard function. Call this before any map/code execution.

    Returns:
        {
          "allowed":  bool,       # True = proceed with execution
          "waiting":  bool,       # True = waiting for user approval
          "denied":   bool,       # True = user denied
          "reply":    str | None  # Message to show user if not allowed
        }
    """
    msg_lower = user_msg.lower().strip()

    # ── Check if this is a reply to a pending permission request ──
    pending = get_pending(session_id)
    if pending:
        if is_confirmation(msg_lower):
            clear_pending(session_id)
            return {"allowed": True, "waiting": False, "denied": False,
                    "reply": None, "params": pending.get("params", {})}
        if is_denial(msg_lower):
            clear_pending(session_id)
            return {"allowed": False, "waiting": False, "denied": True,
                    "reply": "Map generation was cancelled because permission was denied.",
                    "params": pending.get("params", {})}
        # User said something else while permission pending — remind them
        return {"allowed": False, "waiting": True, "denied": False,
                "reply": "This request requires backend map generation.\nAllow execution?\n[YES] [NO]"}

    # ── New request — check if permission needed ──
    if requires_permission(user_msg, intent):
        action_type = "map" if intent.get("is_map") else "code"
        store_pending(session_id, action_type, action_params)
        msg = permission_prompt(action_type, action_params)
        return {"allowed": False, "waiting": True, "denied": False, "reply": msg}

    # ── No permission needed ──
    return {"allowed": True, "waiting": False, "denied": False, "reply": None}
