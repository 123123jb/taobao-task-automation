package io.github.taobaotasks.assistant;

import android.content.pm.PackageManager;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Bounded single-account flow. Every input is guarded by the foreground package. */
final class TaskRunner {
    static final class Stop extends RuntimeException { Stop(String message) { super(message); } }
    private static final Map<String,String> APPS = new LinkedHashMap<>();
    static {
        APPS.put("蚂蚁庄园", "com.eg.android.AlipayGphone"); APPS.put("支付宝", "com.eg.android.AlipayGphone");
        APPS.put("蚂蚁森林", "com.eg.android.AlipayGphone");
        APPS.put("百度", "com.baidu.searchbox"); APPS.put("闲鱼", "com.taobao.idlefish");
        APPS.put("微博", "com.sina.weibo"); APPS.put("京东", "com.jingdong.app.mall");
        APPS.put("拼多多", "com.xunmeng.pinduoduo"); APPS.put("抖音", "com.ss.android.ugc.aweme");
        APPS.put("快手", "com.smile.gifmaker"); APPS.put("美团", "com.sankuai.meituan");
        APPS.put("饿了么", "me.ele"); APPS.put("高德", "com.autonavi.minimap");
    }
    private final AutomationService service;
    private final boolean jumps;
    private final Map<String,Integer> failures = new HashMap<>();
    private final Map<String,String> skipped = new HashMap<>();
    private final long deadline = android.os.SystemClock.elapsedRealtime() + 45*60*1000;
    private int attempts, credited, rewards;
    TaskRunner(AutomationService service, boolean jumps) { this.service = service; this.jumps = jumps; }

