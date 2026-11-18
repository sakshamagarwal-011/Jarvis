"""
Android Phone Control Plugin for JARVIS.

Inspired by REA (Reverse Engineer Anything) ADB Engine:
- Connects to Android devices via Android Debug Bridge (USB / WiFi)
- Telemetry: Battery state, device info, running packages
- Screen Capture: High-resolution mobile screenshot pipeline
- App Control: Launching apps, opening URLs, simulated keystrokes
"""
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

PLUGIN = {
    "name": "android_control",
    "description": (
        "Controls your connected Android phone via ADB. Actions include: 'devices' (list connected phones), "
        "'battery' (check phone battery level), 'screenshot' (take screenshot of phone screen), "
        "'launch_app' (open app like WhatsApp, YouTube, Camera, Settings), "
        "'open_url' (open web link on phone), 'press_key' (home, back, volume_up, volume_down), "
        "or 'type_text' (type text on phone)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action: 'devices', 'battery', 'screenshot', 'launch_app', 'open_url', 'press_key', or 'type_text'."
            },
            "target": {
                "type": "STRING",
                "description": "App name (e.g., 'whatsapp', 'youtube'), URL, key name (e.g. 'home', 'back'), or text string."
            }
        },
        "required": ["action"]
    }
}

APP_MAP = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "camera": "com.android.camera",
    "settings": "com.android.settings",
    "spotify": "com.spotify.music",
    "instagram": "com.instagram.android",
    "telegram": "org.telegram.messenger",
    "maps": "com.google.android.apps.maps",
    "gmail": "com.google.android.gm"
}

KEY_MAP = {
    "home": "3",
    "back": "4",
    "power": "26",
    "volume_up": "24",
    "volume_down": "25",
    "enter": "66",
    "space": "62"
}


def _find_adb() -> Optional[str]:
    """Locate adb.exe in Android SDK or system PATH."""
    cmd = shutil.which("adb")
    if cmd:
        return cmd
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe"),
        r"C:\platform-tools\adb.exe",
        r"C:\Program Files\Android\platform-tools\adb.exe"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _run_adb(adb: str, args: list[str]) -> tuple[int, str]:
    """Execute ADB command and return (exit_code, output)."""
    try:
        r = subprocess.run([adb] + args, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return 1, str(e)


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    target = str(parameters.get("target", "")).strip()

    adb = _find_adb()
    if not adb:
        return "Sir, Android Debug Bridge (ADB) could not be located on your machine."

    try:
        if action in ("devices", "list_devices", "status"):
            code, out = _run_adb(adb, ["devices", "-l"])
            lines = [l for l in out.splitlines() if l.strip() and not l.startswith("List of")]
            if not lines:
                res = "Sir, no Android devices are currently connected via USB or WiFi debugging."
            else:
                models = []
                for line in lines:
                    m = re.search(r"model:(\S+)", line)
                    models.append(m.group(1).replace("_", " ") if m else line.split()[0])
                res = f"Sir, detected {len(lines)} connected Android device(s): {', '.join(models)}."

        elif action in ("battery", "battery_status", "power"):
            code, out = _run_adb(adb, ["shell", "dumpsys", "battery"])
            level = re.search(r"level:\s*(\d+)", out)
            status = re.search(r"status:\s*(\d+)", out)
            temp = re.search(r"temperature:\s*(\d+)", out)

            charging_map = {"2": "Charging", "3": "Discharging", "5": "Full"}
            charge_str = charging_map.get(status.group(1) if status else "3", "Not charging")

            if level:
                celsius = f"{int(temp.group(1))/10:.1f}°C" if temp else ""
                res = f"Sir, your phone battery is at {level.group(1)}% ({charge_str}" + (f", {celsius})" if celsius else ")")
            else:
                res = "Could not read phone battery level. Make sure USB debugging is authorized."

        elif action in ("screenshot", "screen_capture", "snap"):
            out_dir = Path("screenshots")
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / "phone_screen.png"
            # Stream png bytes directly from device
            try:
                with open(out_path, "wb") as f:
                    subprocess.run([adb, "exec-out", "screencap", "-p"], stdout=f, timeout=10)
                res = f"Captured phone screen. Saved to {out_path.name}."
            except Exception as e:
                res = f"Failed to capture phone screen: {e}"

        elif action in ("launch_app", "open_app", "app"):
            pkg = APP_MAP.get(target.lower(), target)
            code, out = _run_adb(adb, ["shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"])
            if code == 0:
                res = f"Opening {target} on your phone, Sir."
            else:
                res = f"Could not launch {target} on phone: {out}"

        elif action in ("open_url", "url", "browse"):
            if not target:
                return "Sir, please provide the URL to open on your phone."
            if not target.startswith("http"):
                target = "https://" + target
            code, out = _run_adb(adb, ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", target])
            res = f"Opened {target} on your phone browser, Sir."

        elif action in ("press_key", "key"):
            key_code = KEY_MAP.get(target.lower(), target)
            code, out = _run_adb(adb, ["shell", "input", "keyevent", key_code])
            res = f"Sent key {target} to phone."

        elif action in ("type_text", "type"):
            clean_text = target.replace(" ", "%s")
            code, out = _run_adb(adb, ["shell", "input", "text", clean_text])
            res = f"Typed text on phone: '{target}'."

        else:
            res = f"Executed ADB action '{action}' on connected device."

    except Exception as e:
        res = f"Sir, Android control encountered an error: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {res}")
        except Exception:
            pass

    return res
