import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location(
    "activity", Path(__file__).resolve().parents[1] / "2026淘宝双11.py")
activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activity)


class ActivityTests(unittest.TestCase):
    def test_claim_rewards_ignores_coupon_behind_task_panel(self):
        xml = '''<hierarchy>
          <node text="¥ 3 限时领取" class="android.widget.Button" bounds="[900,1600][1100,1800]" />
          <node>
            <node><node text="做任务赚能量" /></node>
            <node text="累计任务奖励" />
            <node text="领取1000能量" class="android.widget.Button" bounds="[300,650][500,800]" />
            <node text="已领取" class="android.widget.Button" bounds="[600,650][800,800]" />
          </node>
        </hierarchy>'''
        device = Mock()
        with patch.object(activity, "dump_xml", return_value=xml), \
                patch.object(activity.time, "sleep"), \
                patch.object(activity, "tap_skip"):
            activity.claim_rewards(device)
        device.click.assert_called_once()
        x, y = device.click.call_args.args
        self.assertTrue(300 <= x <= 500 and 650 <= y <= 800)

    def test_reservation_task_is_skipped(self):
        rows = [{"name": "预约组队开赛提醒(0/1)成功订阅组队开赛提醒得+1000", "node": None}]
        self.assertIsNone(activity.pick_task(Mock(), rows, {}, set(), {}))

    def test_slow_activity_load_does_not_press_back(self):
        home = '<hierarchy><node content-desc="领淘金币" bounds="[492,343][683,544]" /></hierarchy>'
        loading = '<hierarchy><node text="加载中" /></hierarchy>'
        page = '<hierarchy><node text="赚金币 赚能量 升级赛车拿钱" /></hierarchy>'
        device = Mock()
        with patch.object(activity, "dump_xml", side_effect=[home, loading, loading, page]), \
                patch.object(activity, "current_app", return_value=(activity.TB_APP, "")), \
                patch.object(activity.time, "sleep"), \
                patch.object(activity, "mute"):
            self.assertTrue(activity.open_coin_page(device))
        device.press.assert_not_called()

    def test_failed_hierarchy_read_reports_connection_error(self):
        device = Mock()
        device.dump_hierarchy.side_effect = OSError("device offline")
        with patch.object(activity.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "USB"):
                activity.dump_xml(device, retries=2)

    def test_ime_cleanup_failure_preserves_original_error(self):
        with patch("sys.argv", ["activity", "--open-only"]), \
                patch.object(activity.u2, "connect", return_value=Mock()), \
                patch.object(activity, "remember_ime"), \
                patch.object(activity, "restart_app", side_effect=RuntimeError("original connection failure")), \
                patch.object(activity, "restore_ime", side_effect=OSError("device offline")):
            with self.assertRaisesRegex(RuntimeError, "original connection failure"):
                activity.main()

    def test_home_ad_close_button_uses_content_description(self):
        xml = '<hierarchy><node class="android.widget.ImageView" content-desc="关闭按钮" clickable="true" bounds="[531,1801][644,1914]" /></hierarchy>'
        device = Mock()
        with patch.object(activity.time, "sleep"):
            self.assertTrue(activity.tap_skip(device, xml))
        device.click.assert_called_once()
        x, y = device.click.call_args.args
        self.assertTrue(531 <= x <= 644 and 1801 <= y <= 1914)

    def test_home_overlay_is_closed_before_entry_is_tapped(self):
        home = '<hierarchy><node content-desc="领淘金币" bounds="[492,343][683,544]" /></hierarchy>'
        page = '<hierarchy><node text="赚金币 赚能量 升级赛车拿钱" /></hierarchy>'
        with patch.object(activity, "dump_xml", side_effect=[home, page]), \
                patch.object(activity, "tap_skip", return_value=True) as close_ad, \
                patch.object(activity, "tap_node") as tap_entry, \
                patch.object(activity, "mute"):
            self.assertTrue(activity.open_coin_page(Mock()))
        close_ad.assert_called_once()
        tap_entry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
