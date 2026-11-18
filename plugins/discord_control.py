"""
Discord Control Plugin for JARVIS.

Reverse-engineered Discord integration:
- Process detection and launcher via AppData Update.exe / Discord.exe
- Discord deep-linking URI protocol (discord://)
- Window focus and voice shortcut integration
"""
import glob
import os
import subprocess
from typing import Optional

PLUGIN = {
    "name": "discord_control",
    "description": (
        "Controls Discord on your computer. Actions include: 'open', 'status', "
        "'focus', 'open_channel', 'open_dm', or 'toggle_mute'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "The action: 'open', 'status', 'focus', 'open_channel', 'open_dm', or 'toggle_mute'."
            },
            "target": {
                "type": "STRING",
                "description": "Server/channel ID or user ID when navigating channels or DMs."
            }
        },
        "required": ["action"]
    }
}


def _find_discord_exe() -> Optional[str]:
    """Find Discord executable in AppData."""
    local = os.environ.get("LOCALAPPDATA", "")
    # Check Update.exe launcher first (standard Discord shortcut target)
    update_exe = os.path.join(local, "Discord", "Update.exe")
    if os.path.exists(update_exe):
        return update_exe
    # Check versioned folders
    matches = glob.glob(os.path.join(local, "Discord", "app-*", "Discord.exe"))
    if matches:
        return sorted(matches)[-1]
    return None


def _is_discord_running() -> bool:
    """Check if any Discord process is currently active."""
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if p.info["name"] and "discord" in p.info["name"].lower():
                return True
    except Exception:
        pass
    return False


def _focus_discord() -> bool:
    """Bring Discord to the foreground."""
    try:
        import win32gui
        target_hwnd = None

        def enum_cb(hwnd, _):
            nonlocal target_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "Discord" in title:
                    target_hwnd = hwnd

        win32gui.EnumWindows(enum_cb, None)
        if target_hwnd:
            win32gui.ShowWindow(target_hwnd, 9)  # SW_RESTORE
            win32gui.SetForegroundWindow(target_hwnd)
            return True
    except Exception:
        pass
    return False


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    target = str(parameters.get("target", "")).strip()

    running = _is_discord_running()

    try:
        if action == "status":
            if running:
                res = "Sir, Discord is currently running in the background."
            else:
                res = "Sir, Discord is not currently running."

        elif action in ("open", "launch", "start"):
            if running:
                _focus_discord()
                res = "Discord is already running, brought it to the foreground, Sir."
            else:
                exe = _find_discord_exe()
                if exe:
                    if exe.endswith("Update.exe"):
                        subprocess.Popen([exe, "--processStart", "Discord.exe"])
                    else:
                        subprocess.Popen([exe])
                    res = "Launching Discord now, Sir."
                else:
                    # Fallback to URI scheme
                    try:
                        os.startfile("discord:")
                        res = "Launching Discord via application protocol."
                    except Exception as e:
                        res = f"Could not find Discord executable: {e}"

        elif action == "focus":
            if _focus_discord():
                res = "Discord brought to focus, Sir."
            elif not running:
                res = "Discord is not currently open, Sir."
            else:
                res = "Could not bring Discord window to the foreground."

        elif action in ("open_channel", "channel"):
            if not target:
                return "Sir, please specify the channel or server identifier."
            uri = f"discord://-/channels/{target}"
            try:
                os.startfile(uri)
                res = f"Opening Discord channel {target}."
            except Exception as e:
                res = f"Failed to navigate Discord channel: {e}"

        elif action in ("open_dm", "dm", "message"):
            if not target:
                return "Sir, please specify the user identifier for direct messaging."
            uri = f"discord://-/channels/@me/{target}"
            try:
                os.startfile(uri)
                res = f"Opening direct message in Discord for {target}."
            except Exception as e:
                res = f"Failed to open direct message: {e}"

        elif action in ("toggle_mute", "mute"):
            # Discord global default mute chord (Ctrl+Shift+M)
            import pyautogui
            pyautogui.hotkey("ctrl", "shift", "m")
            res = "Toggled Discord microphone mute."

        elif action in ("toggle_deafen", "deafen"):
            import pyautogui
            pyautogui.hotkey("ctrl", "shift", "d")
            res = "Toggled Discord deafen."

        else:
            if running:
                _focus_discord()
                res = f"Discord is running. Executed action: {action}"
            else:
                res = f"Discord is not running to perform '{action}'."

    except Exception as e:
        res = f"Sir, Discord control encountered an error: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
