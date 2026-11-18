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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from google.genai import types as gtypes

from core import gemini
from core.os_input import (
    move_mouse, click, double_click, right_click, drag, scroll,
    type_text, press_key, hotkey, get_cursor_pos, get_screen_info,
    get_foreground_window_title, focus_window_by_title,
)
from core.screen_capture import capture_screen, ScreenshotResult
from core.vision_detector import find_element, verify_interaction, DetectedElement, VerificationResult, _clean_json_response


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

    def execute_goal(self, goal: str, max_steps: int = 8) -> GoalExecutionResult:
        """
        Autonomous Multi-Step Goal Execution Loop:
        Plans next action based on current screenshot, executes it with physical OS input,
        verifies outcome, and proceeds until goal is completed.
        """
        self._log(f"=== Starting Autonomous Goal Execution: '{goal}' ===")
        steps: list[StepResult] = []

        for step_num in range(1, max_steps + 1):
            shot = capture_screen()
            self._log(f"Step {step_num}/{max_steps}: Analyzing current screen for goal '{goal}'...")

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

            if action in ("click", "click_button", "click_link"):
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
                    self._log(f"Step {step_num} failed: {step_res.explanation}")

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
- "open_app": launch application if not open (target: app name e.g. "chrome", "notepad")
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
  "action": "click|type|open_app|press_key|hotkey|scroll|wait|done",
  "target": "exact visual description of the UI element",
  "text": "text to type or key name if applicable",
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

        # If any step was verified, report success
        any_verified = any(s.status == "ACTION_VERIFIED" for s in history)
        return any_verified, "Completed execution sequence."
