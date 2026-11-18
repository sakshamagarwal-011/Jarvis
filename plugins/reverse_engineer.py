"""
Reverse Engineering Plugin for JARVIS.

Inspired by REA (Reverse Engineer Anything):
- Application Architecture Detection (Electron, .NET, Win32, Qt, Python)
- Deep Process Telemetry (ports, open files, loaded modules, architecture)
- Safe Read-Only SQLite Database Inspection (tables, schemas, row counts)
- Portable Executable (PE) Binary Inspection (headers, machine type, subsystems, imports)
- Application Storage Discovery (%APPDATA%, %LOCALAPPDATA%)
"""
import glob
import os
import sqlite3
import struct
from pathlib import Path
from typing import Optional

PLUGIN = {
    "name": "reverse_engineer",
    "description": (
        "Reverse-engineers and inspects applications, processes, databases, and binary files. "
        "Actions include: 'inspect_app' (detect if app is Electron, .NET, Win32, or Qt), "
        "'inspect_process' (inspect running process ports, files, and modules), "
        "'inspect_sqlite' (inspect schema and tables of any app's SQLite database in read-only mode), "
        "'inspect_binary' (analyze PE header, architecture, imports of an .exe or .dll), "
        "or 'find_storage' (find where an app stores its data)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action: 'inspect_app', 'inspect_process', 'inspect_sqlite', 'inspect_binary', or 'find_storage'."
            },
            "target": {
                "type": "STRING",
                "description": "App name, process name or PID, or path to executable / SQLite database."
            }
        },
        "required": ["action", "target"]
    }
}


def _find_running_process(target: str):
    """Find a process by name or PID."""
    import psutil
    target_clean = target.strip().lower()

    if target_clean.isdigit():
        try:
            return psutil.Process(int(target_clean))
        except Exception:
            return None

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info["name"] or "").lower()
            exe = (proc.info["exe"] or "").lower()
            if target_clean in name or target_clean in exe:
                return proc
        except Exception:
            continue
    return None


def _detect_app_architecture(exe_path: str) -> dict:
    """Analyze executable file layout to identify app framework (Electron, .NET, Qt, etc.)."""
    if not os.path.exists(exe_path):
        return {"error": "File not found"}

    exe_dir = os.path.dirname(exe_path)
    frameworks = []
    evidence = []

    # Check Electron / Chromium
    asar_files = glob.glob(os.path.join(exe_dir, "**", "*.asar"), recursive=True)
    if asar_files or os.path.exists(os.path.join(exe_dir, "resources", "app.asar")):
        frameworks.append("Electron (Node.js + Chromium)")
        evidence.append(f"Found ASAR archive: {os.path.basename(asar_files[0]) if asar_files else 'app.asar'}")

    # Check .NET (CLR)
    clr_dlls = ["clr.dll", "mscorwks.dll", "coreclr.dll", "hostfxr.dll"]
    for dll in clr_dlls:
        if os.path.exists(os.path.join(exe_dir, dll)):
            frameworks.append(".NET / CoreCLR")
            evidence.append(f"Found runtime: {dll}")
            break

    # Check Qt
    qt_dlls = glob.glob(os.path.join(exe_dir, "Qt*Core*.dll"))
    if qt_dlls:
        frameworks.append("Qt GUI Framework")
        evidence.append(f"Found Qt runtime: {os.path.basename(qt_dlls[0])}")

    # Check Python / PyInstaller
    if os.path.exists(os.path.join(exe_dir, "python3.dll")) or os.path.exists(os.path.join(exe_dir, "base_library.zip")):
        frameworks.append("Python Frozen / PyInstaller")
        evidence.append("Found Python runtime / base_library")

    # Native fallback
    if not frameworks:
        frameworks.append("Native Win32 / C++ binary")

    return {
        "frameworks": frameworks,
        "evidence": evidence,
        "path": exe_path
    }


def _inspect_pe_binary(file_path: str) -> dict:
    """Read Windows PE (Portable Executable) binary header without external dependencies."""
    try:
        with open(file_path, "rb") as f:
            dos_header = f.read(64)
            if dos_header[:2] != b"MZ":
                return {"error": "Not a valid DOS / PE executable"}

            pe_offset = struct.unpack("<I", dos_header[60:64])[0]
            f.seek(pe_offset)
            pe_signature = f.read(4)
            if pe_signature != b"PE\x00\x00":
                return {"error": "Invalid PE signature"}

            coff_header = f.read(20)
            machine, num_sections, timedate, sym_ptr, num_sym, opt_hdr_size, characteristics = struct.unpack("<HHIIIHH", coff_header)

            machine_map = {
                0x014c: "x86 (32-bit Intel)",
                0x8664: "x64 (64-bit AMD/Intel)",
                0xaa64: "ARM64",
                0x01c0: "ARM"
            }
            arch = machine_map.get(machine, f"Unknown (0x{machine:04x})")

            # Read optional header subsystem
            subsystem_name = "Unknown"
            if opt_hdr_size >= 68:
                opt_hdr = f.read(opt_hdr_size)
                magic = struct.unpack("<H", opt_hdr[:2])[0]
                if magic in (0x10b, 0x20b):  # PE32 or PE32+
                    subsystem = struct.unpack("<H", opt_hdr[68:70])[0]
                    subsystem_map = {
                        1: "Native Device Driver",
                        2: "Windows GUI (Graphical)",
                        3: "Windows CUI (Console)",
                        7: "POSIX CUI"
                    }
                    subsystem_name = subsystem_map.get(subsystem, f"Subsystem {subsystem}")

            return {
                "architecture": arch,
                "sections": num_sections,
                "subsystem": subsystem_name,
                "characteristics": f"0x{characteristics:04x}"
            }
    except Exception as e:
        return {"error": str(e)}


