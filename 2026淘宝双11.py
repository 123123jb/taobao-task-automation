"""2026 淘宝双11 淘金币活动自动化（「淘金币双11狂享20亿」赛车版活动页）

为什么不是 618 脚本的改名字版本
------------------------------
2026 双11 的淘金币活动页换了整套界面，和 2026淘宝618活动.py 里的
「做任务赚体力 / 跳一跳拿钱」对不上：
  * 任务是「做任务赚能量」面板，任务是「去完成 / 浏览N秒 +能量」；
  * 能量拿去「升级赛车拿钱」换抵金；
  * 另有独立的「赚金币」入口。
所以这里按当前真实页面重写，流程：

    淘宝首页 -> 领淘金币 -> 淘金币双11活动页 -> 赚能量
      -> 做任务赚能量面板 -> 逐个任务（去完成 -> 浏览够时长 -> 返回）
      -> 领累计奖励 -> 升级赛车拿钱

实现要点
--------
1. 优先解析无障碍树并按坐标点击，避免 WebView 元素查询结果互相矛盾。
2. 界面树只剩外壳时，使用可选的本机 OCR 核对赛车标签、余额及黄色按钮；
   识别失败时有限重连读取服务，不反复重启淘宝。
3. 默认跳过跨应用任务；显式传入 --allow-app-jumps 后处理已安装的目标应用。

运行
----
    python 2026淘宝双11.py                # 做能量任务 + 升级赛车
    python 2026淘宝双11.py --max-tasks 5   # 只做 5 个任务（调试）
    python 2026淘宝双11.py --skip-race     # 不做赛车
    python 2026淘宝双11.py --open-only     # 只打开活动页面，不点任务

前置：adb 可用、手机已连接并登录淘宝。
"""
import argparse
import io
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import uiautomator2 as u2

TB_APP = "com.taobao.taobao"
COIN_DESC = "领淘金币"
COIN_PAGE_TXT = "淘金币首页"
PANEL_TITLE = "做任务赚能量"
ENERGY_RID = "energy_task_button"
RACE_TXT = "升级赛车拿钱"
OPLUS_PKG = "com.oplus.securitypermission"

# 这些任务不做：拉人助力、要真下单/充值的、积分换能量、小游戏（会跳出活动页还拿不到计数）
SKIP_KEYWORDS = [
    "邀请好友", "拉1人", "拉好友", "助力", "邀请",      # 拉人
    "积分换", "积分兑", "兑换能量",                      # 积分换能量
    "游戏", "小游戏",                                    # 小游戏
    "充值", "开通", "办卡", "下单", "购买",              # 要花钱的
    "预约", "订阅", "答题", "考试",                      # 需要额外确认或专门处理
]
# 只选择本次打开，不自动授予 30 天跨应用跳转权限。
JUMP_ALLOW_LABELS = ["仅本次允许", "打开", "允许"]
ALLOW_APP_JUMPS = False
BLOCKED_APPS = set()

# 任务名里出现这些字眼就是往对应 App 跳；手机没装就别浪费时间去点
APP_PACKAGES = {
    "蚂蚁庄园": "com.eg.android.AlipayGphone",
    "百度": "com.baidu.searchbox",
    "闲鱼": "com.taobao.idlefish",
    "支付宝": "com.eg.android.AlipayGphone",
    "微博": "com.sina.weibo",
    "京东": "com.jingdong.app.mall",
    "拼多多": "com.xunmeng.pinduoduo",
    "抖音": "com.ss.android.ugc.aweme",
    "快手": "com.smile.gifmaker",
    "美团": "com.sankuai.meituan",
    "饿了么": "me.ele",
    "高德": "com.autonavi.minimap",
}
SEARCH_KEYS = ["iphone16", "macbook", "airpods", "nike", "switch", "kindle"]  # 用英文，adb 输入中文需要额外输入法

RESTARTS = 0
MAX_RESTARTS = 3
RUN_REPORT = {}
LOG_FILE = None


def log(*args):
    message = f"[{time.strftime('%H:%M:%S')}] " + " ".join(map(str, args))
    print(message, flush=True)
    if LOG_FILE is not None:
        LOG_FILE.write(message + "\n")
        LOG_FILE.flush()


# ---------------------------------------------------------------- 无障碍树工具

