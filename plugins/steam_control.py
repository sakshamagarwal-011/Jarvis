"""
Steam Control Plugin for JARVIS.

Reverse-engineered Steam local architecture:
- Windows Registry inspection for Steam paths and active game telemetry (`RunningAppID`)
- Steam VDF / ACF manifest parsing across all library drives (`libraryfolders.vdf`)
- Game launch and navigation via Steam URL protocol (`steam://run/`, `steam://open/`)
"""
import difflib
import glob
import os
import re
import subprocess
import winreg
from typing import Optional

PLUGIN = {
    "name": "steam_control",
    "description": (
        "Controls Steam on your computer. Actions include: 'launch_game' (by name or ID), "
        "'list_games', 'current_game' (check what game is playing), 'open_friends', "
        "'open_downloads', or 'open_steam'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action: 'launch_game', 'list_games', 'current_game', 'open_friends', 'open_downloads', or 'open_steam'."
            },
            "game": {
                "type": "STRING",
                "description": "Name or App ID of the game to launch when action is 'launch_game'."
            }
        },
        "required": ["action"]
    }
}


def _get_steam_registry_value(value_name: str):
    """Read a key from HKCU\\Software\\Valve\\Steam."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            return val
    except Exception:
        return None


def _get_steam_path() -> Optional[str]:
    """Retrieve Steam root installation directory."""
    path = _get_steam_registry_value("SteamPath")
    if path and os.path.exists(path):
        return os.path.normpath(path)
    # Common fallback defaults
    for p in [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]:
        if os.path.exists(p):
            return p
    return None


def _get_library_folders(steam_path: str) -> list[str]:
    """Parse libraryfolders.vdf to locate all Steam game libraries across all drives."""
    libraries = [os.path.join(steam_path, "steamapps")]
    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if not os.path.exists(vdf_path):
        return libraries

    try:
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        # Find paths defined like "path" "D:\\SteamLibrary"
        found = re.findall(r'"path"\s+"([^"]+)"', content)
        for p in found:
            norm = os.path.normpath(p.replace("\\\\", "\\"))
            apps_dir = os.path.join(norm, "steamapps")
            if os.path.exists(apps_dir) and apps_dir not in libraries:
                libraries.append(apps_dir)
    except Exception:
        pass
    return libraries


def _scan_installed_games() -> dict[str, dict]:
    """Scan ACF manifests across all Steam libraries to return {appid: {name, appid, path}}."""
    steam_path = _get_steam_path()
    if not steam_path:
        return {}

    libraries = _get_library_folders(steam_path)
    games = {}

    for lib in libraries:
        manifests = glob.glob(os.path.join(lib, "appmanifest_*.acf"))
        for m in manifests:
            try:
                with open(m, "r", encoding="utf-8", errors="ignore") as f:
                    data = f.read()
                appid_m = re.search(r'"appid"\s+"(\d+)"', data)
                name_m = re.search(r'"name"\s+"([^"]+)"', data)
                if appid_m and name_m:
                    aid = appid_m.group(1)
                    name = name_m.group(1)
                    # Filter out Steamworks common redistributables
                    if "Steamworks" not in name and "Proton" not in name:
                        games[aid] = {"appid": aid, "name": name, "manifest": m}
            except Exception:
                continue
    return games


def _find_game_appid(target: str, installed_games: dict[str, dict]) -> Optional[str]:
    """Resolve a target name or ID to an installed AppID via exact or fuzzy matching."""
    target_clean = target.strip()
    if target_clean in installed_games:
        return target_clean

    # Case-insensitive name match
    lower_target = target_clean.lower()
    names = {g["name"].lower(): g["appid"] for g in installed_games.values()}

    if lower_target in names:
        return names[lower_target]

    # Partial / substring match
    for name, aid in names.items():
        if lower_target in name:
            return aid

    # Fuzzy match fallback
    matches = difflib.get_close_matches(lower_target, list(names.keys()), n=1, cutoff=0.5)
    if matches:
        return names[matches[0]]

    return None


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    game_arg = str(parameters.get("game", "")).strip()

    steam_path = _get_steam_path()
    if not steam_path:
        return "Sir, Steam could not be located on this machine."

    try:
        if action in ("current_game", "playing", "active_game"):
            running_id = _get_steam_registry_value("RunningAppID")
            if running_id and running_id > 0:
                games = _scan_installed_games()
                name = games.get(str(running_id), {}).get("name", f"AppID {running_id}")
                res = f"Sir, you are currently playing {name}."
            else:
                res = "Sir, no Steam game is currently running."

        elif action in ("list_games", "installed_games", "library"):
            games = _scan_installed_games()
            if not games:
                res = "Sir, no installed Steam games were detected."
            else:
                names = [g["name"] for g in games.values()]
                res = f"Sir, you have {len(names)} installed Steam games: {', '.join(names[:8])}."

        elif action in ("launch_game", "launch", "play"):
            if not game_arg:
                return "Sir, please tell me which game you would like to play."
            games = _scan_installed_games()
            appid = _find_game_appid(game_arg, games)
            if appid:
                game_name = games[appid]["name"]
                os.startfile(f"steam://run/{appid}")
                res = f"Launching {game_name} on Steam, Sir. Enjoy!"
            else:
                # If unknown, try launching by URI query or opening store
                os.startfile(f"steam://open/search/{game_arg.replace(' ', '%20')}")
                res = f"Could not find an installed game matching '{game_arg}', opened Steam search instead."

        elif action in ("open_friends", "friends"):
            os.startfile("steam://open/friends")
            res = "Opening your Steam friends list, Sir."

        elif action in ("open_downloads", "downloads"):
            os.startfile("steam://open/downloads")
            res = "Opening Steam download manager."

        elif action in ("open_steam", "open"):
            steam_exe = os.path.join(steam_path, "steam.exe")
            if os.path.exists(steam_exe):
                subprocess.Popen([steam_exe])
            else:
                os.startfile("steam:")
            res = "Opening Steam client, Sir."

        else:
            os.startfile(f"steam://run/{game_arg}" if game_arg else "steam:")
            res = f"Executed Steam action for '{action}'."

    except Exception as e:
        res = f"Sir, Steam control encountered an error: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
