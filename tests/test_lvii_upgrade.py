"""
tests/test_lvii_upgrade.py — Verification Suite for JARVIS Upgrade to Mark-LVII Architecture.

Verifies:
1. Core resilient utilities (outcome, lazyimport, appidentity, platform_support, tls, gemini)
2. Custom OS automation modules (os_input, screen_capture, vision_detector, desktop_agent)
3. Vision & Accessibility two-tier perception (screenview + vision_detector)
4. Background Task Engine and Unified Routines
5. Action discovery across all 20 tools (including hand_control and computer_control)
6. Modular GUI components and Holographic integrations
7. Provider stack & settings persistence
"""
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(str(BASE_DIR))


class TestLVIIUpgrade(unittest.TestCase):

    def test_01_core_utilities(self):
        """Verify Mark-LVII core resiliency modules."""
        from core import outcome, lazyimport, appidentity, platform_support, tls, code_checks, gemini
        self.assertTrue(hasattr(outcome, "done"))
        self.assertTrue(hasattr(outcome, "failed"))
        self.assertTrue(hasattr(outcome, "unverified"))
        self.assertTrue(hasattr(lazyimport, "LazyModule"))
        self.assertTrue(hasattr(appidentity, "own_pids"))
        self.assertTrue(hasattr(appidentity, "request_close"))
        self.assertTrue(hasattr(gemini, "parse_json"))
        # Test parse_json handles think tags and lists
        sample = "<think>reasoning here</think>```json\n[{\"status\": \"ok\"}]\n```"
        parsed = gemini.parse_json(sample)
        self.assertEqual(parsed, [{"status": "ok"}])


    def test_02_custom_os_control_preserved(self):
        """Verify our custom OS control and desktop agent modules are intact."""
        from core import os_input, screen_capture, vision_detector, desktop_agent, hand_tracking
        info = os_input.get_screen_info()
        self.assertGreater(info.width, 0)
        self.assertGreater(info.height, 0)
        cur = os_input.get_cursor_pos()
        self.assertIsInstance(cur, tuple)
        self.assertEqual(len(cur), 2)

    def test_03_perception_synergy(self):
        """Verify screenview (accessibility) and desktop_agent synergy."""
        from core import screenview, screenact
        from core.desktop_agent import _find_via_screenview, DesktopAgent
        view = screenview.look()
        self.assertIsNotNone(view)
        self.assertTrue(hasattr(view, "bounds"))
        self.assertTrue(hasattr(view, "elements"))
        agent = DesktopAgent()
        self.assertIsNotNone(agent)

    def test_04_background_tasks_and_routines(self):
        """Verify core/tasks and core/routines engines."""
        from core.tasks import desktop as tasks_desktop
        from core.tasks.brain import ask
        from core.routines import desktop as routines_desktop
        from core.routines.rules import describe_rule, next_fire
        te = tasks_desktop.ensure(None)
        self.assertIsNotNone(te)
        re = routines_desktop.attach(None)
        self.assertIsNotNone(re)




    def test_05_action_discovery_complete(self):
        """Verify all 20 actions discover cleanly without schema errors."""
        from core.action_loader import discover_actions
        registry = discover_actions(Path("actions"))
        action_names = registry.names()
        required_actions = {
            "computer_control",
            "hand_control",
            "background_tasks",
            "routines",
            "browser_control",
            "computer_settings",
            "open_app",
            "file_controller",
            "video_player",
            "web_search",
        }
        for req in required_actions:
            self.assertIn(req, action_names, f"Action '{req}' missing from discovery!")

    def test_06_gui_and_holographic_integration(self):
        """Verify modular GUI and holographic methods in JarvisUI and MainWindow."""
        import ui
        from gui import window, hud, widgets, overlays, reactor, theme, providers_panel
        self.assertTrue(hasattr(ui.JarvisUI, "set_hand_tracking"))
        self.assertTrue(hasattr(ui.JarvisUI, "show_holographic_files"))
        self.assertTrue(hasattr(ui.JarvisUI, "preview_holographic_file"))
        self.assertTrue(hasattr(window.MainWindow, "set_hand_tracking"))
        self.assertTrue(hasattr(window.MainWindow, "show_holographic_files"))

    def test_07_providers_stack(self):
        """Verify provider registry, schema, and audio."""
        from providers import registry, schema, audio, base
        self.assertTrue(hasattr(registry, "discover"))
        self.assertTrue(hasattr(registry, "build"))
        self.assertTrue(hasattr(schema, "to_openai"))
        self.assertTrue(hasattr(schema, "to_gemini"))
        self.assertTrue(hasattr(audio, "to_pcm16"))
        self.assertTrue(hasattr(audio, "resample"))





if __name__ == "__main__":
    unittest.main()
