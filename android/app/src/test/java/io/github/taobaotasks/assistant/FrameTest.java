package io.github.taobaotasks.assistant;

import org.junit.Test;
import static org.junit.Assert.*;

public class FrameTest {
    private Frame.Node node(String text, int parent, int top, boolean clickable) {
        return new Frame.Node(text, "", "", "", parent, 10, top, 900, top+60, clickable, false);
    }
    @Test public void nativePanelExcludesUnderlyingPageButtons() {
        Frame f = new Frame(TaskRules.TAOBAO, 1080, 2400, false);
        f.nodes.add(node("底层商品(0/1)", -1, 600, false));
        f.nodes.add(node("去完成", 0, 600, true));
        f.nodes.add(node("", -1, 400, false));
        f.nodes.add(node("做任务赚能量", 2, 440, false));
        f.nodes.add(node("累计任务奖励", 2, 500, false));
        f.nodes.add(node("50/50", 2, 560, false));
        f.nodes.add(node("", 2, 700, false));
        f.nodes.add(node("好物沉浸看(2/5)浏览15秒", 6, 700, false));
        f.nodes.add(node("去完成", 6, 700, true));
        assertEquals(50, f.cumulative());
        assertEquals(1, f.tasks().size());
        assertEquals("好物沉浸看", f.tasks().get(0).key);
    }
    @Test public void visualRowsPairOnlyNearbyTaskLabelsWithButtons() {
        Frame f = new Frame(TaskRules.TAOBAO, 1080, 2400, true);
        f.nodes.add(node("做任务赚能量", -1, 440, false));
        f.nodes.add(node("累计任务奖励", -1, 500, false));
        f.nodes.add(node("商品推荐(0/1)", -1, 200, false));
        f.nodes.add(node("好物沉浸看(2/5)", -1, 700, false));
        f.nodes.add(node("去完成", -1, 700, true));
        f.nodes.add(node("已完成", -1, 1500, true));
        assertEquals(1, f.tasks().size());
    }
    @Test public void aTaskWithFiftyRepetitionsIsNotTheCumulativeCounter() {
        Frame f = new Frame(TaskRules.TAOBAO, 1080, 2400, true);
        f.nodes.add(node("做任务赚能量", -1, 440, false));
        f.nodes.add(node("累计任务奖励", -1, 500, false));
        f.nodes.add(node("任务(2/50)", -1, 700, false));
        assertEquals(-1, f.cumulative());
    }
    @Test public void aWebViewSharedWithTheUnderlyingPageIsNotATaskPanelScope() {
        Frame f = new Frame(TaskRules.TAOBAO,1080,2400,false);
        f.nodes.add(new Frame.Node("", "", "", "android.webkit.WebView", -1, 0, 0, 1080, 2400,false,false));
        f.nodes.add(node("做任务赚能量",0,440,false));
        f.nodes.add(node("累计任务奖励",0,500,false));
        f.nodes.add(node("底层任务(0/1)",0,700,false));
        f.nodes.add(node("去完成",0,700,true));
        assertTrue(f.tasks().isEmpty());
    }
}
