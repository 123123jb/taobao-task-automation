import unittest
from unittest.mock import Mock
from planned_runtime import PlannedRuntime, BagReadTimeout
from Underlying_Operations import ManualActionRequired

class PanelRecoveryTests(unittest.TestCase):
    def test_unjoined_unreadable_bag_is_closed_and_skipped(self):
        r=PlannedRuntime.__new__(PlannedRuntime)
        r.lock=Mock(); r.wait_for_bag=Mock(return_value=(Mock(),70))
        r.room_name=Mock(return_value='followed'); r.open_bag=Mock(side_effect=BagReadTimeout('timeout'))
        r.close_panel=Mock()
        self.assertIsNone(r.inspect())
        r.lock.require_unlocked.assert_called_once()
        r.close_panel.assert_called_once()

    def test_verification_still_pauses_without_closing(self):
        r=PlannedRuntime.__new__(PlannedRuntime)
        r.wait_for_bag=Mock(return_value=(Mock(),70)); r.room_name=Mock(return_value='followed')
        r.open_bag=Mock(side_effect=ManualActionRequired('verification')); r.close_panel=Mock()
        with self.assertRaises(ManualActionRequired): r.inspect()
        r.close_panel.assert_not_called()
