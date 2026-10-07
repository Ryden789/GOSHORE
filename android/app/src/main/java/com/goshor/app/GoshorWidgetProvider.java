package com.goshor.app;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.widget.RemoteViews;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;

/**
 * G8 安卓桌面小组件：不打开 APP 就能看到「距考试天数 + 今日任务完成度」，点一下进 APP。
 *
 * 设计要点：
 * 1. **数据来源是 SharedPreferences，不是 SQLite**：小组件跑在 launcher 进程里，
 *    不可能启动 Chaquopy/Python。所以由 APP 在前端渲染首页/计划页时把
 *    「考试日期 + 今日计划完成度」推给原生（{@link #push}），小组件只读这份快照。
 * 2. **两种刷新时机**：APP 内数据变化 → 前端调 push 立即重画；APP 没开时靠
 *    系统按 {@code updatePeriodMillis}（30 分钟）发 APPWIDGET_UPDATE → onUpdate 重算天数。
 *    天数由 exam_date 现算，所以跨天不会停在旧数字。
 * 3. **跨天保护**：快照里带 day，若不是今天，今日进度按 0 显示，避免昨天做完了
 *    今天一开屏还写着「30/30」。
 * 4. 不引额外依赖，纯 RemoteViews（LinearLayout + TextView + ProgressBar）。
 */
public class GoshorWidgetProvider extends AppWidgetProvider {

    private static final String PREFS = "goshore_widget";
    private static final String K_EXAM = "exam_date";
    private static final String K_DAY = "day";
    private static final String K_DONE = "done";
    private static final String K_TOTAL = "total";

    /** 前端每次渲染首页/计划页调一次（见 m.js 的 syncWidget）。 */
    static void push(Context c, String examDate, int done, int total) {
        Context ctx = c.getApplicationContext();
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString(K_EXAM, examDate == null ? "" : examDate.trim())
                .putString(K_DAY, today())
                .putInt(K_DONE, Math.max(0, done))
                .putInt(K_TOTAL, Math.max(0, total))
                .apply();
        refresh(ctx);
    }

    @Override
    public void onUpdate(Context c, AppWidgetManager mgr, int[] ids) {
        RemoteViews v = build(c.getApplicationContext());
        for (int id : ids) {
            mgr.updateAppWidget(id, v);
        }
    }

    /** 重画所有已放置的小组件（无实例时直接返回，不做事）。 */
    static void refresh(Context c) {
        AppWidgetManager mgr = AppWidgetManager.getInstance(c);
        if (mgr == null) return;
        int[] ids = mgr.getAppWidgetIds(
                new ComponentName(c, GoshorWidgetProvider.class));
        if (ids == null || ids.length == 0) return;
        RemoteViews v = build(c);
        for (int id : ids) {
            mgr.updateAppWidget(id, v);
        }
    }

    private static RemoteViews build(Context c) {
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.goshor_widget);
        SharedPreferences p = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);

        v.setTextViewText(R.id.wgDays, daysText(p.getString(K_EXAM, "")));

        int done = p.getInt(K_DONE, 0);
        int total = p.getInt(K_TOTAL, 0);
        if (!today().equals(p.getString(K_DAY, ""))) {
            done = 0;          // 昨天的完成度不能当成今天的
            total = 0;
        }
        if (total > 0) {
            if (done > total) done = total;
            v.setTextViewText(R.id.wgPlan, "今日 " + done + "/" + total + " 题");
            v.setProgressBar(R.id.wgBar, total, done, false);
        } else {
            v.setTextViewText(R.id.wgPlan, "今日暂无计划");
            v.setProgressBar(R.id.wgBar, 1, 0, false);
        }

        Intent open = new Intent(c, MainActivity.class)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(MainActivity.EXTRA_ROUTE, "home");
        PendingIntent pi = PendingIntent.getActivity(c, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        v.setOnClickPendingIntent(R.id.wgRoot, pi);
        return v;
    }

    /** 'YYYY-MM-DD' → 「距考试 N 天 / 明天考试 / 今天考试」；空或非法 → 未设置。 */
    static String daysText(String iso) {
        int d = daysLeft(iso);
        if (d == Integer.MIN_VALUE) return "未设置考试日期";
        if (d > 1) return "距考试 " + d + " 天";
        if (d == 1) return "明天考试";
        if (d == 0) return "今天考试";
        return "考试已结束";
    }

    /** 距考试的自然日差；空串 / 非法日期返回 {@link Integer#MIN_VALUE}。 */
    static int daysLeft(String iso) {
        if (iso == null || iso.trim().isEmpty()) return Integer.MIN_VALUE;
        try {
            SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
            f.setLenient(false);
            Date d = f.parse(iso.trim());
            if (d == null) return Integer.MIN_VALUE;
            Calendar a = dayStart();
            a.setTime(d);
            Calendar b = dayStart();
            long ms = a.getTimeInMillis() - b.getTimeInMillis();
            // 用 round 而非整除：夏令时地区的"一天"可能是 23 或 25 小时
            return (int) Math.round(ms / 86400000.0);
        } catch (Exception e) {
            return Integer.MIN_VALUE;
        }
    }

    private static Calendar dayStart() {
        Calendar cal = Calendar.getInstance();
        cal.set(Calendar.HOUR_OF_DAY, 0);
        cal.set(Calendar.MINUTE, 0);
        cal.set(Calendar.SECOND, 0);
        cal.set(Calendar.MILLISECOND, 0);
        return cal;
    }

    private static String today() {
        return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
    }
}
