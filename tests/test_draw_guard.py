import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from lottery_planner import RoomLock
from planned_runtime import PlannedRuntime

class DrawGuardTests(unittest.TestCase):
    def test_before_zero_cannot_release_or_leave(self):
        with tempfile.TemporaryDirectory() as folder:
            r = PlannedRuntime.__new__(PlannedRuntime)
            r.lock = RoomLock(Path(folder) / 'lock.json')
            r.lock.acquire('room', 100)
            r.live = Mock()
            r.screen = Mock()
            r.room_name = Mock(return_value='room')
            r.close_panel = Mock()
            with patch('planned_runtime.time.time', return_value=99), patch('planned_runtime.time.sleep', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                r.watch()
            self.assertIsNotNone(r.lock.state)
            self.assertTrue(r.lock.path.exists())
            r.close_panel.assert_not_called()
