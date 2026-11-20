
"""
core/vision_detector.py — High-Accuracy UI Element Detector and Screen Reasoning Engine.

Uses Gemini Vision (via core.gemini ladder) to:
- Detect UI elements (buttons, inputs, links, tabs, menus, icons, dialogs).
- Return normalized bounding boxes [ymin, xmin, ymax, xmax] in [0, 1000] space.
- Calculate exact clickable center coordinates mapped to OS physical desktop pixels.
- Verify whether an interaction succeeded by comparing before-and-after screenshots.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple

from google.genai import types as gtypes

from core import gemini
from core.screen_capture import ScreenshotResult, compute_screen_difference


@dataclass
class DetectedElement:
    description: str
    element_type: str                  # button, input, link, checkbox, menu, icon, text
    box_2d: tuple[int, int, int, int]  # (ymin, xmin, ymax, xmax) in [0, 1000] space
    center_norm: tuple[int, int]       # (x, y) in [0, 1000] space
    screen_x: int                      # Physical OS desktop X pixel
    screen_y: int                      # Physical OS desktop Y pixel
    confidence: float
    reasoning: str


@dataclass
class VerificationResult:
    verified: bool
    status: str                        # "ACTION_VERIFIED", "ACTION_FAILED", "ACTION_EXECUTED"
    explanation: str
    pixel_change_pct: float


def _clean_json_response(raw_text: str) -> str:
    """Extract clean JSON object or array from markdown fenced text."""
    t = raw_text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        # Remove opening and closing fences
        if len(lines) > 2 and lines[-1].strip().startswith("```"):
            t = "\n".join(lines[1:-1]).strip()
        else:
            t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
            t = re.sub(r"\n?```$", "", t).strip()

    # Search for first { or [ to last } or ]
    idx_brace = t.find("{")
    idx_bracket = t.find("[")

    if idx_brace != -1 and (idx_bracket == -1 or idx_brace < idx_bracket):
        end = t.rfind("}")
        if end != -1:
            return t[idx_brace : end + 1]
    elif idx_bracket != -1:
        end = t.rfind("]")
        if end != -1:
            return t[idx_bracket : end + 1]

    return t


def find_element(
    shot: ScreenshotResult,
    description: str,
    context_hint: str = "",
) -> Optional[DetectedElement]:
    """
    Locates a specific UI element described in natural language on the screenshot.
    Returns DetectedElement with exact physical OS screen coordinates (screen_x, screen_y).
    """
    prompt = f"""
You are an expert GUI automation perception system.
Analyze this high-resolution desktop screenshot ({shot.width}x{shot.height}).
Find the UI element described as: "{description}".
{f'Additional context: {context_hint}' if context_hint else ''}

Coordinate system:
- Use normalized coordinates where top-left is [0, 0] and bottom-right is [1000, 1000].
- Bounding box format: [ymin, xmin, ymax, xmax].
- Calculate the center point [center_y, center_x] strictly inside the clickable area.

Respond ONLY with valid JSON in this exact structure:
{{
  "found": true,
  "element_name": "{description}",
  "element_type": "button|input|link|tab|menu|icon|checkbox|dialog",
  "box_2d": [ymin, xmin, ymax, xmax],
  "center_point": [center_y, center_x],
  "confidence": 0.95,
  "reasoning": "brief explanation of visual cues confirming this element"
}}

