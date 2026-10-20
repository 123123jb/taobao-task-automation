package io.github.taobaotasks.assistant;

import org.junit.Test;
import static org.junit.Assert.*;

public class TaskRulesTest {
    @Test public void durationUsesWholeNumberAndSupportsS() {
        assertEquals(27, TaskRules.dwellSeconds("浏览25秒"));
        assertEquals(17, TaskRules.dwellSeconds("浏览15s得400能量"));
    }
    @Test public void identityIgnoresProgressAndReward() {
        assertEquals(TaskRules.key("好物沉浸看(3/10)浏览15秒+400"),
                TaskRules.key("好物沉浸看（4/10）浏览15s得400能量"));
    }
    @Test public void skipsSpendingAndInvitations() {
        assertTrue(TaskRules.skip("积分兑换能量"));
        assertTrue(TaskRules.skip("邀请好友成功助力"));
        assertFalse(TaskRules.skip("好物沉浸看(0/10)浏览15秒"));
    }
    @Test public void saturatedCumulativeCanUseVerifiedRowProgress() {
        assertTrue(TaskRules.credited(50, 50, 2, 3));
        assertFalse(TaskRules.credited(50, 50, 2, 2));
    }
    @Test public void cumulativeOverridesStaleReorderedRows() {
        assertFalse(TaskRules.credited(20, 20, 2, 8));
        assertTrue(TaskRules.credited(20, 21, 2, -1));
    }
    @Test public void missingCountersCannotClaimCredit() {
        assertFalse(TaskRules.credited(-1, -1, 0, -1));
    }
    @Test public void energyRequiresRemainingEnergyLabel() {
        assertEquals(30660, TaskRules.energy("第12笔¥1.18 升级赛车拿钱 剩余30660能量"));
        assertEquals(-1, TaskRules.energy("奖励2000能量"));
    }
    @Test public void detectsHumanVerificationWithoutTreatingOrdinaryTextAsCaptcha() {
        assertTrue(TaskRules.verification("请拖动下方滑块完成验证"));
        assertFalse(TaskRules.verification("浏览15秒"));
    }
}
