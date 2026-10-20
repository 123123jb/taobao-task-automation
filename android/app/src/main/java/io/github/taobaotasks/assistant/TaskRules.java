package io.github.taobaotasks.assistant;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class TaskRules {
    static final String TAOBAO = "com.taobao.taobao";
    static final Pattern PROGRESS = Pattern.compile("[（(]\\s*(\\d+)\\s*/\\s*(\\d+)\\s*[）)]");
    private static final String[] SKIP = {"邀请", "助力", "每拉", "拉好友", "拉1人", "拉新", "分享给", "分享好友",
            "积分换", "积分兑", "兑换能量", "充值", "开通", "办卡", "开户", "付款", "转账",
            "下单", "购买", "预约", "订阅", "答题", "考试", "游戏", "小组件"};

    static int[] progress(String title) {
        Matcher m = PROGRESS.matcher(title);
        return m.find() ? new int[]{number(m.group(1)), number(m.group(2))} : new int[]{-1, -1};
    }

    static String key(String title) {
        Matcher m = PROGRESS.matcher(title);
        return (m.find() ? title.substring(0, m.start()) : title).trim();
    }

    static int dwellSeconds(String title) {
        Matcher m = Pattern.compile("(\\d+)\\s*(?:秒|s\\b|s(?=得))", Pattern.CASE_INSENSITIVE).matcher(title);
        return m.find() ? Math.min(120, number(m.group(1)) + 2) : 17;
    }

    static boolean skip(String title) {
        for (String word : SKIP) if (title.contains(word)) return true;
        return false;
    }

    static boolean credited(int cumulativeBefore, int cumulativeAfter, int rowBefore, int rowAfter) {
        if (cumulativeBefore >= 0 && cumulativeBefore < 50 && cumulativeAfter >= 0) {
            return cumulativeAfter > cumulativeBefore;
        }
        return rowBefore >= 0 && rowAfter > rowBefore;
    }

    static boolean verification(String text) {
        return text.contains("验证") && (text.contains("滑块") || text.contains("滑动") || text.contains("拖动"));
    }

    static boolean needsLogin(String text) {
        return text.contains("验证码登录") || text.contains("密码登录") || text.contains("登录后")
                || text.contains("登录/注册") || (text.contains("登录")
                && (text.contains("验证码") || text.contains("手机号码") || text.contains("密码")));
    }

    static int energy(String text) {
        Matcher m = Pattern.compile("剩余\\s*(\\d+)\\s*能量").matcher(text);
        return m.find() ? number(m.group(1)) : -1;
    }

    private static int number(String value) {
        try { return Integer.parseInt(value); }
        catch (NumberFormatException ignored) { return -1; }
    }
}
