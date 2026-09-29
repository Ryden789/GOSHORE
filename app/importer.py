"""题库导入：自有 JSON 题库 + 网页/文本真题 AI 抽取。

导入的题目以 Markdown 写入 vault 的 99-自导入/{模块}/ 目录，
与人工整理的题库同构，解析、检索、AI 讲题全部复用现有链路。
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

import httpx

from . import db, parser
from .config import load_settings

IMPORT_ROOT = "99-自导入"

MODULES = ["常识判断", "言语理解", "数量关系", "判断推理", "资料分析", "综合分析"]


# ---------------- 题目规范化 ----------------

# 乱码特征：替换符 / 控制字符 / GBK-UTF8 互转的连续产物（须整串匹配，避免误杀"斤""烫"等正常字）
_MOJIBAKE_RE = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")
_MOJIBAKE_SEQS = ("锟斤拷", "烫烫烫", "å¥", "çš„", "ä¸")

# pdfplumber 提取某些 PDF 时，字体缺 ToUnicode 映射会回退到康熙部首（U+2E80-U+2FDF），
# 其中大部分可用 NFKC 还原，极少数需手动兜底。
_RADICAL_FALLBACK = {
    "⻰": "龙",
}


def check_mojibake(text: str) -> bool:
    """检测文本是否含乱码特征（替换符/控制字符/典型转码连串）。"""
    if not text:
        return False
    if _MOJIBAKE_RE.search(text):
        return True
    return any(seq in text for seq in _MOJIBAKE_SEQS)


def normalize_item(raw: dict, idx: int = 0) -> tuple[dict | None, str]:
    """把一条原始题目数据规范化为内部结构。返回 (item, 错误原因)。"""
    stem = str(raw.get("stem") or raw.get("题干") or "").strip()
    if len(stem) < 5:
        return None, f"第{idx}题：题干缺失或过短"

    _fields = [("题干", stem), ("解析", str(raw.get("analysis") or raw.get("解析") or ""))]
    for o in (raw.get("options") or raw.get("选项") or []):
        if isinstance(o, dict):
            _fields.append((f"选项{o.get('label', '')}", str(o.get("text") or "")))
        else:
            _fields.append(("选项", str(o)))
    for field, val in _fields:
        if check_mojibake(val):
            return None, f"第{idx}题：{field}含乱码字符，已拒绝入库"

    opts_raw = raw.get("options") or raw.get("选项") or []
    options: list[dict] = []
    for i, o in enumerate(opts_raw):
        if isinstance(o, str):
            # "A. xxx" 或纯文本
            m = re.match(r"^([A-F])[\.、．:：]?\s*(.*)$", o.strip())
            label, text = (m.group(1), m.group(2)) if m else ("ABCDEF"[i], o)
            options.append({"label": label, "text": text.strip()})
        elif isinstance(o, dict):
            options.append({
                "label": str(o.get("label") or "ABCDEF"[i]).upper(),
                "text": str(o.get("text") or "").strip(),
            })
    if len(options) < 2:
        return None, f"第{idx}题：选项不足 2 个"

    answer = str(raw.get("answer") or raw.get("答案") or "").strip().upper()
    m = re.search(r"[A-F]", answer)
    answer = m.group(0) if m else ""
    labels = {o["label"] for o in options}
    if answer not in labels:
        return None, f"第{idx}题：答案 {answer or '（空）'} 不在选项中"

    module = str(raw.get("module") or raw.get("模块") or "").strip()
    return {
        "stem": stem,
        "options": options,
        "answer": answer,
        "analysis": str(raw.get("analysis") or raw.get("解析") or "").strip(),
        "module": module,
        "kaodian": str(raw.get("kaodian") or raw.get("考点") or "").strip(),
        "region": str(raw.get("region") or raw.get("地区") or "").strip(),
        "year": str(raw.get("year") or raw.get("年份") or "").strip(),
        "exam": str(raw.get("exam") or raw.get("试卷") or "").strip(),
    }, ""


def _split_top_level_objects(text: str) -> list[str]:
    """从（可能截断的）数组文本中切出完整的顶层对象串，用于容错抢救。"""
    objs, depth, start = [], 0, -1
    in_str, esc = False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    objs.append(text[start:i + 1])
                    start = -1
    return objs


def parse_json_bank(text: str) -> tuple[list[dict], list[str]]:
    """解析用户自有题库 JSON（数组）。返回 (items, errors)。

    AI 输出可能因 max_tokens 截断导致整体解析失败，此时逐顶层对象抢救完整题目。
    """
    text = text.strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return [], ["未找到 JSON 数组"]
    raw_text = m.group(0)
    note = ""
    try:
        arr = json.loads(raw_text, strict=False)
    except json.JSONDecodeError as e:
        arr, broken = [], 0
        for seg in _split_top_level_objects(raw_text):
            try:
                arr.append(json.loads(seg, strict=False))
            except json.JSONDecodeError:
                broken += 1
        if not arr:
            return [], [f"JSON 解析失败：{e}"]
        note = f"AI 输出不完整（{e.msg}），已抢救 {len(arr)} 条完整题目" + (f"，丢弃 {broken} 条损坏数据" if broken else "")
    if not isinstance(arr, list):
        return [], ["JSON 顶层必须是数组"]
    items, errors = [], []
    if note:
        errors.append(note)
    for i, raw in enumerate(arr, 1):
        if not isinstance(raw, dict):
            errors.append(f"第{i}条不是对象")
            continue
        item, err = normalize_item(raw, i)
        if item:
            items.append(item)
        else:
            errors.append(err)
    return items, errors


# ---------------- Markdown 生成与入库 ----------------

def to_markdown(item: dict, qid: str, defaults: dict) -> str:
    region = item.get("region") or defaults.get("region", "")
    year = item.get("year") or defaults.get("year", "")
    exam = item.get("exam") or defaults.get("exam", "")
    kaodian = item.get("kaodian") or defaults.get("kaodian", "")
    title = re.sub(r"\s+", "", item["stem"])[:24]
    opts = "\n".join(
        f"- {o['label']}. {o['text']}{' ✅' if o['label'] == item['answer'] else ''}"
        for o in item["options"]
    )
    analysis = item["analysis"] or "（暂无解析）"
    return f"""---
