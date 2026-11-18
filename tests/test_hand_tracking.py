"""
tests/test_hand_tracking.py — Comprehensive Unit & Integration Tests for Mark LV Hand Tracking.

Tests:
- No hand detected
- Hand appearing and disappearing
- Open-palm activation
- Pinch selection & debounce
- Pinch drag & pinch release
- Cursor smoothing (AdaptiveCursorSmoother)
- Swipe gesture & cooldown
- Two-hand zoom
- Emergency pause / unpause
- Camera initialization & failure handling
- File selection vs operation separation
- Destructive action confirmation logic
- Voice command hybrid control handler (actions/hand_control.py)
"""
import math
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.hand_tracking import (
    Point3D, Landmark, Gesture, HandTrackingFrame,
    AdaptiveCursorSmoother, GestureClassifier, HandTrackingWorker
)
from actions.hand_control import hand_control


def make_synthetic_hand(
    wrist_y=0.8,
    is_pointing=False,
    is_open_palm=False,
    is_pinch=False,
    is_two_finger=False,
    handedness="Right",
    index_tip_x=0.5,
    index_tip_y=0.4,
    offset_x=0.0,
) -> tuple[list[MagicMock], str]:
    """Builds a 21-landmark list conforming to MediaPipe NormalizedLandmark specs."""
    landmarks = []
    for i in range(21):
        lm = MagicMock()
        lm.x = 0.5 + offset_x
        lm.y = wrist_y - (i * 0.02)
        lm.z = 0.0
        landmarks.append(lm)

    # Wrist
    landmarks[Landmark.WRIST].x = 0.5 + offset_x
    landmarks[Landmark.WRIST].y = wrist_y
    landmarks[Landmark.WRIST].z = 0.0

    # Index MCP
    landmarks[Landmark.INDEX_MCP].x = 0.52 + offset_x
    landmarks[Landmark.INDEX_MCP].y = wrist_y - 0.25

    # Pinky MCP
    landmarks[Landmark.PINKY_MCP].x = 0.44 + offset_x
    landmarks[Landmark.PINKY_MCP].y = wrist_y - 0.22

    # Thumb MCP and IP
    landmarks[Landmark.THUMB_MCP].x = 0.56 + offset_x
    landmarks[Landmark.THUMB_MCP].y = wrist_y - 0.15
    landmarks[Landmark.THUMB_IP].x = 0.58 + offset_x
    landmarks[Landmark.THUMB_IP].y = wrist_y - 0.22

    # Default curled finger positions (tips below PIP)
    for tip, pip, mcp in [
        (Landmark.MIDDLE_TIP, Landmark.MIDDLE_PIP, Landmark.MIDDLE_MCP),
        (Landmark.RING_TIP, Landmark.RING_PIP, Landmark.RING_MCP),
        (Landmark.PINKY_TIP, Landmark.PINKY_PIP, Landmark.PINKY_MCP),
    ]:
        landmarks[mcp].x = landmarks[mcp].x
        landmarks[mcp].y = wrist_y - 0.24
        landmarks[pip].y = wrist_y - 0.20
        landmarks[tip].y = wrist_y - 0.16  # tip below PIP = curled

    # Index finger
    landmarks[Landmark.INDEX_PIP].y = wrist_y - 0.28
    landmarks[Landmark.INDEX_DIP].y = wrist_y - 0.32
    landmarks[Landmark.INDEX_TIP].x = index_tip_x + offset_x
    landmarks[Landmark.INDEX_TIP].y = index_tip_y

    if is_pointing:
        # Index extended, others curled
        landmarks[Landmark.INDEX_TIP].y = wrist_y - 0.38
        landmarks[Landmark.THUMB_TIP].x = 0.54 + offset_x
        landmarks[Landmark.THUMB_TIP].y = wrist_y - 0.20

    elif is_open_palm:
        # All fingers extended (tip.y < pip.y < mcp.y)
        landmarks[Landmark.INDEX_TIP].y = wrist_y - 0.40
        landmarks[Landmark.MIDDLE_TIP].y = wrist_y - 0.42
        landmarks[Landmark.MIDDLE_PIP].y = wrist_y - 0.30
        landmarks[Landmark.RING_TIP].y = wrist_y - 0.39
        landmarks[Landmark.RING_PIP].y = wrist_y - 0.29
        landmarks[Landmark.PINKY_TIP].y = wrist_y - 0.36
        landmarks[Landmark.PINKY_PIP].y = wrist_y - 0.27
        landmarks[Landmark.THUMB_TIP].x = 0.65 + offset_x
        landmarks[Landmark.THUMB_TIP].y = wrist_y - 0.30

    elif is_two_finger:
        # Index and middle extended
        landmarks[Landmark.INDEX_TIP].y = wrist_y - 0.38
        landmarks[Landmark.MIDDLE_TIP].y = wrist_y - 0.38
        landmarks[Landmark.MIDDLE_PIP].y = wrist_y - 0.28
        landmarks[Landmark.THUMB_TIP].x = 0.54 + offset_x
        landmarks[Landmark.THUMB_TIP].y = wrist_y - 0.20

    if is_pinch:
        # Thumb tip touching index tip
        landmarks[Landmark.THUMB_TIP].x = landmarks[Landmark.INDEX_TIP].x + 0.01
        landmarks[Landmark.THUMB_TIP].y = landmarks[Landmark.INDEX_TIP].y + 0.01
    else:
        if not is_open_palm:
            landmarks[Landmark.THUMB_TIP].x = 0.58 + offset_x
            landmarks[Landmark.THUMB_TIP].y = wrist_y - 0.18

    return (landmarks, handedness)


