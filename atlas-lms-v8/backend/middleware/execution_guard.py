"""
middleware/execution_guard.py
Asks user permission before any map/data-to-backend generation.
YES → proceed. NO → rejection message, no map generated.
"""
from services.permission_manager import (
    is_confirmation, is_denial,
    store_pending, get_pending, clear_pending
)

PERMISSION_MSG = "This request requires backend map generation.\nAllow execution?\n[YES] [NO]"
REJECTION_MSG  = "❌ Map generation cancelled. Atlas AI cannot generate the map without backend execution permission."


def check_execution_guard(user_msg: str, session_id: str,
                           intent: dict, action_params: dict) -> dict:
    """
    Called before map generation.
    - If no pending: ask user YES/NO
    - If pending + user said YES: allow and clear
    - If pending + user said NO: deny and clear
    - If pending + user said something else: remind them
    Returns: { allowed, waiting, denied, reply, params }
    """
    msg_lower = user_msg.lower().strip()

    # ── Check if replying to a pending permission request ──
    pending = get_pending(session_id)
    if pending:
        if is_confirmation(msg_lower):
            clear_pending(session_id)
            return {
                "allowed": True, "waiting": False, "denied": False,
                "reply": None, "params": pending.get("params", {})
            }
        if is_denial(msg_lower):
            clear_pending(session_id)
            return {
                "allowed": False, "waiting": False, "denied": True,
                "reply": REJECTION_MSG, "params": {}
            }
        # User said something else while permission is pending — remind
        return {
            "allowed": False, "waiting": True, "denied": False,
            "reply": PERMISSION_MSG
        }

    # ── New map/execution request — ask permission ──
    if intent.get("is_map") or intent.get("needs_execution") or action_params.get("district_col"):
        store_pending(session_id, "map", action_params)
        return {
            "allowed": False, "waiting": True, "denied": False,
            "reply": PERMISSION_MSG
        }

    # Not a map/execution request — allow freely
    return {"allowed": True, "waiting": False, "denied": False, "reply": None}
