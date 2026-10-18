# 本机使用与验收

项目：`E:\淘宝\taobao-task-automation`。上游基线 `c1a5385`，本机使用 Python 3.11 / uiautomator2 3.5.2，真机为华为 LIO-AN00。

## 启动

```powershell
cd E:\淘宝\taobao-task-automation
.\run.cmd check
.\run.cmd all --allow-app-jumps
```

`all --allow-app-jumps` 尝试可执行的淘宝内及跨 App 任务，最后消耗赛车能量。只做任务用 `tasks --allow-app-jumps`；只消耗能量用 `race`；`trial` 在确认记账 3 次后停止。

`run.cmd` 默认使用 `.venv\Lib\site-packages\adbutils\binaries\adb.exe`（当前 ADB 36）。原 ADB 37 和旧 618 / 链接提取工程均保留；切换后完成了连续试跑，但尚不能认定 ADB 37 是断连原因。

## 已修正

- 识别首页广告关闭按钮，等待活动按钮加载，避免未加载就按返回。
- 在任务面板内定位任务和累计奖励，排除底层商品页、优惠券及面板外按钮。
- 点击前重新定位；进度/奖励文案变化不改变任务身份。
- 按实际累计进度统计成功；未记账不算完成，同一任务失败两次后记录原因。
- 普通浏览不额外等跨 App 检测；复用当前页面，不再开场或每轮强制重启。
- 前台不是目标 App 时停止手势，系统设置不再被当作外部浏览任务。
- 英文搜索使用 `input text`，避免安装或切换输入法。
- 支持不同秒数和 `15s` 文案；报告记录每次确认结果、耗时及跳过原因。
- 赛车先关闭任务面板，持续核对能量变化，处理升级浮层；无进展时有上限。

## 2026-10-18 验证记录

初版曾完成 3 次浏览，由 `2/50` 增至 `5/50`。随后收到卡顿、跳系统设置和任务未完成反馈，因此增加了完整任务循环回归和真机验收。

新版第一轮：5 次浏览全部确认记账，耗时 150 秒，强制重启 0 次。原输入法保持 `com.baidu.input_huawei/.ImeService`。列表重排导致单行计数有时不稳定，后续优先用累计进度作为凭据。

完整淘宝内任务、跨 App 和赛车验收正在进行；最终数据以 `logs/` 分轮报告及末次手机截图为准。

## 检查与记录

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' -m pip check
```

界面 XML、截图、日志和 JSON 报告不提交到 Git。`last-run.json` 为最近一轮，历史记录在 `logs/`，用于核对真实成功次数和跳过原因。

未适配的活动改版、登录/验证码、未安装 App，以及需额外下单/支付/邀请/授权的任务可能需人工处理，不能保证全部完成。
