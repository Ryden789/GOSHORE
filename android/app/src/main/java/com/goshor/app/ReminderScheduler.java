package com.goshor.app;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.provider.Settings;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;

/**
 * N2 学习提醒 · 排程与通知（AlarmManager 精确闹钟 + 本地通知，不引 WorkManager）。
 *
 * 设计要点：
 * 1. **每日一次 + 触发后重排次日**：不用 setRepeating（Doze 下会被延迟/丢弃），
 *    每次在接收器里重排下一天，保证长期可靠。
 * 2. **精确闹钟可降级**：Android 12+ 需要 SCHEDULE_EXACT_ALARM 才允许
 *    setExactAndAllowWhileIdle；拿不到就退回 setAndAllowWhileIdle（允许不精确）。
 * 3. **考前 7/3/1 天额外提醒**：一次性闹钟，固定在当天 10:00（与每日提醒时间错开，
 *    避免同一时刻弹两条）。
 * 4. **按计划提醒**：原生读不到 Python 的计划表，改由前端在首页/计划页把
 *    「今日计划完成度」写进 SharedPreferences（{@link #setPlanState}），
 *    接收器据此决定是否打扰——纯离线、不依赖网络。
 * 5. 所有状态存 SharedPreferences，供开机广播（{@link BootReceiver}）重排。
 */
final class ReminderScheduler {

    static final String CHANNEL_ID = "study";
    private static final String CHANNEL_NAME = "学习提醒";
    private static final String PREFS = "goshore_reminder";

    private static final String K_ON = "on";
    private static final String K_TIME = "time";
    private static final String K_PLAN_ONLY = "plan_only";
    private static final String K_EXAM = "exam_date";
    private static final String K_PLAN_DAY = "plan_day";
    private static final String K_PLAN_DONE = "plan_done";
    private static final String K_PLAN_TOTAL = "plan_total";

    static final String EXTRA_KIND = "kind";
    static final String KIND_DAILY = "daily";
    static final String KIND_EXAM = "exam";

    /** 请求码：每日与三个考前提醒互不覆盖 */
    private static final int RC_DAILY = 9001;
    private static final int RC_EXAM_7 = 9107;
    private static final int RC_EXAM_3 = 9103;
    private static final int RC_EXAM_1 = 9101;

    static final int NOTIFY_ID_DAILY = 8101;
    static final int NOTIFY_ID_EXAM = 8102;

    /** 考前提醒固定时间（与每日提醒错开，避免同一时刻两条通知） */
    private static final int EXAM_HOUR = 10;
    private static final int EXAM_MIN = 0;

    private ReminderScheduler() {
    }

    /* ==================== 偏好读写 ==================== */

