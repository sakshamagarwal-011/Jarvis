

"""
core/screen_capture.py — High-Fidelity Screen Capture and Coordinate Mapping Engine.

Handles:
- Full-resolution screenshot acquisition across single or multi-monitor setups.
- Real physical pixel dimensions vs. logical OS desktop coordinates.
- Conversion between vision normalized coordinates [0, 1000] and physical screen pixels.
- Cropping of regions of interest for high-resolution zoomed inspection.
- Image difference calculation to detect UI changes before and after actions.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional, Tuple

from PIL import Image, ImageChops, ImageGrab
import numpy as np

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

from core.os_input import get_screen_info, ScreenInfo


@dataclass
class ScreenshotResult:
    image: Image.Image
    image_bytes: bytes
    mime_type: str
    width: int
    height: int
    left: int
    top: int
    screen_info: ScreenInfo

    def to_screen_coords(self, norm_x: float, norm_y: float) -> tuple[int, int]:
        """
        Converts normalized coordinates (0.0 to 1.0 or 0 to 1000)
        to physical OS desktop coordinates (x, y).
        """
        # If passed as 0-1000 integer range, convert to 0.0-1.0
        nx = norm_x / 1000.0 if norm_x > 1.0 else norm_x
        ny = norm_y / 1000.0 if norm_y > 1.0 else norm_y

        px = int(round(self.left + nx * self.width))
        py = int(round(self.top + ny * self.height))
        return px, py

    def to_normalized_coords(self, screen_x: int, screen_y: int) -> tuple[float, float]:
        """Converts physical screen coordinates to normalized [0.0, 1.0]."""
        nx = (screen_x - self.left) / float(max(1, self.width))
        ny = (screen_y - self.top) / float(max(1, self.height))
        return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))


def capture_screen(
    monitor_index: int = 1,
    max_dimension: int = 1920,
    quality: int = 85,
) -> ScreenshotResult:
    """
    Captures a crisp, high-fidelity screenshot of the desktop.
    monitor_index: 1 for primary monitor, 0 for all combined virtual desktop.
    """
    s_info = get_screen_info()

    if _MSS:
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index < len(monitors):
                target = monitors[monitor_index]
            else:
                target = monitors[0]

            shot = sct.grab(target)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            left = target.get("left", 0)
            top = target.get("top", 0)
            w = target.get("width", shot.width)
            h = target.get("height", shot.height)
    else:
        img = ImageGrab.grab(all_screens=True).convert("RGB")
        w, h = img.size
        left, top = 0, 0

    # Prepare JPEG bytes for Gemini API vision
    buf = io.BytesIO()
    if max(img.width, img.height) > max_dimension:
        ratio = max_dimension / float(max(img.width, img.height))
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        resized = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
        resized.save(buf, format="JPEG", quality=quality)
    else:
        img.save(buf, format="JPEG", quality=quality)

    img_bytes = buf.getvalue()

    return ScreenshotResult(
        image=img,
        image_bytes=img_bytes,
        mime_type="image/jpeg",
        width=w,
        height=h,
        left=left,
        top=top,
        screen_info=s_info,
    )


def compute_screen_difference(
    before: Image.Image,
    after: Image.Image,
    threshold: int = 15,
) -> float:
    """
    Computes percentage (0.0 to 100.0) of pixels that changed between two screenshots.
    Useful for instant, local verification that an interaction triggered a visual change.
    """
    ref_size = (320, 180)
    img1 = before.resize(ref_size).convert("L")
    img2 = after.resize(ref_size).convert("L")

    diff = ImageChops.difference(img1, img2)
    diff_arr = np.array(diff)
    changed_pixels = np.count_nonzero(diff_arr > threshold)
    total_pixels = ref_size[0] * ref_size[1]
    pct = (changed_pixels / float(total_pixels)) * 100.0
    return float(pct)