类型: 真题
qid: {qid}
地区: {region}
年份: "{year}"
试卷: {exam}
考点: {kaodian}
tags: [自导入]
---

# {title}

## 题干
{item['stem']}

## 选项
{opts}

## 官方解析
答案：{item['answer']}

{analysis}
"""


def commit_items(items: list[dict], defaults: dict) -> dict:
    """写 md 文件到 vault 并直接 upsert 进库（保留原有题库，纯增量）。"""
    s = load_settings()
    vault = Path(s["vault_path"])
    if not vault.exists():
        return {"ok": False, "error": f"vault 路径不存在：{vault}"}

    conn = db.connect()
    db.init_db(conn)
    saved, failed = 0, []
    batch = time.strftime("%Y%m%d%H%M%S")
    for i, item in enumerate(items, 1):
        module = item["module"] if item["module"] in MODULES else (defaults.get("module") or "未分类")
        qid = f"imp-{batch}-{i:03d}"
        rel = f"{IMPORT_ROOT}/{module}/{qid}.md"
        text = to_markdown(item, qid, defaults)
        try:
            fp = vault / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(text, encoding="utf-8")
            p = parser.parse(rel, text)
            db._upsert(conn, p, fp.stat().st_mtime)
            saved += 1
        except Exception as e:
            failed.append(f"第{i}题入库失败：{e}")
    conn.commit()
    conn.close()
    return {"ok": True, "saved": saved, "failed": failed, "total": db.facets().get("counts", {}).get("真题", 0)}


# ---------------- 文件格式解析（PDF / Word / Excel） ----------------

def extract_text_from_file(name: str, data: bytes) -> str:
    """从上传文件中提取纯文本。支持 .pdf/.docx/.xlsx/.csv/.md/.txt。"""
    import io
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "pdf":
        import pdfplumber
        parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t)
        text = "\n\n".join(parts)
        # 修复字体缺 ToUnicode 映射导致的康熙部首乱码（⽉→月、⼒→力），其余字符不动
        text = "".join(
            _RADICAL_FALLBACK.get(ch) or (unicodedata.normalize("NFKC", ch) if "⺀" <= ch <= "⿟" else ch)
            for ch in text
        )
        return text
    if ext == "docx":
        import docx
        doc = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if ext in ("xlsx", "xls"):
        import pandas as pd
        df = pd.read_excel(io.BytesIO(data))
        return df.to_csv(index=False, sep="\t")
    if ext == "csv":
        import pandas as pd
        for enc in ("utf-8", "gbk", "gb18030"):
            try:
                df = pd.read_csv(io.BytesIO(data), encoding=enc)
                return df.to_csv(index=False, sep="\t")
            except Exception:
                continue
        return data.decode("utf-8", errors="ignore")
    # md / txt / 其他纯文本
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


# ---------------- 网页/文本 → AI 抽取 ----------------

async def fetch_url_text(url: str) -> str:
    """抓取网页并剥离 HTML 标签得到纯文本。"""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        follow_redirects=True,
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        html = r.text
    html = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html, flags=re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(p|div|li|tr|h\d)>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_EXTRACT_PROMPT = """你是事业单位C类题库录入员。从用户给的网页/文本内容中抽取所有选择题（真题），输出 JSON 数组，不要任何额外文字或 markdown 代码块，JSON 紧凑输出（不缩进、不换行）。

每题格式：
{"stem":"完整题干（含材料中的设问句）","options":["A. ...","B. ...","C. ...","D. ..."],"answer":"A","analysis":"一两句简析（60字内）","module":"模块","kaodian":"考点","year":"年份","exam":"试卷名"}

