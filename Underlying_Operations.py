import subprocess
from datetime import datetime, timedelta
import os
import time
from PIL import Image, ImageFilter
import io
from pathlib import Path
import shutil
import logging
import re
import random
import json

class ManualActionRequired(RuntimeError):
    """需要本人登录、验证或领取奖品时停止自动操作。"""


class underlying_operations:
    """底层操作类"""
    def __init__(self):
        adb_path = os.environ.get('ADBUTILS_ADB_PATH')
        if adb_path:
            os.environ['PATH'] = str(Path(adb_path).resolve().parent) + os.pathsep + os.environ.get('PATH', '')
        self.tesseract = shutil.which('tesseract')
        self.ocr = None
        if not self.tesseract:
            from paddleocr import PaddleOCR
            self.ocr = PaddleOCR()
        logging.disable(logging.DEBUG)
        logging.disable(logging.WARNING)

    def _adb(self, device_id, *args):
        executable = os.environ.get('ADBUTILS_ADB_PATH') or shutil.which('adb')
        if not executable:
            raise RuntimeError('找不到 adb，请配置 PATH 或 ADBUTILS_ADB_PATH')
        return subprocess.run([executable, '-s', device_id, *map(str, args)],
                              capture_output=True, check=True, timeout=15,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def _ensure_douyin(self, device_id):
        output = self._adb(device_id, 'shell', 'dumpsys', 'window').stdout.decode('utf-8', errors='replace')
        match = re.search(r'mCurrentFocus=.*?\bu0\s+([\w.]+)/([^\s}]+)', output)
        if not match or match.group(1) not in ('com.ss.android.ugc.aweme', 'com.ss.android.ugc.aweme.lite'):
            raise RuntimeError('前台不是抖音，停止手势并保留当前页面')
        if 'login' in match.group(2).lower():
            raise ManualActionRequired('请在手机上手动登录抖音')

    def select_device(self):
        """选择需要连接的设备"""
        string = subprocess.Popen('adb devices', shell=True, stdout=subprocess.PIPE)
        totalstring = string.stdout.read()
        totalstring = totalstring.decode('utf-8')
        # print(totalstring)
        pattern = r'(\b(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?::[0-9]+)?|[A-Za-z0-9]{8,})\b)\s*device\b'
        devicelist = re.findall(pattern, totalstring)
        # devicelist = re.compile(r'(\w*)\s*device\b').findall(totalstring)
        devicenum = len(devicelist)
        if devicenum == 0:
            print("当前无设备连接电脑,请检查设备连接情况!")
            return False
        elif devicenum == 1:
            print("当前有一台设备连接，编号:%s." % devicelist[0])
            return devicelist[0]
        else:
            print("当前存在多台设备连接! 输入数字选择对应设备:")
            dictdevice = {}
            for i in range(devicenum):
                string = subprocess.Popen("adb -s %s shell getprop ro.product.device" % devicelist[i], shell=True,
                                          stdout=subprocess.PIPE)
                modestring = string.stdout.read().strip()  # 去除掉自动生成的回车
                print("%s:%s---%s" % (i + 1, devicelist[i], modestring))
                dictdevice[i + 1] = devicelist[i]
            num = input()
            num = int(num)
            while not num in dictdevice.keys():
                print('输入不正确，请重新输入：')
                num = input()
                num = int(num)
            return dictdevice[num]

    def get_screenshot(self, device_id, path='pic'):
        """一次 ADB 读取截图，验证成功后再替换本机文件。"""
        folder = Path(__file__).resolve().parent / path if path in ('pic', 'target_pic') else Path(path)
        data = self._adb(device_id, 'exec-out', 'screencap', '-p').stdout
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except (OSError, ValueError) as exc:
            raise RuntimeError('无法获取有效截图，请检查手机解锁状态和截图权限') from exc
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'screenshot.png').write_bytes(data)
        print(f"{datetime.now():%H:%M:%S} 获取屏幕截图")
        return True

    def get_current_hour(self):
        """获取当前的时间小时数"""
        time_hour = datetime.now().strftime('%H')
        print("当前时间{}点".format(time_hour))
        return int(time_hour)

    def click_confirm(self, device_id):
        """点击确认键"""
        self._ensure_douyin(device_id)
        self._adb(device_id, 'shell', 'input', 'keyevent', '66')
        print("点击确认键")

    def click_back(self, device_id):
        """点击返回键"""
        self._ensure_douyin(device_id)
        self._adb(device_id, 'shell', 'input', 'keyevent', '4')
        print("点击返回键")

    def get_ballery_level(self, device_id):
        """获取设备电量信息"""
        battery_info = subprocess.Popen("adb -s %s shell dumpsys battery" % device_id, shell=True,
                                        stdout=subprocess.PIPE)
        battery_info_string = battery_info.stdout.read()
        battery_info_string = bytes.decode(battery_info_string)
        location = re.search('level:', battery_info_string)
        span = location.span()
        start, end = span
        start = end + 1
        for i in range(5):
            end += 1
            if battery_info_string[end] == "\n":
                break
        battery_level = battery_info_string[start:end]  # 第几个到第几个中间接冒号
        battery_level = int(battery_level)
        print("设备当前电量为{}".format(battery_level))
        return battery_level

    def get_device_resolution(self, device_id):
        """获取设备分辨率"""
        resolution_info = subprocess.Popen("adb -s %s shell wm size" % device_id, shell=True,
                                        stdout=subprocess.PIPE)
        resolution_info_string = resolution_info.stdout.read()
        resolution_info_string = bytes.decode(resolution_info_string)
        match = re.search(r'Physical size: (\d+)x(\d+)', resolution_info_string)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
            print("设备分辨率为：{}*{}".format(width, height))
            return width, height
        else:
            raise ValueError("Could not find resolution in adb output")
            return False

    def save_reward_pic(self, device_id):
        self.get_screenshot(device_id)
        folder = Path(__file__).resolve().parent / 'pic'
        target = folder / f'{datetime.now():%Y-%m-%d-%H-%M-%S}.png'
        shutil.copyfile(folder / 'screenshot.png', target)
        print('已保存当前页面截图，仅供本机核对')

    def cut_pic(self, left_up=(0, 63), right_down=(1080, 1620), target='', name=''):
        '''裁剪图片，获取需要的区域小图片方便识别'''
        if target == '' or target == False:
            path = os.path.dirname(__file__) + '/pic'
            pic1_path = path + '/screenshot.png'
            pic = Image.open(pic1_path)
            if name == '':
                cut_pic_path = path + '/cut.png'
            else:
                cut_pic_path = path + '/' + name + '.png'
            pic.crop((left_up[0], left_up[1], right_down[0], right_down[1])).save(cut_pic_path)
            return True
        path_target = os.path.dirname(__file__) + '/pic/' + target
        pic1_path = path_target + '/screenshot.png'
        pic = Image.open(pic1_path)
        if name == '':
            cut_pic_path = path_target + '/cut.png'
        else:
            cut_pic_path = path_target + '/' + name + '.png'
        pic.crop((left_up[0], left_up[1], right_down[0], right_down[1])).save(cut_pic_path)

    def analyse_pic_word(self, picname='', change_color=0):
        """识别图像中的文字, change_color=1或2为不同的二值化模式，其他不做处理"""
        path = os.path.dirname(__file__) + '/pic'
        if picname == '':
            pic = path + '/cut.png'
        else:
            pic = path + '/' + picname + '.png'
        img = Image.open(pic)
        img = img.convert('L')  # 转换为灰度图
        if change_color == 1:
            img = img.point(lambda x: 0 if x < 128 else 255)  # 二值化
        elif change_color == 2:
            img = img.point(lambda x: 0 if x < 180 else 255)  # 二值化
        # img.save(pic)
        # img.show()
        if self.tesseract:
            data = io.BytesIO()
            img.save(data, format='PNG')
            result = subprocess.run([self.tesseract, 'stdin', 'stdout', '-l', 'chi_sim+eng', '--psm', '6'],
                                    input=data.getvalue(), capture_output=True, check=True, timeout=10,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return re.sub(r'\s+', '', result.stdout.decode('utf-8'))
        import numpy as np
        img_np = np.array(img)
        result = self.ocr.ocr(img_np)
        if result == [None]:
            return ''
        return self.extract_ocr_content(result)

    def extract_ocr_content(self, content=[]):
        """对OCR识别到的内容进行取值和拼接，变成完整的一段内容"""
        ocr_result = content
        extracted_content = []
        for item in ocr_result[0]:  # item 的结构为 [位置信息, (识别内容, 置信度)]
            extracted_content.append(item[1][0])
        contains = ''.join(context for context in extracted_content if context)
        # print(contain)
        return contains

    def delay(self, seconds=1):
        time.sleep(seconds)

    def random_delay(self, min_seconds=1, max_seconds=100):
        """等待随机的时长"""
        random_wait_seconds = random.randint(min_seconds, max_seconds)
        print("随机等待{}秒.".format(random_wait_seconds))
        self.delay(random_wait_seconds)

    def check_countdown(self, last_time=''):
        """对倒计时时间进行转化，变成秒存储"""
        try:
            last_time = ''.join([char for char in last_time if char.isdigit()])
            if len(last_time) == 4:
                # minutes, seconds = map(int, last_time.split(':'))
                minutes = int(last_time[:2])
                seconds = int(last_time[2:])
            else:
                print("时间格式异常")
                return False
            # 转换为总秒数
            total_seconds = minutes * 60 + seconds
            print("剩余总秒数：", total_seconds)
            if total_seconds > 900:  # 如果识别到的分钟大于15，说明识别异常了，按15分钟处理
                total_seconds = 890
            # datetime.strptime(in_time, '%H:%M')
            # time_obj = datetime.strptime(in_time, '%H:%M')
            # print("转换后的时间格式：", time_obj)
            now = datetime.now()
            future_time = now + timedelta(seconds=total_seconds)
            # 将到期时间转换为时间戳
            future_timestamp = future_time.timestamp()
            future_datetime = datetime.fromtimestamp(future_timestamp)
            # 将datetime对象格式化为通常的时间格式
            formatted_future_time = future_datetime.strftime('%Y-%m-%d %H:%M:%S')
            print("预计开奖时间：", formatted_future_time)
            return total_seconds, future_timestamp
        except ValueError:
            print("输入的字符串不是有效的时间格式")
            return False

    def swipe(self, device_id, left_up_x=0, left_up_y=0, right_down_x=1080, right_down_y=1500, steps=200):
        """划动屏幕"""
        self._ensure_douyin(device_id)
        self._adb(device_id, 'shell', 'input', 'swipe', left_up_x, left_up_y, right_down_x, right_down_y, steps)

    def click(self, device_id, x=500, y=500):
        """点击坐标位置"""
        self._ensure_douyin(device_id)
        self._adb(device_id, 'shell', 'input', 'tap', x, y)

    def input_text(self, device_id: str, text: str):
        raise ManualActionRequired('自动评论未启用，请手动输入与发送')

    def get_douyin_package_name(self, device_id):
        """获取抖音app的包名"""
        try:
            # 运行 adb 命令查找包含 "aweme" 的包名
            cmd = f'adb -s {device_id} shell pm list packages | findstr "aweme"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            output = result.stdout
            for line in output.splitlines():
                if "aweme" in line:
                    # 解析出包名
                    return line.split(":")[1]
        except Exception as e:
            print(f"获取包名时出错: {e}")
        return None

    def get_douyin_activity_name(self, device_id, package_name):
        if package_name not in ('com.ss.android.ugc.aweme', 'com.ss.android.ugc.aweme.lite'):
            raise RuntimeError('未找到支持的抖音安装包')
        output = self._adb(device_id, 'shell', 'cmd', 'package', 'resolve-activity', '--brief',
                           '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER',
                           package_name).stdout.decode('utf-8', errors='replace')
        component = next((line.strip() for line in output.splitlines() if line.strip().startswith(package_name + '/')), None)
        if not component:
            raise RuntimeError('无法解析抖音启动入口')
        return component

    def start_douyin_app(self, device_id):
        """启动抖音"""
        package_name = self.get_douyin_package_name(device_id)
        component = self.get_douyin_activity_name(device_id, package_name)
        self._adb(device_id, 'shell', 'am', 'start', '-n', component)
        print('已启动抖音')
        self.delay(3)

    def stop_douyin_app(self, device_id):
        """强制关闭抖音"""
        try:
            package_name = self.get_douyin_package_name(device_id)
            cmd = f'adb -s {device_id} shell am force-stop {package_name}'
            subprocess.run(cmd)
            print(f"[{datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}] 已在设备 {device_id} 关闭: {package_name}")
            self.delay(2)
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}] 关闭应用时出错: {e}")

    def __del__(self):
        if hasattr(self, 'log_file'):
            self.log_file.close()

    def load_config(self, config_path="config.json", key="contains_want"):
        """从配置文件中加载数据"""
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as file:
                config = json.load(file)
                return config.get(key, [])


    def update_config_with_offsets(self, config_path="config.json", device_offsets=None):
        """
        更新设备偏移值到配置文件
        仅新增未写入过的设备偏移值，不覆盖已存在的记录。
        """
        if device_offsets is None:
            device_offsets = {}

        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as file:
                try:
                    config = json.load(file)
                except Exception:
                    config = {}
        else:
            config = {}

        existing_map = config.get('device_offsets', {})
        # 仅合并未存在的条目
        new_entries = {device_id: offset for device_id, offset in device_offsets.items() if device_id not in existing_map}
        if not new_entries:
            return False

        existing_map.update(new_entries)
        config['device_offsets'] = existing_map
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True

