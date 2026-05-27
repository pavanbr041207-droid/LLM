"""
services/permission_manager.py
Execution permission system.
Before running Python/matplotlib/map code, ask user approval.
Stores pending actions until confirmed.
"""
import os, json
from datetime import datetime, timedelta
from utils.storage import storage_path, new_id

STORAGE      = storage_path()
EXEC_DIR     = os.path.join(STORAGE, "execution_state")
os.makedirs(EXEC_DIR, exist_ok=True)

# ── Phrases that mean YES ──
CONFIRM_WORDS = {
    "yes","yeah","yep","ok","okay","sure","proceed",
    "allow","continue","go ahead","confirm","approved",
    "do it","run it","execute","generate","make it",
    "yes please","go","start",
}

# ── Phrases that mean NO ──
DENY_WORDS = {
    "no","nope","cancel","deny","stop","don't","do not",
    "skip","abort","never mind","nevermind","reject",
}


def requires_permission(user_msg: str, intent: dict) -> bool:
    """
    Decide if this action needs user permission before executing.
    Returns True if permission needed.
    """
    if not intent: return False
    msg = user_msg.lower().strip()

    # Already a confirmation/denial — no need to ask again
    if is_confirmation(msg) or is_denial(msg):
        return False

    # Only execution-layer work needs permission. Dataset requests, uploads,
    # retrieval, memory, and normal chat never reach this branch.
    return bool(intent.get("needs_execution") or intent.get("execution_intent"))


def is_confirmation(msg: str) -> bool:
    msg = msg.lower().strip().rstrip("!.,")
    return msg in CONFIRM_WORDS


def is_denial(msg: str) -> bool:
    msg = msg.lower().strip().rstrip("!.,")
    return msg in DENY_WORDS


def store_pending(session_id: str, action_type: str, params: dict) -> str:
    """Store a pending action awaiting user approval."""
    action_id   = new_id()
    pending     = {
        "id":         action_id,
        "session_id": session_id,
        "type":       action_type,
        "params":     params,
        "created":    datetime.now().isoformat(),
        "expires":    (datetime.now() + timedelta(minutes=10)).isoformat(),
    }
    path = os.path.join(EXEC_DIR, f"{session_id}_pending.json")
    with open(path, "w") as f:
        json.dump(pending, f)
    return action_id


def get_pending(session_id: str) -> dict:
    """Retrieve pending action for session."""
    path = os.path.join(EXEC_DIR, f"{session_id}_pending.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        # Check expiry
        expires = datetime.fromisoformat(data["expires"])
        if datetime.now() > expires:
            clear_pending(session_id)
            return None
        return data
    except Exception:
        return None


def clear_pending(session_id: str):
    """Clear pending action after execution or denial."""
    path = os.path.join(EXEC_DIR, f"{session_id}_pending.json")
    if os.path.exists(path):
        os.remove(path)


def permission_prompt(action_type: str, params: dict) -> str:
    """Build a clear permission request message for the user."""
    if action_type == "map":
        return "This request requires backend map generation.\nAllow execution?\n[YES] [NO]"
    elif action_type == "code":
        return (
            f"**Permission Required**\n\n"
            f"I need to execute Python code on your local machine.\n\n"
            f"**Allow execution?** Type `yes` to proceed or `no` to cancel."
        )
    return (
        f"**Permission Required**\n\n"
        f"This operation requires external tools. Allow execution?\n\n"
        f"Type `yes` to proceed or `no` to cancel."
    )
