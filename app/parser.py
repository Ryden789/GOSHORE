"""Obsidian vault 解析器。

把每篇 Markdown 解析成结构化字段：
- frontmatter（YAML 子集：标量 + 行内数组）
- 按标题切分的章节
- 真题：题干/选项/官方解析/给定材料/推理链/最快解法/易错点/母题/相关题
- 图片相对路径重写为 /img?path=<vault 相对路径>
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from urllib.parse import quote

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", re.S)
HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
IMG_HTML_RE = re.compile(r"(<img\b[^>]*?\bsrc=)[\"']([^\"']+)[\"']", re.I)
IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
OPTION_RE = re.compile(r"^[\-\*]\s*([A-Da-d])[\.、．:：]?\s*(.*)$")
RELATED_RE = re.compile(r"[\-\*]\s*\[\[([^\]|]+)(?:\|([^\]]+))?\]\]\s*(.*)$")
RELDEG_RE = re.compile(r"相关度\s*(\d+)")
WENFA_RE = re.compile(r"\*\*问法模型\*\*[：:]\s*(.+?)(?=\n#{1,6}\s|\n\*\*|\Z)", re.S)
FAST_RE = re.compile(
    r"\*\*最快解法\*\*[：:]\s*(.+?)(?=\n#{1,6}\s|\n\*\*|\Z)", re.S
)


@dataclass
class Parsed:
    rel_path: str
    fm: dict
    kind: str = ""
    title: str = ""
    module: str = ""
    daclass: str = ""
    qid: str = ""
    region: str = ""
    year: str = ""
    exam: str = ""
    kaodian: str = ""
    tags: list = field(default_factory=list)
    data: dict = field(default_factory=dict)
    search_text: str = ""


def _parse_frontmatter(text: str) -> dict:
    fm: dict = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z_一-龥]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            fm[key] = re.findall(r'"([^"]*)"|\'([^\']*)\'', val) and [
                a or b for a, b in re.findall(r'"([^"]*)"|\'([^\']*)\'', val)
            ]
        else:
            fm[key] = val.strip('"').strip("'")
    return fm


def _split_sections(body: str) -> list[tuple[int, str, str]]:
    """按 ##+ 标题切分，返回 (level, title, content)。标题前的内容作为 preamble。"""
    sections: list[tuple[int, str, str]] = [(0, "__preamble__", "")]
    for line in body.splitlines(keepends=True):
        m = HEADING_RE.match(line)
        if m:
            sections.append((len(m.group(1)), m.group(2).strip(), ""))
        else:
            lvl, t, c = sections[-1]
            sections[-1] = (lvl, t, c + line)
    return sections


def _rewrite_imgs(text: str, note_dir: str) -> str:
    def repl_html(m: re.Match) -> str:
        prefix, src = m.group(1), m.group(2)
        if src.startswith("http"):
            return m.group(0)
        p = posixpath.normpath(posixpath.join(note_dir, src.replace("\\", "/")))
        return f'{prefix}"/img?path={quote(p)}"'

    def repl_md(m: re.Match) -> str:
        alt, src = m.group(1), m.group(2)
        if src.startswith("http"):
            return m.group(0)
        p = posixpath.normpath(posixpath.join(note_dir, src.replace("\\", "/")))
        return f"![{alt}](/img?path={quote(p)})"

    text = IMG_HTML_RE.sub(repl_html, text)
    text = IMG_MD_RE.sub(repl_md, text)
    return text


def _strip_wikilinks(text: str) -> str:
    return WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1).split("/")[-1], text)


def _parse_options(text: str) -> list[dict]:
    opts = []
    for line in text.splitlines():
        m = OPTION_RE.match(line.strip())
        if m:
            label = m.group(1).upper()
            content = m.group(2).strip()
            correct = bool(re.search(r"[✅✔]", content))
            content = re.sub(r"[✅✔\s]*$", "", content).strip()
            opts.append({"label": label, "text": content, "correct": correct})
    return opts


