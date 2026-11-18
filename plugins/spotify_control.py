"""
Spotify Control Plugin for JARVIS.

Reverse-engineered Windows media controls and Spotify IPC:
- Media controls via Windows WM_APPCOMMAND (play, pause, next, previous)
- Track detection via Spotify window title inspection
- Spotify URI protocol integration (spotify:search, spotify:track, spotify:playlist)
"""
import ctypes
import os
import subprocess
import time
from typing import Optional

PLUGIN = {
    "name": "spotify_control",
    "description": (
        "Controls Spotify playback and music on the computer. Actions include: "
        "'play', 'pause', 'play_pause', 'next', 'previous', 'current_track', "
        "'volume_up', 'volume_down', 'mute', or 'search' to search and play a song/artist."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "The action: 'play', 'pause', 'play_pause', 'next', 'previous', 'current_track', 'volume_up', 'volume_down', 'mute', 'search', or 'open'."
            },
            "query": {
                "type": "STRING",
                "description": "Search term, artist, song, or playlist name when action is 'search'."
            }
        },
        "required": ["action"]
    }
}

# Windows AppCommand constants for media keys
WM_APPCOMMAND = 0x0319
APPCOMMAND_MEDIA_PLAY_PAUSE = 0xE0000
APPCOMMAND_MEDIA_NEXTTRACK  = 0xB0000
APPCOMMAND_MEDIA_PREVIOUSTRACK = 0xC0000
APPCOMMAND_VOLUME_MUTE      = 0x80000
APPCOMMAND_VOLUME_DOWN      = 0x90000
APPCOMMAND_VOLUME_UP        = 0xA0000

# Virtual key codes
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3


def _send_media_key(vk_code: int) -> None:
    """Send a media keystroke using Windows keybd_event."""
    KEYEVENTF_KEYUP = 0x0002
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)


def _find_spotify_window() -> tuple[Optional[int], str]:
    """Inspect top-level windows to locate Spotify and extract the current track title."""
    try:
        import win32gui
        import win32process

        spotify_hwnd = None
        spotify_title = ""

        def enum_cb(hwnd, _):
            nonlocal spotify_hwnd, spotify_title
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                if cls == "Chrome_WidgetWin_0":
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        import psutil
                        proc = psutil.Process(pid)
                        if "spotify" in proc.name().lower():
                            spotify_hwnd = hwnd
                            if title and title != "Spotify" and title != "Spotify Free" and title != "Spotify Premium":
                                spotify_title = title
                    except Exception:
                        pass

        win32gui.EnumWindows(enum_cb, None)
        return spotify_hwnd, spotify_title
    except Exception:
        return None, ""


def _open_spotify() -> bool:
    """Open Spotify either via executable or via URI handler."""
    appdata = os.environ.get("APPDATA", "")
    spotify_exe = os.path.join(appdata, "Spotify", "Spotify.exe")
    if os.path.exists(spotify_exe):
        subprocess.Popen([spotify_exe])
        return True
    # Try URI launcher
    try:
        os.startfile("spotify:")
        return True
    except Exception:
        return False


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    query = str(parameters.get("query", "")).strip()

    hwnd, track_title = _find_spotify_window()

    try:
        if action in ("current_track", "what_playing", "song"):
            if track_title:
                res = f"Sir, Spotify is currently playing: {track_title}"
            elif hwnd:
                res = "Spotify is open, but playback appears to be paused."
            else:
                res = "Sir, Spotify does not appear to be running."

        elif action in ("play", "pause", "play_pause"):
            _send_media_key(VK_MEDIA_PLAY_PAUSE)
            res = "Toggled Spotify playback."

        elif action in ("next", "skip"):
            _send_media_key(VK_MEDIA_NEXT_TRACK)
            res = "Skipped to the next track on Spotify."

        elif action in ("previous", "prev", "back"):
            _send_media_key(VK_MEDIA_PREV_TRACK)
            res = "Returning to the previous track on Spotify."

        elif action in ("volume_up", "louder"):
            for _ in range(3):
                ctypes.windll.user32.SendMessageW(0xFFFF, WM_APPCOMMAND, 0, APPCOMMAND_VOLUME_UP)
            res = "Raised playback volume."

        elif action in ("volume_down", "softer", "quieter"):
            for _ in range(3):
                ctypes.windll.user32.SendMessageW(0xFFFF, WM_APPCOMMAND, 0, APPCOMMAND_VOLUME_DOWN)
            res = "Lowered playback volume."

        elif action in ("mute", "unmute"):
            ctypes.windll.user32.SendMessageW(0xFFFF, WM_APPCOMMAND, 0, APPCOMMAND_VOLUME_MUTE)
            res = "Toggled mute."

        elif action == "search":
            if not query:
                return "Sir, please specify what artist, song, or playlist to search for."
            uri = f"spotify:search:{query.replace(' ', '%20')}"
            try:
                os.startfile(uri)
                res = f"Searching Spotify for {query}."
            except Exception as e:
                res = f"Failed to open Spotify search: {e}"

        elif action == "open":
            if _open_spotify():
                res = "Opening Spotify, Sir."
            else:
                res = "Could not locate Spotify on your system. You can open it in your browser at open.spotify.com."

        else:
            # Default fallback toggle
            _send_media_key(VK_MEDIA_PLAY_PAUSE)
            res = f"Spotify action '{action}' executed."

    except Exception as e:
        res = f"Sir, Spotify control encountered an issue: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
