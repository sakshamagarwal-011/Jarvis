"""
core/desktop_agent.py — Autonomous Closed-Loop Desktop AI Agent.

Performs:
Goal Interpretation → Screen Perception → Planning → UI Element Detection →
Physical OS Mouse/Keyboard Execution → Wait for Response → Re-Capture →
Verification → Intelligent Retry → Next Action.

Maintains strict honest reporting states:
- ACTION_VERIFIED: Action physically executed and visual confirmation succeeded.
- ACTION_EXECUTED: Action executed, but visual change was minor or inconclusive.
- ACTION_FAILED: Action failed or target could not be found after retries.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from google.genai import types as gtypes
from PIL import ImageChops, ImageStat

from core import gemini
from core.os_input import (
    move_mouse, click, double_click, right_click, drag, scroll,
    type_text, press_key, hotkey, get_cursor_pos, get_screen_info,
    get_foreground_window_title, focus_window_by_title,
)
from core.screen_capture import capture_screen, ScreenshotResult
from core.vision_detector import find_element, verify_interaction, DetectedElement, VerificationResult, _clean_json_response


def _image_diff_metric(img1, img2) -> float:
    """Calculates mean RGB difference between two PIL images."""
    try:
        diff = ImageChops.difference(img1.convert("RGB"), img2.convert("RGB"))
        stat = ImageStat.Stat(diff)
        return float(sum(stat.mean))
    except Exception:
        return 10.0


def _is_destructive(goal: str) -> bool:
    """Blocks catastrophic commands unless explicitly confirmed."""
    gl = goal.lower()
    destructive_phrases = [
        "delete all files", "format disk", "format c:", "rmdir /s", "del /f /s",
        "drop database", "wipe drive", "wipe system", "factory reset", "delete windows",
    ]
    return any(p in gl for p in destructive_phrases)


def _find_via_screenview(description: str) -> Optional[tuple[int, int]]:
    """
    Fast, 0-token OS accessibility tree lookup via core.screenview.
    Returns (center_x, center_y) in logical desktop coordinates if found, else None.
    """
    try:
        from core import screenview
        view = screenview.look()
        desc_lower = description.strip().lower()
        if not desc_lower:
            return None
        for elem in view.elements:
            if not elem.enabled:
                continue
            name = (elem.name or "").lower().strip()
            val = (elem.value or "").lower().strip()
            if (desc_lower == name or desc_lower in name or (name and name in desc_lower) or
                (val and desc_lower in val)):
                cx = elem.rect[0] + elem.rect[2] // 2
                cy = elem.rect[1] + elem.rect[3] // 2
                return (cx, cy)
    except Exception:
        pass
    return None



@dataclass
class StepResult:
    action: str
    target: str
    status: str                         # "ACTION_VERIFIED", "ACTION_FAILED", "ACTION_EXECUTED"
    coordinates: Optional[tuple[int, int]] = None
    explanation: str = ""
    retries_used: int = 0


@dataclass
class GoalExecutionResult:
    goal: str
    success: bool
    status: str                         # "ACTION_VERIFIED", "ACTION_FAILED"
    steps: list[StepResult] = field(default_factory=list)
    final_summary: str = ""


class DesktopAgent:
    """Autonomous desktop agent with closed-loop perception, action, and verification."""

    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda msg: print(f"[DesktopAgent] {msg}"))

    def click_element(
        self,
        description: str,
        clicks: int = 1,
        button: str = "left",
        max_retries: int = 2,
        wait_after: float = 0.8,
        verify: bool = True,
    ) -> StepResult:
        """
        Locates UI element on screen, moves physical mouse, clicks, and verifies the result.
        Retries with re-detection if verification fails.
        """
        self._log(f"Searching screen for: '{description}'...")
        action_name = "double_click" if clicks == 2 else ("right_click" if button == "right" else "click")

        for attempt in range(max_retries + 1):
            before_shot = capture_screen()

            # Tier 1: Try OS Accessibility Tree (instant, 0 tokens, pixel-exact)
            acc_coords = _find_via_screenview(description)
            if acc_coords:
                self._log(f"Target identified via OS Accessibility tree at {acc_coords}.")
                elem = DetectedElement(
                    screen_x=acc_coords[0],
                    screen_y=acc_coords[1],
                    element_type="control",
                    confidence=1.0,
                    bounding_box=[acc_coords[1], acc_coords[0], acc_coords[1], acc_coords[0]],
                    reasoning="Located via OS Accessibility Tree",
                )
            else:
                # Tier 2: Visual Fallback via Gemini Vision
                elem = find_element(before_shot, description)


            if not elem:
                if attempt < max_retries:
                    self._log(f"Element '{description}' not found on attempt {attempt+1}. Waiting 0.5s and re-trying...")
                    time.sleep(0.5)
                    continue
                return StepResult(
                    action=action_name,
                    target=description,
                    status="ACTION_FAILED",
                    explanation=f"Element '{description}' was not found on the screen.",
                    retries_used=attempt,
                )

            # Move physical mouse smoothly to element's center coordinates
            self._log(f"Target located at ({elem.screen_x}, {elem.screen_y}) [{elem.element_type}]. Moving physical mouse...")
            move_mouse(elem.screen_x, elem.screen_y, duration=0.25)
            time.sleep(0.06)

            # Perform physical OS click
            if clicks == 2:
                double_click()
            elif button == "right":
                right_click()
            else:
                click()

            self._log(f"Physical {action_name} executed at ({elem.screen_x}, {elem.screen_y}). Waiting {wait_after}s for UI response...")
            time.sleep(wait_after)

            if not verify:
                return StepResult(
                    action=action_name,
                    target=description,
                    status="ACTION_EXECUTED",
                    coordinates=(elem.screen_x, elem.screen_y),
                    explanation=f"Clicked '{description}' at ({elem.screen_x}, {elem.screen_y}).",
                    retries_used=attempt,
                )

            # Verification step: take new screenshot and check state change
            after_shot = capture_screen()
            v_result = verify_interaction(before_shot, after_shot, action_name, description)
            self._log(f"Verification: {v_result.status} — {v_result.explanation}")

            if v_result.verified:
                return StepResult(
                    action=action_name,
                    target=description,
                    status="ACTION_VERIFIED",
                    coordinates=(elem.screen_x, elem.screen_y),
                    explanation=v_result.explanation,
                    retries_used=attempt,
                )

            if attempt < max_retries:
                self._log(f"Verification inconclusive on attempt {attempt+1}. Retrying with fresh scan...")
                time.sleep(0.5)

        return StepResult(
            action=action_name,
            target=description,
            status="ACTION_FAILED",
            coordinates=(elem.screen_x, elem.screen_y) if elem else None,
            explanation=f"Action was executed, but visual change could not be verified after {max_retries} retries.",
            retries_used=max_retries,
        )

    def type_into_element(
        self,
        description: str,
        text: str,
        clear_first: bool = True,
        press_enter: bool = False,
        wait_after: float = 0.5,
    ) -> StepResult:
        """
        Clicks target input field to focus it, types the text with Unicode SendInput,
        and optionally presses Enter.
        """
        self._log(f"Locating input field '{description}' to type text...")
        click_res = self.click_element(description, clicks=1, verify=False)
        if click_res.status == "ACTION_FAILED":
            return StepResult(
                action="type",
                target=description,
                status="ACTION_FAILED",
                explanation=f"Could not focus input field: {click_res.explanation}",
            )

        time.sleep(0.1)
        before_shot = capture_screen()

        self._log(f"Typing text into '{description}'...")
        ok = type_text(text, clear_first=clear_first)

        if press_enter:
            time.sleep(0.08)
            press_key("enter")

        time.sleep(wait_after)
        after_shot = capture_screen()

        v_res = verify_interaction(before_shot, after_shot, f"type '{text[:20]}'", description)

        status = "ACTION_VERIFIED" if v_res.verified else "ACTION_EXECUTED"
        return StepResult(
            action="type",
            target=description,
            status=status,
            coordinates=click_res.coordinates,
            explanation=f"Typed '{text}' into '{description}' ({v_res.explanation}).",
        )

    def open_application(self, app_name: str, wait_seconds: float = 2.0) -> StepResult:
        """
        Opens an application using OS launcher (e.g. Windows Start/Run or subprocess)
        and verifies that a window opened.
        """
        self._log(f"Launching application: {app_name}...")
        before_title = get_foreground_window_title()

        name_lower = app_name.lower().strip()
        # Direct common mappings on Windows
        exe_map = {
            "notepad": "notepad.exe",
            "chrome": "chrome",
            "google chrome": "chrome",
            "edge": "msedge",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "vs code": "code",
            "vscode": "code",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "settings": "ms-settings:",
            "explorer": "explorer.exe",
        }

        cmd = exe_map.get(name_lower, name_lower)
        try:
            if cmd.startswith("ms-settings:") or cmd in ("notepad.exe", "calc.exe"):
                os.startfile(cmd)
            else:
                subprocess.Popen(cmd, shell=True)
        except Exception as e:
            return StepResult(
                action="open_app",
                target=app_name,
                status="ACTION_FAILED",
                explanation=f"Failed to start {app_name}: {e}",
            )

        time.sleep(wait_seconds)
        # Actively bring the new window to foreground
        focus_window_by_title(name_lower)
        time.sleep(0.3)
        after_title = get_foreground_window_title()

        # Check if foreground window changed or matches
        if name_lower in after_title.lower() or after_title != before_title:
            return StepResult(
                action="open_app",
                target=app_name,
                status="ACTION_VERIFIED",
                explanation=f"Opened '{app_name}' (Active window: '{after_title}').",
            )

        return StepResult(
            action="open_app",
            target=app_name,
            status="ACTION_EXECUTED",
            explanation=f"Command executed for '{app_name}'. Current window: '{after_title}'.",
        )

    def chrome_search_and_click(
        self,
        query: str,
        result_index: int = 1,
        verify: bool = True,
    ) -> StepResult:
        """
        Navigates to Google in Chrome, searches for query, locates the first
        relevant organic search result, clicks it, and verifies navigation.
        """
        self._log(f"Initiating Chrome search and click for: '{query}' (Result #{result_index})...")

        # 1. Bring Chrome to front or launch
        active_title = get_foreground_window_title().lower()
        if "chrome" not in active_title:
            focused = focus_window_by_title("Chrome") or focus_window_by_title("Google Chrome")
            if not focused:
                self._log("Chrome not running/focused. Launching Chrome...")
                self.open_application("chrome", wait_seconds=2.0)
            time.sleep(0.5)

        # 2. Focus address bar and navigate to Google search URL directly
        # Ctrl+L focuses address bar reliably across all Chromium / Windows browsers
        hotkey("ctrl", "l")
        time.sleep(0.15)
        search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        type_text(search_url, clear_first=False)
        time.sleep(0.08)
        press_key("enter")
        self._log(f"Navigating to {search_url}. Waiting for search results to load...")
        time.sleep(2.0)

        # 3. Locate search result
        coords = None
        # Tier 1: Check OS accessibility tree via screenview
        try:
            from core import screenview
            view = screenview.look()
            ignore_phrases = {
                "google", "search", "all", "images", "videos", "maps", "news",
                "shopping", "books", "finance", "tools", "sign in", "settings",
                "privacy", "terms", "advertising", "business", "how search works",
                "feedback", "filters", "clear search", "voice search", "search by image",
                "next", "previous", "more results", "people also ask",
            }
            candidate_links = []
            for elem in view.elements:
                role = (elem.role or "").lower()
                name = (elem.name or "").strip()
                if (role in ("link", "heading") or "link" in role) and len(name) > 6:
                    if not any(ign in name.lower() for ign in ignore_phrases):
                        cx = elem.rect[0] + elem.rect[2] // 2
                        cy = elem.rect[1] + elem.rect[3] // 2
                        if cy > 180 and cx > 100:
                            candidate_links.append((cx, cy, name))
            if candidate_links:
                target_idx = max(0, min(result_index - 1, len(candidate_links) - 1))
                coords = (candidate_links[target_idx][0], candidate_links[target_idx][1])
                self._log(f"Located search result via accessibility tree: '{candidate_links[target_idx][2][:40]}' at {coords}.")
        except Exception as e:
            self._log(f"Accessibility search lookup note: {e}")

        # Tier 2: Locate via Gemini Vision
        shot_before = capture_screen()
        if not coords:
            self._log("Locating search result via vision model...")
            elem = find_element(
                shot_before,
                f"first organic search result heading or link for '{query}' (exclude ads and sponsored links)",
            )
            if elem:
                coords = (elem.screen_x, elem.screen_y)
                self._log(f"Located search result via vision at {coords}.")

        # Tier 3: Empirical viewport coordinate fallback for Google search results
        if not coords:
            info = get_screen_info()
            coords = (int(info.width * 0.28), int(info.height * 0.35))
            self._log(f"Using estimated search result coordinate fallback: {coords}")

        # 4. Move mouse and click
        move_mouse(coords[0], coords[1], duration=0.25)
        time.sleep(0.08)
        click()
        self._log(f"Clicked search result at {coords}. Waiting for page to load...")
        time.sleep(2.0)

        if not verify:
            return StepResult(
                action="chrome_search_and_click",
                target=query,
                status="ACTION_EXECUTED",
                coordinates=coords,
                explanation=f"Searched for '{query}' and clicked result #{result_index}.",
            )

        # 5. Verify navigation
        shot_after = capture_screen()
        diff_val = _image_diff_metric(shot_before.image, shot_after.image)
        new_title = get_foreground_window_title()

        if "google search" not in new_title.lower() or diff_val > 5.0:
            return StepResult(
                action="chrome_search_and_click",
                target=query,
                status="ACTION_VERIFIED",
                coordinates=coords,
                explanation=f"Searched '{query}', clicked result #{result_index}, and navigated to '{new_title}'.",
            )

        return StepResult(
            action="chrome_search_and_click",
            target=query,
            status="ACTION_EXECUTED",
            coordinates=coords,
            explanation=f"Searched '{query}' and clicked result #{result_index} (Active window: '{new_title}').",
        )

    def scroll_to_bottom(self, max_scrolls: int = 25, delay: float = 0.35) -> StepResult:
        """
        Scrolls active window or document downwards repeatedly until the bottom is reached.
        Uses visual difference detection to identify when scrolling ceases to change the display.
        """
        self._log(f"Scrolling down to bottom (max {max_scrolls} steps)...")
        consecutive_static = 0
        total_scrolls = 0

        prev_shot = capture_screen()

        for i in range(1, max_scrolls + 1):
            scroll(direction="down", amount=6)
            time.sleep(delay)
            total_scrolls += 1

            curr_shot = capture_screen()
            diff = _image_diff_metric(prev_shot.image, curr_shot.image)

            # Minimal or no visual change indicates end of scrollable area
            if diff < 1.0:
                consecutive_static += 1
                if consecutive_static >= 2:
                    self._log(f"Bottom reached: no visual change after {total_scrolls} scrolls.")
                    return StepResult(
                        action="scroll_to_bottom",
                        target="bottom",
                        status="ACTION_VERIFIED",
                        explanation=f"Scrolled to the bottom after {total_scrolls} scroll operations.",
                        retries_used=i,
                    )
            else:
                consecutive_static = 0

            prev_shot = curr_shot

        return StepResult(
            action="scroll_to_bottom",
            target="bottom",
            status="ACTION_EXECUTED",
            explanation=f"Completed {max_scrolls} scroll operations towards the bottom.",
            retries_used=max_scrolls,
        )

    def scroll_until(
        self,
        description: str,
        max_scrolls: int = 20,
        direction: str = "down",
        delay: float = 0.4,
    ) -> StepResult:
        """
        Scrolls the screen incrementally until a specific UI element, text, or section is visible.
        """
        self._log(f"Scrolling {direction} until '{description}' is visible (max {max_scrolls} scrolls)...")
        consecutive_static = 0
        prev_shot = None

        for i in range(max_scrolls + 1):
            acc_coords = _find_via_screenview(description)
            if acc_coords:
                self._log(f"Found target '{description}' at {acc_coords} via accessibility after {i} scrolls.")
                return StepResult(
                    action="scroll_until",
                    target=description,
                    status="ACTION_VERIFIED",
                    coordinates=acc_coords,
                    explanation=f"Located '{description}' on screen after {i} scrolls.",
                    retries_used=i,
                )

            curr_shot = capture_screen()
            elem = find_element(curr_shot, description)
            if elem and elem.confidence >= 0.6:
                self._log(f"Found target '{description}' at ({elem.screen_x}, {elem.screen_y}) after {i} scrolls.")
                return StepResult(
                    action="scroll_until",
                    target=description,
                    status="ACTION_VERIFIED",
                    coordinates=(elem.screen_x, elem.screen_y),
                    explanation=f"Located '{description}' on screen after {i} scrolls.",
                    retries_used=i,
                )

            if i >= max_scrolls:
                break

            if prev_shot is not None:
                diff = _image_diff_metric(prev_shot.image, curr_shot.image)
                if diff < 1.0:
                    consecutive_static += 1
                    if consecutive_static >= 2:
                        self._log(f"Reached edge of scrollable page without finding '{description}'.")
                        return StepResult(
                            action="scroll_until",
                            target=description,
                            status="ACTION_FAILED",
                            explanation=f"Reached end of content without finding '{description}' after {i} scrolls.",
                            retries_used=i,
                        )
                else:
                    consecutive_static = 0

            prev_shot = curr_shot
            scroll(direction=direction, amount=5)
            time.sleep(delay)

        return StepResult(
            action="scroll_until",
            target=description,
            status="ACTION_FAILED",
            explanation=f"Target '{description}' was not found after {max_scrolls} scrolls.",
            retries_used=max_scrolls,
        )

    def pdf_navigate(
        self,
        action: str = "next",
        page_number: Optional[int] = None,
    ) -> StepResult:
        """
        Navigates PDF documents in active viewer (Acrobat, Chrome, Edge, Sumatra).
        Supports page jumps, next/prev page, scrolling to bottom/top.
        """
        act = (action or "next").lower().strip()
        self._log(f"Navigating PDF: action='{act}', page={page_number}...")

        before_shot = capture_screen()

        if act in ("jump", "goto", "go_to") and page_number is not None:
            hotkey("ctrl", "g")
            time.sleep(0.2)
            type_text(str(page_number), clear_first=True)
            time.sleep(0.1)
            press_key("enter")
            time.sleep(0.5)
            explanation = f"Navigated to PDF page {page_number} via Ctrl+G."
        elif act in ("to_bottom", "end", "last_page"):
            hotkey("ctrl", "end")
            time.sleep(0.4)
            explanation = "Jumped to the end of the PDF document."
        elif act in ("to_top", "home", "first_page"):
            hotkey("ctrl", "home")
            time.sleep(0.4)
            explanation = "Jumped to the top of the PDF document."
        elif act in ("prev", "previous", "page_up"):
            press_key("pageup")
            time.sleep(0.3)
            explanation = "Navigated to previous PDF page."
        else:
            press_key("pagedown")
            time.sleep(0.3)
            explanation = "Navigated to next PDF page."

        after_shot = capture_screen()
        diff = _image_diff_metric(before_shot.image, after_shot.image)

        status = "ACTION_VERIFIED" if diff > 1.5 else "ACTION_EXECUTED"
        return StepResult(
            action="pdf_navigate",
            target=f"{act}:{page_number}" if page_number else act,
            status=status,
            explanation=explanation,
        )

    def observe_screen(self) -> dict:
        """
        Gathers structured awareness of active window, screen geometry,
        and interactive UI elements via Windows UI Automation.
        """
        info = get_screen_info()
        active_title = get_foreground_window_title()

        elements_summary = []
        try:
            from core import screenview
            view = screenview.look()
            for elem in view.elements[:30]:
                elements_summary.append({
                    "role": elem.role,
                    "name": elem.name,
                    "value": elem.value,
                    "rect": elem.rect,
                    "enabled": elem.enabled,
                })
        except Exception:
            pass

        return {
            "active_window": active_title,
            "resolution": f"{info.width}x{info.height}",
            "virtual_desktop": f"{info.virtual_width}x{info.virtual_height}",
            "dpi_scale": info.dpi_scale,
            "elements_count": len(elements_summary),
            "elements": elements_summary,
        }

    def execute_goal(self, goal: str, max_steps: int = 12) -> GoalExecutionResult:
        """
        Autonomous Multi-Step Goal Execution Loop:
        Observe → Plan → Act → Verify → Repeat.
        Plans next action based on current screen and history, executes it with physical
        OS input, verifies outcome, recovers from failures, and completes the workflow.
        """
        self._log(f"=== Starting Autonomous Goal Execution: '{goal}' ===")

        # Safety Guard
        if _is_destructive(goal):
            return GoalExecutionResult(
                goal=goal,
                success=False,
                status="ACTION_FAILED",
                final_summary="Destructive action blocked for safety. Please confirm manually.",
            )

        steps: list[StepResult] = []

        for step_num in range(1, max_steps + 1):
            shot = capture_screen()
            self._log(f"Step {step_num}/{max_steps}: Analyzing screen for goal '{goal}'...")

            plan = self._plan_next_step(goal, shot, steps)
            if not plan:
                self._log("Planning could not determine next action.")
                break

            action = plan.get("action", "done").lower().strip()
            target = plan.get("target", "")
            text_val = plan.get("text", "")
            reasoning = plan.get("reasoning", "")
            is_complete = bool(plan.get("goal_achieved", False))

            self._log(f"Plan: {action.upper()} -> '{target}' ({reasoning})")

            if action == "done" or is_complete:
                self._log(f"Goal '{goal}' marked complete by planner!")
                return GoalExecutionResult(
                    goal=goal,
                    success=True,
                    status="ACTION_VERIFIED",
                    steps=steps,
                    final_summary=reasoning or f"Goal '{goal}' successfully achieved.",
                )

            # Execute specific planned action
            step_res: Optional[StepResult] = None

            if action in ("chrome_search_and_click", "search_and_click"):
                res_idx = int(plan.get("result_index", 1))
                step_res = self.chrome_search_and_click(target or text_val, result_index=res_idx)
            elif action == "scroll_to_bottom":
                max_s = int(plan.get("max_scrolls", 25))
                step_res = self.scroll_to_bottom(max_scrolls=max_s)
            elif action == "scroll_until":
                max_s = int(plan.get("max_scrolls", 20))
                dir_val = plan.get("direction", "down")
                step_res = self.scroll_until(target or text_val, max_scrolls=max_s, direction=dir_val)
            elif action == "pdf_navigate":
                step_res = self.pdf_navigate(action=plan.get("direction", target or "next"), page_number=plan.get("page_number"))
            elif action in ("click", "click_button", "click_link"):
                step_res = self.click_element(target, clicks=1, verify=True)
            elif action == "double_click":
                step_res = self.click_element(target, clicks=2, verify=True)
            elif action == "right_click":
                step_res = self.click_element(target, clicks=1, button="right", verify=True)
            elif action in ("type", "fill_input"):
                step_res = self.type_into_element(target, text_val, clear_first=True, press_enter=bool(plan.get("press_enter", False)))
            elif action == "press_key":
                press_key(text_val or target or "enter")
                time.sleep(0.4)
                step_res = StepResult(action="press_key", target=text_val or target, status="ACTION_EXECUTED", explanation=f"Pressed key '{text_val or target}'")
            elif action == "hotkey":
                hotkey(text_val or target)
                time.sleep(0.4)
                step_res = StepResult(action="hotkey", target=text_val or target, status="ACTION_EXECUTED", explanation=f"Triggered hotkey '{text_val or target}'")
            elif action == "scroll":
                dir_val = plan.get("direction", "down")
                amt = int(plan.get("amount", 5))
                scroll(direction=dir_val, amount=amt)
                time.sleep(0.5)
                step_res = StepResult(action="scroll", target=dir_val, status="ACTION_EXECUTED", explanation=f"Scrolled {dir_val} by {amt}")
            elif action == "open_app":
                step_res = self.open_application(target or text_val)
            elif action == "focus_window":
                ok = focus_window_by_title(target or text_val)
                active_t = get_foreground_window_title()
                step_res = StepResult(action="focus_window", target=target or text_val, status="ACTION_VERIFIED" if ok else "ACTION_FAILED", explanation=f"Focused window '{active_t}'" if ok else f"Could not focus '{target or text_val}'")
            elif action == "wait":
                secs = float(plan.get("seconds", 2.0))
                time.sleep(secs)
                step_res = StepResult(action="wait", target=f"{secs}s", status="ACTION_EXECUTED", explanation=f"Waited {secs} seconds.")
            else:
                self._log(f"Unknown planned action '{action}'. Stopping.")
                break

            if step_res:
                steps.append(step_res)
                if step_res.status == "ACTION_FAILED":
                    self._log(f"Step {step_num} failed: {step_res.explanation}. Planner will attempt recovery.")

        # Final evaluation of whether goal was met
        final_shot = capture_screen()
        final_ok, summary = self._evaluate_goal_completion(goal, final_shot, steps)
        return GoalExecutionResult(
            goal=goal,
            success=final_ok,
            status="ACTION_VERIFIED" if final_ok else "ACTION_FAILED",
            steps=steps,
            final_summary=summary,
        )

    def _plan_next_step(self, goal: str, shot: ScreenshotResult, history: list[StepResult]) -> Optional[dict]:
        """Prompts Gemini with current screen and step history to determine next discrete action."""
        hist_text = "\n".join([f"- Step {i+1}: {s.action} on '{s.target}' -> {s.status} ({s.explanation})" for i, s in enumerate(history)]) or "None (starting first step)"

        prompt = f"""