def visual_coin_xml(d):
    """仅为空壳活动页补读截图，确认标签、余额及黄色按钮后才提供坐标。"""
    executable = shutil.which("tesseract")
    if not executable or current_app(d)[0] != TB_APP:
        return None
    screenshot = d.screenshot().convert("RGB")
    w, h = screenshot.size
    yellow_rows = []
    for y in range(int(h*.25), int(h*.55), 4):
        row = [screenshot.getpixel((x, y)) for x in range(int(w*.25), int(w*.75), 16)]
        if sum(r > 180 and g > 140 and b < 130 for r, g, b in row) > len(row)*.6:
            yellow_rows.append(y)
    bands = []
    for y in yellow_rows:
        if not bands or y-bands[-1][-1] > h*.025:
            bands.append([])
        bands[-1].append(y)
    bands = [b for b in bands if h*.03 < b[-1]-b[0] < h*.12]
    if not bands:
        return None
    band = max(bands, key=len)
    bounds = (int(w*.19), max(0, band[0]-4), int(w*.81), min(h, band[-1]+5))
    crop = screenshot.crop(bounds)
    sampled = crop.resize((50, 20))
    pixels = [sampled.getpixel((x, y)) for x in range(50) for y in range(20)]
    if sum(r > 180 and g > 140 and b < 130 for r, g, b in pixels) < len(pixels)*.5:
        return None

    def read(region):
        buffer = io.BytesIO()
        region.save(buffer, format="PNG")
        result = subprocess.run([executable, "stdin", "stdout", "-l", "chi_sim+eng", "--psm", "6"],
                                input=buffer.getvalue(), capture_output=True, timeout=6,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return re.sub(r"\s+", "", result.stdout.decode("utf-8")) if result.returncode == 0 else ""

    try:
        text = read(crop)
        energy = re.search(r"剩余(\d+)能量", text)
        if RACE_TXT not in text or not energy:
            return None
        root = ET.Element("hierarchy")
        ET.SubElement(root, "node", text=COIN_PAGE_TXT)
        ET.SubElement(root, "node", text=f"{RACE_TXT} 剩余 {energy.group(1)} 能量",
                      bounds=f"[{bounds[0]},{bounds[1]}][{bounds[2]},{bounds[3]}]", clickable="true")
        side = (int(w*.83), bounds[1], w, bounds[3])
        if "赚能量" in read(screenshot.crop(side)):
            ET.SubElement(root, "node", text="赚能量", **{"resource-id": ENERGY_RID},
                          bounds=f"[{side[0]},{side[1]}][{side[2]},{side[3]}]", clickable="true")
        RUN_REPORT["visual_reads"] = RUN_REPORT.get("visual_reads", 0) + 1
        return ET.tostring(root, encoding="unicode")
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        log(f"截图备用识别失败：{exc}")
        return None


def dump_xml(d, retries=3):
    xml = ""
    for _ in range(retries):
        try:
            xml = d.dump_hierarchy(compressed=False) or ""
        except Exception as e:
            log(f"  取界面失败: {e}")
            xml = ""
        shell_only = COIN_PAGE_TXT in xml and xml.count("<node ") < 120 and not on_coin_page(xml)
        if shell_only:
            visual = visual_coin_xml(d)
            if visual:
                return visual
        if shell_only and RUN_REPORT.get("tree_resets", 0) < 2:
            RUN_REPORT["tree_resets"] = RUN_REPORT.get("tree_resets", 0) + 1
            log("活动页只返回外壳，重连界面读取服务，不重启淘宝")
            d.stop_uiautomator()
            d.start_uiautomator()
            time.sleep(0.3)
            continue
        if xml.count("<node ") >= 15:
            return xml
        time.sleep(1.0)
    if not xml.strip():
        raise RuntimeError("无法读取手机界面，请检查 USB 连接、调试授权和手机解锁状态")
    return xml


def find_nodes(root, text=None, contains=None, rid=None, cls=None, desc=None, clickable=None):
    out = []
    for n in root.findall(".//node"):
        if text is not None and n.get("text") != text:
            continue
        if contains is not None and contains not in (n.get("text") or ""):
            continue
        if rid is not None and (n.get("resource-id") or "").split("/")[-1] != rid:
            continue
        if cls is not None and not (n.get("class") or "").endswith(cls):
            continue
        if desc is not None and n.get("content-desc") != desc:
            continue
        if clickable is not None and n.get("clickable") != clickable:
            continue
        out.append(n)
    return out


def parse_bounds(node):
    m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", node.get("bounds") or "")
    return tuple(int(v) for v in m.groups()) if m else None


def parent_map(root):
    pm = {}
    for p in root.iter():
        for c in p:
            pm[c] = p
    return pm


def center(node):
    b = parse_bounds(node)
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) if b else None


def tap_node(d, node, jitter=0):
    c = center(node)
    if not c:
        return False
    d.click(c[0] + random.randint(-jitter, jitter), c[1] + random.randint(-jitter, jitter))
    return True


def current_app(d):
    out = d.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'").output or ""
    m = re.search(r"(?:mCurrentFocus|mFocusedApp)=.*?\bu\d+\s+([\w.]+)/([\w.$]+)", out)
    return (m.group(1), m.group(2)) if m else (None, None)


def swipe_in_app(d, x1, y1, x2, y2, duration, allowed=(TB_APP,)):
    if current_app(d)[0] not in allowed:
        return False
    try:
        d.swipe(x1, y1, x2, y2, duration)
    except Exception as exc:
        if "INJECT_EVENTS" not in str(exc):
            raise
        time.sleep(0.3)
        if current_app(d)[0] not in allowed:
            return False
        log("页面切换导致手势注入失败，改用已授权的 ADB input")
        result = d.shell(["input", "swipe", str(x1), str(y1), str(x2), str(y2), str(int(duration*1000))])
        if result.exit_code != 0:
            raise RuntimeError(f"ADB 手势失败：{result.output}")
    return True


