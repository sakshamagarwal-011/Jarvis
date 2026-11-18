"""
ui package initialization.
Re-exports everything from root ui.py to maintain 100% backward compatibility
with all existing modules (like main.py: `from ui import JarvisUI`), while also
exposing ui.holographic_file_explorer.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# Load and re-export the root ui.py
_root_ui_path = Path(__file__).resolve().parent.parent / "ui.py"
if _root_ui_path.exists():
    _spec = importlib.util.spec_from_file_location("_jarvis_root_ui", str(_root_ui_path))
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["_jarvis_root_ui"] = _mod
        _spec.loader.exec_module(_mod)
        for _name, _val in _mod.__dict__.items():
            if not _name.startswith("__"):
                globals()[_name] = _val

from .holographic_file_explorer import (
    HolographicFileExplorer,
    HoloFileCard,
    SafeActionConfirmModal,
    HoloColors,
)
from .holographic_gesture_overlay import HoloGestureOverlay

