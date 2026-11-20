"""Regression checks for cautious desktop outcome reporting.

These tests mock OS input and screenshots; they do not require an active PDF
viewer or perform real desktop clicks.
"""
import unittest
from unittest.mock import patch, MagicMock

from core.desktop_agent import DesktopAgent


class TestDesktopSafetyRegressions(unittest.TestCase):
    def test_pdf_rejects_invalid_page_number_before_input(self):
        agent = DesktopAgent()
        with patch("core.desktop_agent.capture_screen") as capture, \
             patch("core.desktop_agent.hotkey") as key:
            result = agent.pdf_navigate(action="jump", page_number=0)
        self.assertEqual(result.status, "ACTION_FAILED")
        capture.assert_called_once()
        key.assert_not_called()

    def test_pdf_rejects_unknown_action_without_keypress(self):
        agent = DesktopAgent()
        with patch("core.desktop_agent.capture_screen") as capture, \
             patch("core.desktop_agent.press_key") as key:
            result = agent.pdf_navigate(action="not_a_pdf_action")
        self.assertEqual(result.status, "ACTION_FAILED")
        capture.assert_called_once()
        key.assert_not_called()

    def test_pdf_visual_change_is_not_verified_page_position(self):
        agent = DesktopAgent()
        shot = MagicMock()
        shot.image = MagicMock()
        with patch("core.desktop_agent.capture_screen", return_value=shot), \
             patch("core.desktop_agent.press_key"), \
             patch("core.desktop_agent.time.sleep"), \
             patch("core.desktop_agent._image_diff_metric", return_value=25.0):
            result = agent.pdf_navigate(action="next")
        self.assertEqual(result.status, "ACTION_EXECUTED")
        self.assertIn("not verified", result.explanation)

    def test_completion_verifier_failure_is_not_success(self):
        agent = DesktopAgent()
        shot = MagicMock()
        with patch("core.desktop_agent.gemini.call", side_effect=RuntimeError("offline")):
            ok, summary = agent._evaluate_goal_completion("open a page", shot, [])
        self.assertFalse(ok)
        self.assertIn("Unable to verify", summary)


if __name__ == "__main__":
    unittest.main()
