package io.github.taobaotasks.assistant;

import android.content.Context;
import android.content.SharedPreferences;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Keeps a bounded, private local activity record, not screen contents. */
final class RunLog {
    private static SharedPreferences prefs;
    private static String lines = "";
    private static String state = "尚未运行";
    static synchronized void init(Context context) {
        if (prefs != null) return;
        prefs = context.getSharedPreferences("run", Context.MODE_PRIVATE);
        lines = prefs.getString("log", "");
        state = "就绪 · 上次记录保留在本机";
    }
    static synchronized void reset() { lines = ""; state = "正在准备"; save(); }
    static synchronized void add(String message) {
        String time = new SimpleDateFormat("HH:mm:ss", Locale.ROOT).format(new Date());
        lines += time + "  " + message + "\n";
        String[] split = lines.split("\n");
        if (split.length > 200) {
            StringBuilder tail = new StringBuilder();
            for (int i = split.length - 200; i < split.length; i++) tail.append(split[i]).append('\n');
            lines = tail.toString();
        }
        save();
    }
    static synchronized void state(String value) { state = value; }
    static synchronized String state() { return state; }
    static synchronized String lines() { return lines; }
    private static void save() { if (prefs != null) prefs.edit().putString("log", lines).apply(); }
}
