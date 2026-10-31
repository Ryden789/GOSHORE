"""附件上传的接口契约与双端一致性。

分三层：
1. 桌面 FastAPI：两个新接口能答对（解析成功 / 未配 Key 的 400 文案）
2. 安卓内置服务：同构分支存在（它跑不了 TestClient，只能静态守）
3. 双端前端：工具条、目标框绑定、两个接口调用、accept 覆盖 docx

运行：python -m pytest tests/test_attach_ui.py -q
"""
from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"

_CSS = """
.wrap { color: red; }
"""


def _docx(inner: str) -> bytes:
    head = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", head + inner + "</w:body></w:document>")
    return buf.getvalue()


def _url(raw: bytes, mime: str = "application/octet-stream") -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


@pytest.fixture()
def client(temp_db, monkeypatch):
    # 空临时库会触发首次建索引，扫开发机真实 vault 会像卡死
    monkeypatch.setattr(temp_db, "reindex", lambda: None)
    with TestClient(main.app) as c:
        yield c


# ---------------- 桌面接口 ----------------

def test_file_extract_endpoint(client):
    raw = _docx("<w:p><w:r><w:t>题目一</w:t></w:r></w:p>")
    r = client.post("/api/file/extract", json={"name": "题干.docx", "data_url": _url(raw)})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["kind"] == "docx"
    assert d["text"] == "题目一"


def test_file_extract_bad_input_is_400(client):
    r = client.post("/api/file/extract", json={"name": "a.png", "data_url": _url(b"xx", "image/png")})
    assert r.status_code == 400
    assert "OCR" in r.json()["detail"]


def test_ocr_requires_key(client, monkeypatch):
    monkeypatch.setattr(main, "load_settings", lambda: {"deepseek_api_key": ""})
    r = client.post("/api/ocr", json={"image": "data:image/jpeg;base64,AAAA", "mode": "essay"})
    assert r.status_code == 400
    assert "API Key" in r.json()["detail"]


def test_ocr_rejects_non_image(client, monkeypatch):
    monkeypatch.setattr(main, "load_settings", lambda: {"deepseek_api_key": "sk-x"})
    r = client.post("/api/ocr", json={"image": "http://evil/a.jpg", "mode": "essay"})
    assert r.status_code == 400


def test_routes_registered():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/file/extract" in paths
    assert "/api/ocr" in paths


# ---------------- 安卓端同构 ----------------

def test_android_server_has_both_branches():
    text = SERVER.read_text(encoding="utf-8")
    assert 'elif path == "/api/file/extract":' in text
    assert 'elif path == "/api/ocr":' in text
    # OCR 是协程，必须走 _run_async，否则返回未 await 的协程对象
    tail = text.split('elif path == "/api/ocr":')[1][:400]
    assert "_run_async(" in tail
    assert "attach" in text.split("\n")[15] or "attach" in text.split("from app import")[1][:400]
    assert "ocr" in text.split("from app import")[1][:400]


# ---------------- 前端契约 ----------------

@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_frontend_has_attach_entry(path):
    text = path.read_text(encoding="utf-8")
    assert "/api/file/extract" in text, f"{path.name} 没接文件解析接口"
    assert "/api/ocr" in text, f"{path.name} 没接图片识别接口"
    assert "function bindAttachBars" in text, f"{path.name} 缺工具条绑定函数"
    assert "attach-bar" in text
    assert "data-target" in text


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_frontend_accept_covers_docx_and_pdf(path):
    text = path.read_text(encoding="utf-8")
    assert ".docx" in text and ".pdf" in text, f"{path.name} 的文件选择没放开 docx/pdf"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_attach_bars_cover_three_fields(path):
    text = path.read_text(encoding="utf-8")
    for target in ('data-target="gQ"', 'data-target="gM"', 'data-target="gA"'):
        assert target in text, f"{path.name} 缺 {target}"
    # 作答框要走申论转写模式，题干/材料走通用模式
    assert 'data-ocr="essay"' in text
    assert 'data-ocr="general"' in text


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_attach_bars_bound_in_grade_page(path):
    text = path.read_text(encoding="utf-8")
    assert "bindAttachBars();" in text, f"{path.name} 批改页没调用绑定"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_ai_page_accepts_files(path):
    text = path.read_text(encoding="utf-8")
    # AI 答疑侧要有附件正文预算，避免把几万字塞进上下文
    assert "ATTACH_TEXT_BUDGET" in text, f"{path.name} 缺附件字数上限"
    assert "【附件：" in text, f"{path.name} 没把附件正文拼进提问"


@pytest.mark.parametrize("css", ["static/styles.css", "static/m/m.css"])
def test_attach_styles_exist(css):
    text = (ROOT / css).read_text(encoding="utf-8")
    for cls in (".attach-bar", ".attach-btn", ".attach-hint"):
        assert cls in text, f"{css} 缺 {cls}"


def test_docx_hint_mentions_shortcut_on_mobile():
    """手机端 PDF 明确指向电脑端，别让用户以为是网络问题。"""
    text = (ROOT / "app" / "attach.py").read_text(encoding="utf-8")
    assert "电脑端" in text
