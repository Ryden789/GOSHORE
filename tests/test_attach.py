"""附件解析（app/attach.py）：docx / txt / 编码 / 截断 / 各类拒绝路径。

覆盖：
- docx 按段落取正文，表格一行压成一行（单元格用制表符）
- txt 支持 UTF-8 与 GB18030（中文旧文件常见）
- 超过 20000 字按上限截断并标 truncated
- 图片、zip、伪装成 txt 的 Office 二进制、坏 data_url、超大文件都要给出可读中文原因
- PDF 在缺 pymupdf 的环境里提示「请在电脑端导入」（安卓端走这条路）

运行：python -m pytest tests/test_attach.py -q
"""
from __future__ import annotations

import base64
import builtins
import io
import zipfile

import pytest

from app import attach

_DOCX_CT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
)

_DOCX_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
{w}</w:body></w:document>"""


def _docx(inner: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", _DOCX_CT)
        z.writestr("word/document.xml", _DOCX_BODY.format(w=inner))
    return buf.getvalue()


def _para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _url(raw: bytes, mime: str = "application/octet-stream") -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


# ---------------- docx ----------------

def test_docx_paragraphs_and_table():
    raw = _docx(
        _para("第一段：概括题作答")
        + _para("一、要点")
        + "<w:tbl><w:tr><w:tc>" + _para("甲") + "</w:tc><w:tc>" + _para("乙") + "</w:tc></w:tr></w:tbl>"
        + _para("结尾一句")
    )
    r = attach.extract("作答.docx", _url(raw))
    assert r["kind"] == "docx"
    assert r["kind_name"] == "Word 文档"
    lines = r["text"].split("\n")
    assert lines[0] == "第一段：概括题作答"
    assert lines[1] == "一、要点"
    # 表格不能拆成孤立短行，否则模型读不出对应关系
    assert "甲\t乙" in r["text"]
    assert lines[-1] == "结尾一句"
    assert r["chars"] == len(r["text"])
    assert r["truncated"] is False


def test_docx_keeps_blank_line_between_paragraphs():
    raw = _docx(_para("问题一") + "<w:p/>" + _para("问题二"))
    text = attach.extract("a.docx", _url(raw))["text"]
    assert text == "问题一\n\n问题二"


def test_docx_broken_zip_rejected():
    with pytest.raises(ValueError) as e:
        attach.extract("坏.docx", _url(b"not a zip at all"))
    assert ".docx" in str(e.value)


def test_docx_without_document_xml_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(ValueError) as e:
        attach.extract("空.docx", _url(buf.getvalue()))
    assert "docx" in str(e.value)


# ---------------- 纯文本与编码 ----------------

def test_txt_utf8_and_gb18030():
    s = "手写内容\n第二行"
    assert attach.extract("a.txt", _url(s.encode("utf-8")))["text"] == s
    # 老 Windows 记事本存的中文多是 GBK 系
    assert attach.extract("b.txt", _url(s.encode("gb18030")))["text"] == s


def test_text_mime_without_extension():
    r = attach.extract("", _url(b"hello", "text/plain"))
    assert r["kind"] == "text"
    assert r["text"] == "hello"


def test_crlf_and_extra_blank_lines_normalized():
    r = attach.extract("a.md", _url("甲\r\n\r\n\r\n\r\n乙".encode("utf-8")))
    assert r["text"] == "甲\n\n乙"


# ---------------- 上限与拒绝 ----------------

def test_long_text_truncated():
    long = "字" * (attach.MAX_FILE_CHARS + 500)
    r = attach.extract("长.txt", _url(long.encode("utf-8")))
    assert r["truncated"] is True
    assert r["chars"] == attach.MAX_FILE_CHARS
    assert "截断" in r["note"]


def test_image_rejected_with_ocr_hint():
    with pytest.raises(ValueError) as e:
        attach.extract("photo.png", _url(b"\x89PNG\r\n\x1a\n0000", "image/png"))
    assert "OCR" in str(e.value)


def test_zip_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", "x")
    with pytest.raises(ValueError) as e:
        attach.extract("包.zip", _url(buf.getvalue(), "application/zip"))
    assert "zip" in str(e.value)


def test_office_binary_named_txt_rejected():
    with pytest.raises(ValueError) as e:
        attach.extract("伪装.txt", _url(b"PK\x03\x04rubbish"))
    assert "不符" in str(e.value)


def test_unsupported_type_rejected():
    with pytest.raises(ValueError) as e:
        attach.extract("a.exe", _url(b"MZ\x90\x00"))
    assert "不支持" in str(e.value)


@pytest.mark.parametrize("bad", ["", "not-a-data-url", "data:text/plain;base64,!!!"])
def test_bad_data_url_rejected(bad):
    with pytest.raises(ValueError):
        attach.extract("a.txt", bad)


def test_oversize_rejected_before_decode(monkeypatch):
    """超大 base64 应在解码前就被拒，别先吃一遍内存。"""
    calls = []
    real = base64.b64decode
    monkeypatch.setattr(attach.base64, "b64decode",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    huge = "data:text/plain;base64," + "A" * (attach.MAX_FILE_BYTES * 2)
    with pytest.raises(ValueError) as e:
        attach.extract("大.txt", huge)
    assert "太大" in str(e.value)
    assert calls == []


def test_empty_file_rejected():
    with pytest.raises(ValueError) as e:
        attach.extract("空.txt", "data:text/plain;base64," + base64.b64encode(b"   ").decode())
    assert "没有可读的文字" in str(e.value)


# ---------------- PDF ----------------

def test_pdf_without_pymupdf_points_to_desktop(monkeypatch):
    """安卓端没有 pymupdf：必须明确让人换路，不能返回空串。"""
    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name == "fitz":
            raise ImportError("no pymupdf on android")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(ValueError) as e:
        attach._pdf_text(b"%PDF-1.4\n%fake")
    assert "电脑端" in str(e.value)


def test_pdf_text_layer_extracted_when_available():
    """桌面装了 pymupdf 时，文字层要被抽出（没装则跳过）。"""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Hello attach")
    raw = doc.tobytes()
    doc.close()
    text = attach._pdf_text(raw)
    assert "Hello attach" in text