module 只能是：常识判断 / 言语理解 / 数量关系 / 判断推理 / 资料分析 / 综合分析（按题目内容判断）。
answer 与 analysis 规则：
- 用户消息附【官方答案表】时，answer 严格按表中题号对应填写，analysis 由你依据该正确答案写简析
- 原文题目附近自带答案（如"【答案】B"）时以原文答案为准
- 都没有时才由你自己作答给出最可能的字母并写简析
只抽取完整的选择题（题干+至少2个选项+答案），不完整的跳过。没有可抽取的题就输出 []。"""


def _chunk_text(text: str, size: int = 8000, overlap: int = 2500) -> list[str]:
    """滑窗切块（带重叠，防止材料与题目被切到不同段），窗口边界对齐到整行。"""
    if len(text) <= size:
        return [text]
    chunks, start, n = [], 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            nl = text.rfind("\n", start + overlap, end)
            if nl > start:
                end = nl
        chunks.append(text[start:end])
        if end >= n:
            break
        nxt = text.find("\n", max(end - overlap, 0), end)
        start = nxt + 1 if nxt != -1 else end - overlap
    return chunks


_ANSWER_PAIR_RE = re.compile(r"(\d{1,3})[ \t]*[.、．:：\]】][ \t]*(?:【答案】[ \t]*)?([A-DＡ-Ｄ])(?![a-zA-Z])")


def _find_answer_region(text: str) -> str:
    """定位答案区：优先找“参考答案/答案速查”等标题，否则找全局最密集的“题号+字母”窗口。"""
    m = list(re.finditer(r"参考答案|答案速查|答案与解析|答案解析|试题答案|答案一览", text))
    if m:
        start = m[-1].start()
        return text[start:start + 8000]
    best, best_cnt = "", 0
    step, win = 2000, 3000
    for i in range(0, max(len(text) - win, 1), step):
        seg = text[i:i + win]
        cnt = len(_ANSWER_PAIR_RE.findall(seg))
        if cnt > best_cnt:
            best, best_cnt = seg, cnt
    return best if best_cnt >= 8 else ""


def _extract_answer_table(text: str) -> dict[int, str]:
    """从全文中识别官方答案表，返回 {题号: 答案字母}。识别不到返回空 dict。"""
    region = _find_answer_region(text)
    if not region:
        return {}
    table: dict[int, str] = {}
    for mm in _ANSWER_PAIR_RE.finditer(region):
        qno, letter = int(mm.group(1)), mm.group(2)
        if "Ａ" <= letter <= "Ｄ":  # 全角字母转半角
            letter = chr(ord(letter) - 0xFEE0)
        if 1 <= qno <= 200 and qno not in table:  # 同题号首次出现为准（答案行总在解析前）
            table[qno] = letter
    return table if len(table) >= 5 else {}


async def ai_extract_questions(text: str) -> tuple[list[dict], str]:
    """用 DeepSeek 从网页文本中抽取真题。返回 (items, 错误信息)。"""
    s = load_settings()
    if not s["deepseek_api_key"]:
        return [], "未配置 DeepSeek API Key，请先在设置页配置"
    chunks = _chunk_text(text)
    # 答案表常在文末，分段后前面段落看不到 → 识别出来附加到每段，强制按官方答案抽取
    answers = _extract_answer_table(text)
    answer_hint = ""
    if answers:
        pairs = " ".join(f"{k}.{v}" for k, v in sorted(answers.items()))
        answer_hint = (
            "\n\n【官方答案表】（answer 必须严格按此表题号对应填写；表中缺失的题号才允许自行作答）\n" + pairs
        )
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    items: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set()  # 重叠区题目会被重复抽取，按题干去重
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        for i, chunk in enumerate(chunks, 1):
            payload = {
                "model": s["deepseek_model"],
                "messages": [
                    {"role": "system", "content": _EXTRACT_PROMPT},
                    {"role": "user", "content": chunk + answer_hint},
                ],
                "temperature": 0,
                "max_tokens": 8000,
            }
            try:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code != 200:
                    notes.append(f"第{i}段：AI 接口错误 {r.status_code}")
                    continue
                content = r.json()["choices"][0]["message"]["content"]
            except Exception as e:
                notes.append(f"第{i}段：请求失败 {e}")
                continue
            got, errors = parse_json_bank(content)
            for it in got:
                key = re.sub(r"\s+", "", it["stem"])[:40]
                if key and key not in seen:
                    seen.add(key)
                    items.append(it)
            notes.extend(f"第{i}段：{e}" for e in errors[:2])
    if not items and not notes:
        return [], "AI 未从内容中识别出完整题目"
    if answers:
        notes.append(f"已检测到官方答案表（{len(answers)} 题），答案以原卷为准")
    # 选项数异常提示（C类正常为4选项，AI 可能漏抽尾部选项）
    odd = [i + 1 for i, it in enumerate(items) if len(it["options"]) < 4]
    if odd:
        notes.append(f"{len(odd)} 题选项不足4个（第 {', '.join(map(str, odd[:10]))} 题），请在预览中核对")
    return items, "；".join(notes[:5])
