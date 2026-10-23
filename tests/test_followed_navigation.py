import unittest
from unittest.mock import Mock, patch
from planned_runtime import PlannedRuntime

class FollowedNavigationTests(unittest.TestCase):
    def runtime(self):
        r = PlannedRuntime.__new__(PlannedRuntime)
        r.lock = Mock(state=None)
        r.a = Mock(resolution_ratio_x=1176)
        r.op = Mock(); r.serial = 'phone'
        return r

    def test_catalog_collects_hidden_rooms_and_stops_at_repeated_page(self):
        r=self.runtime()
        first={'a':(100,300)}; last={'b':(100,300)}
        r.return_to_followed=Mock(return_value=first)
        r.followed_rooms=Mock(side_effect=[first,last,last])
        with patch('planned_runtime.time.sleep'):
            self.assertEqual(r.collect_followed_rooms(), ['a','b'])
        self.assertEqual(r.op.swipe.call_count,3)

    def test_swipe_to_followed_room_avoids_returning_to_list(self):
        r=self.runtime(); r.rooms=['a','b']; r.index=0
        r.live=Mock(); r.screen=Mock(); r.room_name=Mock(return_value='b')
        r.close_panel=Mock(); r.enter=Mock()
        with patch('planned_runtime.time.sleep'):
            self.assertTrue(r.move(1))
        r.a.swipe.assert_called_once()
        r.enter.assert_not_called()
        self.assertEqual(r.index,1)

    def test_swipe_recommendation_returns_to_verified_followed_target(self):
        r=self.runtime(); r.rooms=['a','b']; r.index=0
        r.live=Mock(); r.screen=Mock(); r.room_name=Mock(return_value='stranger')
        r.close_panel=Mock(); r.enter=Mock(return_value=True)
        with patch('planned_runtime.time.sleep'):
            r.move(1)
        r.enter.assert_called_once_with(1)

    def test_locked_draw_cannot_swipe(self):
        r=self.runtime(); r.lock.require_unlocked.side_effect=RuntimeError('locked')
        with self.assertRaises(RuntimeError): r.move(1)
        r.a.swipe.assert_not_called()

    def test_enter_finds_offscreen_followed_avatar_before_tapping(self):
        r=self.runtime(); r.rooms=['hidden']; r.index=0
        r.return_to_followed=Mock(return_value={'visible':(50,300)})
        r.followed_pages=Mock(return_value=iter([{'hidden':(700,300)}]))
        r.screen=Mock(); r.room_name=Mock(return_value='hidden')
        with patch('planned_runtime.time.sleep'):
            self.assertTrue(r.enter(0))
        r.op.click.assert_called_once_with('phone',700,300)

    def test_regular_douyin_followed_tab_accepts_alternate_label_order(self):
        r=self.runtime(); r.device=Mock()
        r.device.dump_hierarchy.return_value='<hierarchy><node content-desc="已选中，关注，按钮"/><node content-desc="隐藏主播直播中" bounds="[100,200][300,400]"/></hierarchy>'
        self.assertEqual(r.followed_rooms(), {'隐藏主播':(200,300)})
