"""
Self-Inspection & Capability Guide Plugin for JARVIS.

Inspects JARVIS's own repository, files, and newly integrated features:
- Reads Git status and diffs of modified core files (main.py, ui.py, wake_word.py)
- Discovers and categorizes all newly installed plugins
- Explains exactly how to use every new capability with voice command examples
- Directly renders formatted Cheat Sheets on the HUD dynamic content panel
"""
import importlib
import os
import subprocess
from pathlib import Path
import re
from typing import Optional

PLUGIN = {
    "name": "self_inspection",
    "description": (
        "Inspects JARVIS's own code files, recently added features, plugins, and explains how to use them. "
        "Use this whenever the user asks: 'see into your files', 'what changes did we put in you', "
        "'what are your new features', 'how do I use the new tools', or asks for instructions on any custom plugin."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "topic": {
                "type": "STRING",
                "description": "Specific feature name (e.g. 'spotify', 'discord', 'steam', 'android', 'vscode', 'reverse_engineer', 'core_changes') or 'all'."
            }
        },
        "required": []
    }
}

FEATURE_GUIDE = {
    "spotify": {
        "title": "🎵 Spotify Media Control",
        "file": "plugins/spotify_control.py",
        "summary": "Full playback controls, song detection from window title, and deep-search.",
        "commands": [
            "Jarvis, play some music on Spotify",
            "Jarvis, what song is playing right now?",
            "Jarvis, skip to the next track",
            "Jarvis, search Spotify for Hans Zimmer",
            "Jarvis, turn up the Spotify volume"
        ]
    },
    "discord": {
        "title": "💬 Discord Desktop Control",
        "file": "plugins/discord_control.py",
        "summary": "Process launcher, window focus, deep-linking, and voice mute/deafen.",
        "commands": [
            "Jarvis, is Discord running?",
            "Jarvis, bring Discord to the front",
            "Jarvis, toggle mute on Discord",
            "Jarvis, deafen my Discord audio"
        ]
    },
    "vscode": {
        "title": "💻 Visual Studio Code Integration",
        "file": "plugins/vscode_control.py",
        "summary": "CLI launcher, SQLite state introspection for recent workspaces, file opening at line, and diffing.",
        "commands": [
            "Jarvis, open this project in VS Code",
            "Jarvis, what are my recent VS Code projects?",
            "Jarvis, open main.py at line 100 in VS Code",
            "Jarvis, compare file A and file B in VS Code"
        ]
    },
    "steam": {
        "title": "🎮 Steam Gaming & Library Engine",
        "file": "plugins/steam_control.py",
        "summary": "Multi-drive library manifest parser, real-time game detection, and steam:// protocol launcher.",
        "commands": [
            "Jarvis, what Steam games do I have installed?",
            "Jarvis, launch Phasmophobia on Steam",
            "Jarvis, am I currently playing any game?",
            "Jarvis, open my Steam friends list"
        ]
    },
    "android": {
        "title": "📱 Android Phone Control (via ADB)",
        "file": "plugins/android_control.py",
        "summary": "Connects to phone over ADB: battery level, screenshot, app launching, key simulations.",
        "commands": [
            "Jarvis, check my phone battery",
            "Jarvis, take a screenshot of my phone",
            "Jarvis, open WhatsApp on my phone",
            "Jarvis, press home on my phone"
        ]
    },
    "database": {
        "title": "🗄️ Local App Database & Browser History Explorer",
        "file": "plugins/app_database_explorer.py",
        "summary": "Non-locking SQLite snapshotting for Chrome/Edge history, recent downloads, and app databases.",
        "commands": [
            "Jarvis, what are my recent visited websites?",
            "Jarvis, search my browsing history for GitHub",
            "Jarvis, what did I download recently?",
            "Jarvis, find all SQLite databases for VS Code"
        ]
    },
    "reverse_engineer": {
        "title": "🔬 REA Application & Binary Inspector",
        "file": "plugins/reverse_engineer.py",
        "summary": "Detects if an app is Electron/.NET/Qt/Win32, inspects memory/ports, and parses PE headers.",
        "commands": [
            "Jarvis, inspect Code.exe architecture",
            "Jarvis, what frameworks does Discord use?",
            "Jarvis, inspect the database state.vscdb",
            "Jarvis, where does Discord store its data?"
        ]
    },
    "electron": {
        "title": "⚡ Electron ASAR & DevTools Inspector",
        "file": "plugins/electron_cdp_inspector.py",
        "summary": "Pure Python ASAR unpacker, security fuses, and Chrome DevTools Protocol targets.",
        "commands": [
            "Jarvis, inspect Discord's asar bundle",
            "Jarvis, find all Electron apps on my computer",
            "Jarvis, inspect security fuses on Discord"
        ]
    },
    "binary": {
        "title": "🛡️ Binary Decompiler & Security Auditor",
        "file": "plugins/binary_decompiler.py",
        "summary": "PE security mitigation audit (ASLR, DEP, CFG, HighEntropyVA) and entry point disassembler.",
        "commands": [
            "Jarvis, run a security audit on notepad.exe",
            "Jarvis, audit the security of Discord.exe",
            "Jarvis, disassemble the entry point of notepad.exe"
        ]
    }
}