def start_taobao(d):
    log("  拉起淘宝")
    d.shell(f"am start -n {TB_APP}/com.taobao.tao.welcome.Welcome")
    time.sleep(2)


def jump_dialog_shown(d):
    """是不是弹了「淘宝想要打开 XX」这类系统确认框"""
    pkg, _ = current_app(d)
    return pkg == OPLUS_PKG


def allow_jump(d):
    """允许本次跨 App 打开，不修改长期授权。"""
    xml = dump_xml(d, retries=2)
    root = ET.fromstring(xml)
    for label in JUMP_ALLOW_LABELS:
        for node in find_nodes(root, text=label):
            if tap_node(d, node):
                log(f"  允许跳转: {label}")
                time.sleep(3)
                return True
    log("  确认框里没找到允许按钮")
    return False


def jump_out(d, dwell=12):
    """在已登录的目标 App 浏览，再保留淘宝进程返回活动。"""
    pkg, activity = current_app(d)
    if "login" in (activity or "").lower():
        BLOCKED_APPS.add(pkg)
        log(f"跨 App 任务暂停：{pkg} 需要先登录")
        return False
    if pkg not in {TB_APP, OPLUS_PKG, *APP_PACKAGES.values()}:
        log(f"停止跨 App 浏览：当前前台是 {pkg}")
        return False
    if jump_dialog_shown(d):
        allow_jump(d)
    w, h = d.window_size()
    start = time.time()
    browsed = False
    while time.time() - start < dwell:
        pkg, activity = current_app(d)
        if "login" in (activity or "").lower():
            BLOCKED_APPS.add(pkg)
            log(f"跨 App 任务暂停：{pkg} 需要先登录")
            return False
        if pkg in APP_PACKAGES.values():
            browsed = True
            if not swipe_in_app(d, w // 2, int(h * 0.75), w // 2, int(h * 0.35), 0.4,
                                allowed=tuple(APP_PACKAGES.values())):
                return False
            time.sleep(random.uniform(1.5, 2.5))
        else:
            if pkg != TB_APP:
                return False
            time.sleep(1.5)
    if browsed:
        log(f"  在对方 App 里逛了 {dwell} 秒")
    # 先保留淘宝进程返回，避免每次跨应用都重新加载整个活动。
    start_taobao(d)
    return back_to_panel(d)


# 跨 App 任务在淘宝里先落一个中间页，页面上有「打开XXApp」这类按钮
OPEN_APP_LABELS = ["打开百度App", "打开App", "打开应用", "立即打开", "去打开", "打开看看", "去赚能量"]

_INSTALLED_CACHE = {}


def app_installed(d, pkg):
    if pkg not in _INSTALLED_CACHE:
        out = d.shell(f"pm list packages {pkg}").output or ""
        _INSTALLED_CACHE[pkg] = pkg in out
    return _INSTALLED_CACHE[pkg]


def missing_app(d, task_name):
    """任务要跳的 App 手机里没装：返回那个 App 的名字，否则返回空串"""
    for label, pkg in APP_PACKAGES.items():
        if label in task_name and not app_installed(d, pkg):
            return label
    return ""


def wait_jump(d, timeout=12):
    """点完去完成之后，等跨 App 的中间页/系统确认框出现；返回 dialog / app / ''"""
    end = time.time() + timeout
    while time.time() < end:
        if jump_dialog_shown(d):
            return "dialog"
        pkg, _ = current_app(d)
        if pkg and pkg != TB_APP:
            return "app" if pkg in APP_PACKAGES.values() else "unexpected"
        xml = dump_xml(d, retries=1)
        root = ET.fromstring(xml)
        for label in OPEN_APP_LABELS:
            found = find_nodes(root, text=label, cls="Button") or find_nodes(root, text=label)
            if found and tap_node(d, found[0]):
                log(f"  点任务页里的「{label}」")
                time.sleep(3)
                break
        time.sleep(1)
    return ""


def tap_skip(d, xml=None):
    """关掉视频广告的「跳过」和「我知道了 / 以后再说」"""
    xml = xml if xml is not None else dump_xml(d, retries=1)
    root = ET.fromstring(xml)
    for node in (find_nodes(root, text="跳过") + find_nodes(root, text="我知道了")
                 + find_nodes(root, desc="关闭按钮")):
        if tap_node(d, node):
            log(f"  关闭弹窗: {node.get('text') or node.get('content-desc')}")
            time.sleep(2)
            return True
    return False


# 活动里会不定时冒出来的浮层（尾翼/车轮解锁、升级提示等）
MODAL_LABELS = ["确认选择", "我知道了", "以后再说", "暂不"]


