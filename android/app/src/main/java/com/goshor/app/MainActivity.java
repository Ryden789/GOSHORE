package com.goshor.app;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * 独立版：首次启动从 payload.zip（纯 Java ZipInputStream 顺序解压）
 * 释放数据库与图片到内部存储，再用 Chaquopy 启动内置 Python 本地服务器，
 * WebView 指向 127.0.0.1。全部数据在手机本地，无需电脑。
 */
public class MainActivity extends Activity {

    private static final int BUF = 1 << 16;
    private static final String PAYLOAD = "payload.zip";

    private FrameLayout root;
    private WebView web;
    private View initBox;
    private TextView initMsg;
    private TextView initPct;
    private ProgressBar bar;
    private int lastPct = -1;

    private ValueCallback<Uri[]> filePathCallback;
    private static final int REQ_FILE_CHOOSER = 71001;

    private File dbFile, imgDir, webDir, readyMarker;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        root = new FrameLayout(this);
        setContentView(root);

        dbFile = new File(getFilesDir(), "goshor.db");
        imgDir = new File(getFilesDir(), "img");
        webDir = new File(getFilesDir(), "web");
        readyMarker = new File(getFilesDir(), "payload.ready");

        showInit();
        new Thread(this::bootstrap).start();
    }

    /* ================= 初始化界面 ================= */

    private void showInit() {
        LinearLayout lay = new LinearLayout(this);
        lay.setOrientation(LinearLayout.VERTICAL);
        lay.setGravity(Gravity.CENTER_HORIZONTAL);
        lay.setPadding(dp(32), 0, dp(32), 0);
        lay.setBackgroundColor(Color.rgb(244, 239, 230));

        TextView title = new TextView(this);
        title.setText("上岸自习室");
        title.setTextSize(26);
        title.setTypeface(android.graphics.Typeface.defaultFromStyle(android.graphics.Typeface.BOLD));
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        tp.topMargin = dp(120);
        title.setLayoutParams(tp);
        lay.addView(title);

        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        bp.topMargin = dp(40);
        bar.setLayoutParams(bp);
        bar.setMax(100);
        lay.addView(bar);

        initPct = new TextView(this);
        initPct.setText("0%");
        LinearLayout.LayoutParams pp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        pp.topMargin = dp(10);
        initPct.setLayoutParams(pp);
        initPct.setTextColor(Color.GRAY);
        lay.addView(initPct);

        initMsg = new TextView(this);
        initMsg.setText("正在准备学习资料…");
        initMsg.setTextColor(Color.GRAY);
        initMsg.setTextSize(13);
        LinearLayout.LayoutParams mp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        mp.topMargin = dp(8);
        initMsg.setLayoutParams(mp);
        lay.addView(initMsg);

        initBox = lay;
        root.addView(initBox, match());
    }

    /** UI 更新必须在主线程；按百分点限频，避免消息洪泛 */
    private void tick(final long done, final long total, final String msg) {
        final int p = total > 0 ? (int) (done * 100 / total) : 0;
        if (p == lastPct && msg == null) return;
        lastPct = p;
        runOnUiThread(() -> {
            bar.setProgress(p);
            initPct.setText(p + "%");
            if (msg != null) initMsg.setText(msg);
        });
    }

    /* ================= 数据释放（后台线程） ================= */

    private void bootstrap() {
        try {
            // 已有题库（首启解压过或被热更新替换过）时跳过 payload 解压；
            // 题库损坏则自动回滚 .bak，回滚不可用才重新解压 payload
            boolean needExtract = !readyMarker.exists() || !dbFile.exists();
            if (!needExtract && !checkBankDb(dbFile)) {
                File bak = new File(getFilesDir(), "goshor.db.bak");
                boolean rolledBack = false;
                if (bak.isFile() && checkBankDb(bak)) {
                    //noinspection ResultOfMethodCallIgnored
                    dbFile.delete();
                    rolledBack = bak.renameTo(dbFile);
                }
                if (rolledBack) {
                    runOnUiThread(() -> Toast.makeText(this,
                            "题库更新包损坏，已回滚到上一版本",
                            Toast.LENGTH_LONG).show());
                } else {
                    //noinspection ResultOfMethodCallIgnored
                    dbFile.delete();
                    //noinspection ResultOfMethodCallIgnored
                    readyMarker.delete();
                    needExtract = true;
                }
            }
            if (needExtract) {
                extractPayload();
            } else {
                runOnUiThread(() -> {
                    bar.setProgress(92);
                    initPct.setText("92%");
                    initMsg.setText("学习资料已就绪");
                });
            }

            // 前端体积小，每次覆盖以保持最新
            lastPct = -1;
            tick(0, 1, "准备界面…");
            copyAssetDir("web", webDir);

            // 启动 Python 本地服务
            tick(1, 1, "启动本地学习服务…");
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            Python py = Python.getInstance();
            int port = py.getModule("goshor_server")
                    .callAttr("start", dbFile.getAbsolutePath(),
                            imgDir.getAbsolutePath(), webDir.getAbsolutePath())
                    .toInt();

            final String url = "http://127.0.0.1:" + port + "/m/";
            runOnUiThread(() -> enterWebView(url));
        } catch (final Exception e) {
            runOnUiThread(() -> showError(e.getMessage()));
        }
    }

    /** 顺序解压 payload.zip：goshor.db → filesDir；img/** → imgDir */
    private void extractPayload() throws Exception {
        // 先统计未压缩总字节
        long total = 0;
        try (ZipInputStream z0 = openPayload()) {
            ZipEntry e;
            while ((e = z0.getNextEntry()) != null) {
                if (e.getSize() > 0) total += e.getSize();
            }
        }
        if (total == 0) total = 1;

        String canonImg = imgDir.getCanonicalPath();
        String canonFiles = getFilesDir().getCanonicalPath();
        long done = 0;
        byte[] buf = new byte[BUF];
        boolean imgStarted = false;

        try (ZipInputStream zis = openPayload()) {
            ZipEntry e;
            while ((e = zis.getNextEntry()) != null) {
                String name = e.getName();
                File out;
                if (name.equals("goshor.db")) {
                    out = dbFile;
                } else if (name.startsWith("img/")) {
                    if (!imgStarted) {
                        imgStarted = true;
                        tick(done, total, "释放题目图片（约 2.2 万张）…");
                    }
                    out = new File(imgDir, name.substring(4));
                } else {
                    continue;
                }
                String canonOut = out.getCanonicalPath();
                if (!(canonOut.startsWith(canonImg + File.separator)
                        || canonOut.equals(dbFile.getCanonicalPath())
                        || canonOut.startsWith(canonFiles + File.separator))) {
                    throw new SecurityException("非法路径: " + name);
                }
                if (e.isDirectory()) {
                    //noinspection ResultOfMethodCallIgnored
                    out.mkdirs();
                    continue;
                }
                //noinspection ResultOfMethodCallIgnored
                out.getParentFile().mkdirs();
                try (OutputStream os = new FileOutputStream(out)) {
                    int n;
                    while ((n = zis.read(buf)) > 0) {
                        os.write(buf, 0, n);
                        done += n;
                        tick(done, total, null);
                    }
                }
            }
        }
        //noinspection ResultOfMethodCallIgnored
        readyMarker.createNewFile();
    }

    private ZipInputStream openPayload() throws Exception {
        InputStream in = getAssets().open(PAYLOAD);
        return new ZipInputStream(in);
    }

    /** 题库可用性校验：能打开且 documents 有题；损坏（热更新包不完整等）返回 false */
    private boolean checkBankDb(File f) {
        SQLiteDatabase d = null;
        try {
            d = SQLiteDatabase.openDatabase(f.getAbsolutePath(), null,
                    SQLiteDatabase.OPEN_READONLY);
            try (Cursor c = d.rawQuery("SELECT COUNT(*) FROM documents", null)) {
                return c.moveToFirst() && c.getLong(0) > 0;
            }
        } catch (Exception e) {
            return false;
        } finally {
            if (d != null) d.close();
        }
    }

    /** 递归复制 asset 目录 */
    private void copyAssetDir(String path, File dst) throws Exception {
        String[] children = getAssets().list(path);
        if (children == null || children.length == 0) {
            try (InputStream in = getAssets().open(path);
                 OutputStream out = new FileOutputStream(dst)) {
                byte[] buf = new byte[BUF];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
        } else {
            //noinspection ResultOfMethodCallIgnored
            dst.mkdirs();
            for (String c : children) copyAssetDir(path + "/" + c, new File(dst, c));
        }
    }

    /* ================= WebView ================= */

    private void enterWebView(String url) {
        root.removeView(initBox);

        WebView.setWebContentsDebuggingEnabled(true);
        web = new WebView(this);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setUseWideViewPort(true);
        ws.setLoadWithOverviewMode(true);
        ws.setSupportZoom(false);
        ws.setBuiltInZoomControls(false);
        ws.setDatabaseEnabled(true);
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(android.webkit.ConsoleMessage cm) {
                android.util.Log.println(
                        cm.messageLevel() == android.webkit.ConsoleMessage.MessageLevel.ERROR
                                ? android.util.Log.ERROR : android.util.Log.INFO,
                        "mweb", cm.message() + " @" + cm.sourceId() + ":" + cm.lineNumber());
                return true;
            }

            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb,
                    FileChooserParams params) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = cb;
                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("application/zip");
                try {
                    startActivityForResult(Intent.createChooser(intent, "选择备份 zip"),
                            REQ_FILE_CHOOSER);
                } catch (Exception e) {
                    filePathCallback = null;
                    return false;
                }
                return true;
            }
        });
        web.addJavascriptInterface(new NativeBridge(this), "GoshorNative");
        root.addView(web, match());
        web.loadUrl(url);
    }

    private void showError(String msg) {
        LinearLayout lay = new LinearLayout(this);
        lay.setOrientation(LinearLayout.VERTICAL);
        lay.setGravity(Gravity.CENTER);
        lay.setPadding(dp(28), 0, dp(28), 0);
        lay.setBackgroundColor(Color.rgb(244, 239, 230));

        TextView tv = new TextView(this);
        tv.setText("启动失败\n\n" + (msg == null ? "" : msg));
        tv.setGravity(Gravity.CENTER);
        tv.setTextColor(Color.rgb(140, 43, 33));
        lay.addView(tv);

        android.widget.Button retry = new android.widget.Button(this);
        retry.setText("重试");
        LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rp.topMargin = dp(24);
        retry.setLayoutParams(rp);
        retry.setOnClickListener(v -> {
            root.removeView(lay);
            showInit();
            new Thread(this::bootstrap).start();
        });
        lay.addView(retry);
        root.addView(lay, match());
    }

    /** 供前端识别运行环境 */
    private static class NativeBridge {
        private final MainActivity activity;

        NativeBridge(MainActivity activity) {
            this.activity = activity;
        }

        @JavascriptInterface
        public String isHosted() {
            return "1";
        }

        @JavascriptInterface
        public String mode() {
            return "standalone";
        }

        /** 系统分享面板：保存到网盘/微信/另一台手机 */
        @JavascriptInterface
        public void shareFile(final String path) {
            activity.runOnUiThread(() -> {
                try {
                    File f = new File(path);
                    Uri uri = FileProvider.getUriForFile(activity,
                            activity.getPackageName() + ".fileprovider", f);
                    Intent send = new Intent(Intent.ACTION_SEND);
                    send.setType("application/zip");
                    send.putExtra(Intent.EXTRA_STREAM, uri);
                    send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    activity.startActivity(Intent.createChooser(send, "保存或发送备份"));
                } catch (Exception e) {
                    android.util.Log.e("mweb", "share fail", e);
                }
            });
        }

        /** 直接保存到公共 Download 目录（API 29+ MediaStore） */
        @JavascriptInterface
        public String saveToDownloads(final String path) {
            if (Build.VERSION.SDK_INT < 29) {
                return "ERROR:系统版本过低，请用「系统分享」发送";
            }
            try {
                File f = new File(path);
                ContentValues v = new ContentValues();
                v.put(MediaStore.Downloads.DISPLAY_NAME, f.getName());
                v.put(MediaStore.Downloads.MIME_TYPE, "application/zip");
                v.put(MediaStore.Downloads.RELATIVE_PATH,
                        Environment.DIRECTORY_DOWNLOADS);
                Uri uri = activity.getContentResolver().insert(
                        MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) return "ERROR:无法写入下载目录";
                try (InputStream in = new FileInputStream(f);
                     OutputStream out =
                             activity.getContentResolver().openOutputStream(uri)) {
                    byte[] b = new byte[BUF];
                    int n;
                    while ((n = in.read(b)) > 0) out.write(b, 0, n);
                }
                return "已保存到 下载/" + f.getName();
            } catch (Exception e) {
                return "ERROR:" + e.getMessage();
            }
        }

        /** 文本/Markdown 报告直接保存到系统下载目录 */
        @JavascriptInterface
        public String saveTextFile(final String name, final String text,
                                   final String mime) {
            if (Build.VERSION.SDK_INT < 29) {
                return "ERROR:系统版本过低，请用分享方式";
            }
            try {
                byte[] bytes = text.getBytes("UTF-8");
                String m = (mime == null || mime.isEmpty())
                        ? "text/plain" : mime;
                ContentValues v = new ContentValues();
                v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                v.put(MediaStore.Downloads.MIME_TYPE, m);
                v.put(MediaStore.Downloads.RELATIVE_PATH,
                        Environment.DIRECTORY_DOWNLOADS);
                Uri uri = activity.getContentResolver().insert(
                        MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) return "ERROR:无法写入下载目录";
                try (ByteArrayInputStream in = new ByteArrayInputStream(bytes);
                     OutputStream out =
                             activity.getContentResolver().openOutputStream(uri)) {
                    byte[] b = new byte[BUF];
                    int n;
                    while ((n = in.read(b)) > 0) out.write(b, 0, n);
                }
                return "已保存到 下载/" + name;
            } catch (Exception e) {
                return "ERROR:" + e.getMessage();
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_FILE_CHOOSER) {
            Uri[] results = null;
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                results = new Uri[]{data.getData()};
            }
            if (filePathCallback != null) {
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
        }
    }

    @Override
    public void onBackPressed() {
        if (web == null) {
            super.onBackPressed();
            return;
        }
        // 先问页面：做题流中（无历史记录）由 JS 退出做题，而不是退出 App
        web.evaluateJavascript("(window.GoshorBack ? GoshorBack() : false)", value -> {
            if (!"true".equals(value)) defaultBack();
        });
    }

    private void defaultBack() {
        // hash 路由每次切换都会进 WebView 历史栈（history.length 封顶 50，
        // 不能拿它判断是否退出）。首页按返回直接退出 App；其余页先回退一条
        // hash 历史，逐步回到首页后再退出。
        web.evaluateJavascript("String(location.hash||'')", hash -> {
            String h = hash == null ? "" : hash.replace("\"", "");
            if (h.isEmpty() || "#/".equals(h) || "#/home".equals(h)) {
                finish();
            } else {
                web.evaluateJavascript("(history.length>1?(history.back(),true):false)",
                    value -> {
                        if (!"true".equals(value)) finish();
                    });
            }
        });
    }

    private FrameLayout.LayoutParams match() {
        return new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }

    private int dp(int v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                getResources().getDisplayMetrics()));
    }
}
