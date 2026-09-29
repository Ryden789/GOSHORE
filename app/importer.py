"""题库导入：自有 JSON 题库 + 网页/文本真题 AI 抽取。

导入的题目以 Markdown 写入 vault 的 99-自导入/{模块}/ 目录，
与人工整理的题库同构，解析、检索、AI 讲题全部复用现有链路。
"""
from __future__ import annotations

import json
import re
import time
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


def parse_json_bank(text: str) -> tuple[list[dict], list[str]]:
    """解析用户自有题库 JSON（数组）。返回 (items, errors)。"""
    text = text.strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return [], ["未找到 JSON 数组"]
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return [], [f"JSON 解析失败：{e}"]
    if not isinstance(arr, list):
        return [], ["JSON 顶层必须是数组"]
    items, errors = [], []
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
        return "\n\n".join(parts)
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


_EXTRACT_PROMPT = """你是事业单位C类题库录入员。从用户给的网页/文本内容中抽取所有选择题（真题），输出 JSON 数组，不要任何额外文字或 markdown 代码块。

每题格式：
{"stem":"完整题干（含材料中的设问句）","options":["A. ...","B. ...","C. ...","D. ..."],"answer":"A","analysis":"解析（原文有则保留，没有则留空）","module":"模块","kaodian":"考点","year":"年份","exam":"试卷名"}

module 只能是：常识判断 / 言语理解 / 数量关系 / 判断推理 / 资料分析 / 综合分析（按题目内容判断）。
只抽取完整的选择题（题干+至少2个选项+答案），不完整的跳过。没有可抽取的题就输出 []。"""


async def ai_extract_questions(text: str) -> tuple[list[dict], str]:
    """用 DeepSeek 从网页文本中抽取真题。返回 (items, 错误信息)。"""
    s = load_settings()
    if not s["deepseek_api_key"]:
        return [], "未配置 DeepSeek API Key，请先在设置页配置"
    # 控制长度，防止超 token
    text = text[:12000]
    payload = {
        "model": s["deepseek_model"],
        "messages": [
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 4000,
    }
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            return [], f"AI 接口错误 {r.status_code}"
        content = r.json()["choices"][0]["message"]["content"]
    items, errors = parse_json_bank(content)
    if not items and not errors:
        return [], "AI 未从内容中识别出完整题目"
    return items, "；".join(errors[:3]) if errors else ""
