/* ============ GOSHORE 共享富文本净化（桌面 app.js / 移动 m.js 共用） ============
 *
 * 题库由用户导入，material / 官方解析 / 题干里的 HTML 会被 innerHTML 进页面。
 * 只删 <script> 挡不住 <img onerror=...>，所以这里做**白名单重建**：只保留允许的
 * 标签与属性，on* 事件属性、style、javascript: 等一律剥离。
 *
 * 原先 static/app.js 与 static/m/m.js 各有一份逐字节相同的实现；现在只在
 * /shared/sanitize.js 维护一份，两个页面在各自 app.js / m.js 之前加载。
 * rawHtml() 包装仍留在各端（桌面是函数、移动是箭头函数），都调用这里的 sanitizeHtml。
 *
 * 修改后请跑：node tools/check_xss_sanitize.mjs、node tools/check_md_parity.mjs。
 */

const SANITIZE_TAGS = ("p br hr div span sub sup b strong u i em s img table thead tbody " +
  "tfoot tr td th ul ol li h1 h2 h3 h4 h5 h6 blockquote code pre a").split(" ");
const SANITIZE_VOID = "br hr img".split(" ");
const escText = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** 净化单个标签：非白名单标签整只丢弃；白名单标签只保留安全属性。 */
function sanitizeTag(tag) {
  const m = /^<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>$/.exec(tag);
  if (!m) return "";
  const close = m[1], name = m[2].toLowerCase(), attrStr = m[3] || "";
  if (SANITIZE_TAGS.indexOf(name) < 0) return "";
  if (close) return "</" + name + ">";
  const allowed = { img: ["src", "alt", "width", "height"], a: ["href", "title"],
                    td: ["colspan", "rowspan"], th: ["colspan", "rowspan"] }[name] || [];
  const urlOk = v => {
    const t = v.trim().replace(/[\u0000-\u0020]/g, "");     // 先去掉空白/控制字符，防绕过
    if (/^https?:\/\//i.test(t)) return true;
    if (t.startsWith("#")) return true;
    if (/^data:/i.test(t)) return /^data:image\/(?:png|jpe?g|gif|webp|bmp);base64,/i.test(t);
    if (/^[a-z][a-z0-9+.-]*:/i.test(t)) return false;       // javascript:/vbscript:/blob:/file: 等
    if (t.startsWith("//")) return false;                   // 协议相对：指向外部主机
    return true;                                            // 站内相对路径 / 绝对路径
  };
  const attrRe = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/g;
  const keep = [];
  let a;
  while ((a = attrRe.exec(attrStr))) {
    const an = a[1].toLowerCase();
    const av = a[2] !== undefined ? a[2] : (a[3] !== undefined ? a[3] : (a[4] || ""));
    if (an === "class") { if (/^[A-Za-z0-9 _-]*$/.test(av)) keep.push('class="' + av + '"'); continue; }
    if (allowed.indexOf(an) < 0) continue;          // on* / style / id 等一律丢弃
    if (an === "src" || an === "href") { if (!urlOk(av)) continue; }
    else if (!/^\d{1,4}$/.test(av.trim())) continue;
    keep.push(an + '="' + av.replace(/"/g, "&quot;") + '"');
  }
  return "<" + name + (keep.length ? " " + keep.join(" ") : "") + ">";
}

/** 净化整段富文本：先连内容删掉危险元素，再逐个标签走 sanitizeTag，文本一律转义。 */
function sanitizeHtml(html) {
  let s = String(html ?? "");
  const danger = "script|style|iframe|object|embed|svg|math|noscript|template|link|meta|base|form|input|button|textarea|select|option|frame|frameset|applet";
  s = s.replace(new RegExp("<(" + danger + ")\\b[^>]*>[\\s\\S]*?<\\/\\1\\s*>", "gi"), "");
  s = s.replace(new RegExp("<\\/?(?:" + danger + ")\\b[^>]*>", "gi"), "");
  let out = "", last = 0, m;
  const tagRe = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
  while ((m = tagRe.exec(s))) {
    out += escText(s.slice(last, m.index));
    out += sanitizeTag(m[0]);
    last = tagRe.lastIndex;
  }
  out += escText(s.slice(last));
  return out;
}

/* shared-sanitize:end */