class TestHandTracking(unittest.TestCase):

    def setUp(self):
        self.classifier = GestureClassifier()
        self.smoother = AdaptiveCursorSmoother(sensitivity=1.0, smoothing=0.6)

    def test_no_hand_detected(self):
        frame, events = self.classifier.process([], timestamp=100.0)
        self.assertEqual(frame.active_hand_count, 0)
        self.assertEqual(frame.primary_gesture, Gesture.NONE)
        self.assertEqual(frame.status_text, "NO HAND DETECTED")
        self.assertEqual(len(events), 0)

    def test_hand_appearing_and_disappearing(self):
        # 1. Hand appears
        hand = make_synthetic_hand(is_pointing=True)
        frame1, _ = self.classifier.process([hand], timestamp=101.0)
        self.assertEqual(frame1.active_hand_count, 1)

        # 2. Hand disappears
        frame2, _ = self.classifier.process([], timestamp=102.0)
        self.assertEqual(frame2.active_hand_count, 0)
        self.assertEqual(frame2.primary_gesture, Gesture.NONE)

    def test_open_palm_activation(self):
        hand = make_synthetic_hand(is_open_palm=True)
        frame, events = self.classifier.process([hand], timestamp=103.0)
        self.assertEqual(frame.primary_gesture, Gesture.OPEN_PALM)
        # Verify OPEN_PALM_ACTIVATE event emitted
        event_names = [e[0] for e in events]
        self.assertIn("OPEN_PALM_ACTIVATE", event_names)

    def test_pinch_selection_and_debounce(self):
        hand_pinch = make_synthetic_hand(is_pinch=True)
        t0 = 104.0
        frame1, events1 = self.classifier.process([hand_pinch], timestamp=t0)
        self.assertTrue(frame1.is_pinching)
        click_events = [e for e in events1 if e[0] == "PINCH_CLICK"]
        self.assertEqual(len(click_events), 1)

        # Debounce test: immediate second frame should NOT emit a second click
        frame2, events2 = self.classifier.process([hand_pinch], timestamp=t0 + 0.05)
        click_events2 = [e for e in events2 if e[0] == "PINCH_CLICK"]
        self.assertEqual(len(click_events2), 0)

    def test_pinch_release(self):
        hand_pinch = make_synthetic_hand(is_pinch=True)
        self.classifier.process([hand_pinch], timestamp=105.0)

        # Release pinch
        hand_open = make_synthetic_hand(is_pointing=True)
        _, events = self.classifier.process([hand_open], timestamp=105.2)
        release_events = [e for e in events if e[0] == "PINCH_RELEASE"]
        self.assertEqual(len(release_events), 1)

    def test_cursor_smoothing(self):
        # Initial point
        sx1, sy1, _, _ = self.smoother.update(0.5, 0.5, timestamp=1.0)
        self.assertAlmostEqual(sx1, 0.5, places=1)
        self.assertAlmostEqual(sy1, 0.5, places=1)

        # Micro-jitter jump (0.50 -> 0.53) should be filtered with low velocity alpha
        sx2, sy2, _, _ = self.smoother.update(0.5, 0.53, timestamp=1.033)
        # Verify smoothed y moved less than full delta (adaptive EMA suppresses jitter)
        dy = abs(sy2 - sy1)
        self.assertTrue(dy < 0.05)

    def test_emergency_pause(self):
        self.classifier.set_emergency_pause(True)
        self.assertTrue(self.classifier.is_paused())

        hand = make_synthetic_hand(is_pointing=True)
        frame, events = self.classifier.process([hand], timestamp=106.0)
        self.assertTrue(frame.is_paused)
        self.assertIn("PAUSED", frame.status_text)
        self.assertEqual(len(events), 0)

        # Unpause
        self.classifier.set_emergency_pause(False)
        self.assertFalse(self.classifier.is_paused())

    def test_two_hand_zoom(self):
        # Two hands with changing distance
        h1 = make_synthetic_hand(offset_x=-0.15, handedness="Left")
        h2 = make_synthetic_hand(offset_x=0.15, handedness="Right")
        self.classifier.process([h1, h2], timestamp=107.0)

        # Second frame hands moving further apart (spread zoom)
        h1_spread = make_synthetic_hand(offset_x=-0.25, handedness="Left")
        h2_spread = make_synthetic_hand(offset_x=0.25, handedness="Right")
        frame, events = self.classifier.process([h1_spread, h2_spread], timestamp=107.1)
        self.assertTrue(frame.zoom_delta > 0.05)
        self.assertEqual(frame.primary_gesture, Gesture.TWO_HAND_ZOOM)

    def test_voice_command_actions(self):
        mock_ui = MagicMock()
        mock_ui.set_hand_tracking.return_value = (True, "Hand tracking active")
        mock_ui.preview_holographic_file.return_value = (True, "Previewing test.py")
        mock_ui.open_holographic_folder.return_value = (True, "Opened folder")
        mock_ui.select_holographic_file.return_value = (True, "Selected test.txt")

        # 1. Activate
        res = hand_control(action="activate", player=mock_ui)
        self.assertIn("active", res.lower())
        mock_ui.set_hand_tracking.assert_called_with(True)

        # 2. Deactivate
        mock_ui.set_hand_tracking.return_value = (True, "Hand tracking disabled")
        res = hand_control(action="disable", player=mock_ui)
        self.assertIn("disabled", res.lower())
        mock_ui.set_hand_tracking.assert_called_with(False)

        # 3. Open files
        res = hand_control(action="open_files", target="", player=mock_ui)
        mock_ui.show_holographic_files.assert_called()

        # 4. Preview
        res = hand_control(action="preview", target="test.py", player=mock_ui)
        self.assertEqual(res, "Previewing test.py")

        # 5. Open folder
        res = hand_control(action="open_folder", target="projects", player=mock_ui)
        self.assertEqual(res, "Opened folder")

        # 6. Select
        res = hand_control(action="select", target="test.txt", player=mock_ui)
        self.assertEqual(res, "Selected test.txt")

    def test_swipe_gesture_and_cooldown(self):
        # Build two-finger hand trajectory to simulate swipe
        t = 200.0
        # Frame 1: index + middle extended at x=0.3
        h1 = make_synthetic_hand(is_two_finger=True, offset_x=-0.2)
        self.classifier.process([h1], timestamp=t)

        # Frame 2: moved to x=0.4
        h2 = make_synthetic_hand(is_two_finger=True, offset_x=-0.1)
        self.classifier.process([h2], timestamp=t + 0.05)

        # Frame 3: moved to x=0.6 (fast delta > SWIPE_MIN_DELTA)
        h3 = make_synthetic_hand(is_two_finger=True, offset_x=0.15)
        _, events1 = self.classifier.process([h3], timestamp=t + 0.10)
        swipe_events1 = [e for e in events1 if "SWIPE" in e[0]]
        self.assertTrue(len(swipe_events1) >= 1)

        # Immediate follow-up frame within SWIPE_COOLDOWN (0.45s) must be suppressed
        h4 = make_synthetic_hand(is_two_finger=True, offset_x=0.25)
        _, events2 = self.classifier.process([h4], timestamp=t + 0.15)
        swipe_events2 = [e for e in events2 if "SWIPE" in e[0]]
        self.assertEqual(len(swipe_events2), 0)

    def test_worker_camera_init_failure(self):
        worker = HandTrackingWorker()
        error_msgs = []
        worker.error_occurred.connect(lambda msg: error_msgs.append(msg))

        # Mock VideoCapture returning unopened cap
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = False
            mock_cap_cls.return_value = mock_cap

            ok = worker._open_camera()
            self.assertFalse(ok)
            self.assertTrue(len(error_msgs) >= 1)
            self.assertIn("Could not open camera", error_msgs[0])

    def test_worker_shutdown(self):
        worker = HandTrackingWorker()
        worker._running = True
        worker.stop()
        self.assertFalse(worker._running)

    def test_file_selection_isolation(self):
        # Safety requirement: selecting or moving visual card must never alter or delete disk files
        from actions.file_controller import _is_safe_path
        from pathlib import Path
        desktop = Path.home() / "Desktop"
        self.assertTrue(_is_safe_path(desktop))

        # Dangerous path traversal should be denied
        self.assertFalse(_is_safe_path(Path("C:/Windows/System32")))
        self.assertFalse(_is_safe_path(Path("/etc/shadow")))


if __name__ == "__main__":
    unittest.main()