def _inspect_sqlite(db_path: str) -> dict:
    """Safely inspect an SQLite database in read-only URI mode without file locking."""
    if not os.path.exists(db_path):
        return {"error": f"Database file not found: {db_path}"}

    try:
        uri = f"file:{os.path.abspath(db_path)}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()

        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()

        table_info = {}
        for name, sql in tables[:10]:
            try:
                cursor.execute(f"SELECT count(*) FROM \"{name}\"")
                count = cursor.fetchone()[0]
            except Exception:
                count = "N/A"
            table_info[name] = {"rows": count, "schema": sql[:120] if sql else ""}

        conn.close()
        return {
            "table_count": len(tables),
            "tables": table_info
        }
    except Exception as e:
        return {"error": str(e)}


def _find_storage(target: str) -> list[str]:
    """Find AppData / Local storage folders for an app."""
    target_clean = target.strip().lower()
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")

    found = []
    for base in [appdata, localappdata]:
        if not os.path.exists(base):
            continue
        for entry in os.listdir(base):
            if target_clean in entry.lower():
                full = os.path.join(base, entry)
                if os.path.isdir(full) and full not in found:
                    found.append(full)
    return found


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    target = str(parameters.get("target", "")).strip()

    try:
        if action in ("inspect_app", "framework", "architecture"):
            # Check if target is a path or process
            exe_path = None
            if os.path.exists(target):
                exe_path = target
            else:
                proc = _find_running_process(target)
                if proc:
                    exe_path = proc.exe()

            if not exe_path:
                return f"Sir, could not locate an active executable for '{target}'."

            info = _detect_app_architecture(exe_path)
            frameworks = ", ".join(info.get("frameworks", []))
            evidence = "; ".join(info.get("evidence", []))
            res = (
                f"Sir, I analyzed {Path(exe_path).name}. "
                f"Architecture: {frameworks}. "
                + (f"Evidence: {evidence}." if evidence else "")
            )

        elif action in ("inspect_process", "process"):
            import psutil
            proc = _find_running_process(target)
            if not proc:
                return f"Sir, no running process found matching '{target}'."

            pid = proc.pid
            name = proc.name()
            mem_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
            num_threads = proc.num_threads()

            # Inspect open connections/ports
            ports = []
            try:
                for conn in proc.net_connections(kind="inet"):
                    if conn.laddr:
                        ports.append(str(conn.laddr.port))
            except Exception:
                pass

            res = (
                f"Process {name} (PID {pid}): Memory {mem_mb} MB, {num_threads} threads. "
                + (f"Listening on ports: {', '.join(set(ports))}." if ports else "No public listening sockets.")
            )

        elif action in ("inspect_sqlite", "sqlite", "database"):
            info = _inspect_sqlite(target)
            if "error" in info:
                res = f"Could not inspect database: {info['error']}"
            else:
                t_count = info["table_count"]
                table_names = list(info["tables"].keys())[:6]
                res = (
                    f"Sir, database {Path(target).name} contains {t_count} tables. "
                    f"Sample tables: {', '.join(table_names)}."
                )

        elif action in ("inspect_binary", "pe", "binary"):
            if not os.path.exists(target):
                proc = _find_running_process(target)
                if proc:
                    target = proc.exe()
                else:
                    return f"Sir, binary file '{target}' was not found."

            info = _inspect_pe_binary(target)
            if "error" in info:
                res = f"PE Inspection error: {info['error']}"
            else:
                res = (
                    f"Binary {Path(target).name}: Architecture {info['architecture']}, "
                    f"Subsystem: {info['subsystem']}, Section count: {info['sections']}."
                )

        elif action in ("find_storage", "storage"):
            paths = _find_storage(target)
            if not paths:
                res = f"Sir, no local storage directories found matching '{target}'."
            else:
                res = f"Found local storage for {target} at: {', '.join(paths)}."

        else:
            res = f"Unknown reverse engineering action: {action}"

    except Exception as e:
        res = f"Reverse engineering analysis failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