def _parse_related(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = RELATED_RE.match(line.strip())
        if not m:
            continue
        path, label, tail = m.group(1), (m.group(2) or ""), m.group(3)
        deg = RELDEG_RE.search(tail)
        out.append(
            {
                "path": path,
                "label": label or path.split("/")[-1],
                "tail": tail.strip("（）() "),
                "degree": int(deg.group(1)) if deg else 1,
            }
        )
    return out


def parse(rel_path: str, text: str) -> Parsed:
    rel_path = rel_path.replace("\\", "/")
    note_dir = posixpath.dirname(rel_path)
    m = FRONTMATTER_RE.match(text)
    if m:
        fm = _parse_frontmatter(m.group(1))
        body = m.group(2)
    else:
        fm, body = {}, text

    body = _rewrite_imgs(body, note_dir)
    sections = _split_sections(body)
    sec_map = {t.strip(): c.strip() for _, t, c in sections if t != "__preamble__"}
    preamble = sections[0][2] if sections else ""

    p = Parsed(rel_path=rel_path, fm=fm)
    p.kind = fm.get("类型", "")
    p.tags = fm.get("tags", []) if isinstance(fm.get("tags"), list) else []
    p.qid = fm.get("qid", "") or fm.get("mid", "")
    p.region = fm.get("地区", "")
    p.year = fm.get("年份", "")
    p.exam = fm.get("试卷", "")
    p.kaodian = fm.get("考点", "")

    parts = rel_path.split("/")
    if len(parts) >= 3 and re.match(r"\d+-", parts[0]):
        p.module = parts[1]
        p.daclass = parts[2] if len(parts) > 3 else ""

    title_m = re.search(r"^#\s+(.+)$", body, re.M)
    p.title = (title_m.group(1).strip() if title_m else parts[-1].replace(".md", ""))

    data: dict = {"preamble": preamble.strip(), "sections": sec_map}

    if p.kind == "真题":
        wenfa = WENFA_RE.search(body)
        fast = FAST_RE.search(body)
        data["wenfa"] = wenfa.group(1).strip() if wenfa else ""
        data["fastest"] = fast.group(1).strip() if fast else ""
        reasoning = sec_map.get("推理链", "")
        # P2-7：推理链尾部常带一段“最快解法：⚡…”，剥离归入 fastest，避免页面重复渲染
        if reasoning:
            m = re.search(r"\n\s*(?:\*\*)?最快解法(?:\*\*)?[：:]", reasoning)
            if m:
                tail = reasoning[m.start():]
                reasoning = reasoning[:m.start()].rstrip()
                if not data["fastest"]:
                    data["fastest"] = re.sub(
                        r"^\s*(?:\*\*)?最快解法(?:\*\*)?[：:]\s*", "", tail
                    ).strip()
        data["reasoning"] = reasoning
        data["pitfalls"] = sec_map.get("易错点", "")
        data["muke"] = sec_map.get("母题抽象", "")
        data["tonglei"] = sec_map.get("同类特征", "")
        data["stem"] = sec_map.get("题干", "")
        data["options_raw"] = sec_map.get("选项", "")
        data["options"] = _parse_options(sec_map.get("选项", ""))
        data["official"] = sec_map.get("官方解析", "")
        data["material"] = sec_map.get("给定材料", "")
        data["related"] = _parse_related(sec_map.get("相关题", ""))
        # 保留章节原始顺序，供前端渲染其余内容
        data["section_order"] = [
            t for _, t, c in sections if t != "__preamble__" and c.strip()
        ]

    elif p.kind == "考点":
        data["stance"] = sec_map.get("核心立场（母题抽象）", "") or sec_map.get(
            "核心立场", ""
        )
        data["zhenti_list"] = sec_map.get("真题（跨卷聚合）", "") or sec_map.get(
            "真题", ""
        )
        data["yidian"] = sec_map.get("疑点待复核（2）", "") or sec_map.get(
            "疑点待复核", ""
        )

    elif p.kind == "材料":
        data["theme"] = fm.get("材料主题", "")
        data["koujing"] = sec_map.get("结构拆解", "")
        data["traps"] = sec_map.get("阅读陷阱", "")
        data["relations"] = sec_map.get("小题群关系", "")
        data["raw_material"] = sec_map.get("材料原文", "")

    p.data = data
    p.search_text = _build_search_text(p)
    return p


def _build_search_text(p: Parsed) -> str:
    d = p.data
    bits = [p.title, p.kaodian, p.exam, p.region, p.year]
    if p.kind == "真题":
        bits += [
            d.get("stem", ""),
            d.get("options_raw", ""),
            d.get("reasoning", ""),
            d.get("muke", ""),
            d.get("pitfalls", ""),
            d.get("wenfa", ""),
            d.get("tonglei", ""),
        ]
    elif p.kind == "考点":
        bits += [d.get("stance", ""), d.get("zhenti_list", "")]
    elif p.kind == "材料":
        bits += [d.get("theme", ""), d.get("raw_material", "")]
    else:
        bits.append(d.get("sections", {}).get("__all__", ""))
        bits.append(d.get("preamble", ""))
    return _strip_wikilinks("\n".join(b for b in bits if b))
