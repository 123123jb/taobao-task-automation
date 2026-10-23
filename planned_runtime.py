"""Scout followed live rooms and keep joined draws locked until they finish.

Only the visually verified Super Lucky Bag layout is actionable. Unknown layouts
stop rather than guessing buttons. Screenshots and state remain local.
"""
import io
from datetime import datetime
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops, ImageStat

from lottery_planner import Candidate, RoomLock, choose_room, parse_countdown
from Underlying_Operations import ManualActionRequired

RECOVERABLE_ERRORS = (RuntimeError, OSError, subprocess.SubprocessError, ET.ParseError)


class PlannedRuntime:
    def __init__(self, analyser, serial, allow_comments=False):
        self.a = analyser
        self.op = analyser.operation
        self.serial = serial
        self.lock = RoomLock(Path('logs') / f'room-lock-{serial}.json')
        self.index = 0
        self.panel = False
        self.allow_comments = allow_comments
        import uiautomator2
        self.device = uiautomator2.connect(serial)
        self.device.jsonrpc.setConfigurator({'waitForIdleTimeout': 0, 'waitForSelectorTimeout': 0})

    def live(self):
        for attempt in range(3):
            focus = self.op._adb(self.serial, 'shell', 'dumpsys', 'window').stdout.decode('utf-8', errors='replace')
            match = re.search(r'mCurrentFocus=.*?\bu0\s+([\w.]+)/([^\s}]+)', focus)
            if match or 'mCurrentFocus=null' not in focus or attempt == 2:
                break
            time.sleep(.3)
        if not match or match[1] not in ('com.ss.android.ugc.aweme', 'com.ss.android.ugc.aweme.lite'):
            raise RuntimeError('前台不是抖音，暂停操作')
        if not match[2].endswith('LivePlayActivity'):
            raise ManualActionRequired('当前不是普通直播间，停止操作；请手动返回直播间')

    def screen(self):
        self.live()
        try:
            source = self.device.screenshot()
            if not isinstance(source, Image.Image):
                raise RuntimeError('截图服务没有返回有效图片')
            source.load()
            picture = source.convert('RGB')
            picture.save('pic/screenshot.png')
            print(f'{datetime.now():%H:%M:%S} 获取屏幕截图（快速）', flush=True)
        except RECOVERABLE_ERRORS:
            self.op.get_screenshot(self.serial)
            with Image.open('pic/screenshot.png') as source:
                picture = source.convert('RGB')
        return picture.resize((1080, 2400))

    def ocr(self, picture, digits=False):
        if not self.op.tesseract:
            raise RuntimeError('规划模式需要本机 Tesseract')
        data = io.BytesIO()
        picture.save(data, format='PNG')
        command = [self.op.tesseract, 'stdin', 'stdout', '--psm', '7' if digits else '6']
        command += ['-c', 'tessedit_char_whitelist=0123456789:'] if digits else ['-l', 'chi_sim+eng']
        output = subprocess.run(command, input=data.getvalue(), capture_output=True,
                                check=True, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return output.stdout.decode('utf-8', errors='replace').strip()

    def room_name(self, picture, expected=None):
        # Accessibility exposes the full name even when the painted title is
        # truncated (several LA MER rooms otherwise look identical).
        for node in ET.fromstring(self.device.dump_hierarchy()).iter('node'):
            bounds = [int(value) for value in re.findall(r'\d+', node.get('bounds', ''))]
            text = node.get('text', '')
            if len(bounds) != 4 or not text:
                continue
            x1, y1, x2, y2 = bounds
            width, height = self.a.resolution_ratio_x, self.a.resolution_ratio_y
            if .10*width < x1 < .20*width and .04*height < y1 < .08*height and y2-y1 < .035*height:
                return re.sub(r'\s+', '', text)
        # The lottery web sheet hides underlying accessibility nodes. The
        # already-verified room title remains painted above it; use that only
        # to confirm the expected room, never to discover/select a new one.
        if expected:
            visible = re.sub(r'[^\w\u4e00-\u9fff]', '', self.ocr(picture.crop((130, 130, 300, 190))))
            normalized = re.sub(r'[^\w\u4e00-\u9fff]', '', expected)
            if len(visible) >= 4 and normalized.casefold().startswith(visible.casefold()):
                return expected
        raise RuntimeError('无法读取完整直播间名称，保留当前页面')

    def click(self, x, y):
        self.live()
        self.a.click(x, y)

    def close_panel(self):
        if self.panel:
            # The web sheet ignores taps on the video behind it on this phone.
            self.live()
            self.op.click_back(self.serial)
            self.panel = False
            time.sleep(1)

    def followed_rooms(self):
        self.op._ensure_douyin(self.serial)
        root = ET.fromstring(self.device.dump_hierarchy())
        if not any(n.get('content-desc') == '关注，已选中，按钮' for n in root.iter('node')):
            raise RuntimeError('未确认关注列表，停止导航')
        rooms = {}
        for node in root.iter('node'):
            label = node.get('content-desc', '')
            bounds = [int(v) for v in re.findall(r'\d+', node.get('bounds', ''))]
            if label.endswith('直播中') and len(bounds) == 4 and bounds[1] < 600:
                x1, y1, x2, y2 = bounds
                rooms[re.sub(r'\s+', '', label[:-3])] = ((x1+x2)//2, (y1+y2)//2)
        if not rooms:
            raise RuntimeError('关注列表当前没有可见直播间')
        return rooms

    def return_to_followed(self):
        self.lock.require_unlocked()
        for attempt in range(4):
            try:
                rooms = self.followed_rooms()
                self.panel = False
                return rooms
            except RuntimeError:
                if attempt == 3:
                    raise
            # Back may first dismiss a result/sheet and only then leave the
            # room. Check the destination after each step, without blind taps.
            self.live()
            self.op.click_back(self.serial)
            time.sleep(2)

    def enter(self, index):
        self.lock.require_unlocked()
        rooms = self.return_to_followed()
        name = self.rooms[index]
        if name not in rooms:
            self.rooms = list(rooms)
            print(f'关注列表已变化，重新筛选当前 {len(self.rooms)} 个直播间', flush=True)
            return False
        self.op.click(self.serial, *rooms[name])
        time.sleep(3)
        self.index = index
        if self.room_name(self.screen()) != name:
            raise RuntimeError('打开的直播间与关注名单不一致，停止操作')
        return True

    def move(self, direction):
        self.lock.require_unlocked()
        return self.enter((self.index + direction) % len(self.rooms))

    def details(self, picture):
        text = re.sub(r'\s+', '', self.ocr(picture.crop((0, 1000, 1080, 2280))))
        if any(word in text for word in ('验证码', '完成验证', '拖动滑块')):
            raise ManualActionRequired('出现人工验证，保留当前页面')
        unclear_tasks = '任务' not in text or ('加入' in text and not re.search(r'加入.{0,45}已达成', text))
        if '福袋' in text and unclear_tasks:
            # Pink labels on the purple sheet are often read as Latin letters.
            # Separate the task header and rows; green separates the label from
            # the background, while enlarged RGB preserves completed statuses.
            header_image = picture.crop((30, 1780, 1050, 1870)).resize((2040, 180))
            header = re.sub(r'\s+', '', self.ocr(header_image.getchannel('G')))
            if '福袋任务' in header:
                rows_image = picture.crop((30, 1840, 1050, 2020)).resize((2040, 360))
                rows = re.sub(r'\s+', '', self.ocr(rows_image))
                text = re.split(r'福袋任务|发送评论', text, maxsplit=1)[0] + header + rows
        if '福袋' not in text or '任务' not in text:
            raise RuntimeError('当前弹层不是已验证的福袋布局，停止点击')
        self.panel = True
        # The current Super Lucky Bag uses pink digits in white boxes. Reading
        # the green channel isolates the digits; old offsets read the prize name.
        # A live video can display its own clock behind the sheet. Only the
        # timer immediately attached to the draw label can end our room lock.
        labelled = re.search(r'(\d{1,2}[:：][0-5]\d)后开奖', text)
        seconds = parse_countdown(labelled[1]) if labelled else None
        for top in (1255, 1305):
            if seconds is not None:
                break
            timer = picture.crop((771, top, 923, top+70)).resize((608, 280))
            timer = timer.getchannel('G').point(lambda value: 255 if value > 160 else 0)
            raw = self.ocr(timer, digits=True).replace(' ', '')
            if re.fullmatch(r'\d{4}', raw):
                raw = raw[:2] + ':' + raw[2:]
            seconds = parse_countdown(raw)
        return text, seconds

    @staticmethod
    def joined(text):
        if any(word in text for word in ('参与成功', '等待开奖', '还需看播', '已参与抽奖')):
            return True
        tasks = re.search(r'福袋任务[（(]?(\d+)/(\d+)[)）]?', text)
        return bool(tasks and int(tasks[2]) > 0 and tasks[1] == tasks[2]
                    and '未达成' not in text[tasks.start():])

    @staticmethod
    def allowed(text, allow_comments=False):
        text = re.sub(r'(?:同意协议并)?加入[^，。]{0,45}?已达成', '', text)
        if not allow_comments and '评论' in text:
            return False
        return not any(word in text for word in
                       ('粉丝团', '钻石', '送礼', '支付', '开通', '购买', '下单', '关注主播', '加入'))

    @staticmethod
    def find_bag(picture):
        with Image.open(Path(__file__).parent / 'target_pic/bag_icon_current.png') as reference:
            for offset in (0, 126, 252, 378):
                crop = picture.crop((33+offset, 350, 128+offset, 420))
                pixels = list(crop.getdata())
                purple = sum(r > g*1.15 and b > g*1.15 and b > r*.7 for r, g, b in pixels) / len(pixels)
                difference = ImageChops.difference(reference.convert('RGB'), crop)
                if purple > .20 and sum(ImageStat.Stat(difference).rms) / 3 < 70:
                    return 70 + offset
        return None

    @staticmethod
    def has_bag(picture):
        return PlannedRuntime.find_bag(picture) is not None

    def wait_for_bag(self):
        until = time.monotonic() + 12
        while True:
            picture = self.screen()
            position = self.find_bag(picture)
            if position is not None or time.monotonic() >= until:
                return picture, position
            time.sleep(2)

    def inspect(self):
        picture, position = self.wait_for_bag()
        room = self.room_name(picture)
        # Match the purple bag shape in any of the four top-row slots; the
        # coupon may precede it. Do not use a fixed first-icon coordinate.
        if position is None:
            print(f'筛选 {room}: 未确认福袋图标', flush=True)
            return None
        picture, text, seconds = self.open_bag(position)
        self.panel_room = room
        if self.joined(text):
            self.lock.acquire(room, time.time() + (seconds or 900))
            self.watch()
            return None
        if seconds is None or not self.allowed(text, self.allow_comments):
            picture.save('logs/last-skipped-panel.png')
            print(f'筛选 {room}: 剩余秒数={seconds}，条件可执行={self.allowed(text, self.allow_comments)}，跳过', flush=True)
            self.close_panel()
            return None
        candidate = Candidate(room, self.index, time.time() + seconds)
        print(f'筛选 {room}: {seconds} 秒后开奖', flush=True)
        return candidate

    def open_bag(self, position, y=403):
        self.click(position, y)
        until = time.monotonic() + 8
        while True:
            time.sleep(0.5)
            picture = self.screen()
            try:
                text, seconds = self.details(picture)
                complete = seconds is not None and (
                    self.joined(text)
                    or not self.allowed(text, self.allow_comments)
                    or self.participation_button(picture) is not None)
                if complete:
                    return picture, text, seconds
            except ManualActionRequired:
                raise
            except RuntimeError:
                if time.monotonic() >= until:
                    raise
                continue
            if time.monotonic() >= until:
                picture.save('logs/incomplete-lottery-panel.png')
                raise RuntimeError('福袋弹层尚未完整展开，暂停操作，避免遗漏评论按钮')

    def participation_button(self, picture):
        button = re.sub(r'\s+', '', self.ocr(picture.crop((260, 2030, 840, 2165))))
        permitted = ('参与抽奖', '立即参与', '开始观看')
        if self.allow_comments:
            permitted += ('一键发表评论', '一键友表评论')
        return button if button in permitted else None

    def join(self, candidate):
        # Re-read the room and countdown after travelling; old observations
        # never authorize a tap in a different room or a later draw.
        picture = self.screen()
        verified_panel = getattr(self, 'panel', False) and getattr(self, 'panel_room', None) == candidate.room
        if not verified_panel and self.room_name(picture, candidate.room) != candidate.room:
            raise RuntimeError('返回后直播间身份不一致，停止参与')
        text, seconds = self.details(picture)
        if seconds is None or seconds < 15 or not self.allowed(text, self.allow_comments):
            self.close_panel()
            return False
        if abs(time.time() + seconds - candidate.deadline) > 15:
            self.close_panel()
            return False
        button = self.participation_button(picture)
        if button is None:
            print('没有确认免费参与按钮，跳过', flush=True)
            self.close_panel()
            return False
        # Persist BEFORE tapping: even a crash or ambiguous response must not
        # permit the next process to switch away from a possibly joined draw.
        self.lock.acquire(candidate.room, time.time() + seconds)
        print(f'已确认按钮“{button}”，点击一次并核实参与状态', flush=True)
        self.click(540, 2095)
        time.sleep(2)
        after = self.screen()
        try:
            text, _ = self.details(after)
        except ManualActionRequired:
            raise
        except RuntimeError:
            # Successful one-key comments dismiss the sheet automatically.
            # Reopen the bag to verify tasks; never click the comment twice.
            position = self.find_bag(after)
            if position is None:
                raise ManualActionRequired('评论已点击，暂无法核实参与状态；锁定直播间')
            _, text, _ = self.open_bag(position, 430)
        if not self.joined(text):
            raise ManualActionRequired('参与结果未确认，已锁定直播间；请手动确认，勿切换')
        print(f'已参与 {candidate.room}，等待倒计时结束后继续抽奖', flush=True)
        self.watch()
        return True

    def watch(self):
        deadline = self.lock.state['deadline']
        while True:
            self.live()
            remaining = deadline - time.time()
            if remaining <= 0:
                self.lock.release('本轮已结束')
                print('开奖倒计时已结束，不检查中奖结果，继续下一轮', flush=True)
                self.panel = True
                self.close_panel()
                return
            picture = self.screen()
            try:
                observed_room = self.room_name(picture)
            except RuntimeError:
                # A modal may hide the underlying title. Stay locked and read
                # its result; absence of a title must never cause navigation.
                observed_room = None
            if observed_room is not None and observed_room != self.lock.state['room']:
                raise ManualActionRequired('蹲守期间直播间变化，停止所有自动操作')
            time.sleep(min(15, remaining))

    def wait_for_resume(self):
        while True:
            time.sleep(5)
            try:
                if self.lock.state is None or time.time() >= self.lock.state['deadline']:
                    try:
                        self.followed_rooms()
                    except RuntimeError:
                        if self.lock.state is not None or not getattr(self, 'rooms', None):
                            continue
                        picture = self.screen()
                        if self.room_name(picture) not in self.rooms:
                            continue
                        text = re.sub(r'\s+', '', self.ocr(picture))
                        if '说点什么' not in text or any(word in text for word in
                                ('验证', '开始检测', '形状相同')):
                            continue
                        self.return_to_followed()
                    if self.lock.state is not None:
                        self.lock.release('本轮已结束')
                    self.panel = False
                    print('已确认关注页面，继续筛选关注主播', flush=True)
                    return
                picture = self.screen()
                room = self.room_name(picture)
                text = re.sub(r'\s+', '', self.ocr(picture))
                if '说点什么' not in text or any(word in text for word in
                        ('验证码', '完成验证', '拖动滑块', '开始检测', '形状相同', '安全验证')):
                    continue
                if self.lock.state is not None:
                    if time.time() >= self.lock.state['deadline']:
                        self.lock.release('本轮已结束')
                    elif room != self.lock.state['room']:
                        continue
                self.panel = False
                print('已恢复普通直播页面，继续自动抽奖', flush=True)
                return
            except RECOVERABLE_ERRORS:
                continue

    def run(self):
        while True:
            try:
                self._run()
            except RECOVERABLE_ERRORS as exc:
                print(f'已暂停，脚本保持运行：{exc}；未参与时请回关注页，未开奖时请回原直播间', flush=True)
                self.wait_for_resume()

    def _run(self):
        self.a.device_id = self.serial
        self.a.resolution_ratio_x, self.a.resolution_ratio_y = self.op.get_device_resolution(self.serial)
        if self.lock.state is not None:
            # Resume waiting if the persisted draw has not finished yet.
            self.watch()
            self.return_to_followed()
        self.rooms = list(self.followed_rooms())
        print(f'仅筛选关注列表当前 {len(self.rooms)} 个直播间，180 秒内开奖优先参与，已开启评论={self.allow_comments}', flush=True)
        while True:
            self.scan_cycle()
            time.sleep(2)

    def scan_cycle(self):
        candidates = []
        for count in range(len(self.rooms)):
            if not self.enter(count):
                return
            candidate = self.inspect()
            if candidate:
                remaining = candidate.deadline - time.time()
                if 15 < remaining <= 120:
                    print('两分钟内开奖，优先参与并蹲守', flush=True)
                    self.join(candidate)
                    self.close_panel()
                    return
                if 120 < remaining <= 180:
                    candidates.append(candidate)
            self.close_panel()
        best = choose_room(candidates, self.index, time.time())
        if best is None or not self.enter(best.index):
            return
        refreshed = self.inspect()
        if (refreshed is not None and refreshed.room == best.room
                and abs(refreshed.deadline - best.deadline) <= 15
                and 15 < refreshed.deadline - time.time() <= 180):
            print('已比较关注直播间，参与剩余时间最短的可执行福袋', flush=True)
            self.join(refreshed)
        self.close_panel()
