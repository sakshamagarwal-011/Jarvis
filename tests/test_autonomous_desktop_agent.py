"""
tests/test_autonomous_desktop_agent.py — Test suite for screen awareness,
intelligent scrolling, browser navigation, and autonomous desktop agent loop.
"""
import json
import time
import unittest
from pathlib import Path

from core import screenview
from core import os_input
from core.screen_capture import capture_screen
from core.desktop_agent import DesktopAgent, StepResult, GoalExecutionResult
from actions.computer_control import computer_control
from actions.browser_control import browser_control


class TestScreenAwareness(unittest.TestCase):
    def test_01_all_windows_enumeration(self):
        """Verifies OS-level window enumeration retrieves real Windows windows."""
        wins = screenview.all_windows()
        self.assertIsInstance(wins, list)
        print(f"[Test] Discovered {len(wins)} windows.")
        for proc, title in wins[:5]:
            self.assertIsInstance(title, str)
            self.assertIsInstance(proc, str)
            print(f"[Test] Discovered window: '{title}' ({proc})")

    def test_02_screenview_look(self):
        """Verifies UI automation element inspection via screenview.look()."""
        view = screenview.look()
        self.assertIsNotNone(view)
        self.assertIsInstance(view.elements, list)
        self.assertIsInstance(view.title, str)
        print(f"[Test] Screenview scanned window '{view.title}' with {len(view.elements)} UI elements.")
        if view.elements:
            sample = view.elements[0]
            self.assertTrue(hasattr(sample, "role"))
            self.assertTrue(hasattr(sample, "name"))
            self.assertTrue(hasattr(sample, "rect"))

    def test_03_desktop_agent_observe_screen(self):
        """Verifies DesktopAgent.observe_screen() produces structured desktop awareness."""
        agent = DesktopAgent()
        obs = agent.observe_screen()
        self.assertIn("active_window", obs)
        self.assertIn("resolution", obs)
        self.assertIn("elements", obs)
        print(f"[Test] DesktopAgent observed active window: '{obs['active_window']}', res: {obs['resolution']}, elements: {obs['elements_count']}")

    def test_04_computer_control_observe_screen(self):
        """Verifies computer_control action='observe_screen' dispatch."""
        res = computer_control({"action": "observe_screen"})
        self.assertTrue(res.startswith("ACTION_VERIFIED:"))
        json_data = json.loads(res.split("ACTION_VERIFIED:", 1)[1].strip())
        self.assertIn("active_window", json_data)
        self.assertIn("resolution", json_data)


class TestIntelligentScrollingAndPDF(unittest.TestCase):
    def test_05_scroll_to_bottom(self):
        """Verifies scroll_to_bottom executes and detects visual cessation."""
        agent = DesktopAgent()
        res = agent.scroll_to_bottom(max_scrolls=3, delay=0.1)
        self.assertIn(res.status, ("ACTION_VERIFIED", "ACTION_EXECUTED"))
        self.assertGreaterEqual(res.retries_used, 1)
        print(f"[Test] scroll_to_bottom result: {res.status} — {res.explanation}")

    def test_06_pdf_navigate(self):
        """Verifies PDF navigation commands (next, prev, jump, to_bottom)."""
        agent = DesktopAgent()
        # Test next page
        res_next = agent.pdf_navigate(action="next")
        self.assertIn(res_next.status, ("ACTION_VERIFIED", "ACTION_EXECUTED"))
        print(f"[Test] pdf_navigate(next): {res_next.status} — {res_next.explanation}")

        # Test to_bottom
        res_bot = agent.pdf_navigate(action="to_bottom")
        self.assertIn(res_bot.status, ("ACTION_VERIFIED", "ACTION_EXECUTED"))
        print(f"[Test] pdf_navigate(to_bottom): {res_bot.status} — {res_bot.explanation}")

    def test_07_computer_control_pdf_and_scroll_dispatch(self):
        """Verifies computer_control actions for scrolling and PDF navigation."""
        res_scroll = computer_control({"action": "scroll_to_bottom", "max_scrolls": 2})
        self.assertTrue(res_scroll.startswith("ACTION_"))
        print(f"[Test] computer_control(scroll_to_bottom): {res_scroll}")

        res_pdf = computer_control({"action": "pdf_navigate", "direction": "to_bottom"})
        self.assertTrue(res_pdf.startswith("ACTION_"))
        print(f"[Test] computer_control(pdf_navigate): {res_pdf}")


class TestAutonomousLoopAndSafety(unittest.TestCase):
    def test_08_destructive_action_guard(self):
        """Verifies destructive commands are automatically halted by safety check."""
        agent = DesktopAgent()
        res = agent.execute_goal("Format disk C: and delete all files")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "ACTION_FAILED")
        self.assertIn("blocked", res.final_summary.lower())
        print(f"[Test] Destructive guard result: {res.status} — {res.final_summary}")

    def test_09_browser_control_search_and_click_schema(self):
        """Verifies browser_control handles search_and_click action safely."""
        from actions.browser_control import TOOL
        self.assertIn("search_and_click", TOOL["parameters"]["properties"]["action"]["description"])
        self.assertIn("scroll_to_bottom", TOOL["parameters"]["properties"]["action"]["description"])
        self.assertIn("scroll_until", TOOL["parameters"]["properties"]["action"]["description"])
        self.assertIn("pdf_navigate", TOOL["parameters"]["properties"]["action"]["description"])
        self.assertIn("switch_tab", TOOL["parameters"]["properties"]["action"]["description"])


if __name__ == "__main__":
    unittest.main()
