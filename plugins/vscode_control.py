"""
VS Code Control Plugin for JARVIS.

Reverse-engineered VS Code integration:
- VS Code CLI dispatch (`code.cmd` / `Code.exe`)
- Deep inspection of VS Code internal SQLite database (`state.vscdb`) for recently opened workspaces
- File and folder opening with line cursor placement (`code -g`)
- Side-by-side diffing (`code --diff`)
"""
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

PLUGIN = {
    "name": "vscode_control",
    "description": (
        "Controls Visual Studio Code on your machine. Actions include: 'open_project', "
        "'open_file', 'recent_projects', 'status', 'diff', or 'new_window'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action: 'open_project', 'open_file', 'recent_projects', 'status', 'diff', or 'new_window'."
            },
            "path": {
                "type": "STRING",
                "description": "Path to file, folder, or project to open in VS Code."
            },
            "line": {
                "type": "INTEGER",
                "description": "Optional line number when opening a specific file."
            },
            "secondary_path": {
                "type": "STRING",
                "description": "Second file path when using the 'diff' action."
            }
        },
        "required": ["action"]
    }
}


def _find_code_cmd() -> Optional[str]:
    """Locate the VS Code CLI binary."""
    # Check PATH first
    cmd = shutil.which("code.cmd") or shutil.which("code")
    if cmd:
        return cmd

    # Common Windows locations
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local, "Programs", "Microsoft VS Code", "bin", "code.cmd"),
        os.path.join(local, "Programs", "Microsoft VS Code", "Code.exe"),
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
        r"C:\Program Files (x86)\Microsoft VS Code\bin\code.cmd",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _get_recent_projects(limit: int = 5) -> list[str]:
    """Reverse-engineer VS Code's internal SQLite database to extract recently opened projects."""
    appdata = os.environ.get("APPDATA", "")
    vscdb = os.path.join(appdata, "Code", "User", "globalStorage", "state.vscdb")
    if not os.path.exists(vscdb):
        return []

    try:
        conn = sqlite3.connect(vscdb)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM ItemTable WHERE key = 'history.recentlyOpenedPathsList'")
        row = cursor.fetchone()
        conn.close()

        if not row:
            return []

        data = json.loads(row[0])
        entries = data.get("entries", [])
        recent = []
        for entry in entries:
            uri = entry.get("folderUri") or entry.get("fileUri")
            if uri:
                parsed = urlparse(uri)
                # Convert URI to standard local Windows path
                path = unquote(parsed.path)
                if path.startswith("/") and len(path) > 2 and path[2] == ":":
                    path = path[1:]  # strip leading slash for Windows drive letters
                path = path.replace("/", "\\")
                if path and path not in recent:
                    recent.append(path)
            if len(recent) >= limit:
                break
        return recent
    except Exception:
        return []


def _is_vscode_running() -> bool:
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if p.info["name"] and "code.exe" in p.info["name"].lower():
                return True
    except Exception:
        pass
    return False


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    target_path = str(parameters.get("path", "")).strip()
    line_num = parameters.get("line")
    secondary_path = str(parameters.get("secondary_path", "")).strip()

    code_bin = _find_code_cmd()
    if not code_bin:
        return "Sir, Visual Studio Code CLI could not be located on your system."

    try:
        if action in ("recent_projects", "recent", "list_recent"):
            recents = _get_recent_projects(limit=5)
            if not recents:
                res = "Sir, no recently opened VS Code workspaces were found in the state cache."
            else:
                names = [Path(p).name or p for p in recents]
                res = f"Sir, your recently opened VS Code projects are: {', '.join(names)}."

        elif action in ("open_project", "open_folder", "open"):
            if not target_path:
                # Open current project directory by default
                target_path = os.getcwd()
            resolved = str(Path(target_path).resolve())
            subprocess.Popen([code_bin, resolved], shell=True)
            res = f"Opening {Path(resolved).name} in VS Code, Sir."

        elif action in ("open_file", "file"):
            if not target_path:
                return "Sir, please specify which file to open."
            resolved = str(Path(target_path).resolve())
            if line_num:
                arg = f"{resolved}:{line_num}"
                subprocess.Popen([code_bin, "-g", arg], shell=True)
                res = f"Opened {Path(resolved).name} at line {line_num} in VS Code."
            else:
                subprocess.Popen([code_bin, resolved], shell=True)
                res = f"Opened {Path(resolved).name} in VS Code."

        elif action in ("diff", "compare"):
            if not target_path or not secondary_path:
                return "Sir, diffing requires both a primary and secondary file path."
            f1 = str(Path(target_path).resolve())
            f2 = str(Path(secondary_path).resolve())
            subprocess.Popen([code_bin, "--diff", f1, f2], shell=True)
            res = f"Opened side-by-side diff in VS Code between {Path(f1).name} and {Path(f2).name}."

        elif action in ("new_window", "empty"):
            subprocess.Popen([code_bin, "-n"], shell=True)
            res = "Opened a new empty VS Code window, Sir."

        elif action == "status":
            running = _is_vscode_running()
            if running:
                res = "Sir, Visual Studio Code is currently running."
            else:
                res = "Sir, Visual Studio Code is not currently running."

        else:
            subprocess.Popen([code_bin, target_path if target_path else "."], shell=True)
            res = f"Executed VS Code command for '{action}'."

    except Exception as e:
        res = f"Sir, VS Code control encountered an error: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
