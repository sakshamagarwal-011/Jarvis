"""
core/os_input.py — Operating-System Level Mouse and Keyboard Input Injection.

Features:
- Native Windows SendInput API implementation with ctypes.
- Per-Monitor DPI Awareness initialization (prevents coordinate scaling skew).
- Smooth visible mouse movement with cubic/Bézier interpolation.
- Left, right, double, middle clicks with physical down/up hold intervals.
- Click and drag between screen coordinates.
- Mouse wheel vertical and horizontal scrolling.
- Unicode keyboard typing via SendInput (KEYEVENTF_UNICODE) — handles all characters.
- Keyboard shortcuts and hotkeys (Ctrl+A, Ctrl+C, Ctrl+V, Enter, Tab, Esc, etc.).
- Window management (focus window by title/process, get foreground window).
- Position querying with physical-to-logical resolution handling.
- Cross-platform fallbacks for macOS and Linux.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import math
import os
import platform
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List, Union

_OS = platform.system()

def _ensure_desktop_access():
    r"""Ensure current thread is attached to the interactive user desktop (WinSta0\Default)."""
    if _OS == "Windows":
        try:
            u32 = ctypes.windll.user32
            # 0x01FF = DESKTOP_ALL_ACCESS
            h_default = u32.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_default:
                u32.SetThreadDesktop(h_default)
        except Exception:
            pass

_ensure_desktop_access()

if _OS == "Windows":
    try:
        # Try Per-Monitor DPI Aware V2 (Windows 10 1703+)
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        elif hasattr(ctypes.windll, "shcore"):
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        else:
            user32.SetProcessDPIAware()
    except Exception as e:
        print(f"[OSInput] ⚠️ DPI awareness initialization note: {e}")

# ── 2. Windows Structures for SendInput ────────────────────────────────────────
if _OS == "Windows":
    PUL = ctypes.POINTER(ctypes.c_ulong)

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", PUL),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", PUL),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_short),
            ("wParamH", ctypes.c_ushort),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_ulong),
            ("u", INPUT_UNION),
        ]

    # Constants
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1

    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_HWHEEL = 0x1000
    MOUSEEVENTF_ABSOLUTE = 0x8000

    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_SCANCODE = 0x0008

    WHEEL_DELTA = 120

    # Common Virtual Keys
    VK_MAP = {
        "enter": 0x0D,
        "return": 0x0D,
        "tab": 0x09,
        "space": 0x20,
        "backspace": 0x08,
        "delete": 0x2E,
        "escape": 0x1B,
        "esc": 0x1B,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
        "home": 0x24,
        "end": 0x23,
        "pageup": 0x21,
        "pagedown": 0x22,
        "shift": 0x10,
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "win": 0x5B,
        "windows": 0x5B,
        "f1": 0x70,
        "f2": 0x71,
        "f3": 0x72,
        "f4": 0x73,
        "f5": 0x74,
        "f6": 0x75,
        "f7": 0x76,
        "f8": 0x77,
        "f9": 0x78,
        "f10": 0x79,
        "f11": 0x7A,
        "f12": 0x7B,
    }


@dataclass
class ScreenInfo:
    width: int
    height: int
    virtual_left: int
    virtual_top: int
    virtual_width: int
    virtual_height: int
    dpi_scale: float


def get_screen_info() -> ScreenInfo:
    """Returns exact physical and virtual desktop metrics."""
    if _OS == "Windows":
        u32 = ctypes.windll.user32
        # SM_CXSCREEN = 0, SM_CYSCREEN = 1
        w = u32.GetSystemMetrics(0)
        h = u32.GetSystemMetrics(1)
        # Virtual desktop (covers multi-monitors)
        # SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77
        # SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79
        vx = u32.GetSystemMetrics(76)
        vy = u32.GetSystemMetrics(77)
        vw = u32.GetSystemMetrics(78)
        vh = u32.GetSystemMetrics(79)
        if vw <= 0:
            vw = w
        if vh <= 0:
            vh = h

        # Calculate DPI scale relative to standard 96 DPI
        scale = 1.0
        try:
            dpi = u32.GetDpiForSystem()
            scale = dpi / 96.0
        except Exception:
            scale = 1.0

        return ScreenInfo(
            width=w,
            height=h,
            virtual_left=vx,
            virtual_top=vy,
            virtual_width=vw,
            virtual_height=vh,
            dpi_scale=scale,
        )
    else:
        # Fallback for non-Windows
        try:
            import pyautogui
            w, h = pyautogui.size()
            return ScreenInfo(w, h, 0, 0, w, h, 1.0)
        except Exception:
            return ScreenInfo(1920, 1080, 0, 0, 1920, 1080, 1.0)


def get_cursor_pos() -> tuple[int, int]:
    """Get physical mouse cursor position."""
    if _OS == "Windows":
        _ensure_desktop_access()
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)
    try:
        import pyautogui
        p = pyautogui.position()
        return int(p.x), int(p.y)
    except Exception:
        return 0, 0


def _send_windows_input(inputs: list) -> int:
    _ensure_desktop_access()
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    return ctypes.windll.user32.SendInput(n, arr, ctypes.sizeof(INPUT))


def _to_normalized_coords(x: int, y: int, s_info: Optional[ScreenInfo] = None) -> tuple[int, int]:
    """Map pixel coordinates to [0, 65535] absolute coordinate space for MOUSEEVENTF_ABSOLUTE."""
    if s_info is None:
        s_info = get_screen_info()
    vw = max(1, s_info.virtual_width)
    vh = max(1, s_info.virtual_height)
    # Windows absolute coordinate space formula
    norm_x = int(((x - s_info.virtual_left) * 65536) / vw)
    norm_y = int(((y - s_info.virtual_top) * 65536) / vh)
    return norm_x, norm_y


def move_mouse(
    x: int,
    y: int,
    duration: float = 0.25,
    steps: int = 25,
    steady_hold: bool = True,
) -> bool:
    """
    Physically moves the real mouse cursor to (x, y) with visible, natural motion.
    duration > 0 ensures user clearly sees the cursor moving to the target.
    """
    _ensure_desktop_access()
    s_info = get_screen_info()
    # Clamp within screen bounds
    target_x = max(s_info.virtual_left, min(s_info.virtual_left + s_info.virtual_width - 1, int(x)))
    target_y = max(s_info.virtual_top, min(s_info.virtual_top + s_info.virtual_height - 1, int(y)))

    start_x, start_y = get_cursor_pos()

    if start_x == target_x and start_y == target_y:
        return True

    if duration <= 0:
        if _OS == "Windows":
            ctypes.windll.user32.SetCursorPos(target_x, target_y)
            nx, ny = _to_normalized_coords(target_x, target_y, s_info)
            inp = INPUT(
                type=INPUT_MOUSE,
                u=INPUT_UNION(
                    mi=MOUSEINPUT(
                        dx=nx,
                        dy=ny,
                        mouseData=0,
                        dwFlags=MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE,
                        time=0,
                        dwExtraInfo=None,
                    )
                ),
            )
            _send_windows_input([inp])
        else:
            try:
                import pyautogui
                pyautogui.FAILSAFE = False
                pyautogui.moveTo(target_x, target_y)
            except Exception:
                pass
        return True

    # Smooth cubic ease-out path interpolation
    num_steps = max(10, int(steps))
    sleep_interval = duration / num_steps

    for i in range(1, num_steps + 1):
        t = i / float(num_steps)
        # Ease out cubic: f(t) = 1 - (1 - t)^3
        ease = 1.0 - math.pow(1.0 - t, 3.0)
        cx = int(round(start_x + (target_x - start_x) * ease))
        cy = int(round(start_y + (target_y - start_y) * ease))

        if _OS == "Windows":
            ctypes.windll.user32.SetCursorPos(cx, cy)
            nx, ny = _to_normalized_coords(cx, cy, s_info)
            inp = INPUT(
                type=INPUT_MOUSE,
                u=INPUT_UNION(
                    mi=MOUSEINPUT(
                        dx=nx,
                        dy=ny,
                        mouseData=0,
                        dwFlags=MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE,
                        time=0,
                        dwExtraInfo=None,
                    )
                ),
            )
            _send_windows_input([inp])
        else:
            try:
                import pyautogui
                pyautogui.FAILSAFE = False
                pyautogui.moveTo(cx, cy)
            except Exception:
                pass

        time.sleep(sleep_interval)

    # Final exact position set
    if _OS == "Windows":
        ctypes.windll.user32.SetCursorPos(target_x, target_y)
    if steady_hold:
        time.sleep(0.04)

    # Verify actual cursor position
    final_x, final_y = get_cursor_pos()
    return abs(final_x - target_x) <= 3 and abs(final_y - target_y) <= 3


def click(
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.12,
    move_duration: float = 0.25,
) -> bool:
    """
    Executes an actual operating-system level mouse click.
    If x, y are provided, smoothly moves mouse first.
    Includes proper down/up hold duration to ensure Windows apps process the event.
    """
    if x is not None and y is not None:
        move_mouse(x, y, duration=move_duration)

    btn = button.lower().strip()
    if btn == "right":
        down_flag = MOUSEEVENTF_RIGHTDOWN
        up_flag = MOUSEEVENTF_RIGHTUP
    elif btn == "middle":
        down_flag = MOUSEEVENTF_MIDDLEDOWN
        up_flag = MOUSEEVENTF_MIDDLEUP
    else:
        down_flag = MOUSEEVENTF_LEFTDOWN
        up_flag = MOUSEEVENTF_LEFTUP

    cur_x, cur_y = get_cursor_pos()
    s_info = get_screen_info()
    nx, ny = _to_normalized_coords(cur_x, cur_y, s_info)

    for c in range(clicks):
        if _OS == "Windows":
            inp_down = INPUT(
                type=INPUT_MOUSE,
                u=INPUT_UNION(
                    mi=MOUSEINPUT(
                        dx=nx, dy=ny, mouseData=0,
                        dwFlags=MOUSEEVENTF_ABSOLUTE | down_flag,
                        time=0, dwExtraInfo=None
                    )
                ),
            )
            _send_windows_input([inp_down])
            # Physical hold time (vital for apps to register down state)
            time.sleep(0.06)

            inp_up = INPUT(
                type=INPUT_MOUSE,
                u=INPUT_UNION(
                    mi=MOUSEINPUT(
                        dx=nx, dy=ny, mouseData=0,
                        dwFlags=MOUSEEVENTF_ABSOLUTE | up_flag,
                        time=0, dwExtraInfo=None
                    )
                ),
            )
            _send_windows_input([inp_up])
        else:
            try:
                import pyautogui
                pyautogui.FAILSAFE = False
                pyautogui.click(button=btn)
            except Exception:
                pass

        if c < clicks - 1:
            time.sleep(interval)

    time.sleep(0.05)
    return True


def double_click(x: Optional[int] = None, y: Optional[int] = None) -> bool:
    """Performs an OS-level double click."""
    return click(x, y, button="left", clicks=2, interval=0.1)


def right_click(x: Optional[int] = None, y: Optional[int] = None) -> bool:
    """Performs an OS-level right click."""
    return click(x, y, button="right", clicks=1)


def drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.5,
) -> bool:
    """Performs a physical drag-and-drop from (start_x, start_y) to (end_x, end_y)."""
    move_mouse(start_x, start_y, duration=0.2)
    time.sleep(0.08)

    s_info = get_screen_info()
    nx, ny = _to_normalized_coords(start_x, start_y, s_info)

    if _OS == "Windows":
        down_inp = INPUT(
            type=INPUT_MOUSE,
            u=INPUT_UNION(
                mi=MOUSEINPUT(
                    dx=nx, dy=ny, mouseData=0,
                    dwFlags=MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN,
                    time=0, dwExtraInfo=None
                )
            ),
        )
        _send_windows_input([down_inp])
        time.sleep(0.08)

    # Move while holding left button down
    move_mouse(end_x, end_y, duration=duration)
    time.sleep(0.08)

    enx, eny = _to_normalized_coords(end_x, end_y, s_info)
    if _OS == "Windows":
        up_inp = INPUT(
            type=INPUT_MOUSE,
            u=INPUT_UNION(
                mi=MOUSEINPUT(
                    dx=enx, dy=eny, mouseData=0,
                    dwFlags=MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTUP,
                    time=0, dwExtraInfo=None
                )
            ),
        )
        _send_windows_input([up_inp])
        time.sleep(0.05)
    return True


def scroll(direction: str = "down", amount: int = 5) -> bool:
    """
    Scrolls the active window using native wheel events.
    direction: 'up', 'down', 'left', 'right'
    amount: positive integer representing scroll notches
    """
    d = direction.lower().strip()
    amt = max(1, int(amount))
    delta = amt * WHEEL_DELTA

    if _OS == "Windows":
        if d == "down":
            wheel_val = -delta
            flags = MOUSEEVENTF_WHEEL
        elif d == "up":
            wheel_val = delta
            flags = MOUSEEVENTF_WHEEL
        elif d == "right":
            wheel_val = delta
            flags = MOUSEEVENTF_HWHEEL
        elif d == "left":
            wheel_val = -delta
            flags = MOUSEEVENTF_HWHEEL
        else:
            wheel_val = -delta
            flags = MOUSEEVENTF_WHEEL

        inp = INPUT(
            type=INPUT_MOUSE,
            u=INPUT_UNION(
                mi=MOUSEINPUT(
                    dx=0, dy=0,
                    mouseData=ctypes.c_ulong(wheel_val).value,
                    dwFlags=flags,
                    time=0, dwExtraInfo=None
                )
            ),
        )
        _send_windows_input([inp])
        time.sleep(0.05)
        return True
    else:
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            clicks = amt * 100 if d in ("up", "right") else -amt * 100
            if d in ("up", "down"):
                pyautogui.scroll(clicks)
            else:
                pyautogui.hscroll(clicks)
            return True
        except Exception:
            return False


# ── 3. OS-Level Keyboard Control ──────────────────────────────────────────────
def press_key(key_name: str) -> bool:
    """Presses and releases a single key by name (e.g. 'enter', 'tab', 'esc', 'backspace')."""
    k = key_name.lower().strip()
    if _OS == "Windows":
        vk = VK_MAP.get(k)
        if vk is None:
            # Single character key
            if len(k) == 1:
                vk = ctypes.windll.user32.VkKeyScanW(ord(k)) & 0xFF
            else:
                return False

        down = INPUT(
            type=INPUT_KEYBOARD,
            u=INPUT_UNION(
                ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
            ),
        )
        up = INPUT(
            type=INPUT_KEYBOARD,
            u=INPUT_UNION(
                ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
            ),
        )
        _send_windows_input([down])
        time.sleep(0.04)
        _send_windows_input([up])
        time.sleep(0.04)
        return True
    else:
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.press(k)
            return True
        except Exception:
            return False


def hotkey(*keys: str) -> bool:
    """
    Executes a key combination like ('ctrl', 'c') or ('ctrl', 'a') or ('alt', 'tab').
    """
    clean_keys = []
    for k in keys:
        if isinstance(k, str):
            clean_keys.extend([x.strip().lower() for x in k.split("+") if x.strip()])

    if not clean_keys:
        return False

    if _OS == "Windows":
        vks = []
        for k in clean_keys:
            vk = VK_MAP.get(k)
            if vk is None and len(k) == 1:
                vk = ctypes.windll.user32.VkKeyScanW(ord(k)) & 0xFF
            if vk:
                vks.append(vk)

        # Press down in order
        for vk in vks:
            inp = INPUT(
                type=INPUT_KEYBOARD,
                u=INPUT_UNION(
                    ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
                ),
            )
            _send_windows_input([inp])
            time.sleep(0.02)

        time.sleep(0.06)

        # Release in reverse order
        for vk in reversed(vks):
            inp = INPUT(
                type=INPUT_KEYBOARD,
                u=INPUT_UNION(
                    ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
                ),
            )
            _send_windows_input([inp])
            time.sleep(0.02)

        time.sleep(0.04)
        return True
    else:
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.hotkey(*clean_keys)
            return True
        except Exception:
            return False


def type_text(text: str, clear_first: bool = False, interval: float = 0.02) -> bool:
    """
    Types text into the currently focused input field.
    Uses native KEYEVENTF_UNICODE on Windows to support emojis, accents, and all Unicode symbols.
    """
    if clear_first:
        hotkey("ctrl", "a") if _OS == "Windows" else hotkey("command", "a")
        time.sleep(0.05)
        press_key("backspace")
        time.sleep(0.05)

    if not text:
        return True

    # If text is long, fast paste via clipboard is much faster and reliable
    if len(text) > 40:
        try:
            import pyperclip
            pyperclip.copy(text)
            time.sleep(0.05)
            hotkey("ctrl", "v") if _OS == "Windows" else hotkey("command", "v")
            time.sleep(0.08)
            return True
        except Exception:
            pass

    if _OS == "Windows":
        for char in text:
            if char == "\n" or char == "\r":
                press_key("enter")
                continue
            if char == "\t":
                press_key("tab")
                continue

            code = ord(char)
            down = INPUT(
                type=INPUT_KEYBOARD,
                u=INPUT_UNION(
                    ki=KEYBDINPUT(
                        wVk=0,
                        wScan=code,
                        dwFlags=KEYEVENTF_UNICODE,
                        time=0,
                        dwExtraInfo=None,
                    )
                ),
            )
            up = INPUT(
                type=INPUT_KEYBOARD,
                u=INPUT_UNION(
                    ki=KEYBDINPUT(
                        wVk=0,
                        wScan=code,
                        dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                        time=0,
                        dwExtraInfo=None,
                    )
                ),
            )
            _send_windows_input([down])
            time.sleep(0.005)
            _send_windows_input([up])
            if interval > 0:
                time.sleep(interval)
        return True
    else:
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.typewrite(text, interval=interval)
            return True
        except Exception:
            return False


# ── 4. Active Window & Process Management ─────────────────────────────────────
def get_foreground_window_title() -> str:
    """Returns the title of the currently active/focused window."""
    if _OS == "Windows":
        _ensure_desktop_access()
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    return ""


def force_bring_window_to_foreground(hwnd: int) -> bool:
    """
    Forces a window to the foreground on Windows, bypassing Windows foreground lock.
    Uses SwitchToThisWindow + ShowWindow(SW_RESTORE) + Alt-key tap + SetForegroundWindow.
    """
    if _OS != "Windows" or not hwnd:
        return False

    _ensure_desktop_access()
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32

    SW_RESTORE = 9
    VK_MENU = 0x12
    try:
        # Restore if minimized or normal
        u32.ShowWindow(hwnd, SW_RESTORE)
        u32.BringWindowToTop(hwnd)

        # SwitchToThisWindow directly signals Windows window manager to switch focus
        try:
            u32.SwitchToThisWindow(hwnd, True)
        except Exception:
            pass

        # Simulate Alt tap to grant foreground privilege
        u32.keybd_event(VK_MENU, 0, 0, 0)
        u32.SetForegroundWindow(hwnd)
        u32.keybd_event(VK_MENU, 0, 2, 0)

        # AttachThreadInput technique as additional safeguard
        fg_hwnd = u32.GetForegroundWindow()
        if fg_hwnd != hwnd:
            fg_tid = u32.GetWindowThreadProcessId(fg_hwnd, None)
            target_tid = u32.GetWindowThreadProcessId(hwnd, None)
            cur_tid = k32.GetCurrentThreadId()

            if fg_tid and fg_tid != cur_tid:
                u32.AttachThreadInput(cur_tid, fg_tid, True)
            if target_tid and target_tid != cur_tid:
                u32.AttachThreadInput(cur_tid, target_tid, True)

            u32.SetForegroundWindow(hwnd)
            u32.BringWindowToTop(hwnd)

            if target_tid and target_tid != cur_tid:
                u32.AttachThreadInput(cur_tid, target_tid, False)
            if fg_tid and fg_tid != cur_tid:
                u32.AttachThreadInput(cur_tid, fg_tid, False)

        time.sleep(0.2)
        return True
    except Exception as e:
        print(f"[OSInput] force_bring_window_to_foreground error: {e}")
        return False


def focus_window_by_title(title_fragment: str) -> bool:
    """Finds and brings a window matching title_fragment to the foreground."""
    tf = title_fragment.lower().strip()
    if not tf:
        return False

    if _OS == "Windows":
        _ensure_desktop_access()
        candidates = []

        def enum_windows_callback(hwnd, extra):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.lower()
                    if tf in title and "antigravity" not in title and "task-" not in title:
                        candidates.append((hwnd, buf.value))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

        if candidates:
            for hwnd, title in candidates:
                if force_bring_window_to_foreground(hwnd):
                    return True

    return False
