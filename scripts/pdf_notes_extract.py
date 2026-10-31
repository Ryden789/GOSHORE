"""批量提取「知识点综合」PDF 的正文，清洗后按模块整理成 Markdown + index.json。

用法:
  python scripts/pdf_notes_extract.py --probe          # 只探测每份 PDF 的文本密度
  python scripts/pdf_notes_extract.py --limit 3        # 只跑前 3 份，验证效果
  python scripts/pdf_notes_extract.py --all            # 全量（自动使用 OCR 缓存）
  python scripts/pdf_notes_extract.py --ocr-only       # 只给低密度 PDF 补 OCR 缓存（可后台跑）

输出:
  知识点综合/_整理/<模块>/<文件名>.md
  知识点综合/_整理/index.json
  OCR 缓存: 知识点综合/_整理/.ocr_cache/<key>/<page>.txt
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(r"D:\GOSHORE\知识点综合\政治理论+常识")
OUT_DIR = Path(r"D:\GOSHORE\知识点综合\_整理")
CACHE_DIR = OUT_DIR / ".ocr_cache"

WATERMARK_RE = re.compile(r"[〔\[（(]?\s*免费微信\s*kaoshi2036\s*[〕\]）)]?")
PAGE_NO_RE = re.compile(r"^[\s\-—·]*\d{1,3}[\s\-—·]*$")
JUNK_RE = re.compile(r"^[~\-=_·\.×√xX?？!！、,，。:：;；\s]{1,6}$")
MARKER_ONLY_RE = re.compile(r"^(?:[①-⑳]|\d{1,2}\.|[A-D]\.?|【[^】]{1,8}】)$")

HEAD_CH = re.compile(r"^(?:知识点\s*\d+[\s、．.]*.*|第[一二三四五六七八九十百零〇\d]+[篇章讲部].*)$")
SUB_HEAD = re.compile(r"^(?:[一二三四五六七八九十]+、.*|（[一二三四五六七八九十]+）.*|【[^】]{1,12}】|※.*)$")

MODULES = {
    "political": "政治理论",
    "common_law": "常识·法律",
    "common_hist": "常识·文史",
    "common_sci": "常识·科技",
    "common_geo": "常识·经济地理",
    "mindmap": "思维导图",
    "mixed": "综合讲练",
}

KW = {
    "common_law": "宪法 刑法 民法 民法典 行政法 诉讼法 法律责任 犯罪 处罚 罪名 合同 侵权 物权 行政许可 行政处罚 公务员法 监察法 治安管理处罚法",
    "common_hist": "朝代 春秋 战国 秦朝 汉朝 唐朝 宋朝 明朝 清朝 诗词 文学 历史 遗址 战役 变法 诸子 古代 近代 革命",
    "common_sci": "物理 化学 生物 天文 医学 航天 元素 细胞 基因 能源 光学 力学 科技 发明 诺贝尔 空间站",
    "common_geo": "地理 气候 山脉 河流 洋流 地形 经济 市场 货币 银行 财政 税收 GDP 通货膨胀 汇率 产业",
    "political": "习近平 中国共产党 社会主义 马克思主义 二十大 新时代 共同富裕 现代化 党建引领",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def clean_inline(s: str) -> str:
    s = WATERMARK_RE.sub("", s)
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    # 数字与汉字之间被 PDF 插入的多余空格：19 世纪60—90 年代 -> 19世纪60—90年代
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


def page_body_lines(page: pymupdf.Page, margin: float) -> list[str]:
    """只保留正文列（左边距对齐）的文本块，丢掉手写/边注图层。"""
    w = page.rect.width
    out: list[str] = []
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
        s = txt.strip()
        if not s:
            continue
        width = x1 - x0
        is_body = x0 <= margin + 26
        # 居中的章节标题也属于正文
        if not is_body and x0 < 0.55 * w and width < 0.5 * w and HEAD_CH.match(clean_inline(s.splitlines()[0])):
            is_body = True
        if not is_body:
            continue
        for line in s.splitlines():
            line = clean_inline(line)
            if line:
                out.append(line)
    return out


NOISE_RE = re.compile(r"上岸村|辜负|扫码|二维码|免费微信|kaoshi|抖音关注|公考小黑|仅供.{0,6}使用|后续更新|微信公众号|Hey，上岸吧|时政要点即时学|橘长一定上岸")


def is_noise(line: str) -> bool:
    if NOISE_RE.search(line) or PAGE_NO_RE.match(line) or JUNK_RE.match(line) or MARKER_ONLY_RE.match(line):
        return True
    if line.count(".") + line.count("…") >= 4:  # 目录点线（第一篇《…》............ 2）
        return True
    digits = sum(ch.isdigit() or ch == " " for ch in line)
    return len(line) > 8 and digits / len(line) > 0.6


def reflow(lines: list[str]) -> list[str]:
    """把 PDF 的硬换行重排成自然段落。"""
    paras: list[str] = []
    buf = ""
    for raw in lines:
        line = raw.strip()
        if not line or is_noise(line):
            continue
        starts_new = bool(HEAD_CH.match(line) or SUB_HEAD.match(line) or re.match(r"^(?:[A-D][\.、]|\d{1,2}[\.、]|※|▶)", line))
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
    return paras


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
        if HEAD_CH.match(p) and len(p) <= 80:
            flush()
            m = re.split(r"（单选）|（多选）|（判断）|【", p, maxsplit=1)
            cur_title = re.sub(r"\s+", " ", m[0]).strip()[:40]
            rest = "".join(m[1:]).strip()
            if rest:
                cur_body.append(p[len(m[0]):].strip())
        else:
            cur_body.append(p)
    flush()

    # 没有识别出章节的文件：按长度切块，标题取首个短语
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


def guess_module(name: str, text: str) -> str:
    n = name.lower()
    if "思维导图" in name:
        return "mindmap"
    if "法律" in name:
        return "common_law"
    if "文史" in name:
        return "common_hist"
    if "科技" in name:
        return "common_sci"
    if "经济" in name or "地理" in name:
        return "common_geo"
    if "理论讲练" in name or "消化清单" in name:
        return "mixed"
    if "政治" in name:
        return "political"
    scores = {k: sum(text.count(w) for w in v.split()) for k, v in KW.items()}
    best = max(scores, key=scores.get)
    if scores[best] < 6:
        return "common_hist" if "常识" in name else "political"
    return best


def ocr_key(path: Path) -> str:
    return hashlib.md5(path.name.encode("utf-8")).hexdigest()[:12]


def ocr_clean(s: str) -> str:
    s = s.replace("〖", "【").replace("〗", "】").replace("〈", "《").replace("〉", "》")
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[，。；：、！？（）“”《》])", "", s)
    s = re.sub(r"(?<=[，。；：、！？（）“”《》])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"[ ]{2,}", " ", s)
    return s.strip()


def win_ocr(path: Path, doc: pymupdf.Document, force: bool = False) -> list[str] | None:
    """渲染全部页面并用 Windows 内置 OCR 识别，结果缓存在 _整理/.ocr_cache。"""
    cache = CACHE_DIR / ocr_key(path)
    txt_dir = cache / "txt"
    img_dir = cache / "img"
    if force or not all((txt_dir / f"{i}.txt").exists() for i in range(doc.page_count)):
        img_dir.mkdir(parents=True, exist_ok=True)
        txt_dir.mkdir(parents=True, exist_ok=True)
        for i, pg in enumerate(doc):
            f = img_dir / f"{i}.png"
            if force or not f.exists():
                pg.get_pixmap(dpi=220).save(f)
        ps1 = Path(__file__).with_name("win_ocr.ps1")
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
             "-InDir", str(img_dir), "-OutDir", str(txt_dir)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        for f in img_dir.glob("*.png"):
            f.unlink()
    lines: list[str] = []
    for i in range(doc.page_count):
        f = txt_dir / f"{i}.txt"
        if not f.exists():
            return None
        for line in f.read_text(encoding="utf-8").splitlines():
            line = ocr_clean(line)
            if line:
                lines.append(line)
    return lines


def extraction_lines(doc: pymupdf.Document, path: Path, allow_ocr: bool) -> tuple[list[str], str]:
    """返回 (文本行, text|ocr|need_ocr)。正文密度过低时说明是图片型 PDF，转 OCR。"""
    sample = sorted({min(p, doc.page_count - 1) for p in (0, 5, 15, doc.page_count // 2, doc.page_count - 1)})
    margin = doc_left_margin(doc, sample)
    all_lines: list[str] = []
    for pg in doc:
        all_lines.extend(page_body_lines(pg, margin))
    per_page = sum(len(x) for x in all_lines) / max(1, doc.page_count)
    if per_page >= 60:
        return all_lines, "text"
    if not allow_ocr:
        return [], "need_ocr"
    lines = win_ocr(path, doc)
    return (lines, "ocr") if lines else ([], "need_ocr")


def write_doc(module: str, name: str, sections: list[dict], source: str, src_kind: str, path: Path) -> dict:
    md_dir = OUT_DIR / MODULES[module]
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / (path.stem + ".md")
    parts = [f"# {path.stem}", "", f"> 来源：{name}｜提取方式：{'OCR' if src_kind == 'ocr' else '文本层'}", ""]
    items = []
    for sec in sections:
        parts += [f"## {sec['title']}", "", sec["body"], ""]
        items.append({
            "id": hashlib.md5((name + sec["title"] + sec["body"][:40]).encode("utf-8")).hexdigest()[:10],
            "module": module,
            "module_name": MODULES[module],
            "source": name,
            "file": str(md_path.relative_to(OUT_DIR)).replace("\\", "/"),
            "title": sec["title"],
            "body": sec["body"],
            "chars": len(sec["body"]),
            "quality": src_kind,
        })
    md_path.write_text("\n".join(parts), encoding="utf-8")
    return {"source": name, "module": module, "file": str(md_path.relative_to(OUT_DIR)).replace("\\", "/"),
            "sections": len(sections), "chars": sum(i["chars"] for i in items), "kind": src_kind, "items": items}


def run(pdfs: list[Path], use_ocr: bool = True) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for idx, path in enumerate(pdfs, 1):
        t0 = time.time()
        try:
            doc = pymupdf.open(path)
        except Exception as e:  # 损坏文件不阻塞整体
            log(f"[{idx}/{len(pdfs)}] 跳过 {path.name}: {e}")
            continue
        lines, kind = extraction_lines(doc, path, allow_ocr=use_ocr)

        if kind == "need_ocr":
            log(f"[{idx}/{len(pdfs)}] {path.name}: 无可用文本（图片型且 OCR 未成功），跳过")
            doc.close()
            continue

        if not lines:
            log(f"[{idx}/{len(pdfs)}] {path.name}: 无可用文本，跳过")
            doc.close()
            continue

        paras = reflow(lines)
        text = "\n".join(paras)
        module = guess_module(path.name, text)
        sections = split_sections(paras, 1)
        rec = write_doc(module, path.name, sections, path.name, kind, path)
        records.append(rec)
        log(f"[{idx}/{len(pdfs)}] {path.name} -> {MODULES[module]} | {rec['sections']} 节 | "
            f"{rec['chars']} 字 | {kind} | {time.time() - t0:.1f}s")
        doc.close()

    index_path = OUT_DIR / "index.json"
    old = {}
    if index_path.exists():
        try:
            old = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    merged = {i["id"]: i for i in old.get("items", [])}
    for rec in records:
        for it in rec.pop("items"):
            merged[it["id"]] = it
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "modules": [{"key": k, "name": v} for k, v in MODULES.items()],
        "docs": records + [d for d in old.get("docs", []) if d["source"] not in {r["source"] for r in records}],
        "items": list(merged.values()),
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    # 同步给 App：app/kb.py 读取 data/kb.json
    kb_path = Path(r"D:\GOSHORE\data\kb.json")
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    kb_path.write_text(json.dumps({"modules": payload["modules"], "items": payload["items"]},
                                  ensure_ascii=False), encoding="utf-8")
    log(f"index.json: {len(payload['items'])} 条知识点，{len(payload['docs'])} 份文档")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    pdfs = sorted(ROOT.rglob("*.pdf"))
    if not pdfs:
        log(f"未找到 PDF: {ROOT}")
        return
    if args.probe:
        for p in pdfs:
            with pymupdf.open(p) as d:
                avg = sum(len(pg.get_text()) for pg in d) / max(1, d.page_count)
                log(f"{avg:7.1f} 字/页  {d.page_count:4d}页  {p.name}")
        return
    if args.limit:
        pdfs = pdfs[: args.limit]
    elif not args.all:
        log("请加 --all 或 --limit N 或 --probe")
        return
    if args.all:  # 全量重跑：清掉旧的模块目录（保留 OCR 缓存）
        import shutil
        for name in MODULES.values():
            shutil.rmtree(OUT_DIR / name, ignore_errors=True)
        (OUT_DIR / "index.json").unlink(missing_ok=True)
    run(pdfs)


if __name__ == "__main__":
    main()
