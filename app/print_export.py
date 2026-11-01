"""可打印导出页（G5 错题导出 / 题库导出 PDF / 整卷导出）。

桌面端与手机端共用同一份拼装逻辑，避免两端各写一套 HTML 模板而慢慢漂移：
- 桌面 `app/main.py` 的 `GET /api/export/print`（支持筛选条件、doc_ids、整卷、全量）；
- 手机 `goshor_server.py` 的同名接口（取到题后交给本模块）。

题干与选项走 `rich_text()`：题库里的图形题题干是
`<img src="/img?path=...">`，直接转义会把标签当字面文本打印出来，图就没了。

题库原始文本里大量出现 `<p>` / `<span>` / `&nbsp;` 这类排版标签（23k 题里
6500+ 道带 `<p>`）。早先把它们整体转义，打印出来就是一行行 `<p>`「乱码」；
现在按「结构性标签转成换行、装饰性标签丢弃、未知标签仍转义」处理。
"""
from __future__ import annotations

import datetime
import html as _html
import re as _re


def esc(s) -> str:
    """HTML 转义（含引号）。"""
    return _html.escape(str(s or ""))


# 常见排版实体 → 真实字符。只还原「展示型」实体：`&amp;` / `&lt;` / `&gt;`
# 不还原（还原就等于把转义撤销了，题干里真有标签时会重新变成可执行标记）。
_ENTITIES = {
    "nbsp": " ", "ensp": " ", "emsp": " ",
    "ldquo": "“", "rdquo": "”", "lsquo": "‘", "rsquo": "’",
    "hellip": "…", "mdash": "—", "ndash": "–", "middot": "·",
    "times": "×", "divide": "÷", "plusmn": "±", "deg": "°",
    "frac12": "½", "frac14": "¼", "frac34": "¾", "sup2": "²", "sup3": "³",
}


def _restore_entities(text: str) -> str:
    """把转义后的 `&amp;nbsp;` 之类还原成可读字符（防打印成字面 `&nbsp;`）。"""
    def named(m):
        return _ENTITIES.get(m.group(1).lower(), m.group(0))
    text = _re.sub(r"&amp;([a-zA-Z][a-zA-Z0-9]{1,9});", named, text)

    def num(m):
        raw = m.group(1) or m.group(2)
        try:
            cp = int(raw, 10) if m.group(1) else int(raw, 16)
        except ValueError:
            return m.group(0)
        # < & > 不还原（会破坏 HTML 结构）；控制字符不还原
        if cp < 0x20 or cp in (0x26, 0x3C, 0x3E) or cp > 0x10FFFF:
            return m.group(0)
        return chr(cp)
    return _re.sub(r"&amp;#(\d+);|&amp;#x([0-9a-fA-F]+);", num, text)


# 题库把「本题没有材料」写成 `（无）`（23k 题里 7600+ 道），还会在材料字段尾部
# 挂 `> [!warning] 疑点…` 复核附注。两者都不是题目内容：原样打印会出现
# 「给定材料 （无）」和字面 `[!warning]`，看起来像乱码。
_MAT_NONE = {"（无）", "(无)", "无", "none", "null", "-", "—", "N/A"}


