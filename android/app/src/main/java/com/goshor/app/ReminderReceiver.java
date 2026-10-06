package com.goshor.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * N2 学习提醒 · 闹钟接收器。
 *
 * 每日提醒触发后**立刻重排次日**（不用 setRepeating，Doze 下会漂移甚至丢失）；
 * 考前提醒是一次性的，触发即结束。
 */
public class ReminderReceiver extends BroadcastReceiver {

    static final String ACTION_DAILY = "com.goshor.app.REMIND_DAILY";
    static final String ACTION_EXAM = "com.goshor.app.REMIND_EXAM";

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? "" : intent.getAction();
        if (!ReminderScheduler.isOn(context)) return;   // 已关闭：什么都不做

        if (ACTION_EXAM.equals(action)) {
            int ahead = intent.getIntExtra("ahead", 0);
            ReminderScheduler.notify(context,
                    "考试临近 · 还有 " + ahead + " 天",
                    ahead <= 1
                            ? "明天就考试了。今天只做一件事：把错题本过一遍，早点睡。"
                            : "距离考试还有 " + ahead + " 天，建议按计划完成今日题量，别再开新坑。",
                    ReminderScheduler.NOTIFY_ID_EXAM);
            return;
        }

        // 每日提醒：按计划提醒时，当天计划已完成就不打扰
        if (ReminderScheduler.planOnlyOf(context)
                && ReminderScheduler.planDoneToday(context)) {
            ReminderScheduler.rescheduleDailyOnly(context);
            return;
        }
        if (ReminderScheduler.notificationsDisabled(context)) {
            ReminderScheduler.rescheduleDailyOnly(context);
            return;
        }
        ReminderScheduler.notify(context,
                "该学习了",
                "今天的学习计划还没完成，花 15 分钟做几道题，保持连续学习。",
                ReminderScheduler.NOTIFY_ID_DAILY);
        ReminderScheduler.rescheduleDailyOnly(context);
    }
}
