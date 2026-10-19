# 淘宝双十一活动自动刷能量做任务

用 Python / uiautomator2 操作已登录的安卓手机，完成能量任务、领取累计奖励，再长按“升级赛车拿钱”消耗能量。

## Windows 本机运行

手机解锁、开启 USB 调试并允许电脑连接后，在项目目录执行：

```powershell
.\run.cmd check                       # 检查设备
.\run.cmd open                        # 只打开活动页；无参数时也是此模式
.\run.cmd trial                       # 确认记账 3 次后停止，不升级赛车
.\run.cmd tasks                       # 做完可执行的淘宝内任务
.\run.cmd all --allow-app-jumps        # 含已安装 App 的跳转任务，最后升级赛车
.\run.cmd race                        # 只消耗剩余赛车能量
```

多台设备时加 `--serial <设备序列号>`。保持手机解锁，运行中避免同时手动操作。只支持单个运行实例操作同一台手机。

`run.cmd` 优先使用虚拟环境内附带的 ADB；可用环境变量 `ADBUTILS_ADB_PATH` 显式选择其他 ADB。

## 安装和直接运行

需要 Python 3.10+、ADB、已登录淘宝的安卓设备。

```powershell
python -m venv .venv
$env:PYTHONUTF8 = '1'
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
```

也可以直接使用活动脚本：

```bash
python 2026淘宝双11.py --skip-race                    # 淘宝内任务
python 2026淘宝双11.py --allow-app-jumps              # 含跨 App 任务，最后升级赛车
python 2026淘宝双11.py --max-tasks 5 --skip-race       # 确认记账 5 次后停止
python 2026淘宝双11.py --race-only                    # 只升级赛车
python 2026淘宝双11.py --open-only                    # 只打开活动页
```

## 完成判定与记录

- 优先以累计任务进度增加确认记账；缺少累计计数时才检查单条任务进度。点击、停留和未确认记账不算成功。
- 点击前重新读取任务位置，排除底层页面和面板外的按钮；列表重排后不依赖旧坐标。
- 复用当前活动页，普通浏览不额外等待跨 App 检测，不在每次返回时强制重启。
- 同一任务连续两次未确认记账后跳过，并记录原因。
- `last-run.json` 是最近一次结果，包含确认数、每次进度、耗时、跳过原因和赛车能量；`logs/` 保留每轮日志和报告。
- Ctrl+C 可停止，正常异常路径会尝试保存报告和还原输入法；直接结束进程无法保证执行收尾。

首次连接可能推送 `u2.jar` 服务到手机。搜索使用英文关键词和系统 `input text`，不会为了搜索安装或切换 AdbKeyboard。

活动页若只返回 WebView 外壳，可选用本机 `tesseract`（需在 PATH 中且有 `chi_sim`、`eng` 语言）从截图识别赛车及赚能量按钮。只有确认黄色按钮、完整赛车标签与余额后才使用截图坐标；未安装或识别不明确时保留原来的有限恢复和停止行为。OCR 截图在本机内存中处理，不上传。

## 任务范围

默认只处理淘宝内任务；`--allow-app-jumps` 才启用支付宝等已安装目标 App。跨 App 确认只选择本次允许/打开，不自动选择“30天内允许”。进入非目标应用（含系统设置）时停止手势并返回淘宝。

邀请、助力、积分兑换、下单/充值/开卡、预约订阅、答题考试和不支持的小游戏跳过。未安装 App 不会自动下载。登录、验证或界面改版可能需要人工处理，不能承诺完成所有任务。

## 检查

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' -m pip check
```

运行与验证记录见 [LOCAL_SETUP.md](LOCAL_SETUP.md)。截图、界面 XML、日志和运行报告仅留在本机，不上传 GitHub。

本项目用于学习自动化；活动规则和界面变化会影响可用性，使用时请遵守平台规则。

基于 [why-au/taobao-task-automation](https://github.com/why-au/taobao-task-automation) 整理和改进。
