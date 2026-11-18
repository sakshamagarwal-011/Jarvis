"""
actions/hand_control.py — Voice + Hand Hybrid Control Action for Mark LV.

Enables Gemini Live to activate, deactivate, and direct the holographic
hand gesture tracking and holographic file explorer via natural speech.

Examples:
- "Jarvis, activate hand control."
- "Jarvis, disable hand control."
- "Jarvis, open my files."
- "Jarvis, preview this document."
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Any

from actions.file_controller import _resolve_path, _is_safe_path
from memory.config_manager import save_hand_tracking_enabled


def hand_control(
    action: str,
    target: str = "",
    player: Any = None,
    speak: Any = None,
    response: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Executes high-level voice commands for the holographic hand gesture system
    and holographic file explorer.
    """
    cmd = (action or "").strip().lower()
    t_name = (target or "").strip()

    print(f"[HandControl] Voice command: action='{cmd}', target='{t_name}'")

    if player is None:
        return "Interface is not available to execute hand control command."

    # 1. Enable / Activate Hand Control
    if cmd in ("activate", "enable", "start", "on"):
        save_hand_tracking_enabled(True)
        if hasattr(player, "set_hand_tracking"):
            ok, msg = player.set_hand_tracking(True)
            return msg if ok else f"Could not activate hand tracking: {msg}"
        return "Hand gesture control is now active."

    # 2. Disable / Deactivate Hand Control
    elif cmd in ("deactivate", "disable", "stop", "off"):
        save_hand_tracking_enabled(False)
        if hasattr(player, "set_hand_tracking"):
            ok, msg = player.set_hand_tracking(False)
            return msg if ok else f"Could not disable hand tracking: {msg}"
        return "Hand gesture control disabled."

    # 3. Open Holographic File Explorer
    elif cmd in ("open_files", "show_files", "files", "browse"):
        p = _resolve_path(t_name) if t_name else Path.home() / "Desktop"
        if not _is_safe_path(p):
            return f"Access denied: {p}"
        if hasattr(player, "show_holographic_files"):
            player.show_holographic_files(str(p))
            return f"Holographic file explorer opened at {p.name or str(p)}."
        return "Holographic file explorer displayed."

    # 4. Preview File
    elif cmd in ("preview", "view", "read"):
        if not t_name:
            return "Please specify which document or file you want to preview."
        if hasattr(player, "preview_holographic_file"):
            ok, msg = player.preview_holographic_file(t_name)
            return msg
        return f"Previewing {t_name}."

    # 5. Open Folder
    elif cmd in ("open_folder", "cd", "enter"):
        if not t_name:
            return "Please specify which folder to open."
        if hasattr(player, "open_holographic_folder"):
            ok, msg = player.open_holographic_folder(t_name)
            return msg
        return f"Opened folder {t_name}."

    # 6. Select File
    elif cmd in ("select", "choose", "highlight"):
        if not t_name:
            return "Please specify which file you want to select."
        if hasattr(player, "select_holographic_file"):
            ok, msg = player.select_holographic_file(t_name)
            return msg
        return f"Selected {t_name}."

    else:
        return f"Unknown hand control action: {action}. Supported: activate, disable, open_files, preview, open_folder, select."


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "hand_control",
    "description": (
        "Controls the Iron Man holographic hand tracking system and visual file explorer. "
        "Use this when the user asks to activate hand control, disable hand control, open files, "
        "show documents, preview a file, or navigate folders using voice."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "The action to perform: 'activate' (turn on hand tracking), "
                    "'disable' (turn off hand tracking), 'open_files' (open holographic explorer), "
                    "'preview' (preview document), 'open_folder' (open specific folder), "
                    "'select' (select a file)."
                ),
            },
            "target": {
                "type": "STRING",
                "description": "Optional file name, folder name, or directory shortcut (e.g. 'desktop', 'documents', 'report.pdf').",
            },
        },
        "required": [
            "action",
        ],
    },
    "handler": hand_control,
}
