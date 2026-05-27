"""
middleware/execution_guard.py
Map requests are ALWAYS auto-approved — no YES/NO permission prompt.
This implements fully automatic map generation flow per architecture diagram.
"""
from services.permission_manager import is_confirmation, is_denial, get_pending, clear_pending


def check_execution_guard(user_msg: str, session_id: str,
                           intent: dict, action_params: dict) -> dict:
    """
    MAP REQUESTS: always auto-allowed. No permission prompt.
    Returns: { allowed, waiting, denied, reply }
    """
    msg_lower = user_msg.lower().strip()

    # Map intent = always auto-approved, clear any stale state
    if intent.get("is_map") or action_params.get("district_col"):
        clear_pending(session_id)
        return {"allowed": True, "waiting": False, "denied": False, "reply": None}

    # Handle stale pending state
    pending = get_pending(session_id)
    if pending:
        if pending.get("type") == "map":
            clear_pending(session_id)
            return {"allowed": True, "waiting": False, "denied": False, "reply": None}
        if is_confirmation(msg_lower):
            clear_pending(session_id)
            return {"allowed": True, "waiting": False, "denied": False,
                    "reply": None, "params": pending.get("params", {})}
        if is_denial(msg_lower):
            clear_pending(session_id)
            return {"allowed": False, "waiting": False, "denied": True,
                    "reply": "Operation cancelled.", "params": {}}

    # All other requests: auto-allow
    return {"allowed": True, "waiting": False, "denied": False, "reply": None}
