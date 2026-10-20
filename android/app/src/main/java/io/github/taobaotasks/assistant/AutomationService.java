package io.github.taobaotasks.assistant;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.KeyguardManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.view.Gravity;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.TextView;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.lang.ref.WeakReference;

public final class AutomationService extends AccessibilityService {
    private static volatile WeakReference<AutomationService> reference = new WeakReference<>(null);
    static AutomationService get() { return reference.get(); }
    private static final int NOTICE = 11;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final ThreadLocal<Long> workerGeneration = new ThreadLocal<>();
    private volatile boolean running;
    private volatile long generation;
    private volatile String external = "";
    private Future<?> job;
    private ScreenReader reader;
    private TextView overlay;
    private NotificationManager notifications;

    @Override protected void onServiceConnected() {
        reference = new WeakReference<>(this); RunLog.init(this);
        notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel("run", "任务运行", NotificationManager.IMPORTANCE_LOW));
    }
    @Override public void onAccessibilityEvent(AccessibilityEvent event) { /* Read on demand only. */ }
    @Override public void onInterrupt() { stopRun("无障碍服务被中断"); }
    @Override public void onDestroy() {
        stopRun("无障碍服务已关闭"); reference.clear(); worker.shutdownNow(); super.onDestroy();
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "STOP".equals(intent.getAction())) stopRun("你已从通知停止运行");
        return START_NOT_STICKY;
    }
    boolean isRunning() { return running; }
    void startRun(int mode, boolean jumps, int captureResult, Intent captureData) {
        if (running) return;
        RunLog.state("正在准备"); running = true; long token = ++generation;
        try {
            showOverlay();
            Notification notice = notification();
            if (Build.VERSION.SDK_INT < 30) startForeground(NOTICE, notice);
            else notifications.notify(NOTICE, notice);
            reader = new ScreenReader(this, captureResult, captureData);
            job = worker.submit(() -> {
                workerGeneration.set(token);
                String result;
                try {
                    check(); RunLog.reset();
                    pause(2500);
                    new TaskRunner(this, jumps).run(mode);
                    result = "本次流程已结束，请查看实际进度";
                } catch (InterruptedException cancelled) {
                    Thread.currentThread().interrupt(); result = "运行已停止";
                } catch (TaskRunner.Stop stopped) {
                    result = stopped.getMessage();
                } catch (Exception failure) {
                    // No raw exception message: vendor errors can include window contents.
                    result = "识别或操作失败（" + failure.getClass().getSimpleName() + "），请重新开始";
                }
                String finalResult = result;
                main.post(() -> { if (generation == token && running) stopRun(finalResult); });
                workerGeneration.remove();
            });
        } catch (RuntimeException failure) {
            stopRun("无法准备截图或运行浮条，请检查授权后重试"); throw failure;
        }
    }
    void stopRun(String reason) {
        if (Looper.myLooper() != Looper.getMainLooper()) { main.post(() -> stopRun(reason)); return; }
        if (!running) return;
        running = false; ++generation; external = "";
        if (job != null) job.cancel(true);
        if (reader != null) { reader.close(); reader = null; }
        if (overlay != null) {
            try { getSystemService(WindowManager.class).removeView(overlay); }
            catch (IllegalArgumentException ignored) { }
            overlay = null;
        }
        stopForeground(STOP_FOREGROUND_REMOVE);
        if (notifications != null) notifications.cancel(NOTICE);
        RunLog.add(reason); RunLog.state(reason);
    }
    void check() throws InterruptedException {
        Long token = workerGeneration.get();
        if (!running || Thread.currentThread().isInterrupted() || token == null || token != generation) throw new InterruptedException();
        if (!getSystemService(PowerManager.class).isInteractive() || getSystemService(KeyguardManager.class).isKeyguardLocked()) {
            throw new TaskRunner.Stop("手机已锁屏，运行停止");
        }
    }
    void pause(long millis) throws InterruptedException {
        long end = android.os.SystemClock.elapsedRealtime() + millis;
        do { check(); Thread.sleep(Math.min(200, Math.max(1, end - android.os.SystemClock.elapsedRealtime()))); }
        while (android.os.SystemClock.elapsedRealtime() < end);
    }
    void expectExternal(String pkg) { external = pkg; }
    String foreground() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return "";
        String pkg = value(root.getPackageName()); root.recycle(); return pkg;
    }
    private boolean allowed(String pkg) { return TaskRules.TAOBAO.equals(pkg) || (!external.isEmpty() && external.equals(pkg)); }
    private void guard() throws InterruptedException {
        check();
        if (!allowed(foreground())) throw new TaskRunner.Stop("前台离开本次允许的 App，已停止操作；请回到活动页重试");
    }
    Frame frame() throws Exception {
        check();
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) { pause(400); root = getRootInActiveWindow(); }
        if (root == null) throw new TaskRunner.Stop("无法读取前台窗口，请确认无障碍服务已开启");
        String pkg = value(root.getPackageName());
        if (!allowed(pkg)) { root.recycle(); throw new TaskRunner.Stop("前台离开本次允许的 App，已停止操作；请回到活动页重试"); }
        android.util.DisplayMetrics metrics = ScreenReader.metrics(this);
        Frame nativeFrame = new Frame(pkg, metrics.widthPixels, metrics.heightPixels, false);
        flatten(root, -1, 0, nativeFrame); root.recycle();
        ScreenReader currentReader = reader;
        if (currentReader == null) throw new InterruptedException();
        Frame result = nativeFrame;
        // A complete native task panel is cheaper and more accurate than OCR.
        boolean panel = nativeFrame.panel(), race = nativeFrame.contains("升级赛车拿钱") != null;
        if ((panel && nativeFrame.tasks().isEmpty()) || (race && TaskRules.energy(nativeFrame.text()) < 0)
                || (!panel && !race && (nativeFrame.text().length() < 160 || nativeFrame.contains("淘金币首页") != null))) {
            result = currentReader.read(nativeFrame);
        }
        check(); guard();
        if (!pkg.equals(foreground())) throw new TaskRunner.Stop("识别期间前台已改变，请回到活动页重试");
        if (TaskRules.verification(result.text())) throw new TaskRunner.Stop("出现人工验证，请完成验证后重新开始");
        if (result.contains("验证码登录") != null || result.contains("密码登录") != null
                || result.contains("登录后") != null || result.contains("登录/注册") != null) {
            throw new TaskRunner.Stop("目标 App 需要登录，请手动登录后重新开始");
        }
        return result;
    }
    private void flatten(AccessibilityNodeInfo info, int parent, int depth, Frame frame) {
        if (depth > 70 || frame.nodes.size() >= 2500 || !info.isVisibleToUser()) return;
        Rect b = new Rect(); info.getBoundsInScreen(b);
        int index = frame.nodes.size();
        frame.nodes.add(new Frame.Node(value(info.getText()), value(info.getContentDescription()),
                value(info.getViewIdResourceName()), value(info.getClassName()), parent,
                Math.max(0,b.left), Math.max(0,b.top), Math.min(frame.width,b.right), Math.min(frame.height,b.bottom),
                info.isClickable(), info.isEditable()));
        for (int i = 0; i < info.getChildCount(); i++) {
            AccessibilityNodeInfo child = info.getChild(i);
            if (child != null) { flatten(child, index, depth + 1, frame); child.recycle(); }
        }
    }
    private static String value(CharSequence text) { return text == null ? "" : text.toString(); }
    void tap(Frame frame, Frame.Node node) throws Exception { stroke(frame, node.x(), node.y(), node.x(), node.y(), 70); }
    void hold(Frame frame, Frame.Node node) throws Exception { stroke(frame, node.x(), node.y(), node.x(), node.y(), 1800); }
    void swipe(Frame frame, float from, float to) throws Exception { stroke(frame, frame.width*.5f, frame.height*from, frame.width*.5f, frame.height*to, 450); }
    private void stroke(Frame frame, float x, float y, float endX, float endY, long duration) throws Exception {
        guard();
        if (!frame.pkg.equals(foreground()) || x < 1 || y < 1 || endY >= frame.height || endX >= frame.width) throw new TaskRunner.Stop("页面位置已变化，请回到活动页重试");
        long token = generation;
        CountDownLatch finished = new CountDownLatch(1); AtomicBoolean ok = new AtomicBoolean();
        main.post(() -> {
            if (!running || generation != token || !frame.pkg.equals(foreground())) { finished.countDown(); return; }
            Path path = new Path(); path.moveTo(x, y); if (x != endX || y != endY) path.lineTo(endX, endY);
            GestureDescription gesture = new GestureDescription.Builder()
                    .addStroke(new GestureDescription.StrokeDescription(path, 0, duration)).build();
            boolean accepted = dispatchGesture(gesture, new GestureResultCallback() {
                @Override public void onCompleted(GestureDescription g) { ok.set(true); finished.countDown(); }
                @Override public void onCancelled(GestureDescription g) { finished.countDown(); }
            }, main);
            if (!accepted) finished.countDown();
        });
        if (!finished.await(duration + 2000, TimeUnit.MILLISECONDS) || !ok.get()) throw new TaskRunner.Stop("手势被打断，已停止；请重新开始");
        check();
    }
    void back() throws Exception {
        guard(); if (!performGlobalAction(GLOBAL_ACTION_BACK)) throw new TaskRunner.Stop("返回操作未成功"); pause(850);
    }
    void launchTaobao() throws Exception {
        check(); String pkg = foreground();
        if (!allowed(pkg)) throw new TaskRunner.Stop("前台为未允许的 App，已停止");
        Intent intent = getPackageManager().getLaunchIntentForPackage(TaskRules.TAOBAO);
        if (intent == null) throw new TaskRunner.Stop("未安装淘宝");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); startActivity(intent); pause(1800);
    }
    boolean setSearchText(String keyword) throws Exception {
        guard(); AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return false;
        try { return TaskRules.TAOBAO.equals(value(root.getPackageName())) && setEditable(root, keyword, 0); }
        finally { root.recycle(); }
    }
    private boolean setEditable(AccessibilityNodeInfo node, String text, int depth) {
        if (depth > 60) return false;
        if (node.isEditable() && node.isVisibleToUser()) {
            Bundle args = new Bundle(); args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i); if (child == null) continue;
            boolean success = setEditable(child, text, depth + 1); child.recycle(); if (success) return true;
        }
        return false;
    }
    void projectionEnded() { if (running) stopRun("屏幕识别授权已结束，请重新开始并授权"); }
    private Notification notification() {
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, AutomationService.class).setAction("STOP"), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent open = PendingIntent.getActivity(this, 2, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, "run").setSmallIcon(io.github.taobaotasks.assistant.R.drawable.ic_task)
                .setContentTitle("双十一任务正在运行").setContentText("保持解锁；点停止可结束本次运行")
                .setContentIntent(open).setOngoing(true).addAction(new Notification.Action.Builder(null, "停止", stop).build()).build();
    }
    private void showOverlay() {
        overlay = new TextView(this); overlay.setText("任务运行中   ■ 停止"); overlay.setTextColor(Color.WHITE);
        overlay.setTextSize(13); int pad = Math.round(12 * getResources().getDisplayMetrics().density);
        overlay.setPadding(pad, pad/2, pad, pad/2); overlay.setBackgroundColor(Color.rgb(151, 57, 20));
        overlay.setOnClickListener(v -> stopRun("你已从浮条停止运行"));
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(-2, -2,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
                android.graphics.PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL; params.y = pad;
        getSystemService(WindowManager.class).addView(overlay, params);
    }
}
