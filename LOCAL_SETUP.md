# 本机使用说明

项目目录：`E:\淘宝\taobao-task-automation`。上游基线：`c1a5385`。

## 现有基础

- `E:\淘宝\android-platform-tools\platform-tools\adb.exe`：复用已有 ADB。
- `E:\淘宝\coin11-tb`：保留之前的 618、淘金币等脚本和环境。
- `E:\淘宝\taobao-gh`：保留之前整理的账号切换、链接提取代码。
- 新项目使用自己的 `.venv`，Python 3.11，`uiautomator2==3.5.2`。

双11 的任务面板已换成“做任务赚能量”和“升级赛车拿钱”，应使用新脚本，不能只给旧 618 脚本改名。先跑通当前单账号；账号切换代码等确有需要时再接入。

## 连接和运行

1. 用可传数据的数据线连接安卓手机，开启 USB 调试，在手机弹窗中允许本机调试。
2. 解锁手机，确认淘宝已经登录。
3. 在本目录的 PowerShell 中按顺序执行：

```powershell
.\run.cmd check   # 只检查 Python、依赖版本和设备连接；不打开淘宝
.\run.cmd open    # 打开活动页，不做任务；不传参数也是此模式
.\run.cmd trial   # 最多尝试 3 次任务，不升级赛车
.\run.cmd tasks   # 做任务，不升级赛车
.\run.cmd all     # 做任务并使用能量升级赛车
.\run.cmd race    # 只使用已有能量升级赛车
```

“3 次”是原脚本任务循环的上限，不保证服务端成功记账 3 次；以手机任务进度为准。

多设备时先用下面命令查看序列号，再指定目标：

```powershell
& '..\android-platform-tools\platform-tools\adb.exe' devices
.\run.cmd trial --serial <设备序列号>
```

运行过程中保持手机解锁，尽量不要同时手动操作。Ctrl+C 可以中断；原脚本会在 finally 中尝试恢复输入法。

## 复建和离线检查

```powershell
python -m venv .venv
$env:PYTHONUTF8 = '1'  # requirements.txt 有 UTF-8 中文注释，避免 pip 按 GBK 读取
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' -m pip check
```

## 当前验证边界

2026-10-18 准备时 ADB 没检测到设备。随后真机联调已连接华为 LIO-AN00，成功启动淘宝并读取界面；首页活动广告弹窗遮住了“领淘金币”入口。补充了按 `content-desc="关闭按钮"` 关闭弹窗的逻辑，并在尝试进入活动前先清理弹窗。

本机检查结果：8 项启动器测试通过；活动脚本、启动器和测试的 Python 编译检查通过；原脚本 `--help` 正常；`pip check` 无依赖冲突；`run.cmd check` 正确提示未连接设备并返回 1。

联调新增 4 项回归检查，合计 12 项测试通过。重试时 USB/ADB 连接多次中断，最后停在 `offline`；自动重连和重启 ADB 服务均未恢复。尚未进入活动页验证，也未开始 3 次任务试跑，任务记账和赛车升级仍待真机验收。

源码检查发现的真机联调关注点：

- 跨 App 授权会优先选择“30天内允许”；这是上游行为。首次联调请留意系统授权弹窗。
- 已修复 `dump_xml` 重试耗尽返回空字符串的问题，现在明确提示检查 USB 连接、调试授权和解锁状态。输入法收尾失败会单独提示，保留主流程原始错误。
- `dwell_seconds` 只识别 15、5、3 秒；其他时长会回落到 12 秒，且“25秒”会误匹配成“5秒”。
- `do_tasks` 的完成数是循环执行次数，任务进度未增加的尝试也可能计入日志总数。

其余关注点尚未修改；真机复现后再做最小修正。当前活动脚本只修改了弹窗处理和界面读取/收尾错误处理。
