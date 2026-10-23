import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, call
from PIL import Image

from lottery_planner import Candidate, RoomLock, choose_room, parse_countdown
from planned_runtime import PlannedRuntime
from Underlying_Operations import ManualActionRequired


class PlannerTests(unittest.TestCase):
    def test_fast_screenshot_preserves_geometry_without_adb_png_capture(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.live = Mock()
        runtime.device = Mock()
        runtime.device.screenshot.return_value = Image.new('RGB', (1176, 2400))
        runtime.op = Mock()
        with patch.object(Image.Image, 'save'):
            picture = runtime.screen()
        self.assertEqual(picture.size, (1080, 2400))
        runtime.live.assert_called_once()
        runtime.op.get_screenshot.assert_not_called()

    def test_failed_fast_screenshot_falls_back_to_validated_adb_capture(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.live = Mock()
        runtime.device = Mock()
        runtime.device.screenshot.side_effect = OSError('截图服务暂时不可用')
        runtime.op = Mock()
        runtime.serial = 'phone'
        with patch('planned_runtime.Image.open', return_value=Image.new('RGB', (1176, 2400))):
            self.assertEqual(runtime.screen().size, (1080, 2400))
        runtime.op.get_screenshot.assert_called_once_with('phone')

    def test_live_checks_exact_foreground_with_one_adb_call(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.op = Mock()
        runtime.serial = 'phone'
        runtime.op._adb.return_value.stdout = b'mCurrentFocus=Window{abc u0 com.ss.android.ugc.aweme/.live.LivePlayActivity}'
        runtime.live()
        runtime.op._adb.assert_called_once()
        runtime.op._ensure_douyin.assert_not_called()
        runtime.op._adb.return_value.stdout = b'mCurrentFocus=Window{abc u0 com.android.settings/.Settings}\ncom.ss.android.ugc.aweme/.live.LivePlayActivity'
        with self.assertRaises(RuntimeError):
            runtime.live()

    def test_panel_load_proceeds_as_soon_as_recognized(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.click = Mock()
        runtime.screen = Mock()
        runtime.details = Mock(side_effect=[RuntimeError('加载中'), ('福袋任务', 160)])
        runtime.allow_comments = True
        runtime.participation_button = Mock(return_value='一键发表评论')
        with patch('planned_runtime.time.monotonic', side_effect=[0, 1]), patch('planned_runtime.time.sleep') as sleep:
            _, text, seconds = runtime.open_bag(70)
        self.assertEqual((text, seconds), ('福袋任务', 160))
        self.assertEqual(sleep.call_args_list, [call(0.5), call(0.5)])
        runtime.click.assert_called_once_with(70, 403)

    def test_partial_sheet_waits_for_countdown_and_complete_comment_button(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.allow_comments = True
        runtime.click = Mock()
        runtime.screen = Mock()
        runtime.details = Mock(side_effect=[('福袋任务发送评论', None),
                                             ('福袋任务发送评论', 61),
                                             ('福袋任务发送评论', 60)])
        runtime.participation_button = Mock(side_effect=[None, '一键发表评论'])
        with patch('planned_runtime.time.monotonic', side_effect=[0, 1, 2]), patch('planned_runtime.time.sleep') as sleep:
            _, _, seconds = runtime.open_bag(70)
        self.assertEqual(seconds, 60)
        self.assertEqual(runtime.screen.call_count, 3)
        self.assertEqual(sleep.call_count, 3)
        runtime.click.assert_called_once()

    def test_zero_countdown_is_a_complete_sheet_and_paid_sheet_is_skipped(self):
        for text in ('福袋任务参与成功等待开奖', '福袋任务支付1钻石'):
            runtime = PlannedRuntime.__new__(PlannedRuntime)
            runtime.allow_comments = True
            runtime.click = Mock()
            runtime.screen = Mock()
            runtime.details = Mock(return_value=(text, 0))
            runtime.participation_button = Mock()
            with patch('planned_runtime.time.sleep'):
                self.assertEqual(runtime.open_bag(70)[2], 0)
            runtime.participation_button.assert_not_called()

    def test_panel_verification_never_retries_or_clicks_again(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.click = Mock()
        runtime.screen = Mock()
        runtime.details = Mock(side_effect=ManualActionRequired('完成验证'))
        with patch('planned_runtime.time.sleep'), self.assertRaises(ManualActionRequired):
            runtime.open_bag(70)
        self.assertEqual(runtime.details.call_count, 1)
        runtime.click.assert_called_once()

    def test_panel_loading_timeout_returns_control_to_pause_handler(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.click = Mock()
        runtime.screen = Mock()
        runtime.details = Mock(side_effect=RuntimeError('未知弹层'))
        with patch('planned_runtime.time.monotonic', side_effect=[0, 9]), patch('planned_runtime.time.sleep'), self.assertRaises(RuntimeError):
            runtime.open_bag(70)
        runtime.click.assert_called_once()

    def test_move_uses_followed_targets_without_recommendation_swipe(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.lock = Mock()
        runtime.a = Mock()
        runtime.op = Mock()
        runtime.live = Mock()
        runtime.close_panel = Mock()
        runtime.screen = Mock()
        runtime.enter = Mock(return_value=True)
        runtime.rooms = ['first', 'second']
        runtime.index = 0
        with patch('planned_runtime.time.sleep'):
            runtime.move(1)
        runtime.enter.assert_called_once_with(1)
        runtime.a.swipe.assert_not_called()
        runtime.op.click_back.assert_not_called()

    def test_three_minute_draw_is_joined_but_longer_draw_is_skipped(self):
        for seconds in (180, 181):
            with self.subTest(seconds=seconds):
                runtime = PlannedRuntime.__new__(PlannedRuntime)
                runtime.rooms = ['room']
                runtime.index = 0
                runtime.inspect = Mock(return_value=Candidate('room', 0, 100+seconds))
                runtime.join = Mock()
                runtime.close_panel = Mock()
                runtime.enter = Mock(return_value=True)
                with patch('planned_runtime.time.time', return_value=100):
                    runtime.scan_cycle()
                self.assertEqual(runtime.join.call_count, int(seconds <= 180))

    def test_page_interruption_pauses_then_restarts_loop(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime._run = Mock(side_effect=[RuntimeError('页面被手动切换'), KeyboardInterrupt])
        runtime.wait_for_resume = Mock()
        with self.assertRaises(KeyboardInterrupt):
            runtime.run()
        runtime.wait_for_resume.assert_called_once()
        self.assertEqual(runtime._run.call_count, 2)

    def test_resume_waits_for_normal_live_page_and_keeps_active_room_lock(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.lock = Mock(state={'room': 'original', 'deadline': 200})
        runtime.screen = Mock(return_value=Image.new('RGB', (1080, 2400)))
        runtime.room_name = Mock(side_effect=['other', 'original', 'original'])
        runtime.ocr = Mock(side_effect=['说点什么', '说点什么 完成验证', '说点什么'])
        runtime.a = Mock()
        with patch('planned_runtime.time.time', return_value=100), patch('planned_runtime.time.sleep') as sleep:
            runtime.wait_for_resume()
        self.assertEqual(sleep.call_count, 3)
        runtime.lock.release.assert_not_called()
        runtime.a.click.assert_not_called()
        runtime.a.swipe.assert_not_called()
        self.assertFalse(runtime.panel)

    def test_resume_releases_expired_lock_after_confirming_followed_page(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = PlannedRuntime.__new__(PlannedRuntime)
            runtime.lock = RoomLock(Path(directory) / 'lock.json')
            runtime.lock.acquire('old', 100)
            runtime.screen = Mock(return_value=Image.new('RGB', (1080, 2400)))
            runtime.room_name = Mock(return_value='new')
            runtime.ocr = Mock(return_value='说点什么')
            runtime.followed_rooms = Mock(return_value={'new': (50, 300)})
            with patch('planned_runtime.time.time', return_value=200), patch('planned_runtime.time.sleep'):
                runtime.wait_for_resume()
            self.assertIsNone(runtime.lock.state)
            runtime.followed_rooms.assert_called_once()
            runtime.screen.assert_not_called()

    def test_unlocked_resume_requires_followed_page_without_tapping(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.lock = Mock(state=None)
        runtime.followed_rooms = Mock(side_effect=[RuntimeError('当前是推荐页'), {'room': (50, 300)}])
        runtime.screen = Mock()
        runtime.a = Mock()
        with patch('planned_runtime.time.sleep') as sleep:
            runtime.wait_for_resume()
        self.assertEqual(sleep.call_count, 2)
        runtime.screen.assert_not_called()
        runtime.a.click.assert_not_called()
        runtime.a.swipe.assert_not_called()

    def test_countdown_requires_real_time_not_prize_number(self):
        self.assertEqual(parse_countdown('01 : 09 后开奖'), 69)
        self.assertIsNone(parse_countdown('海蓝之谜面霜3.5ml 197参考价值'))
        self.assertIsNone(parse_countdown('01:99'))

    def test_choose_shortest_feasible_deadline_including_return_time(self):
        rooms = [Candidate('a', 0, 135), Candidate('b', 1, 180), Candidate('c', 2, 210)]
        self.assertEqual(choose_room(rooms, 2, 100).room, 'b')
        self.assertEqual(choose_room(rooms, 0, 100).room, 'a')

    def test_expired_candidates_are_not_selected(self):
        self.assertIsNone(choose_room([Candidate('a', 0, 105)], 0, 100))

    def test_lock_survives_restart_until_explicit_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock.json'
            lock = RoomLock(path)
            lock.acquire('room', 100)
            resumed = RoomLock(path)
            with self.assertRaises(RuntimeError):
                resumed.require_unlocked()
            with self.assertRaises(ValueError):
                resumed.release('倒计时已到')
            self.assertTrue(path.exists())
            resumed.release('未中奖')
            resumed.require_unlocked()

    def test_attempt_cannot_overwrite_existing_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = RoomLock(Path(directory) / 'lock.json')
            lock.acquire('first', 100)
            with self.assertRaises(RuntimeError):
                lock.acquire('second', 200)

    def test_watch_waits_until_draw_then_continues_without_reading_result(self):
        for times in ([99, 100], [100], [1000]):
            with self.subTest(times=times), tempfile.TemporaryDirectory() as directory:
                runtime = PlannedRuntime.__new__(PlannedRuntime)
                runtime.lock = RoomLock(Path(directory) / 'lock.json')
                runtime.lock.acquire('room', 100)
                runtime.live = Mock()
                runtime.screen = Mock()
                runtime.room_name = Mock(return_value='room')
                runtime.ocr = Mock(return_value='恭喜中奖')
                runtime.close_panel = Mock()
                with patch('planned_runtime.time.time', side_effect=times), patch('planned_runtime.time.sleep') as sleep:
                    runtime.watch()
                self.assertIsNone(runtime.lock.state)
                self.assertFalse(runtime.lock.path.exists())
                runtime.ocr.assert_not_called()
                runtime.close_panel.assert_called_once()
                self.assertEqual(sleep.call_count, len(times) - 1)

    def test_watch_keeps_lock_if_foreground_is_not_douyin(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.lock = Mock(state={'room': 'room', 'deadline': 100})
        runtime.live = Mock(side_effect=RuntimeError('前台不是抖音'))
        with patch('planned_runtime.time.time', return_value=1000), self.assertRaises(RuntimeError):
            runtime.watch()
        runtime.lock.release.assert_not_called()

    def test_locked_runtime_rejects_navigation_before_any_phone_action(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = PlannedRuntime.__new__(PlannedRuntime)
            runtime.lock = RoomLock(Path(directory) / 'lock.json')
            runtime.lock.acquire('room', 100)
            runtime.close_panel = Mock()
            runtime.live = Mock()
            runtime.a = Mock()
            with self.assertRaises(RuntimeError):
                runtime.move(1)
            runtime.close_panel.assert_not_called()
            runtime.a.swipe.assert_not_called()

    def test_comment_and_purchase_conditions_not_eligible(self):
        for condition in ('一键发表评论', '加入粉丝团', '支付1钻石', '购买商品'):
            self.assertFalse(PlannedRuntime.allowed(condition))
        self.assertTrue(PlannedRuntime.allowed('观看直播30秒 参与抽奖'))
        self.assertTrue(PlannedRuntime.allowed('发送评论:你好未达成同意协议并加入店铺会员已达成', True))
        self.assertFalse(PlannedRuntime.allowed('发送评论:你好未达成加入店铺会员未达成', True))
        self.assertFalse(PlannedRuntime.allowed('支付1钻石', True))

    def test_icon_match_rejects_orange_coupon(self):
        picture = Image.new('RGB', (1080, 2400), 'orange')
        self.assertFalse(PlannedRuntime.has_bag(picture))
        with Image.open(Path(__file__).resolve().parents[1] / 'target_pic/bag_icon_current.png') as icon:
            picture.paste(icon, (33, 350))
        self.assertTrue(PlannedRuntime.has_bag(picture))
        picture = Image.new('RGB', (1080, 2400), 'orange')
        with Image.open(Path(__file__).resolve().parents[1] / 'target_pic/bag_icon_current.png') as icon:
            picture.paste(icon, (159, 350))
        self.assertEqual(PlannedRuntime.find_bag(picture), 196)

    def test_followed_rooms_excludes_recommendations_and_preserves_full_names(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.op = Mock()
        runtime.serial = 'phone'
        runtime.device = Mock()
        runtime.device.dump_hierarchy.return_value = '''<hierarchy>
          <node content-desc="关注，已选中，按钮" />
          <node content-desc="LA MER奇迹礼赞直播中" bounds="[20,280][200,460]" />
          <node content-desc="LA MER旗舰店直播中" bounds="[240,280][420,460]" />
          <node content-desc="推荐主播直播中" bounds="[0,700][1080,1600]" />
        </hierarchy>'''
        self.assertEqual(list(runtime.followed_rooms()), ['LAMER奇迹礼赞', 'LAMER旗舰店'])
        runtime.device.dump_hierarchy.return_value = '<hierarchy><node content-desc="推荐，已选中，按钮" /></hierarchy>'
        with self.assertRaises(RuntimeError):
            runtime.followed_rooms()

    def test_missing_followed_target_does_not_tap_or_swipe(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.lock = Mock()
        runtime.close_panel = Mock()
        runtime.op = Mock()
        runtime.serial = 'phone'
        runtime.device = Mock()
        runtime.device.app_current.return_value = {'activity': 'SplashActivity'}
        runtime.rooms = ['原关注直播间']
        runtime.followed_rooms = Mock(return_value={'其他直播间': (50, 300)})
        self.assertFalse(runtime.enter(0))
        self.assertEqual(runtime.rooms, ['其他直播间'])
        runtime.op.click.assert_not_called()
        runtime.op.swipe.assert_not_called()

    def test_enter_checks_room_identity_before_reporting_success(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.lock = Mock()
        runtime.close_panel = Mock()
        runtime.op = Mock()
        runtime.serial = 'phone'
        runtime.device = Mock()
        runtime.device.app_current.return_value = {'activity': 'SplashActivity'}
        runtime.rooms = ['主播']
        runtime.followed_rooms = Mock(return_value={'主播': (50, 300)})
        runtime.screen = Mock()
        runtime.room_name = Mock(return_value='主播')
        with patch('planned_runtime.time.sleep'):
            self.assertTrue(runtime.enter(0))
        runtime.op.click.assert_called_once_with('phone', 50, 300)
        runtime.room_name.return_value = '其他主播'
        with patch('planned_runtime.time.sleep'), self.assertRaises(RuntimeError):
            runtime.enter(0)

    def test_slow_bag_load_is_polled_without_leaving(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        picture = object()
        runtime.screen = Mock(return_value=picture)
        runtime.find_bag = Mock(side_effect=[None, None, 196])
        with patch('planned_runtime.time.monotonic', side_effect=[0, 1, 5]), patch('planned_runtime.time.sleep') as sleep:
            self.assertEqual(runtime.wait_for_bag(), (picture, 196))
        self.assertEqual(runtime.screen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_alternate_panel_height_reads_countdown_not_prize(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.ocr = Mock(side_effect=['超级福袋 福袋任务 调理液194元', '', '21:37'])
        _, seconds = runtime.details(Image.new('RGB', (1080, 2400)))
        self.assertEqual(seconds, 1297)

    def test_panel_hidden_title_can_confirm_but_not_discover_room(self):
        runtime = PlannedRuntime.__new__(PlannedRuntime)
        runtime.device = Mock()
        runtime.device.dump_hierarchy.return_value = '<hierarchy />'
        runtime.ocr = Mock(return_value='HR赫莲娜')
        picture = Image.new('RGB', (1080, 2400))
        self.assertEqual(runtime.room_name(picture, 'HR赫莲娜'), 'HR赫莲娜')
        with self.assertRaises(RuntimeError):
            runtime.room_name(picture)
        with self.assertRaises(RuntimeError):
            runtime.room_name(picture, 'CPB肌肤之钥')

    def test_comment_click_locks_room_before_sending_and_waits_for_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = PlannedRuntime.__new__(PlannedRuntime)
            runtime.lock = RoomLock(Path(directory) / 'lock.json')
            runtime.allow_comments = True
            runtime.screen = Mock(return_value=Image.new('RGB', (1080, 2400)))
            runtime.room_name = Mock(return_value='主播')
            runtime.details = Mock(side_effect=[('福袋任务发送评论', 60), ('参与成功等待开奖', 58)])
            runtime.ocr = Mock(return_value='一键发表评论')
            runtime.click = Mock(side_effect=lambda *args: self.assertIsNotNone(runtime.lock.state))
            runtime.watch = Mock()
            with patch('planned_runtime.time.time', return_value=100), patch('planned_runtime.time.sleep'):
                self.assertTrue(runtime.join(Candidate('主播', 0, 160)))
            runtime.click.assert_called_once()
            runtime.watch.assert_called_once()
