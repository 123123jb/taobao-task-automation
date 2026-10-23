import unittest
from unittest.mock import Mock, patch
from PIL import Image

from lottery_planner import Candidate
from planned_runtime import PlannedRuntime


class SelectionTests(unittest.TestCase):
    def runtime(self, rooms):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.rooms = rooms
        runtime.index = 0
        runtime.enter = Mock(return_value=True)
        runtime.move = Mock(return_value=True)
        runtime.close_panel = Mock()
        runtime.join = Mock()
        return runtime

    def test_three_minute_draw_is_joined_immediately_without_more_scouting(self):
        runtime = self.runtime(['first', 'second'])
        runtime.inspect = Mock(return_value=Candidate('first', 0, 280))
        with patch('planned_runtime.time.time', return_value=100):
            runtime.scan_cycle()
        runtime.enter.assert_called_once_with(0)
        runtime.join.assert_called_once_with(Candidate('first', 0, 280))

    def test_two_minute_draw_is_joined_without_leaving_for_more_scouting(self):
        runtime = self.runtime(['first', 'second'])
        runtime.inspect = Mock(return_value=Candidate('first', 0, 220))
        with patch('planned_runtime.time.time', return_value=100):
            runtime.scan_cycle()
        runtime.enter.assert_called_once_with(0)
        runtime.join.assert_called_once()

    def test_long_or_unreadable_draw_does_not_trigger_participation(self):
        runtime = self.runtime(['first', 'second'])
        runtime.inspect = Mock(side_effect=[None, Candidate('second', 1, 500)])
        with patch('planned_runtime.time.time', return_value=100):
            runtime.scan_cycle()
        runtime.join.assert_not_called()

    def test_participation_uses_completed_personal_tasks_not_audience_count(self):
        self.assertTrue(PlannedRuntime.joined('福袋任务（2/2）发送评论已达成入会已达成'))
        self.assertTrue(PlannedRuntime.joined('参与成功等待开奖'))
        self.assertFalse(PlannedRuntime.joined('95人已参与福袋任务(1/2)发送评论未达成'))
        self.assertFalse(PlannedRuntime.joined('福袋任务(0/0)'))

    def test_countdown_is_anchored_to_draw_label_not_background_video(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.ocr = Mock(return_value='视频计时00:10超级福袋任务01:30后开奖')
        _, seconds = runtime.details(Image.new('RGB', (1080, 2400)))
        self.assertEqual(seconds, 90)

    def test_unrelated_time_requires_reading_actual_timer_region(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.ocr = Mock(side_effect=['视频计时00:10超级福袋任务', '0159'])
        _, seconds = runtime.details(Image.new('RGB', (1080, 2400)))
        self.assertEqual(seconds, 119)

    def test_focused_task_regions_recover_purple_sheet_and_completed_membership(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.ocr = Mock(side_effect=[
            '福袋奖品03:04后开奖BAILA(1/2)发送评论你好未达成加入HR会员BAR',
            '福袋任务(1/2)',
            '发送评论你好未达成加入HR会员已达成',
        ])
        text, seconds = runtime.details(Image.new('RGB', (1080, 2400)))
        self.assertEqual(seconds, 184)
        self.assertTrue(runtime.allowed(text, True))

    def test_close_sheet_uses_back_instead_of_tapping_video_behind_it(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.panel = True
        runtime.live = Mock()
        runtime.op = Mock()
        runtime.serial = 'phone'
        runtime.click = Mock()
        with patch('planned_runtime.time.sleep'):
            runtime.close_panel()
        runtime.op.click_back.assert_called_once_with('phone')
        runtime.click.assert_not_called()

    def test_return_to_followed_handles_nested_sheet_then_room_exit(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.lock = Mock()
        runtime.live = Mock()
        runtime.op = Mock()
        runtime.serial = 'phone'
        runtime.followed_rooms = Mock(side_effect=[RuntimeError('sheet'), RuntimeError('room'), {'room': (5, 5)}])
        with patch('planned_runtime.time.sleep'):
            self.assertEqual(runtime.return_to_followed(), {'room': (5, 5)})
        self.assertEqual(runtime.op.click_back.call_count, 2)

    def test_temporary_focus_gap_during_animation_is_rechecked(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.serial = 'phone'
        runtime.op = Mock()
        runtime.op._adb.side_effect = [Mock(stdout=b'mCurrentFocus=null'),
            Mock(stdout=b'mCurrentFocus=Window{abc u0 com.ss.android.ugc.aweme.lite/.live.LivePlayActivity}')]
        with patch('planned_runtime.time.sleep'):
            runtime.live()
        self.assertEqual(runtime.op._adb.call_count, 2)

    def test_unlocked_known_followed_room_recovers_without_user_navigation(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.lock = Mock(state=None)
        runtime.rooms = ['known']
        runtime.panel = False
        runtime.followed_rooms = Mock(side_effect=RuntimeError('not on list'))
        runtime.screen = Mock()
        runtime.room_name = Mock(return_value='known')
        runtime.ocr = Mock(return_value='说点什么')
        runtime.return_to_followed = Mock(return_value={'known': (5, 5)})
        with patch('planned_runtime.time.sleep'):
            runtime.wait_for_resume()
        runtime.return_to_followed.assert_called_once()
