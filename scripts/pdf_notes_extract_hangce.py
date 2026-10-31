"""把「知识点综合」四大行测模块的 PDF 转成 Markdown 笔记。

分类: 资料分析 / 数量关系 / 言语理解 / 判断推理
输出: 知识点综合/<分类>/整理/<文件名>.md + index.json + index.md

用法:
  python scripts/pdf_notes_extract_hangce.py --probe        # 探测文本密度
  python scripts/pdf_notes_extract_hangce.py --cat 资料分析 # 只跑一个分类
  python scripts/pdf_notes_extract_hangce.py --all          # 全部
  python scripts/pdf_notes_extract_hangce.py --all --no-ocr # 跳过 OCR（只做文本层）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import re
import sys
import time
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(r"D:\GOSHORE\知识点综合")
CATS = ["资料分析", "数量关系", "言语理解", "判断推理"]
OUT_NAME = "整理"

WATERMARK_RE = re.compile(r"[〔\[（(]?\s*免费微信\s*kaoshi2036\s*[〕\]）)]?")
PAGE_NO_RE = re.compile(r"^[\s\-—·]*\d{1,3}[\s\-—·]*$")
JUNK_RE = re.compile(r"^[~\-=_·\.×√xX?？!！、,，。:：;；\s]{1,6}$")
MARKER_ONLY_RE = re.compile(r"^(?:[①-⑳]|\d{1,2}\.|[A-D]\.?|【[^】]{1,8}】)$")
# 目录页码残渣：1.1 / 2.3.1 / 单纯的数字编号
NUM_ONLY_RE = re.compile(r"^\d+(?:\.\d+)*[\.、]?$")
# 不算章节标题的方括注记（例题、注释、解析、真题等）
NOTE_TAG_RE = re.compile(r"^【(?:例|注|解析|答案|真题|补充|拓展|复习|提示|思考|总结|技巧|方法)\s*\d*】")

# 章节标题：第X节 / 第X讲 / 知识点N / 题型N / 专题N / 一、 / （一） / 【…】
HEAD_CH = re.compile(
    r"^(?:第[一二三四五六七八九十百零〇\d]+\s*[节讲章篇部单元]|"
    r"知识点\s*\d+|题型\s*[一二三四五六七八九十\d]+|专题\s*[一二三四五六七八九十\d]+|"
    r"模块\s*[一二三四五六七八九十\d]+|"
    r"[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|"
    r"【[^】]{2,20}】|※)"
)
SUB_HEAD = re.compile(r"^(?:[一二三四五六七八九十]+、.*|（[一二三四五六七八九十]+）.*|【[^】]{1,12}】|※.*|★.*)")

NOISE_RE = re.compile(
    r"上岸村|辜负|扫码|二维码|免费微信|kaoshi|抖音关注|公考小黑|仅供.{0,6}使用|后续更新|"
    r"微信公众号|Hey，上岸吧|时政要点即时学|橘长一定上岸|四海|逢考必过|"
    r"^\s*第\s*\d+\s*页|^\s*共\s*\d+\s*页|客服|咨询微信|flk|微信号"
)


def log(msg: str) -> None:
    print(msg, flush=True)


def clean_inline(s: str) -> str:
    s = WATERMARK_RE.sub("", s)
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    s = re.sub(r"(?<=[\u4e00-\u9fff0-9])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[0-9])", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def doc_left_margin(doc: pymupdf.Document, pages: list[int]) -> float:
    xs: list[float] = []
    for pno in pages:
        pg = doc[pno]
        w = pg.rect.width
        for b in pg.get_text("blocks"):
            if b[4].strip() and (b[2] - b[0]) > 0.4 * w:
                xs.append(round(b[0], 1))
    if not xs:
        return 0.0
    xs.sort()
    return xs[int(len(xs) * 0.12)]


def page_body_lines(page: pymupdf.Page, margin: float | None) -> list[str]:
    """margin=None 时不做左边界过滤（图形页/图文混排页用）。"""
    w = page.rect.width
    out: list[str] = []
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
        s = txt.strip()
        if not s:
            continue
        if margin is not None:
            width = x1 - x0
            is_body = x0 <= margin + 26
            if not is_body and x0 < 0.55 * w and width < 0.5 * w and HEAD_CH.match(clean_inline(s.splitlines()[0])):
                is_body = True
            if not is_body:
                continue
        for line in s.splitlines():
            line = clean_inline(line)
            if line:
                out.append(line)
    return out


def is_noise(line: str) -> bool:
    if NOISE_RE.search(line) or PAGE_NO_RE.match(line) or JUNK_RE.match(line) or MARKER_ONLY_RE.match(line):
        return True
    if NUM_ONLY_RE.match(line):
        return True
    if line.count(".") + line.count("…") >= 4:
        return True
    digits = sum(ch.isdigit() or ch == " " for ch in line)
    return len(line) > 8 and digits / len(line) > 0.6


def reflow(lines: list[str]) -> list[str]:
    paras: list[str] = []
    buf = ""
    prev = ""
    for raw in lines:
        line = raw.strip()
        if not line or is_noise(line):
            continue
        # PPT 翻页造成的相邻重复行只保留一次
        if line == prev:
            continue
        prev = line
        starts_new = bool(
            HEAD_CH.match(line)
            or SUB_HEAD.match(line)
            or re.match(r"^(?:[A-D][\.、]|\d{1,2}[\.、]|※|▶|【例\d|例题|真题|解析)", line)
        )
        if not buf:
            buf = line
            continue
        end_punct = buf[-1] in "。！？；：”』】）》"
        if starts_new or end_punct or len(buf) > 240 or buf.endswith(("A.", "B.", "C.", "D.")):
            paras.append(buf)
            buf = line
        else:
            if re.match(r"^[A-Za-z0-9]", buf[-1]) and re.match(r"^[A-Za-z0-9]", line[0]):
                buf += " " + line
            else:
                buf += line
    if buf:
        paras.append(buf)
    # 同一页/相邻页重复的内容（PPT 翻页动画、双栏重复）只保留一份
    dedup: list[str] = []
    for p in paras:
        if dedup and (p == dedup[-1] or (len(p) > 40 and dedup[-1].endswith(p))):
            continue
        dedup.append(p)
    return dedup


def split_long(sections: list[dict], limit: int = 2600) -> list[dict]:
    """单节过长时按段落切分，便于阅读与后续出题。"""
    out: list[dict] = []
    for sec in sections:
        body = sec["body"]
        if len(body) <= limit:
            out.append(sec)
            continue
        paras = body.split("\n")
        buf: list[str] = []
        size = 0
        part = 1
        for p in paras:
            if size + len(p) > limit and buf:
                out.append({"title": sec["title"] if part == 1 else f"{sec['title']}（{part}）",
                            "body": "\n".join(buf), "page": sec["page"]})
                part += 1
                buf, size = [], 0
            buf.append(p)
            size += len(p) + 1
        if buf:
            out.append({"title": sec["title"] if part == 1 else f"{sec['title']}（{part}）",
                        "body": "\n".join(buf), "page": sec["page"]})
    return out


def split_sections(paras: list[str], first_page: int) -> list[dict]:
    sections: list[dict] = []
    cur_title = "开篇"
    cur_body: list[str] = []
    cur_page = first_page

    def flush():
        nonlocal cur_body
        body = "\n".join(cur_body).strip()
        if body:
            sections.append({"title": cur_title, "body": body, "page": cur_page})
        cur_body = []

    for p in paras:
        head = HEAD_CH.match(p) and len(p) <= 80 and not NOTE_TAG_RE.match(p)
        title = ""
        if head:
            m = re.split(r"（单选）|（多选）|（判断）|【", p, maxsplit=1)
            title = re.sub(r"\s+", " ", m[0]).strip().strip("※·-— ")
        if head and len(title) >= 2:
            flush()
            # 「第二章实用速算技巧尾数法精确求和…」→ 只取第一句作为标题
            title = re.split(r"[。；！？，]", title)[0].strip()
            cur_title = (title[:32] or "正文")
            rest = "".join(m[1:]).strip()
            if rest and m[0].strip():
                cur_body.append(p[len(m[0]):].strip())
            elif rest:
                cur_body.append(rest)
        else:
            cur_body.append(p)
    flush()
    return split_long(sections)

    if len(sections) <= 1:
        text = "\n".join(paras)
        chunks = []
        step = 700
        for i in range(0, len(text), step):
            piece = text[i:i + step]
            title = re.split(r"[。；\n]", piece)[0][:30]
            chunks.append({"title": title or "正文", "body": piece, "page": first_page})
        return chunks
    return sections


def ocr_key(path: Path) -> str:
    return hashlib.md5(str(path).encode("utf-8")).hexdigest()[:12]


def ocr_clean(s: str) -> str:
    s = s.replace("〖", "【").replace("〗", "】").replace("〈", "《").replace("〉", "》")
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[，。；：、！？（）“”《》])", "", s)
    s = re.sub(r"(?<=[，。；：、！？（）“”《》])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"[ ]{2,}", " ", s)
    return s.strip()


_OCR_ENGINE = None


def get_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        import logging
        logging.getLogger().setLevel(logging.WARNING)
        from rapidocr import RapidOCR
        _OCR_ENGINE = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 2})
    return _OCR_ENGINE


def rapid_ocr(path: Path, doc: pymupdf.Document, cache_dir: Path, force: bool = False) -> list[str] | None:
    """渲染整份 PDF 并逐页 OCR（RapidOCR/PP-OCR，中文识别远好于系统 OCR）。

    缓存目录: <整理>/.ocr_cache/rapid_<key>/<page>.txt
    """
    cache = cache_dir / ("rapid_" + ocr_key(path))
    cache.mkdir(parents=True, exist_ok=True)
    todo = [i for i in range(doc.page_count) if force or not (cache / f"{i}.txt").exists()]
    if todo:
        eng = get_engine()
        for i in todo:
            pg = doc[i]
            pix = pg.get_pixmap(dpi=200, colorspace=pymupdf.csRGB)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            res = eng(img)
            lines: list[str] = []
            if res is not None and getattr(res, "txts", None):
                boxes = getattr(res, "boxes", None)
                items = list(zip(res.txts, boxes)) if boxes is not None else [(t, None) for t in res.txts]
                if boxes is not None:
                    # 按版面位置还原阅读顺序（先行后列）
                    items.sort(key=lambda it: (round(it[1][0][1] / 12), it[1][0][0]))
                lines = [t for t, _ in items]
            (cache / f"{i}.txt").write_text("\n".join(lines), encoding="utf-8")
    out: list[str] = []
    for i in range(doc.page_count):
        f = cache / f"{i}.txt"
        if not f.exists():
            return None
        for line in f.read_text(encoding="utf-8").splitlines():
            line = ocr_clean(line)
            if line:
                out.append(line)
    return out


def page_is_toc(lines: list[str]) -> bool:
    """目录页：整页由“….... 页码”点线行或纯编号行占满（避免误杀正文页的分节编号）。"""
    ls = [l for l in lines if l.strip()]
    if len(ls) < 6:
        return False
    dots = sum(1 for l in ls if l.count(".") + l.count("…") >= 4)
    nums = sum(1 for l in ls if NUM_ONLY_RE.match(l))
    return (dots >= 5 and dots / len(ls) >= 0.3) or (nums >= 8 and nums / len(ls) >= 0.5)


def extraction_lines(doc: pymupdf.Document, path: Path, cache_dir: Path, allow_ocr: bool,
                     min_chars: int = 20) -> tuple[list[str], str]:
    sample = sorted({min(p, doc.page_count - 1) for p in (0, 5, 15, doc.page_count // 2, doc.page_count - 1)})
    margin = doc_left_margin(doc, sample)
    all_lines: list[str] = []
    skipped = 0
    for pg in doc:
        page_lines = page_body_lines(pg, margin)
        if page_is_toc(page_lines):
            skipped += 1
            continue
        all_lines.extend(page_lines)
    if skipped:
        log(f"    跳过 {skipped} 页目录页")
    filtered = sum(len(x) for x in all_lines) / max(1, doc.page_count)

    if filtered < 40:
        # 图文混排 / 图形页：放弃左边界过滤，保留全部文本块
        loose: list[str] = []
        for pg in doc:
            page_lines = page_body_lines(pg, None)
            if page_is_toc(page_lines):
                continue
            loose.extend(page_lines)
        if sum(len(x) for x in loose) / max(1, doc.page_count) > filtered:
            all_lines = loose
            filtered = sum(len(x) for x in all_lines) / max(1, doc.page_count)

    kind_now = "text" if filtered >= 60 else "text-lite"
    # 每页字数低于 min_chars（文字被烧进图片的课件/图推）→ 补 OCR
    if filtered >= min_chars or not allow_ocr:
        return all_lines, kind_now
    lines = rapid_ocr(path, doc, cache_dir)
    if not lines:
        return all_lines, kind_now
    ocr_density = sum(len(x) for x in lines) / max(1, doc.page_count)
    # OCR 反而更少内容时保留文本层
    return (lines, "ocr") if ocr_density >= filtered * 0.8 else (all_lines, kind_now)


def write_doc(md_dir: Path, name: str, sections: list[dict], kind: str, path: Path,
              cat: str, pages: int) -> dict:
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / (path.stem + ".md")
    kind_cn = {"text": "文本层", "ocr": "OCR", "text-lite": "文本层（稀疏，含图）"}.get(kind, kind)
    parts = [f"# {path.stem}", "", f"> 来源：{name}｜分类：{cat}｜页数：{pages}｜提取方式：{kind_cn}", ""]
    items = []
    for sec in sections:
        parts += [f"## {sec['title']}", "", sec["body"], ""]
        items.append({
            "id": hashlib.md5((cat + name + sec["title"] + sec["body"][:40]).encode("utf-8")).hexdigest()[:10],
            "module": cat,
            "module_name": cat,
            "source": name,
            "file": md_path.name,
            "title": sec["title"],
            "body": sec["body"],
            "chars": len(sec["body"]),
            "quality": kind,
        })
    md_path.write_text("\n".join(parts), encoding="utf-8")
    return {"source": name, "module": cat, "file": md_path.name,
            "pages": pages, "sections": len(sections),
            "chars": sum(i["chars"] for i in items), "kind": kind, "items": items}


def process_file(task: tuple[str, str, bool, int]) -> dict | None:
    """单份 PDF → md（在子进程中执行，OCR 大文件并行跑）。"""
    cat, pstr, use_ocr, min_chars = task
    path = Path(pstr)
    out_dir = ROOT / cat / OUT_NAME
    cache_dir = out_dir / ".ocr_cache"
    t0 = time.time()
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        log(f"[跳过] {cat}/{path.name}: {e}")
        return None
    pages = doc.page_count
    lines, kind = extraction_lines(doc, path, cache_dir, allow_ocr=use_ocr, min_chars=min_chars)
    if not lines:
        log(f"[跳过] {cat}/{path.name}: 无可用文本")
        doc.close()
        return None
    paras = reflow(lines)
    if not paras:
        log(f"[跳过] {cat}/{path.name}: 清洗后为空")
        doc.close()
        return None
    sections = split_sections(paras, 1)
    rec = write_doc(out_dir, path.name, sections, kind, path, cat, pages)
    log(f"[完成] {cat}/{path.name} | {rec['sections']} 节 | {rec['chars']} 字 | {kind} | "
        f"{time.time() - t0:.1f}s")
    doc.close()
    return rec


def write_index(cat: str, records: list[dict]) -> dict:
    out_dir = ROOT / cat / OUT_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "category": cat,
        "modules": [{"key": cat, "name": cat}],
        "docs": [{k: v for k, v in r.items() if k != "items"} for r in records],
        "items": [it for r in records for it in r["items"]],
    }
    (out_dir / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    lines_md = [f"# {cat} · 资料整理目录", "",
                f"> 生成时间：{payload['generated_at']}｜共 {len(records)} 份资料，"
                f"{len(payload['items'])} 个知识点，{sum(r['chars'] for r in records)} 字", ""]
    for r in records:
        kind_cn = {"text": "文本层", "ocr": "OCR", "text-lite": "文本层（稀疏）"}.get(r["kind"], r["kind"])
        title = r["source"][:-4] if r["source"].lower().endswith(".pdf") else r["source"]
        lines_md.append(f"- [{title}]({r['file']}) — {r['pages']} 页 · {r['sections']} 节 · "
                        f"{r['chars']} 字 · {kind_cn}")
    (out_dir / "index.md").write_text("\n".join(lines_md) + "\n", encoding="utf-8")
    return {"cat": cat, "docs": len(records), "items": len(payload["items"]),
            "chars": sum(r["chars"] for r in records)}


def run_all(cats: list[str], use_ocr: bool = True, workers: int = 8, min_chars: int = 20) -> list[dict]:
    tasks: list[tuple[str, str, bool, int]] = []
    total_pdf = {}
    for cat in cats:
        cat_dir = ROOT / cat
        pdfs = sorted(cat_dir.rglob("*.pdf"))
        total_pdf[cat] = len(pdfs)
        others = [p for p in cat_dir.rglob("*")
                  if p.is_file() and p.suffix.lower() != ".pdf"
                  and OUT_NAME not in p.relative_to(cat_dir).parts]
        log(f"{cat}：{len(pdfs)} 份 PDF" + (f"，{len(others)} 个非 PDF 文件（跳过）" if others else ""))
        tasks += [(cat, str(p), use_ocr, min_chars) for p in pdfs]

    by_cat: dict[str, list[dict]] = {c: [] for c in cats}
    log(f"共 {len(tasks)} 份 PDF 入队，并行度 {workers}")
    if workers > 1:
        with mp.Pool(workers) as pool:
            for rec in pool.imap_unordered(process_file, tasks, chunksize=1):
                if rec:
                    by_cat[rec["module"]].append(rec)
    else:
        for t in tasks:
            rec = process_file(t)
            if rec:
                by_cat[rec["module"]].append(rec)

    summary = []
    for cat in cats:
        recs = sorted(by_cat[cat], key=lambda r: r["source"])
        if not recs:
            continue
        s = write_index(cat, recs)
        s["skipped"] = total_pdf[cat] - len(recs)
        log(f"→ {cat}/整理：{s['docs']} 份 md，{s['items']} 条知识点，{s['chars']} 字")
        summary.append(s)
    return summary


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cat", default="")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-chars", type=int, default=20, help="每页字数低于该值时补 OCR")
    args = ap.parse_args()

    cats = [args.cat] if args.cat else CATS
    if args.probe:
        for cat in cats:
            for p in sorted((ROOT / cat).rglob("*.pdf")):
                with pymupdf.open(p) as d:
                    avg = sum(len(pg.get_text()) for pg in d) / max(1, d.page_count)
                    log(f"{avg:7.1f} 字/页 {d.page_count:4d} 页  [{cat}] {p.name}")
        return
    if not args.all and not args.cat:
        log("请加 --all 或 --cat <分类> 或 --probe")
        return

    t0 = time.time()
    summary = run_all(cats, use_ocr=not args.no_ocr, workers=args.workers, min_chars=args.min_chars)
    log("\n===== 汇总 =====")
    for s in summary:
        log(f"{s['cat']}: {s['docs']} 份 md / {s['items']} 条知识点 / {s['chars']} 字"
            + (f" / 跳过 {s['skipped']} 份" if s["skipped"] else ""))
    log(f"总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    mp.freeze_support()
    main()