    void run(int mode) throws Exception {
        RunLog.add("开始" + (mode == 2 ? "赛车流程" : "能量任务流程") + "；点击或停留不算完成");
        try {
            if (mode != 2) {
                openPanel(); tasks();
                Frame frame = read(); if (frame.panel()) claimRewards();
            } else openPanel();
            if (mode != 1) { closePanel(); race(); }
        } finally {
            RunLog.add("本轮：尝试 " + attempts + " 次，确认记账 " + credited + " 次，领取奖励 " + rewards + " 次");
        }
    }
    private Frame read() throws Exception {
        if (android.os.SystemClock.elapsedRealtime() > deadline) throw new Stop("已达到本轮 45 分钟上限");
        return service.frame();
    }
    private boolean coin(Frame frame) {
        return frame.contains("升级赛车拿钱") != null && TaskRules.energy(frame.text()) >= 0;
    }
    private void openPanel() throws Exception {
        boolean entryTapped = false;
        for (int i = 0; i < 24; i++) {
            Frame frame = read();
            if (frame.panel()) return;
            if (dismiss(frame)) continue;
            Frame.Node energy = frame.exact("赚能量");
            if (energy == null) for (Frame.Node n : frame.nodes) if (n.id.endsWith("energy_task_button")) { energy=n; break; }
            if (energy != null && (coin(frame) || frame.contains("淘金币首页") != null || frame.contains("赚金币") != null)) {
                service.tap(frame,energy); service.pause(1200); continue;
            }
            Frame.Node entry = frame.exact("领淘金币");
            if (entry != null && !entryTapped) {
                RunLog.add("打开领淘金币活动页"); service.tap(frame,entry); entryTapped=true; service.pause(2200); continue;
            }
            if (entryTapped || frame.contains("淘金币首页") != null || coin(frame)) { service.pause(1200); continue; }
            if (i < 4) service.back();
            else throw new Stop("未找到活动入口，请手动打开「淘金币 → 赚能量」后重新开始");
        }
        throw new Stop("活动面板未加载，请手动打开「做任务赚能量」后重新开始");
    }
    private void tasks() throws Exception {
        int pages = 0, unchanged = 0; String previous = "";
        while (attempts < 100 && pages < 8 && unchanged < 2) {
            Frame frame = read();
            if (dismiss(frame)) continue;
            if (!frame.panel()) throw new Stop("任务面板已离开，请回到活动页重新开始");
            List<Frame.Task> rows = frame.tasks(); Frame.Task chosen = null;
            for (Frame.Task row : rows) {
                if (!row.available() || failures.getOrDefault(row.key,0) >= 2) continue;
                String reason = skipReason(row);
                if (reason != null) { skip(row.key, reason); continue; }
                chosen = row; break;
            }
            if (chosen == null) {
                StringBuilder signature = new StringBuilder();
                for (Frame.Task row : rows) signature.append(row.key).append(':').append(row.current).append(';');
                String current = signature.toString(); unchanged = current.equals(previous) ? unchanged+1 : 0; previous = current;
                service.swipe(frame,.84f,.48f); service.pause(600); pages++; continue;
            }
            pages=0; unchanged=0; previous="";
            attempt(chosen.key);
        }
        RunLog.add(attempts >= 100 ? "已达到本轮 100 次尝试上限" : "当前列表中可执行的任务已处理；跳过或未确认的任务未算成功");
    }
    private String skipReason(Frame.Task task) {
        if (TaskRules.skip(task.title)) return "需要人工操作或不在自动浏览范围";
        String pkg = appFor(task.title);
        if (!pkg.isEmpty()) {
            if (!jumps) return "本轮未开启跨 App 浏览";
            try { service.getPackageManager().getPackageInfo(pkg,0); }
            catch (PackageManager.NameNotFoundException absent) { return "目标 App 未安装"; }
        }
        return null;
    }
    private String appFor(String title) {
        for (Map.Entry<String,String> entry : APPS.entrySet()) if (title.contains(entry.getKey())) return entry.getValue();
        return "";
    }
    private void skip(String key, String reason) {
        if (skipped.put(key,reason) == null) RunLog.add("跳过「"+key+"」："+reason);
    }
    private Frame.Task row(Frame frame, String key) {
        for (Frame.Task task : frame.tasks()) if (task.key.equals(key)) return task;
        return null;
    }
    private void attempt(String key) throws Exception {
        // Re-read immediately before the tap: the list can reorder when a reward arrives.
        Frame beforeFrame = read(); Frame.Task before = row(beforeFrame,key);
        if (before == null || !before.available()) return;
        int cumulative = beforeFrame.cumulative(); attempts++;
        String external = appFor(before.title); service.expectExternal(external);
        RunLog.state("正在浏览 · " + key); RunLog.add("尝试「"+key+"」 "+before.current+"/"+before.total);
        service.tap(beforeFrame,before.button); service.pause(1400);
        boolean browsed = browse(before.title,external);
        backToPanel();
        boolean ok = false; int lastRow=-1;
        for (int i=0; i<3; i++) {
            Frame afterFrame = read(); Frame.Task after=row(afterFrame,key);
            int afterCount=after == null ? -1 : after.current;
            if (browsed && TaskRules.credited(cumulative,afterFrame.cumulative(),before.current,afterCount)) {
                if (cumulative >= 0 && cumulative < 50 || afterCount == lastRow) { ok=true; break; }
            }
            lastRow=afterCount; service.pause(800);
        }
        if (ok) {
            credited++; failures.remove(key); RunLog.add("已确认记账「"+key+"」");
        } else {
            int count=failures.getOrDefault(key,0)+1; failures.put(key,count);
            RunLog.add("未确认记账「"+key+"」"+(count>=2 ? "，本轮跳过" : "，最多再试一次"));
        }
    }
    private boolean browse(String title, String external) throws Exception {
        Frame first=read();
        if (first.panel()) { service.pause(900); first=read(); if (first.panel()) return false; }
        if (!external.isEmpty() && TaskRules.TAOBAO.equals(first.pkg)) {
            for (String label : new String[]{"打开App","打开应用","立即打开","去打开","打开看看"}) {
                Frame.Node button=first.exact(label);
                if (button != null) { service.tap(first,button); service.pause(1800); first=read(); break; }
            }
        }
        if (title.contains("搜")) {
            if (!TaskRules.TAOBAO.equals(first.pkg) || !service.setSearchText("iphone16")) {
                RunLog.add("搜索框不支持直接输入，保留给手动完成"); return false;
            }
            service.pause(450); Frame search=read(); Frame.Node button=search.exact("搜索");
            if (button == null || button.editable) return false;
            service.tap(search,button); service.pause(1800);
        }
        long until=android.os.SystemClock.elapsedRealtime()+TaskRules.dwellSeconds(title)*1000L;
        while (android.os.SystemClock.elapsedRealtime()<until) {
            Frame frame=read();
            if (frame.panel()) return false;
            service.swipe(frame,.73f,.47f); service.pause(2200);
        }
        return true;
    }
    private void backToPanel() throws Exception {
        for (int i=0;i<5;i++) {
            if (!TaskRules.TAOBAO.equals(service.foreground())) { service.launchTaobao(); continue; }
            Frame frame=read();
            if (frame.panel()) { service.expectExternal(""); return; }
            if (coin(frame)) { openPanel(); service.expectExternal(""); return; }
            service.back();
        }
        throw new Stop("无法返回任务面板，已保留当前页面");
    }
    private void claimRewards() throws Exception {
        for (int i=0;i<3;i++) {
            Frame frame=read(); if (!frame.panel()) return;
            int firstRow=frame.height;
            for (Frame.Task task : frame.tasks()) firstRow=Math.min(firstRow,task.button.top);
            Frame.Node target=null;
            for (Frame.Node n:frame.nodes) if (n.label().equals("立即领取") && frame.inPanel(n) && n.top<firstRow) { target=n; break; }
            if (target==null) return;
            service.tap(frame,target); service.pause(1000);
            Frame after=read();
            if (dismiss(after)) after=read();
            // Confirm the claim button at this reward position disappeared before counting it.
            boolean remains=false;
            for (Frame.Node n:after.nodes) if (n.label().equals("立即领取") && Math.abs(n.y()-target.y())<frame.height*.025
                    && Math.abs(n.x()-target.x())<frame.width*.12) { remains=true; break; }
            if (after.panel() && !remains) { rewards++; RunLog.add("累计奖励领取按钮已更新"); }
            else { RunLog.add("累计奖励领取结果未确认"); return; }
        }
    }
    private void closePanel() throws Exception {
        Frame frame=read(); if (frame.panel()) { service.back(); service.pause(600); }
    }
    private boolean dismiss(Frame frame) throws Exception {
        String text=frame.text();
        boolean activity=text.contains("解锁") || text.contains("车轮") || text.contains("尾翼") || text.contains("送你能量")
                || text.contains("升级赛车拿钱") || frame.panel();
        if (!activity) return false;
        if (text.contains("送你能量最高")) {
            Frame.Node close=frame.exact("关闭");
            if (close!=null) { service.tap(frame,close); service.pause(700); return true; }
        }
        for (String label:new String[]{"确认选择","我知道了","以后再说","暂不"}) {
            Frame.Node button=frame.exact(label);
            if (button!=null) { service.tap(frame,button); service.pause(700); return true; }
        }
        return false;
    }
    private void race() throws Exception {
        RunLog.state("正在消耗赛车能量");
        int previous=-1,stuck=0,missing=0,zero=0;
        for (int i=0;i<250;i++) {
            Frame frame=read(); if (dismiss(frame)) continue;
            Frame.Node button=frame.raceButton();
            int energy=TaskRules.energy(frame.text());
            if (button==null || energy<0) {
                if (++missing>=3) throw new Stop("无法确认赛车按钮或余额，请手动打开赛车页；未确认能量耗尽");
                service.pause(1000); continue;
            }
            missing=0;
            if (previous<0) RunLog.add("赛车开始余额："+energy);
            RunLog.state("赛车剩余能量 · "+energy);
            if (energy==0) {
                if (++zero>=2) { RunLog.add("已连续两次确认剩余能量为 0"); return; }
                service.pause(1200); continue;
            }
            zero=0;
            stuck=energy==previous ? stuck+1 : 0;
            if (stuck>=3) { RunLog.add("连续三次长按余额未下降，实际剩余 "+energy+" 能量"); return; }
            previous=energy; service.hold(frame,button); service.pause(900);
        }
        throw new Stop("已达到赛车操作上限，请核对剩余能量");
    }
}
