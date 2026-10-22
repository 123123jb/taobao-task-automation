import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import Underlying_Operations as operations
from douyin_fudai import fudai_analyse


class RuntimeTests(unittest.TestCase):
    def test_import_does_not_require_paddle(self):
        subprocess.run([sys.executable, '-c', "import sys;sys.modules.update({'paddleocr':None,'numpy':None});import Underlying_Operations"], check=True, capture_output=True)

    def test_screenshot_is_validated_before_replacing_previous_file(self):
        op = operations.underlying_operations.__new__(operations.underlying_operations)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'screenshot.png'
            target.write_bytes(b'previous screenshot')
            with patch.object(op, '_adb', return_value=Mock(stdout=b'not a png')):
                with self.assertRaises(RuntimeError):
                    op.get_screenshot('serial', folder)
            self.assertEqual(target.read_bytes(), b'previous screenshot')
            data = io.BytesIO()
            Image.new('RGB', (4, 4)).save(data, format='PNG')
            with patch.object(op, '_adb', return_value=Mock(stdout=data.getvalue())):
                self.assertTrue(op.get_screenshot('serial', folder))
            with Image.open(target) as picture:
                self.assertEqual(picture.size, (4, 4))

    def test_foreign_app_prevents_click_and_swipe(self):
        op = operations.underlying_operations.__new__(operations.underlying_operations)
        with patch.object(op, '_adb', return_value=Mock(stdout=b'mCurrentFocus=Window{abc u0 com.android.settings/.Settings}')) as adb:
            with self.assertRaises(RuntimeError):
                op.click('serial', 100, 100)
            with self.assertRaises(RuntimeError):
                op.swipe('serial')
        self.assertFalse(any('input' in call.args for call in adb.call_args_list))

    def test_click_is_sent_only_after_confirming_douyin_foreground(self):
        op = operations.underlying_operations.__new__(operations.underlying_operations)
        focus = b'mCurrentFocus=Window{abc u0 com.ss.android.ugc.aweme/.live.LivePlayActivity}'
        with patch.object(op, '_adb', side_effect=[Mock(stdout=focus), Mock()]) as adb:
            op.click('serial', 100, 200)
        self.assertEqual(adb.call_args.args, ('serial', 'shell', 'input', 'tap', 100, 200))

    def test_launcher_resolver_uses_exact_package_component(self):
        op = operations.underlying_operations.__new__(operations.underlying_operations)
        output = b'priority=0\ncom.ss.android.ugc.aweme/.splash.SplashActivity\n'
        with patch.object(op, '_adb', return_value=Mock(stdout=output)):
            self.assertEqual(op.get_douyin_activity_name('serial', 'com.ss.android.ugc.aweme'), 'com.ss.android.ugc.aweme/.splash.SplashActivity')

    def test_tesseract_ocr_normalizes_text_without_loading_paddle(self):
        op = operations.underlying_operations.__new__(operations.underlying_operations)
        op.tesseract = 'tesseract'
        picture = Image.new('RGB', (10, 10))
        with patch.object(operations.Image, 'open', return_value=picture), \
                patch.object(operations.subprocess, 'run', return_value=Mock(stdout='参与 抽奖\n'.encode('utf-8'))) as execute:
            self.assertEqual(op.analyse_pic_word('test'), '参与抽奖')
        self.assertIn('chi_sim+eng', execute.call_args.args[0])

    def test_verification_requires_manual_action_without_gestures(self):
        analyser = fudai_analyse.__new__(fudai_analyse)
        analyser.operation = Mock()
        analyser.device_id = 'serial'
        analyser.check_have_robot_analyse = Mock(return_value=1)
        analyser.click = Mock()
        analyser.swipe = Mock()
        with self.assertRaises(operations.ManualActionRequired):
            analyser.deal_robot_analyse()
        analyser.click.assert_not_called()
        analyser.swipe.assert_not_called()

    def test_comment_or_paid_requirements_are_skipped(self):
        for condition in ['发送评论参与抽奖', '送礼物', '加入粉丝团', '支付1元', '消耗1钻石', '开通会员']:
            analyser = fudai_analyse.__new__(fudai_analyse)
            analyser.operation = Mock()
            analyser.operation.analyse_pic_word.return_value = condition
            analyser.device_id = 'serial'
            analyser.cut_pic = Mock()
            analyser.find_fudai_detail_top_y = Mock(return_value=900)
            analyser.click = Mock()
            self.assertFalse(analyser.attend_choujiang(), condition)
            analyser.click.assert_not_called()

    def test_winning_prize_does_not_submit_order(self):
        analyser = fudai_analyse.__new__(fudai_analyse)
        analyser.operation = Mock()
        analyser.device_id = 'serial'
        analyser.click = Mock()
        with self.assertRaises(operations.ManualActionRequired):
            analyser.get_reward(1490)
        analyser.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