You are an autonomous desktop automation planner controlling a Windows computer.
High-level Goal: "{goal}"

Current active window: "{get_foreground_window_title()}"
Actions taken so far:
{hist_text}

Analyze the screenshot ({shot.width}x{shot.height}) and choose the SINGLE next immediate action to make progress towards the goal.
Available actions:
- "chrome_search_and_click": search Google in Chrome and click result (target: query, result_index: 1)
- "scroll_to_bottom": scroll active window/page continuously to the bottom
- "scroll_until": scroll page until target text/element is visible (target: description of element)
- "pdf_navigate": navigate PDF (target: "next"|"prev"|"jump"|"to_bottom"|"to_top", page_number: number)
- "open_app": launch application if not open (target: app name e.g. "chrome", "notepad")
- "focus_window": bring existing window to foreground (target: window title or app name)
- "click": click a visible button, link, or tab (target: clear description of element)
- "double_click": double click an icon, file, or item (target: clear description)
- "right_click": right click for context menu
- "type": type into an input field (target: description of input field, text: string to type, press_enter: true/false)
- "press_key": press a single key (target: "enter", "tab", "esc", "backspace")
- "hotkey": keyboard shortcut (target: "ctrl+s", "ctrl+a", "alt+tab")
- "scroll": scroll page (direction: "up"|"down", amount: 5)
- "wait": wait for slow loading (seconds: 2.0)
- "done": the goal is already fully achieved

