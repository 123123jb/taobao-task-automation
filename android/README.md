# 安卓独立运行版

**v0.1.0-alpha1 测试版，Android 9 及以上。** 手机安装后通过无障碍服务执行任务，日常运行无需电脑、USB 调试、Root 或 Google Play 服务。

[下载 APK](https://github.com/123123jb/taobao-task-automation/releases/download/v0.1.0-android-alpha1/taobao-task-assistant-0.1.0-alpha1.apk) · [版本与校验文件](https://github.com/123123jb/taobao-task-automation/releases/tag/v0.1.0-android-alpha1)

## 手机安装与运行

1. 在手机浏览器下载 APK，按系统提示允许该浏览器安装应用，然后安装「双十一任务助手」。
2. 先打开淘宝并手动登录，再打开助手，点击「开启无障碍服务」，在系统设置中找到并手动开启「双十一任务助手」。返回助手。
3. 选择「做任务 + 领取奖励 + 赛车」「只做任务与领取奖励」或「只消耗赛车能量」，点击开始。Android 9/10 每轮还会请求一次屏幕识别授权；Android 11 及以上使用无障碍截图。
4. 保持竖屏和解锁，运行期间不要同时操作手机。点顶部浮条、通知中的「停止」，或回到助手点「停止运行」，都能结束本轮。已经发出的长按最多约 2 秒结束。

如果 Android 提示「受限设置」而无法开启无障碍，可到系统「应用信息 → 双十一任务助手 → 右上角菜单」手动允许受限设置，再返回开启；不同手机的名称可能不同。

首次可从淘宝「领淘金币 → 赚能量」手动打开任务面板后启动助手。入口未被识别时也按这个方式重试。助手不会通过反复重启 App 寻找入口。

## 当前范围与验证边界

- 自动浏览当前活动的单账号能量任务、尝试领取累计奖励和长按升级赛车。默认仅淘宝内；勾选跨 App 浏览后，仅处理已安装且识别出的目标 App。
- 返回后核对进度；累计未满 50 时看累计增加，满 50 或无法读取累计时核对连续两次单项进度。没有证据的尝试不算成功。
- 同一任务连续两次未确认后跳过；每轮最多 100 次任务尝试、250 轮赛车、45 分钟。余量无法读取或不再下降时如实记录，不把它当作清零。
- 登录、人工验证、锁屏、未知前台（含系统设置）和不支持的界面会停止，手动处理后再开始。
- 付费、积分兑换、订阅、邀请、分享助力与账号切换不包含在本版自动流程中。
- 本版完成了规则单元测试、Android lint、APK 构建和签名校验。制作时手机未连接，**尚未验证 APK 在真机上的安装、权限兼容、活动页面识别、任务记账和赛车结果**；不能保证直接完成所有任务。原 Python 程序仍保留。

## 权限与本机数据

无障碍用于读取页面和发送点击/滑动；旧系统额外请求屏幕识别授权。浮条和通知提供停止入口。截图只在内存中进行中文 OCR，停止后释放截图资源；应用只保存最多 200 行任务标题、进度和停止原因，不保存界面全文、账号、密码、剪贴板或截图。

APK 移除了 `INTERNET` 权限；识别模型已打包。SDK 保留 `ACCESS_NETWORK_STATE` 用于兼容 Android 14 的任务调度权限检查，该权限本身不能联网。系统通知与旧版屏幕识别前台服务使用对应权限。应用没有申请存储、联系人、短信或悬浮窗权限（停止浮条使用无障碍浮层）。

## 开发构建

JDK 17、Android SDK 35、Gradle 8.11.1、AGP 8.9.2。将本地 SDK 路径写入本目录的 `local.properties`，不要提交该文件。

```powershell
$env:JAVA_HOME='你的 JDK 17 目录'
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

本机 Windows 中文目录会导致 Gradle 测试工作进程无法找到类，已使用英文目录联接 `E:\Codex\taobao-task-android` 指向本 `android` 目录，在该英文目录执行命令即可。`android.overridePathCheck=true` 只绕过 AGP 路径检查，不能替代这个工作路径。其他开发机建议直接检出到英文路径。

发布签名在项目根目录的 `.android-signing/` 中，仅保存在本机且已忽略，不推送 GitHub。`signing.properties` 结构如下，路径相对本 `android` 目录；口令从独立文本文件读取，不写进 Gradle 或命令参数。

```properties
storeFile=../.android-signing/release.jks
passwordFile=../.android-signing/password.txt
keyAlias=release
```

存在本机签名配置时，执行 `testReleaseUnitTest lintRelease assembleRelease` 可构建签名版。无配置时只能产出未签名 Release；可使用自动签名的 Debug 版进行开发。请自行妥善备份整个 `.android-signing/`，遗失后无法用同一签名覆盖更新。Debug 与发布版签名不同，不能相互覆盖。

设计和验收范围见 [SPEC.md](docs/SPEC.md)。
