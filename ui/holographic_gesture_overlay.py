"""
ui/holographic_gesture_overlay.py — Iron Man Holographic Gesture Cursor & HUD Overlay.

Draws a state-of-the-art holographic cursor, glowing motion trails, interaction feedback rings,
and real-time tracking badges over the Mark LV interface.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Optional, List, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath,
    QPen, QRadialGradient,
)
from PyQt6.QtWidgets import QWidget

from core.hand_tracking import Gesture, HandTrackingFrame
from ui.holographic_file_explorer import HoloColors


class HoloGestureOverlay(QWidget):
    """
    Transparent HUD overlay widget that renders holographic cursor feedback,
    trails, pinch/grab animations, and gesture status.
    """
    pause_toggled = pyqtSignal(bool)
    tracking_stopped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)

        self._active = False
        self._current_frame: Optional[HandTrackingFrame] = None
        self._cursor_norm = (0.5, 0.5)
        self._trail: deque[tuple[float, float, float]] = deque(maxlen=10) # (x, y, time)

        # Reticle rotation angle
        self._rot_angle = 0.0

        # Pinch animation state
        self._pinch_anim = 0.0

        # Click ripple animations: list of [x, y, radius, alpha]
        self._ripples: list[list[float]] = []

        # Timer for smooth cursor animation
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._step_anim)
        self.hide()

    def set_tracking_active(self, active: bool):
        self._active = active
        if active:
            self.show()
            self.raise_()
            self._anim_timer.start()
        else:
            self._anim_timer.stop()
            self._trail.clear()
            self._ripples.clear()
            self.hide()

    def update_frame(self, frame: HandTrackingFrame):
        self._current_frame = frame
        self._cursor_norm = frame.cursor_pos
        now = time.time()
        self._trail.append((frame.cursor_pos[0], frame.cursor_pos[1], now))
        if frame.is_pinching:
            self._pinch_anim = min(1.0, self._pinch_anim + 0.25)
        else:
            self._pinch_anim = max(0.0, self._pinch_anim - 0.2)

    def trigger_click_ripple(self, norm_x: float, norm_y: float):
        w = self.width()
        h = self.height()
        self._ripples.append([norm_x * w, norm_y * h, 10.0, 1.0])

    def _step_anim(self):
        self._rot_angle = (self._rot_angle + 2.5) % 360.0
        # Age out ripples
        alive = []
        for r in self._ripples:
            r[2] += 3.5  # expand radius
            r[3] -= 0.06 # fade alpha
            if r[3] > 0.05:
                alive.append(r)
        self._ripples = alive
        self.update()

    def paintEvent(self, event):
        if not self._active or self._current_frame is None:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W = float(self.width())
        H = float(self.height())
        frame = self._current_frame

        # ── 1. Holographic Top Status HUD ─────────────────────────────────────
        self._paint_hud_banner(p, W, H, frame)

        # ── 2. Motion Trail ───────────────────────────────────────────────────
        if len(self._trail) >= 2:
            now = time.time()
            trail_pts = list(self._trail)
            for i in range(len(trail_pts) - 1):
                p0 = trail_pts[i]
                p1 = trail_pts[i + 1]
                age_factor = max(0.0, 1.0 - (now - p0[2]) / 0.35)
                alpha = int(age_factor * 120)
                pen = QPen(QColor(0, 212, 255, alpha), max(1.0, (i + 1) * 0.45))
                p.setPen(pen)
                p.drawLine(
                    QPointF(p0[0] * W, p0[1] * H),
                    QPointF(p1[0] * W, p1[1] * H),
                )

        # ── 3. Click Ripples ──────────────────────────────────────────────────
        for rx, ry, r_rad, r_alpha in self._ripples:
            col = QColor(0, 255, 255, int(r_alpha * 220))
            p.setPen(QPen(col, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(rx, ry), r_rad, r_rad)

        # ── 4. Holographic Cursor Reticle ─────────────────────────────────────
        cx = self._cursor_norm[0] * W
        cy = self._cursor_norm[1] * H
        self._paint_cursor(p, cx, cy, frame)

    def _paint_hud_banner(self, p: QPainter, W: float, H: float, frame: HandTrackingFrame):
        banner_w = 420.0
        banner_h = 28.0
        bx = (W - banner_w) / 2.0
        by = 8.0

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 8, 14, 210)))
        p.drawRoundedRect(QRectF(bx, by, banner_w, banner_h), 4, 4)

        border_col = QColor(HoloColors.AMBER if frame.is_paused else HoloColors.PRI)
        p.setPen(QPen(border_col, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(bx, by, banner_w, banner_h), 4, 4)

        # Tech corner accents
        acc_len = 5.0
        p.setPen(QPen(QColor(HoloColors.WHITE), 1.4))
        p.drawLine(QPointF(bx, by + acc_len), QPointF(bx, by))
        p.drawLine(QPointF(bx, by), QPointF(bx + acc_len, by))
        p.drawLine(QPointF(bx + banner_w - acc_len, by), QPointF(bx + banner_w, by))
        p.drawLine(QPointF(bx + banner_w, by), QPointF(bx + banner_w, by + acc_len))

        # Status text
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        status = "⏸ PAUSED" if frame.is_paused else f"✋ GESTURE: {frame.primary_gesture.value}"
        info = f"{status}  |  {frame.fps:.0f} FPS  |  HANDS: {frame.active_hand_count}"
        p.setPen(QPen(border_col))
        p.drawText(QRectF(bx + 12, by, banner_w - 24, banner_h), Qt.AlignmentFlag.AlignCenter, info)

    def _paint_cursor(self, p: QPainter, cx: float, cy: float, frame: HandTrackingFrame):
        p.save()
        p.translate(cx, cy)

        is_paused = frame.is_paused
        is_pinching = frame.is_pinching
        is_dragging = frame.is_dragging
        is_grabbing = frame.is_grabbing

        theme_col = QColor(HoloColors.AMBER if is_paused else (HoloColors.RED if is_grabbing else (HoloColors.ACC if is_pinching else HoloColors.PRI)))

        # Outer soft glow aura
        rad = 32.0 - self._pinch_anim * 8.0
        g = QRadialGradient(0, 0, rad * 1.5)
        g.setColorAt(0.0, QColor(theme_col.red(), theme_col.green(), theme_col.blue(), 100))
        g.setColorAt(0.5, QColor(theme_col.red(), theme_col.green(), theme_col.blue(), 35))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(-rad * 1.5, -rad * 1.5, rad * 3.0, rad * 3.0))

        # Center dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(HoloColors.WHITE)))
        p.drawEllipse(QRectF(-3, -3, 6, 6))

        # Inner ring
        inner_r = 12.0 - self._pinch_anim * 4.0
        p.setPen(QPen(theme_col, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(-inner_r, -inner_r, inner_r * 2, inner_r * 2))

        # Rotating outer brackets / arc segments
        p.rotate(self._rot_angle)
        outer_r = 22.0 - self._pinch_anim * 6.0
        p.setPen(QPen(theme_col, 1.6))
        for a in (0, 90, 180, 270):
            p.drawArc(QRectF(-outer_r, -outer_r, outer_r * 2, outer_r * 2), int(a * 16), int(45 * 16))

        # Crosshair ticks
        tick_in = outer_r + 3.0
        tick_out = outer_r + 8.0
        p.setPen(QPen(QColor(HoloColors.WHITE), 1.2))
        p.drawLine(QPointF(tick_in, 0), QPointF(tick_out, 0))
        p.drawLine(QPointF(-tick_in, 0), QPointF(-tick_out, 0))
        p.drawLine(QPointF(0, tick_in), QPointF(0, tick_out))
        p.drawLine(QPointF(0, -tick_in), QPointF(0, -tick_out))

        # Mode label badge below cursor
        p.rotate(-self._rot_angle)
        badge_y = outer_r + 12.0
        label_text = "PAUSED" if is_paused else ("GRAB" if is_grabbing else ("DRAG" if is_dragging else ("PINCH" if is_pinching else "POINT")))
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        badge_rect = QRectF(-30, badge_y, 60, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 10, 18, 190)))
        p.drawRoundedRect(badge_rect, 2, 2)
        p.setPen(QPen(theme_col, 1))
        p.drawRoundedRect(badge_rect, 2, 2)
        p.setPen(QPen(theme_col))
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label_text)

        p.restore()
