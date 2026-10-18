import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location(
    "reliable_activity", Path(__file__).resolve().parents[1] / "2026淘宝双11.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def panel(current=0, cumulative=5):
    return f'''<hierarchy>
      <node><node text="底层无关任务(0/1)" class="android.widget.TextView" />
        <node text="去完成" class="android.widget.Button" bounds="[10,100][100,200]" /></node>
      <node bounds="[0,400][1080,2200]">
        <node text="做任务赚能量" /><node text="累计任务奖励" />
        <node text="当前进度" /><node text="{cumulative}/50" />
        <node><node text="好物沉浸看({current}/10)浏览15秒+400" class="android.widget.TextView" />
          <node text="去完成" class="android.widget.Button" bounds="[850,600][1000,700]" /></node>
        <node><node text="屏幕外任务(0/1)" class="android.widget.TextView" />
          <node text="去完成" class="android.widget.Button" bounds="[850,2350][1000,2400]" /></node>
      </node>
    </hierarchy>'''


class ReliabilityTests(unittest.TestCase):
    def test_empty_coin_webview_resets_reader_once(self):
        shell = '<hierarchy><node text="淘金币首页" />' + '<node text="" />' * 74 + '</hierarchy>'
        ready = shell.replace('淘金币首页', '淘金币首页 赚金币 赚能量 升级赛车拿钱')
        d = Mock()
        d.dump_hierarchy.side_effect = [shell, ready]
        with patch.object(a.time, 'sleep'), patch.dict(a.RUN_REPORT, {'tree_resets': 0}):
            self.assertIn('赚能量', a.dump_xml(d))
        d.stop_uiautomator.assert_called_once()
        d.start_uiautomator.assert_called_once()

    def test_login_page_is_not_treated_as_external_browsing(self):
        d = Mock()
        with patch.object(a, 'current_app', return_value=('com.eg.android.AlipayGphone', '.LoginActivity')):
            self.assertFalse(a.jump_out(d, dwell=1))
        d.swipe.assert_not_called()
        self.assertIn('com.eg.android.AlipayGphone', a.BLOCKED_APPS)

    def test_energy_recommendation_popup_is_closed(self):
        x = '<hierarchy><node text="送你能量最高" /><node text="关闭" class="android.widget.Button" bounds="[500,1800][650,1920]" /></hierarchy>'
        d = Mock()
        with patch.object(a.time, 'sleep'):
            self.assertTrue(a.handle_modals(d, x))
        d.click.assert_called_once_with(575, 1860)

    def test_inject_events_error_can_use_authorized_adb_input(self):
        d = Mock()
        d.swipe.side_effect = RuntimeError('SecurityException INJECT_EVENTS')
        d.shell.return_value.exit_code = 0
        with patch.object(a, 'current_app', return_value=(a.TB_APP, '.Task')), patch.object(a.time, 'sleep'):
            self.assertTrue(a.swipe_in_app(d, 500, 1700, 500, 1100, 0.4))
        d.shell.assert_called_once_with(['input', 'swipe', '500', '1700', '500', '1100', '400'])

    def test_input_fallback_does_not_touch_settings(self):
        d = Mock()
        d.swipe.side_effect = RuntimeError('SecurityException INJECT_EVENTS')
        with patch.object(a, 'current_app', side_effect=[(a.TB_APP, '.Task'), ('com.android.settings', '.Settings')]), \
                patch.object(a.time, 'sleep'):
            self.assertFalse(a.swipe_in_app(d, 500, 1700, 500, 1100, 0.4))
        d.shell.assert_not_called()

    def test_race_closes_panel_and_uses_energy_until_empty(self):
        def race(energy):
            return ('<hierarchy><node class="android.widget.Button" '
                    f'text="升级赛车拿钱 剩余 {energy} 能量" bounds="[200,900][900,1100]" /></hierarchy>')
        d = Mock()
        with patch.object(a, 'dump_xml', side_effect=[panel(), race(100), race(40), race(0)]), \
                patch.object(a, 'close_panel') as close, \
                patch.object(a, 'handle_modals', return_value=False), \
                patch.object(a, 'current_app', return_value=(a.TB_APP, '.Race')), \
                patch.object(a.time, 'sleep'):
            a.do_race(d)
        close.assert_called_once()
        self.assertEqual(d.long_click.call_count, 2)
        self.assertEqual(a.RUN_REPORT['race']['after'], 0)

    def test_cumulative_counter_overrides_reordered_row_counter(self):
        with patch.object(a, 'dump_xml', return_value=panel(8, 5)), patch.object(a.time, 'sleep'):
            verified, _ = a.check_task_progress(Mock(), '好物沉浸看', 3, 5)
        self.assertFalse(verified)

    def test_foreground_falls_back_when_window_focus_is_temporarily_null(self):
        d = Mock()
        d.shell.return_value.output = ('mCurrentFocus=null\n'
            'mFocusedApp=ActivityRecord{abc u0 com.taobao.taobao/.TBMainActivity t27}')
        self.assertEqual(a.current_app(d)[0], a.TB_APP)

    def test_main_does_not_force_restart_an_existing_activity(self):
        with patch('sys.argv', ['activity', '--open-only']), \
                patch.object(a.u2, 'connect', return_value=Mock()), \
                patch.object(a, 'remember_ime'), patch.object(a, 'restore_ime'), \
                patch.object(a, 'open_coin_page', return_value=True), \
                patch.object(a, 'start_run', create=True), \
                patch.object(a, 'save_run_report', create=True), \
                patch.object(a, 'restart_app') as restart:
            a.main()
        restart.assert_not_called()

    def run_one_attempt(self, verified):
        d = Mock()
        row = {'name': '好物沉浸看(0/10)浏览15秒+400', 'node': None}
        with patch.object(a, 'ensure_rows', return_value=[row]), \
                patch.object(a, 'pick_task', side_effect=[row, None, None]), \
                patch.object(a, 'scroll_panel', return_value=False), \
                patch.object(a, 'dump_xml', return_value=panel()), \
                patch.object(a, 'click_task', return_value=True), \
                patch.object(a, 'browse', return_value=True), \
                patch.object(a, 'back_to_panel', return_value=True), \
                patch.object(a, 'check_task_progress', return_value=(verified, int(verified))), \
                patch.object(a, 'claim_rewards'), \
                patch.object(a, 'mute'), \
                patch.object(a, 'handle_modals'), \
                patch.object(a, 'current_app', return_value=(a.TB_APP, '.Task')), \
                patch.object(a, 'wait_jump') as jump, patch.object(a.time, 'sleep'):
            result = a.do_tasks(d, max_tasks=1)
        jump.assert_not_called()
        return result

    def test_task_loop_counts_only_confirmed_credit(self):
        self.assertEqual(self.run_one_attempt(False), 0)
        self.assertEqual(self.run_one_attempt(True), 1)

    def test_rows_are_limited_to_visible_task_panel(self):
        rows = a.panel_rows(Mock(), panel())
        self.assertEqual([a.task_key(r['name']) for r in rows], ['好物沉浸看'])

    def test_task_identity_survives_changed_reward_description(self):
        self.assertEqual(a.task_key('好物沉浸看(3/10)浏览15秒+400'),
                         a.task_key('好物沉浸看（4/10）浏览15s得400能量'))

    def test_duration_parses_full_number_and_english_unit(self):
        self.assertGreaterEqual(a.dwell_seconds('浏览25秒'), 25)
        self.assertGreaterEqual(a.dwell_seconds('浏览15s得1000'), 15)

    def test_settings_is_not_an_external_task_app(self):
        d = Mock()
        with patch.object(a, 'current_app', return_value=('com.android.settings', '.Settings')):
            self.assertEqual(a.wait_jump(d, timeout=1), 'unexpected')
            self.assertFalse(a.jump_out(d, dwell=1))
        d.swipe.assert_not_called()

    def test_browsing_stops_if_settings_is_in_foreground(self):
        d = Mock()
        with patch.object(a, 'current_app', return_value=('com.android.settings', '.Settings')):
            self.assertFalse(a.browse(d, '浏览15秒'))
        d.swipe.assert_not_called()
        d.send_keys.assert_not_called()

    def test_cross_app_tasks_are_skipped_by_default(self):
        rows = [{'name': '逛一逛蚂蚁庄园(0/1)', 'node': None},
                {'name': '好物沉浸看(0/10)浏览15秒', 'node': None}]
        self.assertEqual(a.pick_task(Mock(), rows, {}, set(), {}), rows[1])

    def test_no_credit_is_reported_when_progress_does_not_change(self):
        with patch.object(a, 'dump_xml', return_value=panel()), patch.object(a.time, 'sleep'):
            verified, _ = a.check_task_progress(Mock(), '好物沉浸看', 0, 5)
        self.assertFalse(verified)

    def test_credit_is_reported_after_delayed_progress_refresh(self):
        with patch.object(a, 'dump_xml', side_effect=[panel(), panel(1, 6)]), patch.object(a.time, 'sleep'):
            verified, current = a.check_task_progress(Mock(), '好物沉浸看', 0, 5)
        self.assertTrue(verified)
        self.assertEqual(current, 1)

    def test_click_uses_fresh_task_position(self):
        d = Mock()
        with patch.object(a, 'dump_xml', return_value=panel(2)), \
                patch.object(a, 'current_app', return_value=(a.TB_APP, '.Task')):
            self.assertTrue(a.click_task(d, '好物沉浸看'))
        d.click.assert_called_once_with(925, 650)


if __name__ == '__main__':
    unittest.main()
