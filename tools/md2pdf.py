# -*- coding: utf-8 -*-
"""Markdown 备考总纲转 PDF（fpdf2，中文字体支持）。

用法：
    python md2pdf.py <输入.md> <输出.pdf>
"""
import re
import sys
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]
BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyhbd.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
]

# 雅黑缺字替换表
GLYPH_FIX = {
    "\u2713": "\u221a",   # ✓ -> √
    "\u2717": "\u00d7",   # ✗ -> ×
    "\u2194": "\uff0f",   # <-> -> ／
    "\u2082": "2", "\u2081": "1", "\u2084": "4", "\u2083": "3",
    "\u207a": "+", "\u00b2": "2", "\u00b3": "3",
}


def find_font(cands):
    for p in cands:
        if Path(p).exists():
            return p
    raise FileNotFoundError("未找到可用中文字体：" + ", ".join(cands))


def sanitize(s):
    for k, v in GLYPH_FIX.items():
        s = s.replace(k, v)
    return s


def strip_md(s):
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"~~([^~]+)~~", r"\1", s)
    return sanitize(s)


class MD2PDF(FPDF):
    def __init__(self, title):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_title(title)
        self.set_auto_page_break(True, margin=15)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("msyh", "", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 6, self.title, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("msyh", "", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, f"第 {self.page_no()} 页", align="C")
        self.set_text_color(0, 0, 0)


def render_table(pdf, rows):
    def parse_row(r):
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        return [strip_md(c) for c in cells]

    body = [r for r in rows if not re.match(r"^\|?[\s:|-]+\|?$", r.replace(" ", "").replace("|", "|"))]
    body = [r for r in body if not re.match(r"^[\s:|-]+$", r.strip().replace("|", "").replace(" ", ""))]
    if not body:
        return
    header = parse_row(body[0])
    data = [parse_row(r) for r in body[1:]]
    ncols = max([len(header)] + [len(r) for r in data])
    header += [""] * (ncols - len(header))
    data = [r + [""] * (ncols - len(r)) for r in data]
    # 首列略宽
    if ncols >= 3:
        widths = [1.35] + [1.0] * (ncols - 1)
    else:
        widths = [1.0] * ncols

    pdf.set_font("msyh", "", 8.8)
    head_style = FontFace(emphasis="BOLD", fill_color=(238, 231, 222),
                          color=(60, 40, 30))
    with pdf.table(
        col_widths=widths,
        width=pdf.epw,
        text_align="LEFT",
        line_height=5.1,
        padding=1.4,
        headings_style=head_style,
        repeat_headings=1,
        borders_layout="ALL",
    ) as table:
        hr = table.row()
        for c in header:
            hr.cell(c)
        for row in data:
            r = table.row()
            for c in row:
                r.cell(c)
    pdf.ln(3)


def render(lines, out_path, title, pdf=None):
    if pdf is None:
        pdf = MD2PDF(title)
        font_path = find_font(FONT_CANDIDATES)
        bold_path = find_font(BOLD_CANDIDATES)
        pdf.add_font("msyh", "", font_path)
        if bold_path != font_path:
            pdf.add_font("msyh", "B", bold_path)
        pdf.add_page()

    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip()

        if not line.strip() or line.strip().startswith(">") is False and False:
            pass

        # 空行 / 引用块
        if not line.strip():
            i += 1
            continue
        if line.strip().startswith(">"):
            txt = strip_md(line.lstrip()[1:]).strip()
            if txt:
                pdf.set_font("msyh", "", 9)
                pdf.set_text_color(90, 90, 90)
                pdf.set_fill_color(246, 243, 238)
                x0 = pdf.l_margin + 2
                pdf.set_x(x0)
                pdf.multi_cell(0, 5, txt, fill=True, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1.2)
            i += 1
            continue

        # 水平线
        if re.match(r"^---+\s*$", line):
            pdf.ln(1)
            pdf.set_draw_color(180, 180, 180)
            pdf.set_line_width(0.3)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(3)
            i += 1
            continue

        # 表格块
        if line.lstrip().startswith("|"):
            tbl = []
            while i < n and lines[i].lstrip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            render_table(pdf, tbl)
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            txt = strip_md(m.group(2)).strip()
            if level == 1:
                pdf.ln(4)
                pdf.set_font("msyh", "B", 17)
                pdf.multi_cell(0, 9, txt, align="C", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)
                pdf.set_draw_color(140, 43, 33)
                pdf.set_line_width(0.6)
                y = pdf.get_y()
                pdf.line(pdf.l_margin + 55, y, pdf.w - pdf.r_margin - 55, y)
                pdf.ln(4)
            elif level == 2:
                if pdf.get_y() > 250:
                    pdf.add_page()
                pdf.ln(3)
                pdf.set_fill_color(238, 231, 222)
                pdf.set_text_color(60, 40, 30)
                pdf.set_font("msyh", "B", 12.5)
                pdf.multi_cell(0, 8, "  " + txt, fill=True, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1.5)
            elif level == 3:
                pdf.ln(2)
                pdf.set_font("msyh", "B", 11.5)
                pdf.set_text_color(140, 43, 33)
                pdf.multi_cell(0, 7, txt, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(0.8)
            else:
                pdf.ln(1)
                pdf.set_font("msyh", "B", 10.5)
                pdf.multi_cell(0, 6.5, txt, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(0.5)
            i += 1
            continue

        # 列表
        m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)", line)
        if m:
            indent = len(m.group(1)) // 2
            txt = strip_md(m.group(3)).strip()
            if txt.startswith("[ ]"):
                txt = "□ " + txt[3:].strip()
            elif txt.startswith("[x]") or txt.startswith("[X]"):
                txt = "☑ " + txt[3:].strip()
            marker = "• " if m.group(2) in "-*" else ""
            pdf.set_font("msyh", "", 9.5)
            pdf.set_x(pdf.l_margin + 3 + indent * 4)
            pdf.multi_cell(0, 5.4, marker + txt, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(0.4)
            i += 1
            continue

        # 普通段落
        txt = strip_md(line).strip()
        if txt:
            pdf.set_font("msyh", "", 9.5)
            pdf.multi_cell(0, 5.4, txt, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(0.6)
        i += 1

    if out_path:
        pdf.output(out_path)
    return pdf


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("用法: python md2pdf.py <输入1.md> [输入2.md ...] <输出.pdf>")
        sys.exit(1)
    srcs, dst = args[:-1], args[-1]
    title = Path(dst).stem
    pdf = None
    for idx, src in enumerate(srcs):
        lines = Path(src).read_text(encoding="utf-8").splitlines()
        pdf = render(lines, None, title, pdf=pdf)
        if idx < len(srcs) - 1:
            pdf.add_page()  # 文档之间分页
    pdf.output(dst)
    print(f"[OK] {dst}")


if __name__ == "__main__":
    main()