def material_text(raw) -> str:
    """清洗材料字段：去掉「（无）」占位与复核附注，只留真正的材料正文。"""
    lines: list[str] = []
    for ln in str(raw or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.strip("*_` \t") in _MAT_NONE:
            continue
        if s.startswith(">") or s.lower().startswith("[!warning]"):
            continue
        lines.append(s)
    return "\n".join(lines)


# 任意标签（含属性）。破坏性/未知标签最终仍走转义，保持原有安全口径。
_TAG = _re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>", _re.S)
_SRC = _re.compile(r"""src\s*=\s*("([^"]*)"|'([^']*)')""", _re.I)
_INLINE_KEEP = {"u", "b", "strong", "em", "i", "s", "sub", "sup", "code"}
# 结构性容器：开标签丢弃，闭标签转成换行（相当于把 <p>x</p> 变成 x<br>）
_BLOCK = {"p", "div", "section", "article", "blockquote", "li", "tr", "pre"}
# 纯装饰/表格骨架：标签直接丢弃，内部文字保留（打印时由 CSS 负责排版）
_STRIP = {"span", "a", "font", "center", "table", "tbody", "thead", "tfoot",
          "ul", "ol", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"}


def rich_text(s) -> str:
    """转义文本，但保留白名单内联标签；<img> 只保留 src 属性。

    只保留 src 是为了防注入：原始标签可能带 onerror 等属性，
    整体放行等于给题库内容开了个执行口子。

    结构性标签（`<p>` `<div>` `<li>` …）转成 `<br>`，装饰性标签（`<span>`
    `<table>` `<td>` …）只丢标签、留文字，其余标签照旧转义成字面文本
    （`<script>` 仍会显示成 `&lt;script&gt;`，不会被当成代码执行）。
    """
    text = str(s or "")
    out: list[str] = []
    last = 0

    def plain(chunk: str) -> str:
        return _restore_entities(esc(chunk))

    for m in _TAG.finditer(text):
        out.append(plain(text[last:m.start()]))
        closing, name = m.group(1) == "/", m.group(2).lower()
        if name == "img":
            src = _SRC.search(m.group(3) or "")
            if src:
                url = src.group(2) if src.group(2) is not None else src.group(3)
                out.append(f'<img class="qimg" src="{esc(url)}"/>')
        elif name == "br":
            out.append("<br>")
        elif name in _INLINE_KEEP:
            out.append(f"</{name}>" if closing else f"<{name}>")
        elif name in _BLOCK:
            if closing:
                out.append("<br>")
        elif name in _STRIP:
            if name in ("td", "th") and not closing:
                out.append(" ")
        else:
            # 未知标签：保持原样（已转义），绝不按标签解析
            out.append(esc(m.group(0)))
        last = m.end()
    out.append(plain(text[last:]))
    return "".join(out)


_STYLE = """
  :root { --ink:#2f2a24; --ink-2:#6b6358; --ink-3:#8a8073; --line:#e7e0d5;
          --paper:#f7f3ec; --panel:#fffdf8; --cinnabar:#b23a30; --mat:#f1ebdf; }
  * { box-sizing: border-box; }
  body {
    font-family: "Noto Serif SC", "Songti SC", "SimSun", serif;
    margin: 0; color: var(--ink); background: var(--paper); line-height: 1.75;
  }
  .wrap { max-width: 820px; margin: 0 auto; padding: 40px 28px 72px; }
  .masthead { border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 26px; }
  .eyebrow { display: inline-flex; align-items: center; gap: 8px; color: var(--cinnabar);
             font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; font-size: 12px;
             letter-spacing: .18em; text-transform: uppercase; }
  .eyebrow i { display: inline-block; width: 22px; height: 2px; background: var(--cinnabar); }
  h1 { font-size: 26px; letter-spacing: .02em; margin: 10px 0 6px; word-break: break-word; }
  .sub { color: var(--ink-3); font-size: 12.5px; font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .chip { border: 1px solid var(--line); background: var(--panel); border-radius: 999px;
          padding: 3px 12px; font-size: 12px; color: var(--ink-2);
          font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
  h2 { font-size: 15px; letter-spacing: .06em; margin: 26px 0 14px; padding-left: 10px;
       border-left: 3px solid var(--cinnabar); font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
       break-after: avoid; page-break-after: avoid; }
  .q { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
       padding: 14px 16px; margin-bottom: 14px;
       /* 长题（资料分析材料 + 4 个选项 + 解析）允许自然跨页：原先
          page-break-inside:avoid 会把整题挤到下一页，上一页留大片空白，
          打印预览里看起来像「内容被折叠/截断」。 */
       break-inside: auto; page-break-inside: auto; overflow-wrap: anywhere; }
  .qt { font-weight: 700; break-after: avoid; page-break-after: avoid; }
  .meta { color: var(--ink-3); font-size: 11.5px; margin-left: 8px; font-weight: 400;
          font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
  .qs { margin: 8px 0; orphans: 3; widows: 3; }
  .mat { background: var(--mat); border-left: 3px solid #c9bfae; border-radius: 4px;
         padding: 10px 13px; margin: 8px 0 12px; font-size: 13px; line-height: 1.85;
         orphans: 3; widows: 3; }
  .mat-h { font-size: 11px; letter-spacing: .14em; color: var(--ink-3); margin-bottom: 6px;
           font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
  .mat.reuse { background: transparent; border-left-style: dashed; color: var(--ink-3);
               font-size: 12px; padding: 6px 13px; }
  .opt { margin: 3px 0 3px 1.6em; color: var(--ink); break-inside: avoid; page-break-inside: avoid; }
  .ans { margin-top: 8px; color: var(--cinnabar); font-weight: 700; break-after: avoid; }
  .ana { color: var(--ink-2); font-size: 12.5px; line-height: 1.75; white-space: pre-wrap;
         overflow-wrap: anywhere; margin-top: 6px; padding-top: 6px;
         border-top: 1px dashed var(--line); orphans: 2; widows: 2; }
  .qimg { max-width: 100%; height: auto; display: block; margin: 8px 0; break-inside: avoid; }
  .pagebreak { break-before: page; page-break-before: always; }
  .noprint.tip { border: 1px solid var(--line); border-left: 3px solid var(--cinnabar);
                 background: var(--panel); padding: 10px 14px; border-radius: 8px;
                 font-size: 12.5px; color: var(--ink-2); margin-bottom: 22px;
                 font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
  @media print {
    .noprint { display: none; }
    body { background: #fff; }
    .q { background: #fff; }
    .mat { background: #f7f7f7; }
  }
"""


def render_html(items: list[dict], with_answer: bool = True,
                heading: str = "题库导出", title_suffix: str = "",
                subtitle: str = "") -> str:
    """把题目列表拼成可打印的整页 HTML。

    `items` 元素形如
    ``{"title","module","exam","stem","material","options":[{"label","text","correct"}],
       "answer","analysis"}``；缺字段按空处理。题号按传入顺序 1..N 连续编，
    整卷导出时后端已按「科目 + 原题号」排好，所以读起来就是真题顺序。

    `material` 是资料分析等题的「给定材料」（题库里的 HTML 片段）。同一篇材料
    往往被子题共用：只在第一处完整打印，后续标「共用上题材料」，避免同一段
    材料重复几十遍把卷子撑长。

    `subtitle` 用于整卷导出时写明「哪一套卷」（题名太长，塞不进 h1）。
    """
    seen_material: set[str] = set()
    exams = {str(it.get("exam") or "").strip() for it in items} - {""}
    same_exam = len(exams) == 1          # 同一套卷：每题题头不再重复卷名

    def block(it: dict, idx: int, show_ans: bool) -> str:
        opts = "".join(
            f"<div class='opt'>{esc(o.get('label', ''))}. {rich_text(o.get('text', ''))}</div>"
            for o in (it.get("options") or []))
        mat = ""
        raw_mat = material_text(it.get("material"))
        if raw_mat and not show_ans:            # 答案部分不再重复材料
            if raw_mat in seen_material:
                mat = "<div class='mat reuse'>共用上题材料</div>"
            else:
                seen_material.add(raw_mat)
                mat = (f"<div class='mat'><div class='mat-h'>给定材料</div>"
                       f"{rich_text(raw_mat)}</div>")
        ans = ""
        if show_ans:
            analysis = it.get("analysis") or ""
            ans = (f"<div class='ans'>【答案】{esc(it.get('answer') or '')}</div>"
                   + (f"<div class='ana'>{rich_text(analysis)}</div>" if analysis else ""))
        meta = "" if same_exam else (
            f"<span class='meta'>{esc(it.get('exam') or '')} · "
            f"{esc(it.get('module') or '')}</span>")
        return (f"<div class='q'><div class='qt'>{idx}. {esc(it.get('title') or '')}"
                f"{meta}</div>"
                f"{mat}<div class='qs'>{rich_text(it.get('stem') or '')}</div>{opts}{ans}</div>")

    questions = "".join(block(it, i + 1, False) for i, it in enumerate(items))
    answers = ("".join(block(it, i + 1, True) for i, it in enumerate(items))
               if with_answer else "")
    title = (heading or "题库导出").strip()[:30]
    suffix = title_suffix or f"{len(items)} 题"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    single = "（单题）" if len(items) == 1 else ""
    mods = sorted({str(it.get("module") or "").strip() for it in items} - {""})
    chips = "".join(f"<span class='chip'>{esc(m)}</span>" for m in mods[:6])
    chips_html = f"<div class='chips'>{chips}</div>" if chips else ""
    sub_extra = f"{esc(subtitle)} · " if subtitle else ""
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{esc(title)} · {esc(suffix)}</title>
<style>{_STYLE}</style></head><body><div class="wrap">
<div class="noprint tip">打印为 PDF：按 <b>Ctrl + P</b> → 目标选「另存为 PDF」→ 勾选背景图形。共 {len(items)} 题。</div>
<div class="masthead">
  <div class="eyebrow"><i></i>GOSHORE · 题库导出</div>
  <h1>{esc(title)}{single}</h1>
  <div class="sub">{sub_extra}生成于 {stamp} · 共 {len(items)} 题 · 试题在前，答案与解析在后</div>
  {chips_html}
</div>
<h2>第一部分 · 试题</h2>
{questions or "<p>没有匹配的题目</p>"}
<h2 class="pagebreak">第二部分 · 答案与解析</h2>
{answers or "<p>未包含答案</p>"}
</div></body></html>"""
