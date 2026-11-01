"""把开源行测真题库（github.com/ERRRC/xingcezhenti）整套卷导入 vault 的 99-自导入。

为什么需要它：题库主源（vault 10-真题）只收了判断推理与资料分析两科，
其余模块靠零散补充，于是「每套卷」只能凑出 60 题左右（国考行测本应 130~135 题）。
本脚本按「卷 × 题」逐条入库，每套卷都齐；题目全部来自真实真题，不做 AI 生成。

用法（先干跑看数量，再真跑）：
    python tools/import_open_bank.py --src D:\\_xczt_src --dry-run
    python tools/import_open_bank.py --src D:\\_xczt_src
    python tools/import_open_bank.py --src D:\\_xczt_src --only-inserted   # 只写库里没有的题

写入位置是 vault 的 99-自导入/<模块>/<题型>/open-<qid>-<卷指纹>.md，
与人工整理的题库同构：之后在设置里点「重建索引」也不会丢。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, parser  # noqa: E402
from app.config import load_settings  # noqa: E402

# 仓库目录名 → 题库模块名（政治理论并入常识判断，与现有模块口径一致）
MODULE_MAP = {
    "01-政治理论": "常识判断",
    "02-常识判断": "常识判断",
    "03-言语理解与表达": "言语理解",
    "04-数量关系": "数量关系",
    "05-判断推理": "判断推理",
    "06-资料分析": "资料分析",
}

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", re.S)
MAT_HEAD_RE = re.compile(r"^#{2,3}\s+材料\s*(\d+)\s*$")
Q_HEAD_RE = re.compile(r"^#{2,3}\s+第\s*(\d+)\s*题\s*(?:　|\s)*<sub>qid\s*(\d+)\s*·\s*(.*?)</sub>\s*$")
Q_HEAD_PLAIN_RE = re.compile(r"^#{2,3}\s+第\s*(\d+)\s*题\s*$")
OPT_RE = re.compile(r"^[-*]\s*(?:\*\*)?([A-Fa-f])(?:\*\*)?\s*[\.、．]\s*(.*)$")
ANS_RE = re.compile(r"^\*\*答案\*\*\s*[：:]\s*([A-Fa-f])")
ANA_HEAD_RE = re.compile(r"^\*\*官方解析\*\*\s*$")
FM_KV_RE = re.compile(r"^([A-Za-z_一-龥]+)\s*:\s*(.*)$")
TAG_RE = re.compile(r"<[^>]+>")


def read_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = FM_KV_RE.match(line)
        if kv:
            fm[kv.group(1)] = kv.group(2).strip().strip('"').strip("'")
    return fm, m.group(2)


def parse_paper(text: str) -> tuple[dict, list[dict]]:
    """把一份套卷 markdown 拆成题目列表（材料挂在对应小题上）。"""
    fm, body = read_frontmatter(text)
    paper = fm.get("试卷", "")
    region = fm.get("地区", "")
    year = fm.get("年份", "")
    module = fm.get("模块", "")

    questions: list[dict] = []
    material_lines: list[str] = []
    in_material = False
    cur: dict | None = None
    sec = "stem"      # stem → options → analysis
    ans = ""
    stem_lines: list[str] = []
    opt_lines: list[str] = []
    ana_lines: list[str] = []

    def flush() -> None:
        nonlocal cur, sec, ans, stem_lines, opt_lines, ana_lines
        if cur is None:
            return
        stem = "\n".join(stem_lines).strip()
        options = []
        for line in opt_lines:
            m = OPT_RE.match(line.strip())
            if not m:
                continue
            content = m.group(2).strip()
            correct = "✅" in content or "✔" in content
            content = content.replace("✅", "").replace("✔", "").replace("\u3000", " ").strip()
            options.append({"label": m.group(1).upper(), "text": content, "correct": correct})
        answer = ans or next((o["label"] for o in options if o["correct"]), "")
        questions.append({
            "no": cur["no"],
            "qid": cur["qid"],
            "tag": cur["tag"],
            "stem": stem,
            "options": options,
            "answer": answer,
            "analysis": "\n".join(ana_lines).strip(),
            "material": "\n".join(material_lines).strip(),
        })
        cur = None
        sec = "stem"
        ans = ""
        stem_lines, opt_lines, ana_lines = [], [], []

    for raw in body.splitlines():
        line = raw.rstrip()
        mmat = MAT_HEAD_RE.match(line)
        if mmat:
            flush()
            material_lines = []
            in_material = True
            sec = "stem"
            continue
        mq = Q_HEAD_RE.match(line) or Q_HEAD_PLAIN_RE.match(line)
        if mq:
            flush()
            no = int(mq.group(1))
            qid = mq.group(2) if len(mq.groups()) >= 3 and mq.group(2) else ""
            tag = (mq.group(3) if len(mq.groups()) >= 3 and mq.group(3) else "").strip()
            cur = {"no": no, "qid": qid, "tag": tag}
            sec = "stem"
            continue
        if cur is None:
            # 只有「## 材料 N」之后、第一道小题之前的正文才算材料
            if in_material and line.strip() and not line.strip().startswith("#"):
                material_lines.append(line)
            continue
        if line.strip() == "---":
            continue
        if sec == "stem":
            mo = OPT_RE.match(line.strip())
            if mo:
                sec = "options"
                opt_lines.append(line)
                continue
            ma = ANS_RE.match(line.strip())
            if ma:
                ans = ma.group(1).upper()
                sec = "analysis"
                continue
            if ANA_HEAD_RE.match(line.strip()):
                sec = "analysis"
                continue
            stem_lines.append(line)
        elif sec == "options":
            mo = OPT_RE.match(line.strip())
            if mo:
                opt_lines.append(line)
                continue
            ma = ANS_RE.match(line.strip())
            if ma:
                ans = ma.group(1).upper()
                sec = "analysis"
                continue
            if ANA_HEAD_RE.match(line.strip()):
                sec = "analysis"
                continue
            # 选项后、答案前的零散行（如选项图说明）并入最后一个选项
            if opt_lines and line.strip():
                sub = OPT_RE.match(opt_lines[-1].strip())
                if sub:
                    opt_lines[-1] += "\n" + line
        else:
            if ANA_HEAD_RE.match(line.strip()):
                continue
            ana_lines.append(line)
    flush()
    meta = {"paper": paper, "region": region, "year": year, "module": module}
    return meta, questions


def plain(text: str, n: int = 24) -> str:
    s = TAG_RE.sub("", text)
    s = re.sub(r"\s+", "", s)
    return s[:n] or "真题"


def safe_part(s: str, fallback: str) -> str:
    s = (s or "").strip().replace("/", "-").replace("\\", "-").replace('"', "")
    return s or fallback


def to_markdown(q: dict, paper: str, region: str, year: str, src: str) -> str:
    """生成与人工题库同构的 md（parser 可直接解析）。"""
    opts = "\n".join(
        f"- {o['label']}. {o['text']}{' ✅' if o['label'] == q['answer'] else ''}"
        for o in q["options"])
    mat = f"\n## 给定材料\n{q['material']}\n" if q["material"] else ""
    ana = q["analysis"] or "（暂无解析）"
    return f"""---
