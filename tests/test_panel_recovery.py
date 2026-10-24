import unittest
from unittest.mock import Mock, patch
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

    def test_completed_task_sheet_is_recognized_without_original_task_heading(self):
        from PIL import Image
        r=PlannedRuntime.__new__(PlannedRuntime)
        r.ocr=Mock(return_value='超级福袋00:00后开奖任务已完成等待开奖请勿离开直播间')
        text, seconds=r.details(Image.new('RGB',(1080,2400)))
        self.assertEqual(seconds,0)
        self.assertTrue(r.joined(text))

    def test_expired_paused_draw_resumes_watch_from_live_sheet(self):
        r=PlannedRuntime.__new__(PlannedRuntime)
        r.lock=Mock(state={'room':'a','deadline':100})
        r.followed_rooms=Mock(side_effect=RuntimeError('live sheet'))
        r.watch=Mock(); r.return_to_followed=Mock()
        with patch('planned_runtime.time.time',return_value=200), patch('planned_runtime.time.sleep',side_effect=[None,KeyboardInterrupt]):
            r.wait_for_resume()
        r.watch.assert_called_once()
        r.return_to_followed.assert_called_once()
