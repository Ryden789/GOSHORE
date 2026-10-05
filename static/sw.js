/* GOSHORE Service Worker —— PWA 离线应用壳（功能 3.1）
 *
 * 设计原则：
 *  - 只缓存「应用壳」（HTML/CSS/JS/图标），绝不缓存 /api/ 接口与题库数据；
 *    题库与个人作答始终以本地服务为准，避免离线读到陈旧数据。
 *  - 页面导航：network-first → 缓存 → 离线页。
 *  - 静态资源：cache-first + 后台静默更新（stale-while-revalidate）。
 *  - 升级版本号即整体失效旧缓存（activate 阶段清理非当前版本前缀的缓存）。
 *
 * ⚠ 发布约定：每次改动前端资源（app.js / m.js / *.css / index.html）后，
 *   必须同步升级下面的 VERSION。否则旧 SW 会继续用 runtime 缓存里的旧 JS
 *   响应请求，用户看到的是上一版界面（stale-while-revalidate 的固有代价）。
 *   建议直接复用 index.html 里的 ?v= 日期号。
 */
const VERSION = "goshore-20261012";
const SHELL_CACHE = VERSION + "-shell";
const RUNTIME_CACHE = VERSION + "-runtime";
const OFFLINE_URL = "/offline.html";

// 应用壳最小集合：单个失败不影响整体安装
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/m/",
  "/m/index.html",
  "/offline.html",
  "/styles.css",
  "/app.js",
  "/m/m.css",
  "/m/m.js",
  "/m/manifest.json",
  "/manifest-desktop.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await Promise.all(SHELL_ASSETS.map(async (url) => {
      try {
        await cache.add(new Request(url, { cache: "reload" }));
      } catch (e) {
        // 缺某个资源（如未生成的图标）不应阻断安装
      }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

const STATIC_RE = /\.(?:css|mjs?|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|otf|webmanifest)$/i;

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  let url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return;   // 跨域（如 CDN）不接管

  // 接口 / 题目图片：永不缓存，直接走网络（离线时失败，前端已有降级提示）
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/img")) return;

  // 页面导航：network-first，失败回落缓存页，再回落离线页
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(SHELL_CACHE);
        cache.put(req, fresh.clone());
        return fresh;
      } catch (e) {
        const cached = await caches.match(req);
        if (cached) return cached;
        const shell = await caches.match(url.pathname.startsWith("/m") ? "/m/index.html" : "/index.html");
        return shell || (await caches.match(OFFLINE_URL)) || Response.error();
      }
    })());
    return;
  }

  // 静态资源：cache-first + 后台更新
  if (STATIC_RE.test(url.pathname)) {
    event.respondWith((async () => {
      const cache = await caches.open(RUNTIME_CACHE);
      const cached = await caches.match(req);
      const network = fetch(req).then((res) => {
        if (res && res.ok && res.type === "basic") cache.put(req, res.clone());
        return res;
      }).catch(() => null);
      if (cached) { network; return cached; }   // 命中即返回，同时后台刷新
      const fresh = await network;
      return fresh || Response.error();
    })());
  }
});