def handle_modals(d, xml=None):
    """处理挡在页面上的浮层；返回是否点掉了什么"""
    xml = xml if xml is not None else dump_xml(d, retries=1)
    root = ET.fromstring(xml)
    pm = parent_map(root)
    if find_nodes(root, text="送你能量最高"):
        close = find_nodes(root, text="关闭", cls="Button")
        if close and tap_node(d, close[-1]):
            log("关闭挡住活动页的能量推荐弹窗")
            time.sleep(0.5)
            return True
    for label in MODAL_LABELS:
        for node in find_nodes(root, text=label):
            parent = pm.get(node)
            target = parent if parent is not None and parent.get("clickable") == "true" else node
            if tap_node(d, target):
                log(f"  处理浮层: {label}")
                time.sleep(2.5)
                return True
    return False


def close_ad(d, xml=None):
    """点掉视频广告的「跳过」（可点的是它的父节点，不是文字节点本身）"""
    xml = xml if xml is not None else dump_xml(d, retries=1)
    root = ET.fromstring(xml)
    pm = {}
    for p in root.iter():
        for c in p:
            pm[c] = p
    for node in find_nodes(root, text="跳过"):
        target = node
        parent = pm.get(node)
        if parent is not None and parent.get("clickable") == "true":
            target = parent
        if tap_node(d, target):
            log("  关闭视频广告")
            time.sleep(2)
            return True
    return False


def on_coin_page(xml):
    return RACE_TXT in xml and (("赚金币" in xml and "赚能量" in xml) or
                               (COIN_PAGE_TXT in xml and bool(re.search(r"剩余\s*\d+\s*能量", xml))))


def mute(d, xml=None):
    """关掉活动页音效（按钮文案是「关闭音效」，关掉后会变成「开启音效」）"""
    xml = xml if xml is not None else dump_xml(d, retries=1)
    root = ET.fromstring(xml)
    for node in find_nodes(root, text="关闭音效"):
        if tap_node(d, node):
            log("已关闭活动页音效")
            time.sleep(2)
            return True
    return False


