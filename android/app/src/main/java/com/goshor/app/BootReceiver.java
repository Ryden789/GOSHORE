package com.goshor.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * N2 学习提醒 · 开机重排。
 *
 * AlarmManager 的闹钟在关机后全部丢失，必须监听 BOOT_COMPLETED 重新排程
 * （以及应用被系统更新/替换后的 MY_PACKAGE_REPLACED）。
 */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? "" : intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
                && !"android.intent.action.QUICKBOOT_POWERON".equals(action)) {
            return;
        }
        ReminderScheduler.ensureChannel(context);
        ReminderScheduler.rescheduleFromPrefs(context);
    }
}
