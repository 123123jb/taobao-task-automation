import argparse
import os
from pathlib import Path
import sys

from douyin_fudai import fudai_analyse
from Underlying_Operations import ManualActionRequired, underlying_operations

class fudai_guaji:
    def __init__(self):
        self.analyser = fudai_analyse()

    def guaji(self, serial=None):
        """挂机函数"""
        device_id = serial or self.analyser.operation.select_device()
        if device_id:
            self.analyser.fudai_choujiang(device_id, False, 15)
            return True
        raise RuntimeError('未检测到已授权设备，请连接手机并开启 USB 调试')

if __name__ == '__main__':
    os.chdir(Path(__file__).resolve().parent)
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', help='指定手机序列号')
    parser.add_argument('--check', action='store_true', help='只检查环境与设备，不操作手机')
    args = parser.parse_args()
    original_stdout = sys.stdout
    choujiang = None
    try:
        if args.check:
            operation = underlying_operations()
            device = args.serial or operation.select_device()
            if not device:
                raise RuntimeError('未检测到已授权设备')
            operation._adb(device, 'get-state')
            operation.get_device_resolution(device)
            operation.get_ballery_level(device)
            package = operation.get_douyin_package_name(device)
            operation.get_douyin_activity_name(device, package)
            print('检查通过；OCR：' + ('本机 Tesseract' if operation.tesseract else 'PaddleOCR'))
        else:
            choujiang = fudai_guaji()
            choujiang.guaji(args.serial)
    except KeyboardInterrupt:
        print('已停止')
    except (ManualActionRequired, RuntimeError) as exc:
        print(str(exc))
        raise SystemExit(2)
    finally:
        sys.stdout = original_stdout
        if choujiang is not None:
            choujiang.analyser.log_file.close()