def mute_panel(d, xml=None):
    """任务面板里还有一个独立的「音效」开关，按滑块位置判断开关状态"""
    xml = xml if xml is not None else dump_xml(d, retries=1)
    if "音效" not in xml:
        return False
    root = ET.fromstring(xml)
    pm = parent_map(root)
    for label in find_nodes(root, text="音效"):
        wrapper = pm.get(label)
        if wrapper is None:
            continue
        for switch in wrapper.iter():
            if switch is label or switch.get("clickable") != "true":
                continue
            sb = parse_bounds(switch)
            if not sb:
                continue
            knob = next((c for c in switch.iter()
                         if (c.get("class") or "").endswith("TextView") and c is not label), None)
            kb = parse_bounds(knob) if knob is not None else None
            # 滑块中心在开关中心偏右 = 开着
            on = True if kb is None else ((kb[0] + kb[2]) / 2) > ((sb[0] + sb[2]) / 2 + 5)
            if not on:
                return False
            d.click((sb[0] + sb[2]) // 2, (sb[1] + sb[3]) // 2)
            log("已关闭任务面板音效")
            time.sleep(2)
            return True
    return False


def restart_app(d, why=""):
    global RESTARTS
    if RESTARTS >= MAX_RESTARTS:
        log("重启次数已达上限")
        return False
    RESTARTS += 1
    log(f"重启淘宝（第 {RESTARTS} 次，原因：{why}）")
    d.shell(f"am force-stop {TB_APP}")
    time.sleep(2)
    start_taobao(d)
    return True


# ---------------------------------------------------------------- 页面跳转

def open_coin_page(d):
    for attempt in range(6):
        xml = dump_xml(d)
        if handle_modals(d, xml):
            continue
        if on_coin_page(xml):
            log("已在淘金币活动页")
            mute(d, xml)
            return True
        root = ET.fromstring(xml)
        if tap_skip(d, xml):
            continue
        entries = find_nodes(root, desc=COIN_DESC)
        if entries:
            clickable = [n for n in entries if n.get("clickable") == "true"] or entries
            log("点击「领淘金币」入口")
            tap_node(d, clickable[0])
            time.sleep(3)
            # WebView 首次加载较慢；等到活动按钮出现，再判断是否需要返回。
            for _ in range(12):
                loading_xml = dump_xml(d, retries=1)
                if on_coin_page(loading_xml):
                    log("已进入淘金币活动页")
                    mute(d, loading_xml)
                    return True
                tap_skip(d, loading_xml)
                time.sleep(2)
            continue
        if COIN_PAGE_TXT in xml or "赚能量" in xml:
            log("  等待活动页按钮加载")
            time.sleep(1)
            continue
        pkg, _ = current_app(d)
        if pkg != TB_APP:
            start_taobao(d)
        else:
            log(f"  返回首页找入口（第 {attempt + 1} 次）")
            d.press("back")
            time.sleep(1.5)
    return on_coin_page(dump_xml(d))


def open_energy_panel(d):
    for attempt in range(8):
        xml = dump_xml(d)
        root = ET.fromstring(xml)
        if handle_modals(d, xml):
            continue
        if task_panel(root) is not None:
            mute_panel(d, xml)
            return True
        if current_app(d)[0] != TB_APP:
            start_taobao(d)
            continue
        btns = find_nodes(root, rid=ENERGY_RID) or find_nodes(root, text="赚能量")
        if btns:
            if attempt in (0, 4):
                log("点击「赚能量」")
                tap_node(d, btns[0])
            time.sleep(0.6)
            continue
        if close_ad(d, xml):
            continue
        if not open_coin_page(d):
            return False
    log("任务面板未就绪，保留当前页面")
    return False


def task_panel(root):
    """定位真正的任务面板，排除同一 WebView 内被遮住的底层内容。"""
    pm = parent_map(root)
    for title in reversed(find_nodes(root, text=PANEL_TITLE)):
        panel = title
        while panel is not None and panel.get("class") != "android.webkit.WebView":
            if find_nodes(panel, text="累计任务奖励"):
                return panel
            panel = pm.get(panel)
    return None


def panel_rows(d, xml=None):
    """解析面板里的任务行：每行 = 可点 View[图标, 任务名, 去完成按钮]"""
    xml = xml if xml is not None else dump_xml(d)
    if PANEL_TITLE not in xml:
        return []
    root = ET.fromstring(xml)
    panel = task_panel(root)
    if panel is None:
        return []
    pm = parent_map(panel)
    pb = parse_bounds(panel)
    rows = []
    for btn in find_nodes(panel, text="去完成", cls="Button"):
        b = parse_bounds(btn)
        if btn.get("visible-to-user") == "false" or not b:
            continue
        if pb and not (pb[0] <= (b[0]+b[2])/2 <= pb[2] and pb[1] <= (b[1]+b[3])/2 < pb[3]):
            continue
        p = pm.get(btn)
        texts = [(t.get("text") or "").strip() for t in p.iter()
                 if (t.get("class") or "").endswith("TextView") and (t.get("text") or "").strip()] if p is not None else []
        rows.append({"name": max(texts, key=len) if texts else "", "node": btn})
    return rows


def panel_progress(xml):
    panel = task_panel(ET.fromstring(xml))
    if panel is not None:
        for node in panel.iter():
            m = re.fullmatch(r"\s*(\d+)\s*/\s*50\s*", node.get("text") or "")
            if m:
                return int(m.group(1))
    return None


def click_task(d, key):
    if current_app(d)[0] != TB_APP:
        return False
    rows = panel_rows(d)
    row = next((r for r in rows if task_key(r["name"]) == key), None)
    return bool(row and tap_node(d, row["node"]))


def check_task_progress(d, key, before, cumulative_before):
    current = None
    for attempt in range(3):
        xml = dump_xml(d, retries=1)
        row = next((r for r in panel_rows(d, xml) if task_key(r["name"]) == key), None)
        current = progress_of(row["name"])[0] if row else None
        cumulative = panel_progress(xml)
        if cumulative_before is not None and cumulative is not None:
            if cumulative > cumulative_before:
                return True, current if current is not None and current > before else None
        elif current is not None and current > before:
            return True, current
        if attempt < 2:
            time.sleep(0.7)
    return False, current


def close_panel(d):
    xml = dump_xml(d, retries=1)
    if PANEL_TITLE not in xml:
        return False
    root = ET.fromstring(xml)
    for node in find_nodes(root, text="关闭", cls="Button"):
        tap_node(d, node)
        log("关闭任务面板")
        time.sleep(3)
        return True
    return False


def ensure_rows(d):
    """优先复用当前面板；有限恢复失败后保留现场，不循环重启。"""
    for attempt in range(3):
        xml = dump_xml(d)
        rows = panel_rows(d, xml)
        if rows:
            return rows
        if handle_modals(d, xml):
            continue
        if task_panel(ET.fromstring(xml)) is not None:
            return []
        if on_coin_page(xml):
            open_energy_panel(d)
            continue
        if back_to_panel(d):
            continue
    log("无法恢复任务面板，停止本轮，避免反复重启")
    return []


# ---------------------------------------------------------------- 做任务

def progress_of(name):
    m = re.search(r"[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def task_key(name):
    return re.split(r"[（(]\s*\d+\s*/\s*\d+\s*[）)]", name, maxsplit=1)[0].strip()


def dwell_seconds(task_name):
    """解析秒/s 文案，增加 2 秒余量，未标时长时停留 17 秒。"""
    m = re.search(r"(\d+)\s*(?:秒|s\b|s(?=得))", task_name, re.I)
    return int(m.group(1)) + 2 if m else 17


def browse(d, task_name):
    """任务页停留够时长；搜索类任务先搜索再逛"""
    duration = dwell_seconds(task_name)
    if current_app(d)[0] != TB_APP:
        log("浏览暂停：前台已离开淘宝")
        return False
    xml = dump_xml(d, retries=2)
    if task_panel(ET.fromstring(xml)) is not None:
        time.sleep(0.8)
        xml = dump_xml(d, retries=1)
        if task_panel(ET.fromstring(xml)) is not None:
            log("任务页未打开，不在任务面板内执行浏览手势")
            return False
    root = ET.fromstring(xml)
    edits = find_nodes(root, cls="EditText")
    if edits and "搜一搜" in task_name:
        keyword = random.choice(SEARCH_KEYS)
        log(f"  搜索：{keyword}")
        tap_node(d, edits[0])
        time.sleep(1.2)
        # 搜索词只用英文，走系统 input 通道，不安装或切换输入法。
        d.shell(["input", "text", keyword])
        time.sleep(1.5)
        root = ET.fromstring(dump_xml(d, retries=1))
        buttons = find_nodes(root, text="搜索", clickable="true") or find_nodes(root, desc="搜索")
        if buttons:
            tap_node(d, buttons[0])
        else:
            d.shell(["input", "keyevent", "66"])
        time.sleep(4)
        xml = dump_xml(d, retries=1)

    if "验证" in xml and any(label in xml for label in ("滑块", "滑动", "拖动")):
        reason = "搜索触发人工验证，停止浏览手势"
        RUN_REPORT.setdefault("skipped", {})[task_key(task_name)] = reason
        log(reason)
        return False

    w, h = d.window_size()
    start = time.monotonic()
    while time.monotonic() - start < duration:
        if current_app(d)[0] != TB_APP:
            log("停止手势：前台已离开淘宝")
            return False
        if not swipe_in_app(d, w // 2, int(h * 0.72), w // 2, int(h * 0.46), 0.4):
            return False
        time.sleep(2.5)
    return True


def back_to_panel(d):
    """按返回键回到任务面板，最多 5 次"""
    for _ in range(4):
        pkg, _ = current_app(d)
        if pkg != TB_APP:
            log(f"前台离开淘宝（{pkg}），仅拉回淘宝，不在外部页面执行手势")
            start_taobao(d)
            continue
        xml = dump_xml(d, retries=2)
        if task_panel(ET.fromstring(xml)) is not None:
            return True
        if on_coin_page(xml):
            return open_energy_panel(d)
        d.press("back")
        time.sleep(0.7)
    return False


def claim_rewards(d):
    """只领取当前任务面板内 5 / 20 / 50 次的累计奖励。"""
    xml = dump_xml(d, retries=1)
    if PANEL_TITLE not in xml:
        return
    root = ET.fromstring(xml)
    panel = task_panel(root)
    if panel is None:
        return
    for node in find_nodes(panel, contains="领取", cls="Button"):
        text = node.get("text") or ""
        if "已领取" in text:
            continue
        log(f"  领取累计奖励：{text}")
        tap_node(d, node)
        time.sleep(3)
        tap_skip(d)


def pick_task(d, rows, failed, logged_missing, attempted):
    """从面板里挑一条能做的任务（按 跳过规则 / 进度 / 是否计上 过滤）"""
    for row in rows:
        name = row["name"]
        key = task_key(name)
        if any(k in name for k in SKIP_KEYWORDS):
            RUN_REPORT.setdefault("skipped", {})[key] = "邀请/付费/预约/答题等需单独处理的任务"
            continue
        if not ALLOW_APP_JUMPS and any(k in name for k in APP_PACKAGES):
            RUN_REPORT.setdefault("skipped", {})[key] = "跨 App 任务默认关闭"
            continue
        if any(k in name and pkg in BLOCKED_APPS for k, pkg in APP_PACKAGES.items()):
            RUN_REPORT.setdefault("skipped", {})[key] = "目标 App 需要先登录"
            continue
        cur, total = progress_of(name)
        if total and cur >= total:
            continue
        if failed.get(key, 0) >= 2:
            RUN_REPORT.setdefault("skipped", {})[key] = "连续两次未确认记账或点击失败"
            continue
        miss = missing_app(d, name)
        if miss:
            if key not in logged_missing:
                logged_missing.add(key)
                log(f"  跳过「{name[:12]}…」：手机没装 {miss}")
            continue
        if attempted.get(key, 0) >= 15:
            continue
        return row
    return None


def do_tasks(d, max_tasks=0):
    done = 0
    attempted = {}
    failed = {}
    logged_missing = set()
    trials = RUN_REPORT.setdefault("tasks", [])
    while len(trials) < 100:
        if max_tasks and done >= max_tasks:
            log(f"已确认记账 {done} 次，到达 --max-tasks {max_tasks}，停止")
            break
        rows = ensure_rows(d)
        candidate = pick_task(d, rows, failed, logged_missing, attempted)
        if candidate is None:
            for _ in range(8):
                if not scroll_panel(d):
                    break
                rows = panel_rows(d)
                candidate = pick_task(d, rows, failed, logged_missing, attempted)
                if candidate is not None:
                    break
            if candidate is None:
                log("本轮可执行任务已处理完；跳过和未记账原因见运行报告")
                break
        name = candidate["name"]
        key = task_key(name)
        attempted[key] = attempted.get(key, 0) + 1
        before = progress_of(name)[0]
        total = progress_of(name)[1]
        cumulative_before = panel_progress(dump_xml(d, retries=1))
        started = time.monotonic()
        log(f"尝试 {len(trials)+1}：{name}，已确认 {done} 次")
        trial = {"task": key, "before": before, "after": None, "verified": False,
                 "status": "in_progress"}
        trials.append(trial)
        if not click_task(d, key):
            failed[key] = failed.get(key, 0) + 1
            trial.update({"status": "unverified", "reason": "任务行重排或前台变化",
                          "seconds": round(time.monotonic()-started, 1)})
            log("  任务行已重排或前台变化，重新读取")
            continue
        time.sleep(0.8)
        is_external = any(k in name for k in APP_PACKAGES)
        if ALLOW_APP_JUMPS and is_external:
            kind = wait_jump(d, timeout=4)
            browsed = kind in ("dialog", "app") and jump_out(d, dwell=dwell_seconds(name))
        else:
            browsed = browse(d, name)
        returned = back_to_panel(d)
        verified, after = check_task_progress(d, key, before, cumulative_before) if returned else (False, None)
        trial.update({"after": after, "verified": verified, "browsed": bool(browsed),
                      "status": "verified" if verified else "unverified",
                      "seconds": round(time.monotonic()-started, 1)})
        if verified:
            done += 1
            detail = f"{key} {before} → {after}" if after is not None else "累计任务进度已增加，单行重排不用于计数"
            log(f"  已确认记账：{detail}，本轮累计 {done} 次")
            claim_rewards(d)
        else:
            failed[key] = failed.get(key, 0) + 1
            log(f"  未确认记账，不计入完成数（{failed[key]}/2）")
        if not returned:
            RUN_REPORT["stop_reason"] = "任务面板恢复失败"
            log("未能返回任务面板，保留现场并停止")
            break
    RUN_REPORT["verified"] = done
    return done


def scroll_panel(d):
    """面板里上滑，看有没有新任务冒出来"""
    before = {task_key(r["name"]) for r in panel_rows(d)}
    if current_app(d)[0] != TB_APP:
        return False
    w, h = d.window_size()
    if not swipe_in_app(d, w // 2, int(h * 0.82), w // 2, int(h * 0.4), 0.6):
        return False
    time.sleep(0.7)
    after = {task_key(r["name"]) for r in panel_rows(d)}
    return bool(after - before)


# ---------------------------------------------------------------- 升级赛车

def do_race(d, min_energy=20):
    """长按「升级赛车拿钱」把能量换成抵金；每轮会冒出「解锁新车轮/尾翼」浮层"""
    last_energy = None
    stuck = 0
    unreadable = 0
    low_energy_reads = 0
    race = RUN_REPORT.setdefault("race", {"before": None, "after": None, "holds": 0})
    for _ in range(100):
        if current_app(d)[0] != TB_APP:
            race["stop_reason"] = "前台已离开淘宝"
            break
        xml = dump_xml(d)
        if task_panel(ET.fromstring(xml)) is not None:
            close_panel(d)
            continue
        if handle_modals(d, xml):
            continue
        root = ET.fromstring(xml)
        btns = find_nodes(root, contains=RACE_TXT)
        if not btns:
            unreadable += 1
            low_energy_reads = 0
            if unreadable >= 3:
                race["stop_reason"] = "连续三次找不到赛车按钮，未确认能量耗尽"
                log(race["stop_reason"])
                break
            log("赛车按钮暂未出现，等待页面刷新")
            time.sleep(2)
            continue
        text = btns[0].get("text") or ""
        m = re.search(r"剩余\s*(\d+)\s*能量", text)
        energy = int(m.group(1)) if m else -1
        if energy < 0:
            unreadable += 1
            low_energy_reads = 0
            if unreadable >= 3:
                race["stop_reason"] = "连续三次无法读取剩余能量"
                break
            time.sleep(2)
            continue
        unreadable = 0
        if race["before"] is None:
            race["before"] = energy
        race["after"] = energy
        log(f"赛车：剩余 {energy} 能量")
        if energy < min_energy:
            low_energy_reads += 1
            if low_energy_reads >= 2:
                race["stop_reason"] = "能量已用尽或不足一次升级"
                break
            time.sleep(3)
            continue
        low_energy_reads = 0
        if energy == last_energy:
            stuck += 1
            if stuck >= 3:
                race["stop_reason"] = "连续三次长按能量未下降"
                break
        else:
            stuck = 0
        last_energy = energy
        c = center(btns[0])
        if not c:
            break
        d.long_click(c[0], c[1], duration=4)
        race["holds"] += 1
        time.sleep(1.5)


# ---------------------------------------------------------------- 输入法还原

ORIGINAL_IME = ""


def current_ime(d):
    out = d.shell("settings get secure default_input_method").output or ""
    return out.strip()


def remember_ime(d):
    """开跑前记下手机原来的默认输入法（u2 打字时会切到 AdbKeyboard）"""
    global ORIGINAL_IME
    ime = current_ime(d)
    if "com.github.uiautomator" in ime:
        # 已经是 AdbKeyboard 了（比如之前跑过一次没还原）：从已装输入法里推断原来的那个
        others = [x.strip() for x in (d.shell("ime list -s").output or "").splitlines()
                  if x.strip() and "com.github.uiautomator" not in x]
        if len(others) == 1:
            ORIGINAL_IME = others[0]
            log(f"当前是 AdbKeyboard，推断原来的输入法是：{ORIGINAL_IME}")
        else:
            log(f"当前是 AdbKeyboard，可选的输入法有 {len(others)} 个，推断不出原来的，收尾时不动它")
        return
    if not ime or ime.lower() == "null":
        return
    ORIGINAL_IME = ime
    log(f"已记录原输入法：{ime}")


def restore_ime(d):
    """收尾：把默认输入法切回原来的（正常结束、异常、Ctrl+C 都会走到）"""
    if not ORIGINAL_IME:
        return
    now = current_ime(d)
    if now == ORIGINAL_IME:
        log("输入法仍是原来的，无需还原")
        return
    log(f"把输入法从 {now} 切回 {ORIGINAL_IME}")
    d.shell(f"ime set {ORIGINAL_IME}")
    d.shell(f"settings put secure default_input_method {ORIGINAL_IME}")
    time.sleep(1)
    now = current_ime(d)
    log("输入法已切回原样" if now == ORIGINAL_IME else f"输入法切回失败，当前是 {now}")


# ---------------------------------------------------------------- main

def start_run():
    global LOG_FILE, RESTARTS
    RESTARTS = 0
    BLOCKED_APPS.clear()
    RUN_REPORT.clear()
    RUN_REPORT.update({"run_id": time.strftime("%Y%m%d-%H%M%S"), "tasks": [], "skipped": {}})
    folder = Path(__file__).resolve().parent / "logs"
    folder.mkdir(exist_ok=True)
    LOG_FILE = (folder / (RUN_REPORT["run_id"] + ".log")).open("a", encoding="utf-8")


def save_run_report(started):
    global LOG_FILE
    RUN_REPORT["seconds"] = round(time.monotonic() - started, 1)
    RUN_REPORT["restarts"] = RESTARTS
    RUN_REPORT["verified"] = sum(t["verified"] for t in RUN_REPORT.get("tasks", []))
    error = sys.exc_info()[1]
    RUN_REPORT["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else ("error" if error else "finished")
    if error:
        RUN_REPORT["error"] = str(error)
    folder = Path(__file__).resolve().parent
    body = json.dumps(RUN_REPORT, ensure_ascii=False, indent=2)
    (folder / "last-run.json").write_text(body, encoding="utf-8")
    (folder / "logs" / (RUN_REPORT["run_id"] + ".json")).write_text(body, encoding="utf-8")
    log(f"运行汇总：尝试 {len(RUN_REPORT.get('tasks', []))} 次，确认记账 {RUN_REPORT['verified']} 次，"
        f"重启 {RESTARTS} 次，用时 {RUN_REPORT['seconds']} 秒；报告：last-run.json")
    if LOG_FILE is not None:
        LOG_FILE.close()
        LOG_FILE = None


def main():
    global ALLOW_APP_JUMPS
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tasks", type=int, default=0, help="最多做几个任务（0=不限）")
    parser.add_argument("--skip-race", action="store_true", help="不做升级赛车")
    parser.add_argument("--race-only", action="store_true", help="只把能量拿去升级赛车，不做任务")
    parser.add_argument("--open-only", action="store_true", help="只打开活动页，不做任务")
    parser.add_argument("--serial", default="", help="设备序列号")
    parser.add_argument("--allow-app-jumps", action="store_true", help="启用跨 App 任务；默认只处理淘宝内任务")
    args = parser.parse_args()
    if args.max_tasks < 0:
        parser.error("--max-tasks 不能小于 0")
    ALLOW_APP_JUMPS = args.allow_app_jumps
    start_run()
    started = time.monotonic()
    d = None
    try:
        d = u2.connect(args.serial) if args.serial else u2.connect()
        log(f"已连接设备：{d.serial}；按真实进度统计任务")
        remember_ime(d)
        if not open_coin_page(d):
            raise SystemExit("进不去淘金币活动页")
        if args.open_only:
            log("已打开活动页（--open-only）")
            return

        if not args.race_only:
            if not open_energy_panel(d):
                raise SystemExit("打不开「做任务赚能量」面板")
            RUN_REPORT["cumulative_before"] = panel_progress(dump_xml(d, retries=1))
            done = do_tasks(d, max_tasks=args.max_tasks)
            RUN_REPORT["cumulative_after"] = panel_progress(dump_xml(d, retries=1))
            log(f"共确认记账 {done} 次能量任务")
            if RUN_REPORT.get("stop_reason"):
                raise SystemExit("任务尚未处理完，请检查报告和当前页面；未自动进入赛车")
            if not args.skip_race:
                close_panel(d)

        if not args.skip_race:
            do_race(d)

    finally:
        try:
            if d is not None:
                restore_ime(d)
        except Exception as exc:
            log(f"输入法还原未完成，请重新连接手机后核对输入法：{exc}")
        save_run_report(started)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("已停止，已保存本轮报告")
    except Exception as exc:
        log(f"运行停止：{exc}")
        raise SystemExit(1)
