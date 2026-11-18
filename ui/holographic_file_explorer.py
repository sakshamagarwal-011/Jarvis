"""
ui/holographic_file_explorer.py — Iron Man Holographic File Explorer for Mark LV.

A futuristic visual file-management workspace designed to look and feel like
Tony Stark's holographic lab interface while remaining a safe, dependable desktop tool.

Features:
- Dark glassmorphism, cyan/amber glowing outlines, corner brackets, and floating tech cards.
- Interactive breadcrumb navigation, search/filter, back/forward history.
- Floating file/folder cards with category glyphs, metadata, and visual rearrangement.
- Integrated file previewer (text, code, markdown, images).
- Safe file operations powered by actions/file_controller.py and core/undo.py.
- Strict confirmation gate for destructive actions (delete, overwrite, move).
- Hand-gesture control endpoints (point, select, drag, swipe, zoom, grab).
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from PyQt6.QtCore import (
    QEasingCurve, QLineF, QObject, QPoint, QPointF, QPropertyAnimation,
    QRect, QRectF, QSize, QSizeF, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from actions.file_controller import (
    _get_desktop, _get_documents, _get_downloads, _get_pictures, _get_music,
    _get_videos, _is_safe_path, _resolve_path, _format_size,
    create_file, create_folder, delete_file, move_file, copy_file, rename_file, read_file
)
from core.undo import push_undo, undo_last, can_undo, peek

_OS = platform.system()


# ── Color Palette ─────────────────────────────────────────────────────────────
class HoloColors:
    BG          = "#00060a"
    PANEL       = "#010d14"
    PANEL2      = "#010f18"
    PANEL_GLASS = QColor(1, 15, 24, 215)
    BORDER      = "#0d3347"
    BORDER_A    = "#1a5570"
    BORDER_B    = "#00a0cc"
    PRI         = "#00d4ff"         # Stark Cyan
    PRI_DIM     = "#0088aa"
    PRI_GLOW    = QColor(0, 212, 255, 60)
    ACC         = "#00ffff"
    ACC2        = "#0099ff"
    AMBER       = "#ffaa00"         # Holographic Warning / Folder accent
    AMBER_DIM   = "#996600"
    GREEN       = "#00ff88"
    RED         = "#ff3355"
    WHITE       = "#d8f4ff"
    TEXT_DIM    = "#4a758c"
    TEXT_MED    = "#80a8bf"


# ── Category Helper ──────────────────────────────────────────────────────────
def get_file_category(path: Path) -> tuple[str, str, str]:
    """Returns (category_name, icon_glyph, color_hex)."""
    if path.is_dir():
        return "FOLDER", "📁", HoloColors.AMBER
    ext = path.suffix.lower()
    if ext in (".py", ".js", ".ts", ".html", ".css", ".json", ".cpp", ".c", ".h", ".rs", ".go", ".java", ".sh", ".bat"):
        return "CODE", "</>", HoloColors.PRI
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"):
        return "IMAGE", "🖼", HoloColors.ACC
    if ext in (".mp4", ".mkv", ".avi", ".mov", ".mp3", ".wav", ".flac", ".ogg"):
        return "MEDIA", "🎬", "#bf80ff"
    if ext in (".zip", ".tar", ".gz", ".7z", ".rar"):
        return "ARCHIVE", "🗜", HoloColors.AMBER
    if ext in (".md", ".txt", ".pdf", ".docx", ".doc", ".rtf", ".csv", ".xlsx"):
        return "DOC", "📄", HoloColors.WHITE
    return "FILE", "◈", HoloColors.TEXT_MED


# ── Safe Confirmation Modal ───────────────────────────────────────────────────
class SafeActionConfirmModal(QDialog):
    """
    Iron Man styled confirmation dialog for destructive or modifying operations.
    Requires conscious human confirmation — cannot be dismissed or accepted
    by accidental gestures.
    """
    def __init__(self, title: str, message: str, details: str = "", is_destructive: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(480, 260)

        border_col = HoloColors.RED if is_destructive else HoloColors.PRI
        glow_col = "#ff1144" if is_destructive else HoloColors.PRI

        self.setStyleSheet(f"""
            QDialog {{
                background-color: rgba(0, 8, 14, 250);
                border: 2px solid {border_col};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        icon = QLabel("⚠️" if is_destructive else "◈")
        icon.setFont(QFont("Segoe UI Emoji", 14))
        icon.setStyleSheet("background: transparent;")
        hdr.addWidget(icon)

        title_lbl = QLabel(title.upper())
        title_lbl.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {border_col}; background: transparent; letter-spacing: 1px;")
        hdr.addWidget(title_lbl)
        hdr.addStretch()
        layout.addLayout(hdr)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {border_col};")
        layout.addWidget(sep)

        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setFont(QFont("Courier New", 9))
        msg_lbl.setStyleSheet(f"color: {HoloColors.WHITE}; background: transparent;")
        layout.addWidget(msg_lbl)

        if details:
            det_box = QTextEdit()
            det_box.setReadOnly(True)
            det_box.setFont(QFont("Courier New", 8))
            det_box.setPlainText(details)
            det_box.setMaximumHeight(70)
            det_box.setStyleSheet(f"""
                QTextEdit {{
                    background: {HoloColors.PANEL2};
                    color: {HoloColors.TEXT_MED};
                    border: 1px solid {HoloColors.BORDER};
                    border-radius: 3px;
                    padding: 4px;
                }}
            """)
            layout.addWidget(det_box)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {HoloColors.TEXT_MED};
                border: 1px solid {HoloColors.BORDER}; border-radius: 3px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ color: {HoloColors.WHITE}; border-color: {HoloColors.BORDER_B}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("PROCEED" if not is_destructive else "CONFIRM DELETE")
        confirm_btn.setFixedHeight(32)
        confirm_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: {HoloColors.PANEL2};
                color: {border_col};
                border: 1px solid {border_col};
                border-radius: 3px;
                padding: 0 18px;
            }}
            QPushButton:hover {{
                background: {border_col};
                color: #000;
            }}
        """)
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)


# ── Floating Holographic File Card ───────────────────────────────────────────
class HoloFileCard(QFrame):
    """
    Holographic interactive card representing an item in the directory.
    Supports visual hover glowing, selection pulsing, and floating movement.
    """
    clicked = pyqtSignal(object)       # self
    double_clicked = pyqtSignal(object) # self

    CARD_W = 160
    CARD_H = 110

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.name = path.name
        self.is_dir = path.is_dir()
        self.category, self.icon_glyph, self.theme_color = get_file_category(path)
        self.size_str = "" if self.is_dir else _format_size(path.stat().st_size if path.exists() else 0)
        self.mod_time = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m %H:%M") if path.exists() else ""

        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._is_selected = False
        self._is_hovered = False
        self._is_dragged = False
        self.virtual_pos = QPointF(0, 0)

        # Pulse timer for selection aura
        self._pulse_alpha = 0.0
        self._pulse_dir = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._step_pulse)

    def set_selected(self, selected: bool):
        self._is_selected = selected
        if selected:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._pulse_alpha = 0.0
        self.update()

    def set_hovered(self, hovered: bool):
        if self._is_hovered != hovered:
            self._is_hovered = hovered
            self.update()

    def set_dragged(self, dragged: bool):
        self._is_dragged = dragged
        self.update()

    def _step_pulse(self):
        self._pulse_alpha += 0.08 * self._pulse_dir
        if self._pulse_alpha >= 1.0:
            self._pulse_alpha = 1.0
            self._pulse_dir = -1.0
        elif self._pulse_alpha <= 0.2:
            self._pulse_alpha = 0.2
            self._pulse_dir = 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        base_color = QColor(self.theme_color)

        # Background fill
        if self._is_selected:
            bg_col = QColor(0, 20, 35, 235)
            border_col = QColor(HoloColors.ACC)
            border_w = 2.0
        elif self._is_hovered:
            bg_col = QColor(0, 16, 28, 220)
            border_col = base_color
            border_w = 1.5
        else:
            bg_col = QColor(1, 13, 20, 190)
            border_col = QColor(HoloColors.BORDER)
            border_w = 1.0

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bg_col))
        p.drawRoundedRect(rect, 4, 4)

        # Holographic outer glowing border
        if self._is_selected:
            glow_pen = QPen(QColor(0, 212, 255, int(120 + 100 * self._pulse_alpha)), border_w + 1.0)
            p.setPen(glow_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 4, 4)

        p.setPen(QPen(border_col, border_w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 4, 4)

        # Futuristic corner brackets
        bracket_len = 8.0
        p.setPen(QPen(base_color if self._is_hovered or self._is_selected else QColor(HoloColors.BORDER_B), 1.6))
        # Top-left
        p.drawLine(QPointF(rect.left(), rect.top() + bracket_len), QPointF(rect.left(), rect.top()))
        p.drawLine(QPointF(rect.left(), rect.top()), QPointF(rect.left() + bracket_len, rect.top()))
        # Top-right
        p.drawLine(QPointF(rect.right() - bracket_len, rect.top()), QPointF(rect.right(), rect.top()))
        p.drawLine(QPointF(rect.right(), rect.top()), QPointF(rect.right(), rect.top() + bracket_len))
        # Bottom-left
        p.drawLine(QPointF(rect.left(), rect.bottom() - bracket_len), QPointF(rect.left(), rect.bottom()))
        p.drawLine(QPointF(rect.left(), rect.bottom()), QPointF(rect.left() + bracket_len, rect.bottom()))
        # Bottom-right
        p.drawLine(QPointF(rect.right() - bracket_len, rect.bottom()), QPointF(rect.right(), rect.bottom()))
        p.drawLine(QPointF(rect.right(), rect.bottom()), QPointF(rect.right(), rect.bottom() - bracket_len))

        # Icon / Category Glyph
        p.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        p.setPen(QPen(base_color))
        p.drawText(QRectF(rect.left() + 10, rect.top() + 10, 36, 36), Qt.AlignmentFlag.AlignCenter, self.icon_glyph)

        # Extension Badge (for files)
        if not self.is_dir and self.path.suffix:
            badge_text = self.path.suffix.upper()[1:][:5]
            badge_rect = QRectF(rect.right() - 48, rect.top() + 10, 38, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(0, 30, 45, 180)))
            p.drawRoundedRect(badge_rect, 2, 2)
            p.setPen(QPen(QColor(HoloColors.TEXT_MED)))
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # File Name
        name_font = QFont("Courier New", 8, QFont.Weight.Bold if self.is_dir else QFont.Weight.Normal)
        p.setFont(name_font)
        p.setPen(QPen(QColor(HoloColors.WHITE if (self._is_selected or self._is_hovered) else HoloColors.WHITE)))
        name_rect = QRectF(rect.left() + 10, rect.top() + 50, rect.width() - 20, 34)
        elided = p.fontMetrics().elidedText(self.name, Qt.TextElideMode.ElideMiddle, int(name_rect.width()))
        p.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, elided)

        # Metadata footer (size & date)
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(QColor(HoloColors.TEXT_DIM)))
        meta_rect = QRectF(rect.left() + 10, rect.bottom() - 18, rect.width() - 20, 14)
        info_txt = "DIR" if self.is_dir else self.size_str
        if self.mod_time:
            info_txt += f"  {self.mod_time.split()[0]}"
        p.drawText(meta_rect, Qt.AlignmentFlag.AlignLeft, info_txt)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self)
        super().mouseDoubleClickEvent(event)


# ── Holographic File Explorer Widget ──────────────────────────────────────────
class HolographicFileExplorer(QWidget):
    """
    Full futuristic file manager widget integrated into Mark LV.
    """
    file_opened = pyqtSignal(str)          # Emitted when a file is opened
    status_message = pyqtSignal(str)       # Status updates

    def __init__(self, start_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("HolographicFileExplorer")
        self.setStyleSheet(f"""
            QWidget#HolographicFileExplorer {{
                background-color: {HoloColors.BG};
            }}
        """)

        # Directory state
        self.current_dir = (start_dir or _get_desktop()).resolve()
        if not self.current_dir.exists():
            self.current_dir = Path.home().resolve()

        self._history: list[Path] = [self.current_dir]
        self._history_idx = 0

        self.selected_card: Optional[HoloFileCard] = None
        self.cards: list[HoloFileCard] = []
        self._hovered_card: Optional[HoloFileCard] = None

        # Drag state
        self._dragging_card: Optional[HoloFileCard] = None
        self._drag_offset = QPointF(0, 0)

        # Scale / Zoom
        self._card_zoom = 1.0

        # UI Setup
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(12, 10, 12, 10)
        root_lay.setSpacing(8)

        # ── Header Toolbar ───────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        def _tool_btn(text: str, tip: str = "") -> QPushButton:
            b = QPushButton(text)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setFixedHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if tip:
                b.setToolTip(tip)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {HoloColors.PANEL2};
                    color: {HoloColors.TEXT_MED};
                    border: 1px solid {HoloColors.BORDER};
                    border-radius: 3px;
                    padding: 0 10px;
                }}
                QPushButton:hover {{
                    color: {HoloColors.PRI};
                    border-color: {HoloColors.BORDER_B};
                    background: rgba(0, 212, 255, 15);
                }}
                QPushButton:disabled {{
                    color: {HoloColors.BORDER_A};
                    border-color: {HoloColors.BORDER};
                }}
            """)
            return b

        self._btn_back = _tool_btn("←", "Back")
        self._btn_back.clicked.connect(self.go_back)
        hdr.addWidget(self._btn_back)

        self._btn_fwd = _tool_btn("→", "Forward")
        self._btn_fwd.clicked.connect(self.go_forward)
        hdr.addWidget(self._btn_fwd)

        self._btn_up = _tool_btn("↑", "Parent Directory")
        self._btn_up.clicked.connect(self.go_up)
        hdr.addWidget(self._btn_up)

        self._btn_home = _tool_btn("⌂", "Home / Desktop")
        self._btn_home.clicked.connect(lambda: self.navigate_to(_get_desktop()))
        hdr.addWidget(self._btn_home)

        # Breadcrumbs bar
        self._crumb_container = QWidget()
        self._crumb_container.setStyleSheet(f"""
            background: {HoloColors.PANEL};
            border: 1px solid {HoloColors.BORDER};
            border-radius: 3px;
        """)
        self._crumb_lay = QHBoxLayout(self._crumb_container)
        self._crumb_lay.setContentsMargins(8, 2, 8, 2)
        self._crumb_lay.setSpacing(4)
        hdr.addWidget(self._crumb_container, stretch=1)

        # Search box
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 Filter files...")
        self._search_input.setFont(QFont("Courier New", 8))
        self._search_input.setFixedHeight(28)
        self._search_input.setFixedWidth(180)
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {HoloColors.PANEL2};
                color: {HoloColors.WHITE};
                border: 1px solid {HoloColors.BORDER};
                border-radius: 3px;
                padding: 0 8px;
            }}
            QLineEdit:focus {{
                border-color: {HoloColors.PRI};
            }}
        """)
        self._search_input.textChanged.connect(self._filter_cards)
        hdr.addWidget(self._search_input)

        # Actions: New Folder, Refresh, Undo
        self._btn_new_folder = _tool_btn("+ FOLDER", "Create new folder")
        self._btn_new_folder.clicked.connect(self._prompt_create_folder)
        hdr.addWidget(self._btn_new_folder)

        self._btn_refresh = _tool_btn("↻", "Refresh")
        self._btn_refresh.clicked.connect(self.refresh)
        hdr.addWidget(self._btn_refresh)

        self._btn_undo = _tool_btn("↶ UNDO", "Undo last file operation")
        self._btn_undo.clicked.connect(self._do_undo)
        hdr.addWidget(self._btn_undo)

        self._btn_close = _tool_btn("✕ CLOSE", "Close holographic explorer")
        self._btn_close.clicked.connect(self.hide)
        hdr.addWidget(self._btn_close)

        root_lay.addLayout(hdr)

        # ── Main Workspace Splitter (Cards + Inspector) ───────────────────────
        self._split = QSplitter(Qt.Orientation.Horizontal)
        self._split.setStyleSheet(f"""
            QSplitter::handle {{
                background: {HoloColors.BORDER};
                width: 2px;
            }}
        """)

        # Left / Center: Holographic card canvas
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background: transparent; border: none;")

        self._canvas = QWidget()
        self._canvas.setStyleSheet("background: transparent;")
        self._grid_lay = QHBoxLayout(self._canvas)
        self._grid_lay.setContentsMargins(10, 10, 10, 10)
        self._grid_lay.setSpacing(12)

        # Flow container inside scroll
        self._card_flow_widget = QWidget(self._canvas)
        self._card_flow_widget.setStyleSheet("background: transparent;")
        self._scroll.setWidget(self._canvas)
        self._split.addWidget(self._scroll)

        # Right: Holographic File Inspector & Preview Panel
        self._inspector = self._build_inspector()
        self._split.addWidget(self._inspector)
        self._split.setSizes([600, 260])

        root_lay.addWidget(self._split, stretch=1)

        # ── Footer Status Bar ────────────────────────────────────────────────
        foot = QHBoxLayout()
        foot.setContentsMargins(4, 0, 4, 0)
        self._status_lbl = QLabel("HOLOGRAPHIC FILE SYSTEM ACTIVE")
        self._status_lbl.setFont(QFont("Courier New", 7))
        self._status_lbl.setStyleSheet(f"color: {HoloColors.TEXT_MED}; background: transparent;")
        foot.addWidget(self._status_lbl)
        foot.addStretch()

        gesture_hint = QLabel("✋ GESTURES: [INDEX] POINT  |  [PINCH] SELECT  |  [DRAG] REARRANGE  |  [SWIPE] NAVIGATE")
        gesture_hint.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        gesture_hint.setStyleSheet(f"color: {HoloColors.PRI_DIM}; background: transparent; letter-spacing: 0.5px;")
        foot.addWidget(gesture_hint)

        root_lay.addLayout(foot)

    def _build_inspector(self) -> QWidget:
        w = QWidget()
        w.setObjectName("HoloInspector")
        w.setStyleSheet(f"""
            QWidget#HoloInspector {{
                background: {HoloColors.PANEL};
                border: 1px solid {HoloColors.BORDER};
                border-radius: 4px;
            }}
        """)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        hdr = QLabel("◈ ITEM INSPECTOR")
        hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {HoloColors.PRI}; background: transparent; letter-spacing: 1px;")
        lay.addWidget(hdr)

        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {HoloColors.BORDER};")
        lay.addWidget(sep)

        # Details
        self._insp_name = QLabel("No item selected")
        self._insp_name.setWordWrap(True)
        self._insp_name.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._insp_name.setStyleSheet(f"color: {HoloColors.WHITE}; background: transparent;")
        lay.addWidget(self._insp_name)

        self._insp_meta = QLabel("")
        self._insp_meta.setFont(QFont("Courier New", 7))
        self._insp_meta.setStyleSheet(f"color: {HoloColors.TEXT_MED}; background: transparent;")
        lay.addWidget(self._insp_meta)

        # Preview area (Text or Image)
        self._insp_preview = QTextEdit()
        self._insp_preview.setReadOnly(True)
        self._insp_preview.setFont(QFont("Courier New", 8))
        self._insp_preview.setStyleSheet(f"""
            QTextEdit {{
                background: {HoloColors.PANEL2};
                color: {HoloColors.WHITE};
                border: 1px solid {HoloColors.BORDER};
                border-radius: 3px;
                padding: 6px;
            }}
        """)
        self._insp_preview.setPlaceholderText("Select a file to preview contents...")
        lay.addWidget(self._insp_preview, stretch=1)

        # Action Buttons
        btn_box = QVBoxLayout()
        btn_box.setSpacing(4)

        def _action_btn(text: str, color: str = HoloColors.PRI) -> QPushButton:
            b = QPushButton(text)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setFixedHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {HoloColors.PANEL2};
                    color: {color};
                    border: 1px solid {color};
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background: {color};
                    color: #000;
                }}
                QPushButton:disabled {{
                    color: {HoloColors.TEXT_DIM};
                    border-color: {HoloColors.BORDER};
                }}
            """)
            return b

        self._btn_open = _action_btn("🚀  OPEN ITEM")
        self._btn_open.clicked.connect(self._open_selected_item)
        btn_box.addWidget(self._btn_open)

        self._btn_rename = _action_btn("✏  RENAME", HoloColors.TEXT_MED)
        self._btn_rename.clicked.connect(self._prompt_rename)
        btn_box.addWidget(self._btn_rename)

        self._btn_delete = _action_btn("🗑  MOVE TO TRASH", HoloColors.RED)
        self._btn_delete.clicked.connect(self._prompt_delete)
        btn_box.addWidget(self._btn_delete)

        lay.addLayout(btn_box)
        return w

    # ── Breadcrumb Updates ────────────────────────────────────────────────────
    def _update_breadcrumbs(self):
        while self._crumb_lay.count():
            item = self._crumb_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        parts = []
        curr = self.current_dir
        while curr != curr.parent:
            parts.append(curr)
            curr = curr.parent
        parts.append(curr)  # Root
        parts.reverse()

        for idx, part in enumerate(parts):
            display_name = part.name if part.name else str(part)
            btn = QPushButton(display_name)
            btn.setFont(QFont("Courier New", 8))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {HoloColors.PRI if idx == len(parts) - 1 else HoloColors.TEXT_MED};
                    background: transparent; border: none; padding: 2px 4px;
                }}
                QPushButton:hover {{ color: {HoloColors.WHITE}; }}
            """)
            btn.clicked.connect(lambda _, p=part: self.navigate_to(p))
            self._crumb_lay.addWidget(btn)

            if idx < len(parts) - 1:
                sep = QLabel("▸")
                sep.setFont(QFont("Courier New", 7))
                sep.setStyleSheet(f"color: {HoloColors.TEXT_DIM}; background: transparent;")
                self._crumb_lay.addWidget(sep)

        self._crumb_lay.addStretch()

    # ── Directory Navigation ──────────────────────────────────────────────────
    def navigate_to(self, target: Path):
        try:
            res = target.resolve()
            if not _is_safe_path(res):
                self._show_error("Access Denied", f"Path outside safe boundary: {res}")
                return
            if not res.exists() or not res.is_dir():
                self._show_error("Path Not Found", f"Directory does not exist: {res}")
                return

            self.current_dir = res
            # Maintain history
            if not self._history or self._history[self._history_idx] != res:
                self._history = self._history[:self._history_idx + 1]
                self._history.append(res)
                self._history_idx = len(self._history) - 1

            self.refresh()
        except Exception as e:
            self._show_error("Navigation Error", str(e))

    def go_back(self):
        if self._history_idx > 0:
            self._history_idx -= 1
            self.current_dir = self._history[self._history_idx]
            self.refresh()

    def go_forward(self):
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.current_dir = self._history[self._history_idx]
            self.refresh()

    def go_up(self):
        if self.current_dir != self.current_dir.parent:
            self.navigate_to(self.current_dir.parent)

    def refresh(self):
        self._btn_back.setEnabled(self._history_idx > 0)
        self._btn_fwd.setEnabled(self._history_idx < len(self._history) - 1)
        self._update_breadcrumbs()

        # Clear existing cards
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()
        self.selected_card = None
        self._update_inspector_empty()

        # Update undo button
        lbl = peek()
        if lbl and can_undo():
            self._btn_undo.setEnabled(True)
            self._btn_undo.setText(f"↶ {lbl[:14]}")
        else:
            self._btn_undo.setEnabled(False)
            self._btn_undo.setText("↶ UNDO")

        # Load directory entries safely
        try:
            entries = []
            for item in sorted(self.current_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.name.startswith("."):
                    continue
                entries.append(item)

            for item in entries:
                card = HoloFileCard(item, parent=self._canvas)
                card.clicked.connect(self._on_card_clicked)
                card.double_clicked.connect(self._on_card_double_clicked)
                self.cards.append(card)

            self._arrange_cards()
            self._status_lbl.setText(f"PATH: {self.current_dir}  |  ITEMS: {len(self.cards)}")
        except Exception as e:
            self._show_error("Directory Read Error", str(e))

    def _arrange_cards(self):
        """Layout cards in a flexible responsive grid inside the canvas."""
        padding = 16
        spacing_x = 16
        spacing_y = 16
        card_w = HoloFileCard.CARD_W
        card_h = HoloFileCard.CARD_H

        view_w = max(400, self._scroll.viewport().width() - 32)
        cols = max(1, view_w // (card_w + spacing_x))

        for idx, card in enumerate(self.cards):
            r = idx // cols
            c = idx % cols
            x = padding + c * (card_w + spacing_x)
            y = padding + r * (card_h + spacing_y)
            card.move(int(x), int(y))
            card.virtual_pos = QPointF(x, y)
            card.show()

        total_rows = (len(self.cards) + cols - 1) // cols if cols else 1
        canvas_h = max(300, padding * 2 + total_rows * (card_h + spacing_y))
        self._canvas.resize(view_w, canvas_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_cards()

    # ── Search / Filtering ────────────────────────────────────────────────────
    def _filter_cards(self, query: str):
        q = query.strip().lower()
        visible_count = 0
        for card in self.cards:
            match = (not q) or (q in card.name.lower())
            card.setVisible(match)
            if match:
                visible_count += 1
        # Re-pack visible cards
        padding = 16
        spacing_x = 16
        spacing_y = 16
        card_w = HoloFileCard.CARD_W
        card_h = HoloFileCard.CARD_H
        view_w = max(400, self._scroll.viewport().width() - 32)
        cols = max(1, view_w // (card_w + spacing_x))

        vis_idx = 0
        for card in self.cards:
            if not card.isVisible():
                continue
            r = vis_idx // cols
            c = vis_idx % cols
            x = padding + c * (card_w + spacing_x)
            y = padding + r * (card_h + spacing_y)
            card.move(int(x), int(y))
            vis_idx += 1

    # ── Selection & Inspector ─────────────────────────────────────────────────
    def _on_card_clicked(self, card: HoloFileCard):
        if self.selected_card and self.selected_card != card:
            self.selected_card.set_selected(False)
        self.selected_card = card
        card.set_selected(True)
        self._update_inspector(card)

    def _on_card_double_clicked(self, card: HoloFileCard):
        if card.is_dir:
            self.navigate_to(card.path)
        else:
            self._open_file_system_default(card.path)

    def _update_inspector_empty(self):
        self._insp_name.setText("No item selected")
        self._insp_meta.setText("")
        self._insp_preview.clear()
        self._insp_preview.setPlaceholderText("Select a file to preview contents...")
        self._btn_open.setEnabled(False)
        self._btn_rename.setEnabled(False)
        self._btn_delete.setEnabled(False)

    def _update_inspector(self, card: HoloFileCard):
        self._insp_name.setText(card.name)
        meta = f"TYPE: {card.category}\nSIZE: {card.size_str or 'Directory'}\nMODIFIED: {card.mod_time}\nPATH: {card.path}"
        self._insp_meta.setText(meta)
        self._btn_open.setEnabled(True)
        self._btn_rename.setEnabled(True)
        self._btn_delete.setEnabled(True)

        # Populate Preview
        if card.is_dir:
            try:
                sub_items = [p.name for p in list(card.path.iterdir())[:20] if not p.name.startswith(".")]
                self._insp_preview.setPlainText(f"Folder contains {len(sub_items)} visible items:\n\n" + "\n".join(f"📁 {i}" for i in sub_items))
            except Exception as e:
                self._insp_preview.setPlainText(f"Cannot read directory: {e}")
        elif card.category in ("CODE", "DOC"):
            try:
                content = read_file(str(card.path), max_chars=3000)
                self._insp_preview.setPlainText(content)
            except Exception as e:
                self._insp_preview.setPlainText(f"Error previewing file: {e}")
        elif card.category == "IMAGE":
            self._insp_preview.setHtml(f"<div style='color:#00d4ff;'>[IMAGE FILE]<br><b>{card.name}</b><br><br>Ready for viewing. Click OPEN ITEM to view in full resolution.</div>")
        else:
            self._insp_preview.setPlainText(f"Binary file ({card.category})\nSize: {card.size_str}\nPath: {card.path}")

    # ── Safe File Actions ─────────────────────────────────────────────────────
    def _open_selected_item(self):
        if not self.selected_card:
            return
        if self.selected_card.is_dir:
            self.navigate_to(self.selected_card.path)
        else:
            self._open_file_system_default(self.selected_card.path)

    def _open_file_system_default(self, path: Path):
        try:
            if _OS == "Windows":
                os.startfile(str(path))
            elif _OS == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            self.file_opened.emit(str(path))
            self.status_message.emit(f"Opened {path.name}")
        except Exception as e:
            self._show_error("Open Error", f"Could not open file: {e}")

    def _prompt_create_folder(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Create Folder", "Enter new folder name:")
        if ok and name.strip():
            res = create_folder(str(self.current_dir), name.strip())
            self.status_message.emit(res)
            self.refresh()

    def _prompt_rename(self):
        if not self.selected_card:
            return
        from PyQt6.QtWidgets import QInputDialog
        old_name = self.selected_card.name
        new_name, ok = QInputDialog.getText(self, "Rename Item", "Enter new name:", text=old_name)
        if ok and new_name.strip() and new_name.strip() != old_name:
            res = rename_file(str(self.current_dir), old_name, new_name.strip())
            self.status_message.emit(res)
            self.refresh()

    def _prompt_delete(self):
        if not self.selected_card:
            return
        target = self.selected_card.path
        # Destructive Confirmation Modal
        modal = SafeActionConfirmModal(
            title="CONFIRM DELETION",
            message=f"Are you sure you want to move '{target.name}' to the Recycle Bin / Trash?",
            details=f"Path: {target}\nThis action is recoverable via Trash or Mark LV Undo.",
            is_destructive=True,
            parent=self,
        )
        if modal.exec() == QDialog.DialogCode.Accepted:
            res = delete_file(str(self.current_dir), target.name)
            self.status_message.emit(res)
            self.refresh()

    def _do_undo(self):
        res = undo_last()
        self.status_message.emit(res)
        self.refresh()

    def _show_error(self, title: str, msg: str):
        QMessageBox.warning(self, title, msg)

    # ── Hand Gesture Hooks (Point, Select, Drag, Swipe, Zoom) ─────────────────
    def handle_cursor_move(self, norm_x: float, norm_y: float) -> Optional[HoloFileCard]:
        """
        Maps normalized HUD screen coords (0.0 to 1.0) into the canvas space,
        highlighting any card under the cursor with pixel-perfect alignment.
        """
        hud_pt_global = self.mapToGlobal(QPoint(int(norm_x * self.width()), int(norm_y * self.height())))

        hovered: Optional[HoloFileCard] = None
        for card in self.cards:
            if not card.isVisible():
                continue
            card_global = card.mapToGlobal(QPoint(0, 0))
            card_rect = QRect(card_global, card.size())
            if card_rect.contains(hud_pt_global):
                hovered = card
                break

        if self._hovered_card != hovered:
            if self._hovered_card:
                self._hovered_card.set_hovered(False)
            self._hovered_card = hovered
            if self._hovered_card:
                self._hovered_card.set_hovered(True)

        return hovered

    def handle_pinch_select(self, norm_x: float, norm_y: float):
        """Pinch select click on item or button under cursor."""
        card = self.handle_cursor_move(norm_x, norm_y)
        if card:
            if self.selected_card == card:
                self._on_card_double_clicked(card)
            else:
                self._on_card_clicked(card)
            return

        hud_pt_global = self.mapToGlobal(QPoint(int(norm_x * self.width()), int(norm_y * self.height())))
        for btn in (getattr(self, '_btn_close', None), getattr(self, '_btn_back', None),
                    getattr(self, '_btn_fwd', None), getattr(self, '_btn_open', None)):
            if btn and btn.isVisible() and btn.isEnabled():
                b_rect = QRect(btn.mapToGlobal(QPoint(0, 0)), btn.size())
                if b_rect.contains(hud_pt_global):
                    btn.click()
                    break

    def handle_pinch_drag(self, norm_x: float, norm_y: float, dx: float, dy: float):
        """
        Visual rearrangement of card within the holographic workspace.
        Does NOT move real files on disk.
        """
        if not self._dragging_card and self._hovered_card:
            self._dragging_card = self._hovered_card
            self._dragging_card.set_dragged(True)

        if self._dragging_card:
            delta_px = QPointF(dx * self.width(), dy * self.height())
            new_pos = self._dragging_card.pos() + delta_px.toPoint()
            self._dragging_card.move(new_pos)

    def handle_pinch_release(self, norm_x: float, norm_y: float):
        if self._dragging_card:
            self._dragging_card.set_dragged(False)
            self._dragging_card = None

    def handle_swipe(self, direction: str):
        """Two-finger navigation swipe."""
        if direction == "SWIPE_LEFT":
            self.go_forward()
        elif direction == "SWIPE_RIGHT":
            self.go_back()
        elif direction == "SWIPE_UP":
            sb = self._scroll.verticalScrollBar()
            sb.setValue(sb.value() + 120)
        elif direction == "SWIPE_DOWN":
            sb = self._scroll.verticalScrollBar()
            sb.setValue(sb.value() - 120)

    def handle_zoom(self, delta: float):
        """Two-hand zoom workspace scale."""
        self._card_zoom = max(0.7, min(1.6, self._card_zoom + delta * 0.1))
        # Subtle card scale feedback
        for card in self.cards:
            card.setFixedSize(
                int(HoloFileCard.CARD_W * self._card_zoom),
                int(HoloFileCard.CARD_H * self._card_zoom),
            )
        self._arrange_cards()
