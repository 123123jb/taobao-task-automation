"""本地启动入口：检查设备、打开页面、试跑，再按需执行完整流程。"""
import argparse
from importlib.metadata import version
import os
from pathlib import Path
import subprocess
import sys

import adbutils


ROOT = Path(__file__).resolve().parent
MODES = {
    "check": [],
    "open": ["--open-only"],
    "trial": ["--max-tasks", "3", "--skip-race"],
    "tasks": ["--skip-race"],
    "all": [],
    "race": ["--race-only"],
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default="open", choices=MODES)
    parser.add_argument("--serial", default="", help="多设备时指定 adb 序列号")
    parser.add_argument("--allow-app-jumps", action="store_true", help="启用跨 App 任务")
    args = parser.parse_args(argv)

    # 保留显式选择的 ADB，便于在不同设备上验证连接兼容性。
    adb = Path(os.environ.get("ADBUTILS_ADB_PATH") or
               ROOT.parent / "android-platform-tools" / "platform-tools" / "adb.exe")
    if adb.is_file():
        os.environ["ADBUTILS_ADB_PATH"] = str(adb)
        os.environ["PATH"] = str(adb.parent) + os.pathsep + os.environ.get("PATH", "")
    print(f"Python {sys.version.split()[0]} / uiautomator2 {version('uiautomator2')}", flush=True)
    try:
        devices = adbutils.adb.device_list()
    except Exception as exc:
        print(f"ADB 连接失败：{exc}")
        return 1
    if not devices:
        print("未检测到已授权设备。请用数据线连接安卓手机，开启 USB 调试，并在手机上允许本机调试。")
        return 1
    if args.serial:
        if args.serial not in {d.serial for d in devices}:
            print("指定设备未连接或尚未授权，请用 adb devices 核对。")
            return 1
        serial = args.serial
    elif len(devices) == 1:
        serial = devices[0].serial
    else:
        print("检测到多台设备，请用 --serial 指定目标。")
        return 1
    if args.mode == "check":
        print("设备连接检查通过；尚未打开淘宝或执行任务。")
        return 0
    flags = MODES[args.mode] + (["--allow-app-jumps"] if args.allow_app_jumps else [])
    return subprocess.run([
        sys.executable, "-X", "utf8", str(ROOT / "2026淘宝双11.py"),
        "--serial", serial, *flags,
    ], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
