package io.github.taobaotasks.assistant;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private static final int CAPTURE = 20;
    private final Handler handler = new Handler();
    private TextView status, permission, record;
    private Button start, authorize;
    private Spinner mode;
    private CheckBox jumps;
    private int pendingMode;
    private boolean pendingJumps;
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            AutomationService service = AutomationService.get();
            boolean enabled = service != null, running = enabled && service.isRunning();
            permission.setText(enabled ? "无障碍已开启 · 截图识别仅在运行时使用" : "第 1 步 · 开启「双十一任务助手」无障碍服务");
            authorize.setVisibility(enabled ? View.GONE : View.VISIBLE);
            start.setEnabled(enabled && !running);
            mode.setEnabled(!running); jumps.setEnabled(!running);
            status.setText(RunLog.state());
            record.setText(RunLog.lines().isEmpty() ? "开始后，这里会显示任务进度和停止原因。" : RunLog.lines());
            handler.postDelayed(this, 1000);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state); RunLog.init(this);
        getWindow().setStatusBarColor(Color.rgb(250, 247, 242));
        getWindow().setNavigationBarColor(Color.rgb(250, 247, 242));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        ScrollView scroll = new ScrollView(this);
        LinearLayout content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(24), dp(30), dp(24), dp(36)); content.setBackgroundColor(Color.rgb(250, 247, 242));
        scroll.setFillViewport(true); scroll.addView(content); setContentView(scroll);
        TextView eyebrow = text("手机独立运行  /  v0.1 测试版", 12); eyebrow.setTextColor(Color.rgb(159, 75, 37)); content.addView(eyebrow);
        TextView title = text("双十一任务助手", 30); title.setTypeface(null, Typeface.BOLD); content.addView(title);
        content.addView(text("浏览任务、领能量，再升级赛车。\n运行时保持解锁，并让手机留在任务页面。", 15));
        permission = text("", 14); content.addView(permission);
        authorize = button("开启无障碍服务", false); content.addView(authorize);
        authorize.setOnClickListener(v -> new AlertDialog.Builder(this)
                .setTitle("允许读取与操作任务页面")
                .setMessage("运行时，助手通过无障碍读取屏幕文字、点击和滑动；页面文字缺失时在本机截图识别。截图不保存、不上传。可随时点浮条停止。\n\n进入系统设置后，找到「双十一任务助手」并手动开启。助手不会自行更改系统设置。")
                .setPositiveButton("前往系统设置", (d, w) -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)))
                .setNegativeButton("取消", null).show());
        content.addView(text("第 2 步 · 选择本次流程", 14));
        mode = new Spinner(this);
        mode.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item,
                new String[]{"做任务 + 领取奖励 + 赛车", "只做任务与领取奖励", "只消耗赛车能量"}));
        content.addView(mode, new LinearLayout.LayoutParams(-1, dp(54)));
        jumps = new CheckBox(this); jumps.setText(R.string.allow_jumps); jumps.setTextSize(14);
        content.addView(jumps);
        start = button("开始本次任务", true); content.addView(start);
        start.setOnClickListener(v -> prepare());
        Button stop = button("停止运行", false); content.addView(stop);
        stop.setOnClickListener(v -> { AutomationService service=AutomationService.get(); if (service!=null) service.stopRun("你已停止运行"); });
        status = text("", 18); status.setTypeface(null, Typeface.BOLD); content.addView(status);
        content.addView(text("本机记录", 13));
        record = text("", 13); record.setTextIsSelectable(true); record.setTypeface(Typeface.MONOSPACE); content.addView(record);
        content.addView(text("登录或验证出现时会停止，请手动处理后重新开始。付费、兑换、订阅、邀请和账号切换由你操作。活动改版可能导致部分任务无法完成。", 12));
    }
    private void prepare() {
        if (AutomationService.get() == null) return;
        pendingMode = mode.getSelectedItemPosition(); pendingJumps = jumps.isChecked();
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 21);
            return;
        }
        beginOrCapture();
    }
    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == 21) beginOrCapture(); // Floating stop control also works if notifications are declined.
    }
    private void beginOrCapture() {
        if (AutomationService.get() == null) return;
        if (Build.VERSION.SDK_INT < 30) {
            MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
            startActivityForResult(manager.createScreenCaptureIntent(), CAPTURE);
        } else startRun(0, null);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == CAPTURE && result == RESULT_OK && data != null) startRun(result, data);
        else if (request == CAPTURE) RunLog.state("未授权屏幕识别，本次未启动");
    }
    private void startRun(int result, Intent data) {
        AutomationService service = AutomationService.get();
        if (service == null) return;
        Intent taobao = getPackageManager().getLaunchIntentForPackage(TaskRules.TAOBAO);
        if (taobao == null) { RunLog.state("请先安装并登录淘宝"); return; }
        try {
            service.startRun(pendingMode, pendingJumps, result, data);
            startActivity(taobao);
        } catch (RuntimeException failure) {
            service.stopRun("启动失败，请重新开启无障碍后再试");
        }
    }
    @Override protected void onResume() { super.onResume(); handler.post(refresh); }
    @Override protected void onPause() { handler.removeCallbacks(refresh); super.onPause(); }
    private int dp(int value) { return Math.round(getResources().getDisplayMetrics().density * value); }
    private TextView text(String value, int size) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size);
        view.setTextColor(Color.rgb(48, 42, 36)); view.setPadding(0, dp(10), 0, dp(10)); view.setLineSpacing(dp(3), 1);
        return view;
    }
    private Button button(String label, boolean primary) {
        Button button = new Button(this); button.setText(label); button.setAllCaps(false); button.setMinHeight(dp(52));
        button.setTextColor(primary ? Color.WHITE : Color.rgb(145, 60, 24));
        GradientDrawable background = new GradientDrawable(); background.setCornerRadius(dp(14));
        background.setColor(primary ? Color.rgb(199, 78, 28) : Color.rgb(246, 231, 216)); button.setBackground(background);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(54)); params.topMargin = dp(10);
        button.setLayoutParams(params); return button;
    }
}
