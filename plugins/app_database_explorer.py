"""
Local Application Database & Browser History Explorer Plugin for JARVIS.

Inspired by REA (Reverse Engineer Anything) SQLite Engine:
- Safe, non-locking SQLite database snapshotting
- Browser History Search (Chrome, Edge, Brave): URLs, page titles, visit counts
- Recent Downloads Inspection from local browser databases
- Application SQLite discovery across %APPDATA% and %LOCALAPPDATA%
"""
import glob
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

PLUGIN = {
    "name": "app_database_explorer",
    "description": (
        "Explores local application databases and browser history on your machine. "
        "Actions include: 'search_history' (search Chrome/Edge browsing history by keyword), "
        "'recent_history' (get recent visited websites), "
        "'recent_downloads' (check recent browser downloads), "
        "or 'list_databases' (find all SQLite databases for an app)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action: 'search_history', 'recent_history', 'recent_downloads', or 'list_databases'."
            },
            "query": {
                "type": "STRING",
                "description": "Search keyword, website name, or app name to find databases for."
            }
        },
        "required": ["action"]
    }
}


def _find_browser_history_files() -> list[tuple[str, str]]:
    """Locate History SQLite files for Chrome, Edge, and Brave."""
    local = os.environ.get("LOCALAPPDATA", "")
    paths = [
        ("Chrome", os.path.join(local, r"Google\Chrome\User Data\Default\History")),
        ("Edge", os.path.join(local, r"Microsoft\Edge\User Data\Default\History")),
        ("Brave", os.path.join(local, r"BraveSoftware\Brave-Browser\User Data\Default\History")),
    ]
    return [(name, p) for name, p in paths if os.path.exists(p)]


def _query_history_snapshot(history_path: str, sql: str, params: tuple = ()) -> list[tuple]:
    """Take an atomic temporary snapshot to read active SQLite files without file-lock collisions."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_name = tmp.name
    try:
        shutil.copy2(history_path, tmp_name)
        conn = sqlite3.connect(tmp_name)
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception:
        return []
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except Exception:
                pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    query = str(parameters.get("query", "")).strip()

    browsers = _find_browser_history_files()

    try:
        if action in ("recent_history", "history"):
            if not browsers:
                return "Sir, no browser history databases could be located."

            browser_name, hpath = browsers[0]
            sql = "SELECT title, url FROM urls WHERE title != '' ORDER BY last_visit_time DESC LIMIT 5"
            rows = _query_history_snapshot(hpath, sql)
            if not rows:
                res = f"No recent browsing history found in {browser_name}."
            else:
                titles = [r[0][:40] for r in rows]
                res = f"Sir, recent {browser_name} history: {', '.join(titles)}."

        elif action in ("search_history", "search"):
            if not query:
                return "Sir, please specify what you want to search for in your browsing history."
            if not browsers:
                return "Sir, no browser history databases found."

            all_matches = []
            for bname, hpath in browsers:
                sql = (
                    "SELECT title, url FROM urls "
                    "WHERE title LIKE ? OR url LIKE ? "
                    "ORDER BY last_visit_time DESC LIMIT 4"
                )
                like_arg = f"%{query}%"
                rows = _query_history_snapshot(hpath, sql, (like_arg, like_arg))
                for title, url in rows:
                    all_matches.append(f"{title or url} ({bname})")

            if not all_matches:
                res = f"Sir, no browsing history records matched '{query}'."
            else:
                res = f"Found {len(all_matches)} history match(es) for '{query}': {'; '.join(all_matches[:3])}."

        elif action in ("recent_downloads", "downloads"):
            if not browsers:
                return "Sir, no browser history databases found."
            browser_name, hpath = browsers[0]
            sql = (
                "SELECT target_path FROM downloads "
                "ORDER BY start_time DESC LIMIT 4"
            )
            rows = _query_history_snapshot(hpath, sql)
            if not rows:
                res = f"No recent download records in {browser_name}."
            else:
                files = [Path(r[0]).name for r in rows if r[0]]
                res = f"Sir, recent {browser_name} downloads: {', '.join(files)}."

        elif action in ("list_databases", "databases", "find_db"):
            if not query:
                return "Sir, please specify which application name to find databases for."
            local = os.environ.get("LOCALAPPDATA", "")
            roaming = os.environ.get("APPDATA", "")
            found_dbs = []

            for base in [local, roaming]:
                pattern = os.path.join(base, f"*{query}*", "**", "*.sqlite*")
                for match in glob.glob(pattern, recursive=True)[:5]:
                    found_dbs.append(Path(match).name)

            if not found_dbs:
                res = f"No SQLite databases found for application '{query}'."
            else:
                res = f"Found databases for {query}: {', '.join(found_dbs[:5])}."

        else:
            res = f"Executed database action: '{action}'."

    except Exception as e:
        res = f"Database exploration encountered an error: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