    private static SharedPreferences prefs(Context c) {
        return c.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static boolean isOn(Context c) {
        return prefs(c).getBoolean(K_ON, false);
    }

    static String timeOf(Context c) {
        return prefs(c).getString(K_TIME, "20:00");
    }

    static boolean planOnlyOf(Context c) {
        return prefs(c).getBoolean(K_PLAN_ONLY, false);
    }

    static String examDateOf(Context c) {
        return prefs(c).getString(K_EXAM, "");
    }

    /** 前端同步「今日计划完成度」：接收器据此判断 planOnly 要不要打扰 */
    static void setPlanState(Context c, String day, int done, int total) {
        prefs(c).edit()
                .putString(K_PLAN_DAY, day == null ? "" : day)
                .putInt(K_PLAN_DONE, done)
                .putInt(K_PLAN_TOTAL, total)
                .apply();
    }

    /** 当天计划是否已完成（无计划 → 视为未完成，该提醒还是要提醒） */
    static boolean planDoneToday(Context c) {
        SharedPreferences p = prefs(c);
        if (!today().equals(p.getString(K_PLAN_DAY, ""))) return false;
        int total = p.getInt(K_PLAN_TOTAL, 0);
        return total > 0 && p.getInt(K_PLAN_DONE, 0) >= total;
    }

    /* ==================== 通知渠道 ==================== */

    static void ensureChannel(Context c) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null || nm.getNotificationChannel(CHANNEL_ID) != null) return;
        NotificationChannel ch = new NotificationChannel(
                CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_HIGH);
        ch.setDescription("每日学习提醒与考前提醒");
        ch.enableVibration(true);
        nm.createNotificationChannel(ch);
    }

    /** 渠道被用户在系统里关掉也算「通知不可达」 */
    private static boolean channelBlocked(Context c) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return false;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) return false;
        NotificationChannel ch = nm.getNotificationChannel(CHANNEL_ID);
        return ch != null && ch.getImportance() == NotificationManager.IMPORTANCE_NONE;
    }

    static boolean exactAllowed(Context c) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true;   // 12 以下无需授权
        AlarmManager am = c.getSystemService(AlarmManager.class);
        return am != null && am.canScheduleExactAlarms();
    }

    /** 给前端看的可读状态（中文，直接 toast / 展示） */
    static String status(Context c) {
        if (!isOn(c)) return "已关闭";
        StringBuilder sb = new StringBuilder();
        sb.append("已开启 · 每日 ").append(timeOf(c));
        if (planOnlyOf(c)) sb.append("（仅当天计划未完成时）");
        String ex = examDateOf(c);
        if (ex != null && !ex.isEmpty()) sb.append(" · 考前 7/3/1 天另提醒");
        if (!exactAllowed(c)) sb.append(" · 系统未授权精确闹钟，提醒可能略有延迟");
        return sb.toString();
    }

    /* ==================== 排程 ==================== */

    /**
     * 保存配置并重排全部闹钟。
     *
     * @param hhmm    'HH:mm'，非法则退回 20:00
     * @param examDate 'YYYY-MM-DD'，可为空
     * @return 给前端的状态文案（成功 / 缺权限原因）
     */
    static String schedule(Context c, boolean on, String hhmm, boolean planOnly,
                           String examDate) {
        String t = normalize(hhmm);
        prefs(c).edit()
                .putBoolean(K_ON, on)
                .putString(K_TIME, t)
                .putBoolean(K_PLAN_ONLY, planOnly)
                .putString(K_EXAM, examDate == null ? "" : examDate.trim())
                .apply();
        ensureChannel(c);
        cancelAll(c);
        if (!on) return "已关闭学习提醒";
        applyAll(c);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && !hasNotifyPermission(c)) {
            return "已保存，但系统通知权限未开启，请到「系统设置 → 通知」允许本应用通知";
        }
        if (channelBlocked(c)) {
            return "已保存，但「学习提醒」通知渠道被系统关闭，请到通知设置里打开";
        }
        return status(c);
    }

    static String cancel(Context c) {
        prefs(c).edit().putBoolean(K_ON, false).apply();
        cancelAll(c);
        return "已关闭学习提醒";
    }

    /** 开机 / 应用更新后重排（供 BootReceiver 调用） */
    static void rescheduleFromPrefs(Context c) {
        if (!isOn(c)) return;
        ensureChannel(c);
        cancelAll(c);
        applyAll(c);
    }

    private static void applyAll(Context c) {
        scheduleDaily(c);
        scheduleExamAlerts(c);
    }

    /** 每日闹钟触发后重排次日（考前提醒是一次性的，不重排） */
    static void rescheduleDailyOnly(Context c) {
        if (!isOn(c)) return;
        scheduleDaily(c);
    }

    private static void scheduleDaily(Context c) {
        String t = timeOf(c);
        long at = nextDailyTrigger(t);
        Intent i = new Intent(c, ReminderReceiver.class)
                .setAction(ReminderReceiver.ACTION_DAILY)
                .putExtra(EXTRA_KIND, KIND_DAILY);
        setAlarm(c, at, RC_DAILY, i);
    }

    private static void scheduleExamAlerts(Context c) {
        String ex = examDateOf(c);
        if (ex == null || ex.isEmpty()) return;
        Date exam = parseDate(ex);
        if (exam == null) return;
        int[] ahead = {7, 3, 1};
        int[] codes = {RC_EXAM_7, RC_EXAM_3, RC_EXAM_1};
        for (int k = 0; k < ahead.length; k++) {
            long at = examMinusDays(exam, ahead[k]);
            if (at <= System.currentTimeMillis()) continue;
            Intent i = new Intent(c, ReminderReceiver.class)
                    .setAction(ReminderReceiver.ACTION_EXAM)
                    .putExtra(EXTRA_KIND, KIND_EXAM)
                    .putExtra("ahead", ahead[k]);
            setAlarm(c, at, codes[k], i);
        }
    }

    /** 精确闹钟不可用时退回不精确版本（Doze 下可能被推迟几分钟到几小时） */
    private static void setAlarm(Context c, long at, int reqCode, Intent intent) {
        AlarmManager am = c.getSystemService(AlarmManager.class);
        if (am == null) return;
        PendingIntent pi = PendingIntent.getBroadcast(c, reqCode, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        try {
            if (exactAllowed(c)) {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
            } else {
                am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
            }
        } catch (SecurityException e) {
            // 极端情况：刚被系统收回权限，降级重试一次
            try {
                am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
            } catch (Exception ignored) {
                // 排程彻底失败也不能崩，前端会看到状态文案
            }
        }
    }

    private static void cancelAll(Context c) {
        AlarmManager am = c.getSystemService(AlarmManager.class);
        if (am == null) return;
        for (int rc : new int[]{RC_DAILY, RC_EXAM_7, RC_EXAM_3, RC_EXAM_1}) {
            Intent i = new Intent(c, ReminderReceiver.class);
            PendingIntent pi = PendingIntent.getBroadcast(c, rc, i,
                    PendingIntent.FLAG_NO_CREATE | PendingIntent.FLAG_IMMUTABLE);
            if (pi != null) {
                am.cancel(pi);
                pi.cancel();
            }
        }
    }

    /* ==================== 通知 ==================== */

    @SuppressWarnings("deprecation")
    static void notify(Context c, String title, String text, int id) {
        ensureChannel(c);
        Intent open = new Intent(c, MainActivity.class)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(MainActivity.EXTRA_ROUTE, "home");
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        PendingIntent pi = PendingIntent.getActivity(c, id, open, flags);

        Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(c, CHANNEL_ID)
                : new Notification.Builder(c);
        b.setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setAutoCancel(true)
                .setContentIntent(pi);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) {
            try {
                nm.notify(id, b.build());
            } catch (SecurityException ignored) {
                // 通知权限被撤销：静默失败，不影响其他功能
            }
        }
    }

    /* ==================== 时间计算 ==================== */

    static boolean hasNotifyPermission(Context c) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true;
        return c.checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    /** 是否被系统禁止弹通知（用户手动关过） */
    static boolean notificationsDisabled(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        return nm != null && !nm.areNotificationsEnabled();
    }

    static String openNotificationSettings(Context c) {
        try {
            Intent i = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, c.getPackageName())
                    .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            c.startActivity(i);
            return "已打开系统通知设置";
        } catch (Exception e) {
            try {
                Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                        .setData(android.net.Uri.parse("package:" + c.getPackageName()))
                        .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                c.startActivity(i);
                return "已打开应用详情页";
            } catch (Exception e2) {
                return "ERROR:无法打开系统设置，请手动进入「设置 → 应用 → 上岸自习室 → 通知」";
            }
        }
    }

    /** 'H:mm' / 'HH:mm' → 'HH:mm'；非法退回 20:00 */
    static String normalize(String hhmm) {
        if (hhmm == null) return "20:00";
        String s = hhmm.trim();
        if (s.length() == 4 && s.charAt(1) == ':') s = "0" + s;   // 9:05 → 09:05
        if (s.matches("^([01]\\d|2[0-3]):[0-5]\\d$")) return s;
        return "20:00";
    }

    /** 下一个 'HH:mm' 的绝对毫秒（今天已过则顺延到明天） */
    static long nextDailyTrigger(String hhmm) {
        String t = normalize(hhmm);
        int h = Integer.parseInt(t.substring(0, 2));
        int m = Integer.parseInt(t.substring(3, 5));
        Calendar cal = Calendar.getInstance();
        cal.set(Calendar.HOUR_OF_DAY, h);
        cal.set(Calendar.MINUTE, m);
        cal.set(Calendar.SECOND, 0);
        cal.set(Calendar.MILLISECOND, 0);
        if (cal.getTimeInMillis() <= System.currentTimeMillis()) {
            cal.add(Calendar.DAY_OF_YEAR, 1);
        }
        return cal.getTimeInMillis();
    }

    private static Date parseDate(String iso) {
        try {
            return new SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(iso.trim());
        } catch (Exception e) {
            return null;
        }
    }

    /** 考前 N 天的 10:00（本地时区） */
    private static long examMinusDays(Date exam, int ahead) {
        Calendar cal = Calendar.getInstance();
        cal.setTime(exam);
        cal.add(Calendar.DAY_OF_YEAR, -ahead);
        cal.set(Calendar.HOUR_OF_DAY, EXAM_HOUR);
        cal.set(Calendar.MINUTE, EXAM_MIN);
        cal.set(Calendar.SECOND, 0);
        cal.set(Calendar.MILLISECOND, 0);
        return cal.getTimeInMillis();
    }

    static String today() {
        return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
    }
}