类型: 真题
qid: {q['qid']}
题号: {q['no']}
来源科目: {src}
地区: {region}
年份: "{year}"
试卷: {paper}
考点: {q['tag']}
tags: [自导入, 开放题库]
---

# {plain(q['stem'])}

## 题干
{q['stem']}

## 选项
{opts}

## 官方解析
答案：{q['answer']}

{ana}
{mat}"""


def image_relative(text: str) -> str:
    """笔记比仓库文件深两级（99-自导入/模块/题型/），图片相对路径要多两个 ..。"""
    return text.replace('src="../90-图片/', 'src="../../../90-图片/').replace(
        '](/90-图片/', '](../../../90-图片/')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="克隆下来的开源题库目录")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    ap.add_argument("--only-inserted", action="store_true", help="只导入库里(qid,试卷)都没有的题")
    ap.add_argument("--refresh", action="store_true",
                    help="只重写已存在的笔记（补新字段用），不新增、不改题量")
    ap.add_argument("--limit-papers", type=int, default=0, help="只处理前 N 份卷（调试用）")
    args = ap.parse_args()

    s = load_settings()
    vault = Path((s.get("vault_path") or "").strip())
    if not vault.is_dir():
        print(f"vault 路径不可用：{vault}")
        return 1

    conn = db.connect()
    with conn:
        existing = {(r[0], r[1]) for r in conn.execute(
            "SELECT qid, exam FROM documents WHERE qid!=''")}
        exam_counts = {r[0]: r[1] for r in conn.execute(
            "SELECT exam, COUNT(*) FROM documents WHERE exam!='' GROUP BY exam")}

    files: list[tuple[str, str, Path]] = []
    for repo_dir, module in MODULE_MAP.items():
        d = Path(args.src) / repo_dir
        if not d.is_dir():
            continue
        for fp in sorted(d.glob("*.md")):
            if fp.name.lower() == "readme.md":
                continue
            files.append((module, repo_dir, fp))
    if args.limit_papers:
        files = files[:args.limit_papers]

    wconn = db.content_writer() if db.split_enabled() else conn
    written = skipped = 0
    per_module: dict[str, int] = {}
    per_paper: dict[str, int] = {}
    for module, repo_dir, fp in files:
        text = image_relative(fp.read_text(encoding="utf-8"))
        meta, questions = parse_paper(text)
        paper = meta["paper"] or fp.stem
        paper_hash = hashlib.md5(paper.encode("utf-8")).hexdigest()[:6]
        for q in questions:
            if not q["qid"] or not q["stem"]:
                continue
            if args.only_inserted and (q["qid"], paper) in existing:
                skipped += 1
                continue
            tag = safe_part(q["tag"], "未分类")
            rel = f"99-自导入/{module}/{tag}/open-{q['qid']}-{paper_hash}.md"
            # 刷新模式只补字段，不新增笔记（否则会把人工整理过的题再复制一份）
            if args.refresh and not (vault / rel).exists():
                skipped += 1
                continue
            note = to_markdown(q, paper, meta["region"], meta["year"], repo_dir)
            written += 1
            per_module[module] = per_module.get(module, 0) + 1
            per_paper[paper] = per_paper.get(paper, 0) + 1
            if args.dry_run:
                continue
            target = vault / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(note, encoding="utf-8")
            p = parser.parse(rel, note)
            db._upsert(wconn, p, target.stat().st_mtime)
            if written % 2000 == 0:
                wconn.commit()
                print(f"  已写入 {written} …", flush=True)
    if not args.dry_run:
        wconn.commit()
        if wconn is not conn:
            wconn.close()
        conn.close()

    print(("干跑" if args.dry_run else "已导入") + f"：待写 {written} 题，跳过 {skipped} 题")
    for m, c in sorted(per_module.items()):
        print(f"  {m}: {c}")
    papers = sorted(per_paper.items(), key=lambda x: -x[1])[:5]
    print("  题量最多的卷：", papers)
    if args.dry_run:
        print(f"  预计套卷总数：{len(exam_counts) + len([p for p in per_paper if p not in exam_counts])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
