"""把「知识点综合/申论」的 PDF 转成 Markdown 笔记。

复用 pdf_notes_extract_hangce.py 的清洗 / 目录页剔除 / RapidOCR / 分节管线，
只把分类换成「申论」；扫描件（红宝书 / 解题思维册 / 题型通关册）自动补 OCR。

用法:
  python scripts/pdf_notes_extract_shenlun.py            # 提取（含 OCR）
  python scripts/pdf_notes_extract_shenlun.py --probe    # 只探测文本密度
输出:
  知识点综合/申论/整理/<文件名>.md + index.json + index.md + .ocr_cache/
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pdf_notes_extract_hangce as base  # noqa: E402

CAT = "申论"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if "--probe" in sys.argv:
        for p in sorted((base.ROOT / CAT).rglob("*.pdf")):
            with base.pymupdf.open(p) as d:
                avg = sum(len(pg.get_text()) for pg in d) / max(1, d.page_count)
                base.log(f"{avg:7.1f} 字/页 {d.page_count:4d} 页  {p.name}")
        return
    base.run_all([CAT], use_ocr=True, workers=10, min_chars=20)


if __name__ == "__main__":
    mp.freeze_support()
    main()
