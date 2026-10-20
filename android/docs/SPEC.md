# 安卓独立运行版

## 目标与验收

将当前 Python 项目已有的单账号淘宝能量任务、累计领奖和赛车升级迁到手机端。生成可安装 APK；正常使用不需要电脑、ADB、Root、Google Play 服务或云端识别。

- 手机内选择完整流程、仅任务、仅赛车，明确开始和停止。
- 系统无障碍服务由用户手动授权；仅在用户启动后读取并操作白名单 App。锁屏、未知前台、登录和人工验证时停止。
- 适配当前已验证页面：按文字与可见范围匹配任务，解析时长，返回后核对累计或单项进度；累计达到 50 后仍可按单项进度确认。
- 有界重试，未记账不算完成；领取 5/20/50 档奖励；处理已知浮层并消耗赛车能量，报告真实余量。
- 无障碍树缺失时使用离线中文 OCR。Android 11+ 使用无障碍截图；Android 9/10 使用用户明确同意的屏幕录制授权。
- 运行浮条和通知提供停止入口；停止后不再识别或操作。输入法、淘宝登录信息不变。
- 用户自行处理登录和验证码。付费、兑换、邀请、订阅与账号切换保留为人工操作；这部分不在当前 Python 主项目已实现流程内。
- APK、签名验证、构建和测试通过。真机安装及任务验收以设备连接和用户授权为前提，缺少的实机证据需如实说明。

## 实现顺序

1. Gradle 工程、可独立测试的任务规则。
2. 用户界面、服务授权、可停止的手势和本机日志。
3. 任务与赛车状态流程、离线截图识别及旧系统截图兼容。
4. 测试、lint、构建、APK 签名和清单检查；真机安装与运行验证。

## 工程与命令

Java 17、Android SDK 35、AGP 8.9.2、Gradle 8.11.1；`app/src/main/java` 为业务代码，`app/src/test/java` 为规则回归检查。

```powershell
$env:JAVA_HOME='C:\Program Files (x86)\Android\openjdk\jdk-17.0.14'
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

## 权限与数据边界

只使用无障碍、用户授权的屏幕识别及前台通知所需权限。截图仅保留于内存，日志仅记录任务标题、进度及错误原因，不收集口令、手机号、剪贴板或完整界面文本。应用不申请网络权限，不提供可被外部调用的自动化入口；服务须由 Android 的绑定权限保护。APK 在用户明确开启服务后才执行任务。

规则示例：`TaskRules.progress("浏览(2/5)")` 返回 `[2,5]`。Java 使用清楚的类名与小方法，复用 Android 平台控件，保持当前 Python 实现作为回退。

参考：[无障碍服务](https://developer.android.com/guide/topics/ui/accessibility/service)、[离线中文识别](https://developers.google.com/ml-kit/vision/text-recognition/v2/android)。
