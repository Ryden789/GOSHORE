"""可打印导出页（G5 错题导出 / 题库导出 PDF）。

桌面端与手机端共用同一份拼装逻辑，避免两端各写一套 HTML 模板而慢慢漂移：
- 桌面 `app/main.py` 的 `GET /api/export/print`（支持筛选条件与 doc_ids 两种取题方式）；
- 手机 `goshor_server.py` 的同名接口（只支持 doc_ids，取到题后交给本模块）。

题干与选项走 `rich_text()`：题库里的图形题题干是
`<img src="/img?path=...">`，直接转义会把标签当字面文本打印出来，图就没了。
"""
from __future__ import annotations

import datetime
import html as _html
import re as _re


def esc(s) -> str:
    """HTML 转义（含引号）。"""
    return _html.escape(str(s or ""))


# 允许保留的内联标签：图片（parser 已重写成 /img?path=...）、下划线/加粗
# （原卷着重线）、换行；其余一律转义。
_RICH_TAGS = _re.compile(
    r'<img\b[^>]*?\bsrc="([^"]+)"[^>]*>|</?u>|</?b>|</?strong>|</?em>|<br\s*/?>',
    _re.I)


def rich_text(s) -> str:
    """转义文本，但保留白名单内联标签；<img> 只保留 src 属性。

    只保留 src 是为了防注入：原始标签可能带 onerror 等属性，
    整体放行等于给题库内容开了个执行口子。
    """
    text = str(s or "")
    out: list[str] = []
    last = 0
    for m in _RICH_TAGS.finditer(text):
        out.append(esc(text[last:m.start()]))
        if m.group(1) is not None:              # <img src="...">
            out.append(f'<img class="qimg" src="{esc(m.group(1))}"/>')
        else:
            out.append(m.group(0).lower())
        last = m.end()
    out.append(esc(text[last:]))
    return "".join(out)


_STYLE = """
  body { font-family: "Noto Serif SC", "SimSun", serif; margin: 0; color: #1a1a1a; }
  .wrap { max-width: 800px; margin: 0 auto; padding: 32px 24px; }
  h1 { font-size: 20px; } .sub { color: #666; font-size: 13px; margin-bottom: 20px; }
  .q { margin-bottom: 18px; page-break-inside: avoid; }
  .qt { font-weight: 700; } .meta { color: #888; font-size: 12px; margin-left: 8px; font-weight: 400; }
  .qs { margin: 6px 0; line-height: 1.7; }
  .opt { margin: 2px 0 2px 1.5em; }
  .ans { margin-top: 4px; color: #b3352b; font-weight: 700; }
  .ana { color: #555; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
  /* 图形题的图：不超出纸宽，避免打印时被裁掉 */
  .qimg { max-width: 100%; height: auto; display: block; margin: 6px 0; }
  .pagebreak { page-break-before: always; }
  h2 { font-size: 16px; border-bottom: 2px solid #333; padding-bottom: 4px; }
  @media print { .noprint { display: none; } }
  .tip { background: #fdf6e3; border: 1px solid #e0d5b0; padding: 10px 14px; border-radius: 6px; font-size: 13px; }
"""


def render_html(items: list[dict], with_answer: bool = True,
                heading: str = "题库导出", title_suffix: str = "") -> str:
    """把题目列表拼成可打印的整页 HTML。

    `items` 元素形如
    ``{"title","module","exam","stem","options":[{"label","text","correct"}],
       "answer","analysis"}``；缺字段按空处理。
    """
    def block(it: dict, idx: int, show_ans: bool) -> str:
        opts = "".join(
            f"<div class='opt'>{esc(o.get('label', ''))}. {rich_text(o.get('text', ''))}</div>"
            for o in (it.get("options") or []))
        ans = ""
        if show_ans:
            analysis = it.get("analysis") or ""
            ans = (f"<div class='ans'>【答案】{esc(it.get('answer') or '')}</div>"
                   + (f"<div class='ana'>{rich_text(analysis)[:600]}</div>" if analysis else ""))
        return (f"<div class='q'><div class='qt'>{idx}. {esc(it.get('title') or '')}"
                f"<span class='meta'>{esc(it.get('exam') or '')} · "
                f"{esc(it.get('module') or '')}</span></div>"
                f"<div class='qs'>{rich_text(it.get('stem') or '')}</div>{opts}{ans}</div>")

    questions = "".join(block(it, i + 1, False) for i, it in enumerate(items))
    answers = ("".join(block(it, i + 1, True) for i, it in enumerate(items))
               if with_answer else "")
    title = (heading or "题库导出").strip()[:30]
    suffix = title_suffix or f"{len(items)} 题"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    single = "（单题）" if len(items) == 1 else ""
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{esc(title)} · {esc(suffix)}</title>
<style>{_STYLE}</style></head><body><div class="wrap">
<div class="noprint tip">打印为 PDF：按 <b>Ctrl + P</b> → 目标选「另存为 PDF」→ 勾选背景图形。共 {len(items)} 题。</div>
<h1>{esc(title)}{single}</h1>
<div class="sub">生成于 {stamp}</div>
<h2>第一部分 · 试题</h2>
{questions or "<p>没有匹配的题目</p>"}
<h2 class="pagebreak">第二部分 · 答案与解析</h2>
{answers or "<p>未包含答案</p>"}
</div></body></html>"""