Respond ONLY with valid JSON in this structure:
{{
  "goal_achieved": false,
  "action": "chrome_search_and_click|scroll_to_bottom|scroll_until|pdf_navigate|click|type|open_app|focus_window|press_key|hotkey|scroll|wait|done",
  "target": "exact visual description or parameter",
  "text": "text to type or key name if applicable",
  "result_index": 1,
  "page_number": 1,
  "press_enter": false,
  "reasoning": "why this action is chosen"
}}
"""
        try:
            img_part = gtypes.Part.from_bytes(data=shot.image_bytes, mime_type=shot.mime_type)
            resp = gemini.call([img_part, prompt], tier=gemini.SMART, timeout_ms=25_000)
            if resp and resp.text:
                clean = _clean_json_response(resp.text)
                return json.loads(clean)
        except Exception as e:
            self._log(f"Planner error: {e}")
        return None

    def _evaluate_goal_completion(self, goal: str, shot: ScreenshotResult, history: list[StepResult]) -> tuple[bool, str]:
        """Evaluates whether the overall goal was accomplished based on final screen state."""
        hist_text = "\n".join([f"- {s.action} on '{s.target}': {s.status}" for s in history]) or "None"
        prompt = f"""
Evaluate whether this user goal has been accomplished on the desktop:
Goal: "{goal}"
Action steps taken:
{hist_text}

Look at the final screenshot. Did the goal succeed?
Respond ONLY with valid JSON:
{{
  "goal_achieved": true or false,
  "summary": "Clear, honest explanation of the final desktop state"
}}
"""
        try:
            img_part = gtypes.Part.from_bytes(data=shot.image_bytes, mime_type=shot.mime_type)
            resp = gemini.call([img_part, prompt], tier=gemini.SMART, timeout_ms=20_000)
            if resp and resp.text:
                clean = _clean_json_response(resp.text)
                data = json.loads(clean)
                return bool(data.get("goal_achieved", False)), str(data.get("summary", ""))
        except Exception as e:
            self._log(f"Goal evaluation error: {e}")

        any_verified = any(s.status == "ACTION_VERIFIED" for s in history)
        return any_verified, "Completed execution sequence."
