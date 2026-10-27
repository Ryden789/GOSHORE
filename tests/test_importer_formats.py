"""题库导入的格式解析回归（app/importer.py 的 extract_text_from_file）。

为什么单独有这个文件
--------------------
导入是「用户把自己的题源塞进软件」的唯一通路，但它有三种格式各自依赖一个
第三方库（pdf→pdfplumber、docx→python-docx、xlsx→pandas+openpyxl）。这些
import 都写在函数体里（可选依赖，不装也能启动），于是：

  * 静态分析看不到依赖，requirements.txt 漏了 openpyxl 也没人发现；
  * 测试没覆盖到，`pip install -r requirements.txt` 装完仍然导不进 Excel。

实测就是这样：装完 requirements 里声明的包之后，上传 .xlsx 报
`ImportError: Import openpyxl failed`。本文件把三种格式都跑一遍，缺库即红。

运行：python -m pytest tests/test_importer_formats.py -q
"""
from __future__ import annotations

import io

import pytest

from app.importer import extract_text_from_file


def _csv_bytes(text: str, enc: str = "utf-8") -> bytes:
    return text.encode(enc)


class TestCsv:
    """CSV 走标准库 csv，不依赖 pandas（实测冷启动差 900ms）。"""

    def test_utf8(self):
        out = extract_text_from_file("t.csv", _csv_bytes("题干,答案\n1+1=?,B\n"))
        assert "题干\t答案" in out
        assert "1+1=?\tB" in out

    def test_utf8_bom(self):
        out = extract_text_from_file("t.csv", _csv_bytes("题干,答案\n甲,乙\n", "utf-8-sig"))
        assert "题干" in out
        assert "\ufeff" not in out, "BOM 必须被剥掉，否则首列列名会带不可见字符"

    def test_gbk(self):
        out = extract_text_from_file("t.csv", _csv_bytes("题干,答案\n甲,乙\n", "gbk"))
        assert "题干\t答案" in out

    def test_ragged_rows_are_padded(self):
        """短行要补空列，否则制表符列数不齐，下游按列切会错位。"""
        out = extract_text_from_file("t.csv", _csv_bytes("a,b,c\n1,2\n"))
        lines = out.splitlines()
        assert lines[1].count("\t") == 2
        assert lines[1].endswith("\t")

    def test_embedded_tabs_and_newlines_are_flattened(self):
        """字段内的 tab/换行会破坏「一列一 tab」的结构，必须压成空格。"""
        out = extract_text_from_file("t.csv", _csv_bytes('a,b\n"x\ty","p\nq"\n'))
        body = out.splitlines()[1]
        assert body.count("\t") == 1
        assert "\n" not in body

    def test_unknown_encoding_falls_back_without_raising(self):
        out = extract_text_from_file("t.csv", b"\xff\xfe\x00bad")
        assert isinstance(out, str)


class TestXlsx:
    """xlsx 走 pandas.read_excel，**实际引擎是 openpyxl**。

    这条测试就是为了钉住 openpyxl 必须在 requirements 里：漏了它，
    pandas 会抛 `Import openpyxl failed`，而 CSV/JSON 都正常，很难发现。
    """

    def test_xlsx_roundtrip(self):
        openpyxl = pytest.importorskip("openpyxl", reason="xlsx 导入依赖 openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["题干", "答案"])
        ws.append(["1+1=?", "B"])
        buf = io.BytesIO()
        wb.save(buf)

        out = extract_text_from_file("t.xlsx", buf.getvalue())

        assert "题干" in out
        assert "1+1=?" in out
        assert "B" in out
        # 输出约定是「制表符分隔」，下游按 \t 切列
        assert "\t" in out


class TestDocx:
    def test_docx_roundtrip(self):
        docx = pytest.importorskip("docx", reason="docx 导入依赖 python-docx")
        doc = docx.Document()
        doc.add_paragraph("第一题：1+1=?")
        doc.add_paragraph("")            # 空段落要被跳过
        doc.add_paragraph("第二题：2+2=?")
        buf = io.BytesIO()
        doc.save(buf)

        out = extract_text_from_file("t.docx", buf.getvalue())

        assert "第一题" in out
        assert "第二题" in out
        assert "\n\n" not in out, "空段落不应留下空行"

    def test_docx_bad_file_raises(self):
        pytest.importorskip("docx")
        with pytest.raises(Exception):
            extract_text_from_file("t.docx", b"not a docx")


class TestPdf:
    def test_pdf_text_extraction(self):
        fitz = pytest.importorskip("fitz", reason="PDF 解析依赖 pymupdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Question 1")
        data = doc.tobytes()
        doc.close()

        out = extract_text_from_file("t.pdf", data)

        assert "Question" in out

    def test_kangxi_radicals_are_normalized(self):
        """字体缺 ToUnicode 映射时 PDF 会给出康熙部首（⽉/⼒），要还原成常用字。"""
        out = extract_text_from_file("t.txt", "⽉".encode())
        assert out == "⽉"      # 非 pdf 路径不做转换，确认没有误伤


class TestPlainText:
    @pytest.mark.parametrize("name", ["t.txt", "t.md", "noext"])
    def test_text_passthrough(self, name):
        assert "hello" in extract_text_from_file(name, b"hello world")
