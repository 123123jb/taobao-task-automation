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
1. 元素定位全部用 dump_hierarchy 解析无障碍树 + 按坐标点击。
   本机 uiautomator2 3.5.2 + Android 17 上 `.exists` / `.count` 会给出互相矛盾的
   结果（同一个按钮 exists=False 但 count=3），所以不用它们。
2. 活动页是 WebView，无障碍树偶尔会整片消失（只剩 70 多个壳节点）。检测到这种
   情况就依次尝试：关闭面板重开 -> 重启淘宝 -> 重新进活动页。
3. 跨应用任务（支付宝/小程序）会弹系统确认框，默认跳过，避免跳出淘宝。

运行
----
    python 2026淘宝双11.py                # 做能量任务 + 升级赛车
    python 2026淘宝双11.py --max-tasks 5   # 只做 5 个任务（调试）
    python 2026淘宝双11.py --skip-race     # 不做赛车
    python 2026淘宝双11.py --open-only     # 只打开活动页面，不点任务

前置：adb 可用、手机已连接并登录淘宝。
"""
import argparse
import random
import re
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
# 跨 App 任务的系统确认框按钮，优先点「30天内允许」以后就不再拦
JUMP_ALLOW_LABELS = ["30天内允许", "仅本次允许", "打开", "允许"]

# 任务名里出现这些字眼就是往对应 App 跳；手机没装就别浪费时间去点
APP_PACKAGES = {
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
MAX_RESTARTS = 24


def log(*args):
    print(*args, flush=True)


# ---------------------------------------------------------------- 无障碍树工具

def dump_xml(d, retries=3):
    xml = ""
    for _ in range(retries):
        try:
            xml = d.dump_hierarchy(compressed=False) or ""
        except Exception as e:
            log(f"  取界面失败: {e}")
            xml = ""
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


def tap_node(d, node, jitter=8):
    c = center(node)
    if not c:
        return False
    d.click(c[0] + random.randint(-jitter, jitter), c[1] + random.randint(-jitter, jitter))
    return True


def current_app(d):
    out = d.shell("dumpsys window | grep mCurrentFocus").output or ""
    m = re.search(r"mCurrentFocus=Window\{.*? u0 ([\w.]+)/([\w.$]+)\}", out)
    return (m.group(1), m.group(2)) if m else (None, None)


def start_taobao(d):
    log("  拉起淘宝")
    d.shell(f"am start -n {TB_APP}/com.taobao.tao.welcome.Welcome")
    time.sleep(10)


def jump_dialog_shown(d):
    """是不是弹了「淘宝想要打开 XX」这类系统确认框"""
    pkg, _ = current_app(d)
    return pkg == OPLUS_PKG


def allow_jump(d):
    """允许跨 App 跳转：优先「30天内允许」，之后就不会再拦"""
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
    """跨 App 任务：允许跳转 -> 在对方 App 里逛够时间 -> 重启淘宝回活动页"""
    if jump_dialog_shown(d):
        allow_jump(d)
    w, h = d.window_size()
    start = time.time()
    browsed = False
    while time.time() - start < dwell:
        pkg, _ = current_app(d)
        if pkg and pkg != TB_APP:
            browsed = True
            d.swipe(w // 2, int(h * 0.75), w // 2, int(h * 0.35), random.uniform(0.4, 0.8))
            time.sleep(random.uniform(1.5, 2.5))
        else:
            time.sleep(1.5)
    if browsed:
        log(f"  在对方 App 里逛了 {dwell} 秒")
    # 从别的 App 回到活动页最容易乱（H5 容器会停在跳过去的页面），直接重启最稳
    restart_app(d, "跨 App 任务返回")
    return open_coin_page(d) and open_energy_panel(d)


# 跨 App 任务在淘宝里先落一个中间页，页面上有「打开XXApp」这类按钮
OPEN_APP_LABELS = ["打开百度App", "打开App", "打开应用", "立即打开", "去打开", "下载并打开", "打开看看"]

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
            return "app"
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
    for label in MODAL_LABELS:
        for node in find_nodes(root, text=label):
            if tap_node(d, node):
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
    return ("赚金币" in xml) and ("赚能量" in xml) and (RACE_TXT in xml)


def mute(d):
    """关掉活动页音效（按钮文案是「关闭音效」，关掉后会变成「开启音效」）"""
    xml = dump_xml(d, retries=1)
    root = ET.fromstring(xml)
    for node in find_nodes(root, text="关闭音效"):
        if tap_node(d, node):
            log("已关闭活动页音效")
            time.sleep(2)
            return True
    return False


def mute_panel(d):
    """任务面板里还有一个独立的「音效」开关，按滑块位置判断开关状态"""
    xml = dump_xml(d, retries=1)
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
        if on_coin_page(xml):
            log("已在淘金币活动页")
            mute(d)
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
                    mute(d)
                    return True
                tap_skip(d, loading_xml)
                time.sleep(2)
            continue
        if COIN_PAGE_TXT in xml or "赚能量" in xml:
            restart_app(d, "活动页按钮节点缺失")
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
    ad_tries = 0
    ok = False
    for _ in range(6):
        xml = dump_xml(d)
        if PANEL_TITLE in xml:
            ok = True
            break
        if handle_modals(d, xml):
            continue
        if ad_tries < 2 and close_ad(d, xml):
            ad_tries += 1
            continue
        root = ET.fromstring(xml)
        btns = find_nodes(root, rid=ENERGY_RID) or find_nodes(root, text="赚能量")
        if btns:
            log("点击「赚能量」")
            tap_node(d, btns[0])
            time.sleep(8)
            continue
        if not open_coin_page(d):
            return False
    if not ok:
        ok = PANEL_TITLE in dump_xml(d, retries=1)
    if ok:
        mute_panel(d)
    return ok


def panel_rows(d, xml=None):
    """解析面板里的任务行：每行 = 可点 View[图标, 任务名, 去完成按钮]"""
    xml = xml if xml is not None else dump_xml(d)
    if PANEL_TITLE not in xml:
        return []
    root = ET.fromstring(xml)
    pm = {}
    for p in root.iter():
        for c in p:
            pm[c] = p
    rows = []
    for btn in find_nodes(root, text="去完成", cls="Button"):
        p = pm.get(btn)
        texts = [(t.get("text") or "").strip() for t in p.iter()
                 if (t.get("class") or "").endswith("TextView") and (t.get("text") or "").strip()] if p is not None else []
        rows.append({"name": max(texts, key=len) if texts else "", "node": btn})
    return rows


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
    """拿到任务行；拿不到就按 清浮层 -> 关面板重开 -> 重启 的顺序自愈"""
    for attempt in range(5):
        xml = dump_xml(d)
        rows = panel_rows(d, xml)
        if rows:
            return rows
        if handle_modals(d, xml):
            continue
        if PANEL_TITLE in xml:
            log("  面板在，但任务行取不到，关闭重开")
            close_panel(d)
            continue
        if on_coin_page(xml):
            open_energy_panel(d)
            continue
        if not restart_app(d, "取不到任务面板"):
            break
        if not open_coin_page(d) or not open_energy_panel(d):
            break
    return panel_rows(d)


# ---------------------------------------------------------------- 做任务

def progress_of(name):
    m = re.search(r"\((\d+)/(\d+)\)", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def task_key(name):
    return re.sub(r"\(\d+/\d+\)", "", name).strip()


def dwell_seconds(task_name):
    """任务要求浏览多久：文案里写「浏览15秒 / 浏览5秒」，兜底 12 秒"""
    if "15秒" in task_name:
        return 16
    if "5秒" in task_name:
        return 7
    if "3秒" in task_name:
        return 5
    return 12


def browse(d, task_name):
    """任务页停留够时长；搜索类任务先搜索再逛"""
    duration = dwell_seconds(task_name)
    xml = dump_xml(d, retries=2)
    root = ET.fromstring(xml)
    edits = find_nodes(root, cls="EditText")
    if edits and "搜一搜" in task_name:
        keyword = random.choice(SEARCH_KEYS)
        log(f"  搜索：{keyword}")
        tap_node(d, edits[0])
        time.sleep(1.2)
        # 走 uiautomator2 的输入法通道（必要时会自动装 AdbKeyboard，中文也能打）；
        # 跑完在 main 的 finally 里会把默认输入法切回你原来的那个。
        d.send_keys(keyword)
        time.sleep(1.5)
        for btn in find_nodes(root, cls="Button", contains="搜索"):
            tap_node(d, btn)
            break
        time.sleep(4)

    w, h = d.window_size()
    start = time.time()
    while time.time() - start < duration:
        x1 = random.randint(w // 6, w // 2)
        y1 = random.randint(h // 2, h - h // 4)
        d.swipe(x1, y1, random.randint(x1 - 120, x1), random.randint(200, y1 - 300),
                random.uniform(0.4, 1))
        time.sleep(random.uniform(1.2, 2.0))


def back_to_panel(d):
    """按返回键回到任务面板，最多 5 次"""
    for _ in range(5):
        xml = dump_xml(d, retries=2)
        if PANEL_TITLE in xml:
            return True
        pkg, _ = current_app(d)
        if pkg and pkg != TB_APP:
            start_taobao(d)
            continue
        d.press("back")
        time.sleep(1.5)
    return PANEL_TITLE in dump_xml(d, retries=1)


def claim_rewards(d):
    """领取累计任务奖励（20 次 / 50 次那几格变可领时）"""
    xml = dump_xml(d, retries=1)
    if PANEL_TITLE not in xml:
        return
    root = ET.fromstring(xml)
    titles = find_nodes(root, text=PANEL_TITLE)
    if not titles:
        return
    pm = parent_map(root)
    panel = titles[0]
    # WebView 还会暴露被面板遮住的商品页；只在当前任务面板内领奖。
    while panel is not None and not find_nodes(panel, text="累计任务奖励"):
        panel = pm.get(panel)
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
            continue
        cur, total = progress_of(name)
        if total and cur >= total:
            continue
        if failed.get(key, 0) >= 2:
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
    while True:
        if max_tasks and done >= max_tasks:
            log(f"到达 --max-tasks {max_tasks}，停止")
            break
        rows = ensure_rows(d)
        if not rows:
            log("取不到任务行，结束任务循环")
            break
        mute(d)  # 页面每次重载音效都会回到「开」，每轮顺手再确认一次（没有就什么也不做）

        candidate = pick_task(d, rows, failed, logged_missing, attempted)

        if candidate is None:
            # 可能还有没露出来的任务，往下翻两次再决定
            for _ in range(2):
                if scroll_panel(d):
                    break
            rows = ensure_rows(d)
            candidate = pick_task(d, rows, failed, logged_missing, attempted)
            if candidate is None:
                log("可见任务都做完/跳过了")
                break

        name = candidate["name"]
        key = task_key(name)
        attempted[key] = attempted.get(key, 0) + 1
        before = progress_of(name)[0]
        total = progress_of(name)[1]
        log(f"[{done + 1}] {name}" + (f"  还差 {total - before} 次" if total else ""))
        tap_node(d, candidate["node"])
        time.sleep(4)
        jump_kind = wait_jump(d, timeout=8)
        if jump_kind:
            log(f"  这是跨 App 任务（{jump_kind}）")
            if not jump_out(d, dwell=dwell_seconds(name)):
                log("  跨 App 任务回来后打不开面板，结束")
                break
        else:
            x2 = dump_xml(d, retries=1)
            if PANEL_TITLE in x2 and "去完成" in x2:
                failed[key] = failed.get(key, 0) + 1
                log(f"  点了没反应（还停在面板），跳过这条（{failed[key]}/2）")
                continue
            handle_modals(d)
            browse(d, name)
            if not back_to_panel(d):
                log("  没回到面板")
                if not ensure_rows(d):
                    break
        claim_rewards(d)
        done += 1
        # 核对计数有没有涨：页面刷新有延迟，等一下再看；两次没涨就不再碰这条任务
        time.sleep(2)
        after_rows = panel_rows(d) or ensure_rows(d)
        m = next((progress_of(r["name"]) for r in after_rows if task_key(r["name"]) == key), None)
        if m is not None and m[0] <= before:
            failed[key] = failed.get(key, 0) + 1
            log(f"  计数没变（{m[0]}/{m[1]}），这条任务这次没算上（{failed[key]}/2）")
    return done


def scroll_panel(d):
    """面板里上滑，看有没有新任务冒出来"""
    before = {task_key(r["name"]) for r in panel_rows(d)}
    w, h = d.window_size()
    d.swipe(w // 2, int(h * 0.82), w // 2, int(h * 0.4), 0.6)
    time.sleep(3)
    after = {task_key(r["name"]) for r in panel_rows(d)}
    return bool(after - before)


# ---------------------------------------------------------------- 升级赛车

def do_race(d, min_energy=20):
    """长按「升级赛车拿钱」把能量换成抵金；每轮会冒出「解锁新车轮/尾翼」浮层"""
    last_energy = None
    for _ in range(15):
        xml = dump_xml(d)
        if handle_modals(d, xml):
            continue
        root = ET.fromstring(xml)
        btns = find_nodes(root, contains=RACE_TXT)
        if not btns:
            log("找不到「升级赛车拿钱」，结束赛车")
            return
        text = btns[0].get("text") or ""
        m = re.search(r"剩余\s*(\d+)\s*能量", text)
        energy = int(m.group(1)) if m else -1
        log(f"赛车：剩余 {energy} 能量")
        if energy < min_energy:
            break
        if energy == last_energy:
            log("  能量没有变化，这轮长按没生效，结束赛车")
            break
        last_energy = energy
        c = center(btns[0])
        if not c:
            break
        d.long_click(c[0], c[1], duration=4)
        time.sleep(6)
        handle_modals(d)
        if PANEL_TITLE in dump_xml(d, retries=1):
            close_panel(d)


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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tasks", type=int, default=0, help="最多做几个任务（0=不限）")
    parser.add_argument("--skip-race", action="store_true", help="不做升级赛车")
    parser.add_argument("--race-only", action="store_true", help="只把能量拿去升级赛车，不做任务")
    parser.add_argument("--open-only", action="store_true", help="只打开活动页，不做任务")
    parser.add_argument("--serial", default="", help="设备序列号")
    args = parser.parse_args()

    d = u2.connect(args.serial) if args.serial else u2.connect()
    log(f"已连接设备：{d.serial}")
    started = time.time()
    remember_ime(d)
    try:
        restart_app(d, "开场重置页面")
        if not open_coin_page(d):
            raise SystemExit("进不去淘金币活动页")
        if args.open_only:
            log("已打开活动页（--open-only）")
            return

        if not args.race_only:
            if not open_energy_panel(d):
                raise SystemExit("打不开「做任务赚能量」面板")
            done = do_tasks(d, max_tasks=args.max_tasks)
            log(f"共完成 {done} 个能量任务")
            close_panel(d)

        if not args.skip_race:
            do_race(d)

        minutes, seconds = divmod(int(time.time() - started), 60)
        log(f"共耗时: {minutes} 分钟 {seconds} 秒，重启淘宝 {RESTARTS} 次")
    finally:
        try:
            restore_ime(d)
        except Exception as exc:
            log(f"输入法还原未完成，请重新连接手机后核对输入法：{exc}")


if __name__ == "__main__":
    main()
