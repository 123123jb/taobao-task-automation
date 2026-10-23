import unittest
from unittest.mock import Mock, patch

from lottery_planner import Candidate
from planned_runtime import PlannedRuntime


class SelectionTests(unittest.TestCase):
    def runtime(self, rooms):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.rooms = rooms
        runtime.index = 0
        runtime.enter = Mock(return_value=True)
        runtime.close_panel = Mock()
        runtime.join = Mock()
        return runtime

    def test_compare_rooms_before_joining_a_longer_draw(self):
        runtime = self.runtime(['first', 'second'])
        runtime.inspect = Mock(side_effect=[Candidate('first', 0, 260),
                                            Candidate('second', 1, 240),
                                            Candidate('second', 1, 239)])
        with patch('planned_runtime.time.time', return_value=100):
            runtime.scan_cycle()
        runtime.join.assert_called_once_with(Candidate('second', 1, 239))

    def test_two_minute_draw_is_joined_without_leaving_for_more_scouting(self):
        runtime = self.runtime(['first', 'second'])
        runtime.inspect = Mock(return_value=Candidate('first', 0, 220))
        with patch('planned_runtime.time.time', return_value=100):
            runtime.scan_cycle()
        runtime.enter.assert_called_once_with(0)
        runtime.join.assert_called_once()

    def test_later_round_is_not_joined_using_an_old_observation(self):
        runtime = self.runtime(['first'])
        runtime.inspect = Mock(side_effect=[Candidate('first', 0, 250), Candidate('first', 0, 600)])
        with patch('planned_runtime.time.time', return_value=100):
            runtime.scan_cycle()
        runtime.join.assert_not_called()

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
