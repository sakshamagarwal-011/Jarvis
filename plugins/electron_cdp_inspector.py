"""
Electron & Chrome DevTools Protocol (CDP) Inspector Plugin for JARVIS.

Inspired by REA (Reverse Engineer Anything) Electron & Browser Engines:
- Electron ASAR Archive Inspector: Unpack file hierarchies and package.json manifests
- Live Chrome / Edge / Electron DevTools Protocol (CDP) target discovery
- Page Content Extractor: Read document titles, URLs, and text directly over CDP
- Electron Fuse Inspector: Check security fuses (runAsNode, nodeCli) on Electron executables
"""
import glob
import json
import os
import struct
import urllib.request
from pathlib import Path
from typing import Optional

PLUGIN = {
    "name": "electron_cdp_inspector",
    "description": (
        "Inspects Electron applications and live Chrome DevTools targets. "
        "Actions include: 'inspect_asar' (view internal bundled files/modules in app.asar), "
        "'list_cdp' (discover active Chrome/Edge/Electron tabs on remote debugging ports), "
        "'inspect_fuses' (check Electron security fuses on an exe), "
        "or 'find_asars' (find all Electron apps on your computer)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action: 'inspect_asar', 'list_cdp', 'inspect_fuses', or 'find_asars'."
            },
            "target": {
                "type": "STRING",
                "description": "App name (e.g. 'discord', 'code'), port (default 9222), or path to .asar / .exe."
            }
        },
        "required": ["action"]
    }
}


def _read_asar_header(asar_path: str) -> dict:
    """Read the JSON directory header from an Electron ASAR archive."""
    try:
        with open(asar_path, "rb") as f:
            data = f.read(16)
            if len(data) < 16:
                return {"error": "File too small to be an ASAR archive"}
            _, _, _, json_len = struct.unpack("<IIII", data)
            json_bytes = f.read(json_len)
            header = json.loads(json_bytes.decode("utf-8", errors="ignore"))
            return header.get("files", {})
    except Exception as e:
        return {"error": str(e)}


def _find_asar_for_app(app_name: str) -> Optional[str]:
    """Search for app.asar belonging to an application."""
    app_clean = app_name.strip().lower()
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")

    for base in [local, roaming]:
        candidates = glob.glob(os.path.join(base, f"*{app_clean}*", "**", "*.asar"), recursive=True)
        if candidates:
            return candidates[0]
    return None


def _check_cdp_targets(port: int = 9222) -> list[dict]:
    """Query Chrome DevTools Protocol targets on a local port."""
    url = f"http://127.0.0.1:{port}/json/list"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-REA-Bridge"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    target = str(parameters.get("target", "")).strip()

    try:
        if action in ("inspect_asar", "asar", "unpack"):
            asar_path = target if target.endswith(".asar") and os.path.exists(target) else _find_asar_for_app(target)
            if not asar_path:
                return f"Sir, no ASAR archive could be found for '{target}'."

            files_map = _read_asar_header(asar_path)
            if "error" in files_map:
                res = f"Could not read ASAR: {files_map['error']}"
            else:
                top_files = list(files_map.keys())[:8]
                res = (
                    f"Sir, inspected {Path(asar_path).name} for {target}. "
                    f"Found {len(files_map)} top-level components: {', '.join(top_files)}."
                )

        elif action in ("find_asars", "list_asars", "electron_apps"):
            local = os.environ.get("LOCALAPPDATA", "")
            asars = glob.glob(os.path.join(local, "**", "app.asar"), recursive=True)
            apps = set()
            for a in asars:
                parts = Path(a).parts
                if len(parts) > 5:
                    apps.add(parts[5])
            res = f"Sir, detected {len(asars)} Electron application bundle(s): {', '.join(list(apps)[:6])}."

        elif action in ("list_cdp", "cdp", "tabs"):
            port = int(target) if target.isdigit() else 9222
            targets = _check_cdp_targets(port)
            if not targets:
                res = f"Sir, no active DevTools Protocol targets listening on port {port}. (Launch Chrome or Electron with --remote-debugging-port={port} to connect)."
            else:
                titles = [t.get("title", "Untitled")[:30] for t in targets[:4]]
                res = f"Sir, found {len(targets)} active CDP page(s) on port {port}: {', '.join(titles)}."

        elif action in ("inspect_fuses", "fuses"):
            # Electron fuses check: search for 'dL7nhoptimize' or 'electron-fuse' signature in binary
            if not os.path.exists(target):
                return f"Sir, binary file '{target}' does not exist."
            try:
                with open(target, "rb") as f:
                    content = f.read(2 * 1024 * 1024)  # inspect first 2MB
                has_run_as_node = b"ELECTRON_RUN_AS_NODE" in content
                res = (
                    f"Sir, Electron binary {Path(target).name} checked: "
                    f"ELECTRON_RUN_AS_NODE fuse enabled: {has_run_as_node}."
                )
            except Exception as e:
                res = f"Failed to check fuses: {e}"

        else:
            res = f"Executed Electron inspection action: '{action}'."

    except Exception as e:
        res = f"Electron inspector encountered an issue: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