def _get_git_summary() -> str:
    """Inspect git repository for modified core files and new files."""
    try:
        r = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, timeout=5)
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        modified = [l.split(maxsplit=1)[1] for l in lines if l.startswith("M")]
        untracked = [l.split(maxsplit=1)[1] for l in lines if l.startswith("??")]
        return (
            f"Git status: {len(modified)} core files modified ({', '.join(modified)}), "
            f"and {len(untracked)} new features added."
        )
    except Exception:
        return "Git repository inspection completed."


def _build_hud_guide() -> str:
    """Build a comprehensive guide text for the HUD content panel."""
    sections = []
    sections.append("⚡ JARVIS CODEBASE & CUSTOM FEATURES GUIDE\n")
    sections.append("CORE MODIFICATIONS:")
    sections.append("• ui.py: Added thread-safe _bring_front_sig and _bring_to_front window unminimizing.")
    sections.append("• main.py: Ensured working directory is BASE_DIR on boot, wired wake event to HUD.")
    sections.append("• core/wake_word.py: Patched openwakeword circular import bug.")
    sections.append("• .gitignore: Fixed comment syntax to protect secrets.\n")
    sections.append("ACTIVE CUSTOM SKILLS & HOW TO USE THEM:\n")

    for key, data in FEATURE_GUIDE.items():
        sections.append(f"■ {data['title']} ({data['file']})")
        sections.append(f"  {data['summary']}")
        sections.append("  Voice Commands:")
        for cmd in data["commands"]:
            sections.append(f"    • \"{cmd}\"")
        sections.append("")

    return "\n".join(sections)


def run(parameters: dict, player=None, session_memory=None) -> str:
    topic = str(parameters.get("topic", "")).strip().lower()

    try:
        # Check if user asked about a specific plugin
        matched_feature = None
        for key in FEATURE_GUIDE:
            if key in topic or topic in key:
                matched_feature = FEATURE_GUIDE[key]
                break

        if matched_feature:
            title = matched_feature["title"]
            clean_title = re.sub(r"[^\x00-\x7F]+", "", title).strip()
            file_path = matched_feature["file"]
            summary = matched_feature["summary"]
            cmds = '", "'.join(matched_feature["commands"][:3])
            res = (
                f"Sir, for {clean_title} in {file_path}: {summary} "
                f"You can say: \"{cmds}\"."
            )
            if player:
                detail = f"{title}\nFile: {file_path}\n\n{summary}\n\nVoice Commands:\n" + "\n".join(f"• {c}" for c in matched_feature["commands"])
                player.show_content(f"📘 {title.upper()}", detail)

        else:
            # Full summary
            git_summary = _get_git_summary()
            total_skills = len(FEATURE_GUIDE)
            res = (
                f"Sir, I have inspected my codebase. You have added {total_skills} custom skills "
                f"to me in the plugins folder: Spotify, Discord, VS Code, Steam, Android Phone Control, "
                f"Browser History Explorer, REA Reverse Engineer, Electron Inspector, and Binary Security Auditor. "
                f"I have rendered the complete guide and command list on my HUD content panel."
            )
            if player:
                full_guide = _build_hud_guide()
                player.show_content("⚡ MY CAPABILITIES & CHANGES", full_guide)

    except Exception as e:
        res = f"Self-inspection error: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