If the element is NOT visible on screen, return:
{{
  "found": false,
  "reasoning": "why element could not be found"
}}
"""
    try:
        image_part = gtypes.Part.from_bytes(data=shot.image_bytes, mime_type=shot.mime_type)
        response = gemini.call(
            [image_part, prompt],
            tier=gemini.SMART,
            timeout_ms=25_000,
        )
        if not response or not response.text:
            return None

        clean_json = _clean_json_response(response.text)
        data = json.loads(clean_json)

        if not data.get("found"):
            print(f"[VisionDetector] Element '{description}' not found: {data.get('reasoning')}")
            return None

        box = data.get("box_2d")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return None
        try:
            ymin, xmin, ymax, xmax = (float(v) for v in box)
            confidence = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            return None
        if not (0 <= ymin < ymax <= 1000 and 0 <= xmin < xmax <= 1000):
            return None
        if not (0.6 <= confidence <= 1.0):
            return None
        cp = data.get("center_point")
        if isinstance(cp, (list, tuple)) and len(cp) == 2:
            try:
                cy, cx = int(cp[0]), int(cp[1])
            except (TypeError, ValueError):
                return None
        else:
            cy = int((ymin + ymax) / 2)
            cx = int((xmin + xmax) / 2)
        if not (ymin <= cy <= ymax and xmin <= cx <= xmax):
            return None

        # Convert normalized (0-1000) coordinates to physical OS desktop coordinates
        screen_x, screen_y = shot.to_screen_coords(cx, cy)

        return DetectedElement(
            description=description,
            element_type=data.get("element_type", "element"),
            box_2d=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
            center_norm=(cx, cy),
            screen_x=screen_x,
            screen_y=screen_y,
            confidence=confidence,
            reasoning=str(data.get("reasoning", "")),
        )

    except Exception as e:
        print(f"[VisionDetector] ⚠️ Error detecting '{description}': {e}")
        return None


def verify_interaction(
    before_shot: ScreenshotResult,
    after_shot: ScreenshotResult,
    expected_action: str,
    target_description: str,
) -> VerificationResult:
    """
    Closed-loop verification: compares before and after screenshots to confirm
    whether the requested action produced the expected UI state change.
    """
    diff_pct = compute_screen_difference(before_shot.image, after_shot.image)

    # If virtually no pixels changed at all (< 0.05%), the click likely missed or was ignored
    if diff_pct < 0.05 and "scroll" not in expected_action.lower():
        return VerificationResult(
            verified=False,
            status="ACTION_FAILED",
            explanation=f"No visual change detected on screen ({diff_pct:.2f}% pixel delta). The click or keypress did not register.",
            pixel_change_pct=diff_pct,
        )

    prompt = f"""
You are an autonomous computer vision verification agent.
Compare these two screenshots:
1. BEFORE screenshot: before executing "{expected_action}" on "{target_description}".
2. AFTER screenshot: taken after the action was performed.

Analyze what changed:
- Did the button, link, or menu open/close/toggle?
- Did a new page, modal, tab, or window load?
- Did typed text appear in the target input box?
- Did navigation occur?

Respond ONLY with valid JSON in this structure:
{{
  "verified": true,
  "status": "ACTION_VERIFIED" or "ACTION_FAILED",
  "explanation": "Concrete description of the verified visual change (e.g. login dialog appeared, or text 'Hello' was typed into Notepad)",
  "confidence": 0.95
}}
"""
    try:
        p_before = gtypes.Part.from_bytes(data=before_shot.image_bytes, mime_type=before_shot.mime_type)
        p_after = gtypes.Part.from_bytes(data=after_shot.image_bytes, mime_type=after_shot.mime_type)

        resp = gemini.call(
            [p_before, p_after, prompt],
            tier=gemini.SMART,
            timeout_ms=25_000,
        )
        if resp and resp.text:
            clean_json = _clean_json_response(resp.text)
            data = json.loads(clean_json)
            verified = bool(data.get("verified", False))
            status = "ACTION_VERIFIED" if verified else "ACTION_FAILED"
            return VerificationResult(
                verified=verified,
                status=status,
                explanation=str(data.get("explanation", "Verification completed.")),
                pixel_change_pct=diff_pct,
            )
    except Exception as e:
        print(f"[VisionDetector] Verification call error: {e}")

    # Fallback heuristic if vision call had a network issue: check pixel change percentage
    if diff_pct > 0.4:
        return VerificationResult(
            verified=True,
            status="ACTION_VERIFIED",
            explanation=f"Visual UI update confirmed ({diff_pct:.1f}% screen delta).",
            pixel_change_pct=diff_pct,
        )

    return VerificationResult(
        verified=False,
        status="ACTION_FAILED",
        explanation=f"Action could not be verified ({diff_pct:.2f}% pixel delta).",
        pixel_change_pct=diff_pct,
    )
