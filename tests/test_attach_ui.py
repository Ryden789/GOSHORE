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


# ---------------- 附件正文不被 /api/ai/ask 静默截断 ----------------
# 历史缺陷：前端把「提问 + 8000 字附件」拼成同一条 content，后端
# normalize_ask_messages 按 ASK_MAX_TEXT=4000 静默截断，于是附件后半段
# 永远到不了模型，用户也拿不到任何提示。修法是前端按条切块。

def _js_chunk(path):
    import re
    text = path.read_text(encoding="utf-8")
    m = re.search(r"const ASK_CHUNK = (\d+);", text)
    assert m, f"{path.name} 缺 ASK_CHUNK 常量"
    return int(m.group(1))


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_attach_chunks_fit_backend_limit(path):
    from app.ai import ASK_MAX_TEXT

    chunk = _js_chunk(path)
    # 分块必须小于后端单条上限，且留得下「【附件：xx（第 1/3 段）】」这类标题
    assert chunk <= ASK_MAX_TEXT - 100, f"{path.name} 的 ASK_CHUNK={chunk} 太贴近 {ASK_MAX_TEXT}"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_attach_text_is_chunked_not_concatenated(path):
    text = path.read_text(encoding="utf-8")
    # 旧写法：把附件拼进提问再一起发
    assert "${ask}\n\n${attachText}" not in text, f"{path.name} 又把附件拼回提问里了"
    # 新写法：按 ASK_CHUNK 逐段 push 独立消息
    assert "i += ASK_CHUNK" in text, f"{path.name} 缺分块循环"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_attach_over_budget_truncates_instead_of_rejecting(path):
    text = path.read_text(encoding="utf-8")
    assert "const room = ATTACH_TEXT_BUDGET - used;" in text, f"{path.name} 超额应取剩余额度而非整份拒绝"


def test_chunked_attach_reaches_backend_intact():
    """8000 字附件按前端策略切块后，经后端规范化应一字不少。"""
    from app.ai import normalize_ask_messages

    chunk = _js_chunk(APP_JS)
    body = "材料" * 4000            # 8000 字
    total = max(1, -(-len(body) // chunk))
    msgs = []
    for i in range(0, len(body), chunk):
        k = i // chunk + 1
        head = f"【附件：材料.docx（第 {k}/{total} 段）】\n" if total > 1 else "【附件：材料.docx】\n"
        msgs.append({"role": "user", "content": head + body[i:i + chunk]})
    msgs.append({"role": "user", "content": "核心论点是什么？"})

    before = sum(len(m["content"]) for m in msgs)
    out, _ = normalize_ask_messages(msgs)
    after = sum(len(m["content"]) for m in out)

    assert after == before, f"分块后仍被截断：送出 {before} 字，到达 {after} 字"
    assert out[-1]["content"] == "核心论点是什么？"
    assert all(len(m["content"]) <= 4000 for m in out)


def test_single_giant_message_still_capped():
    """保留后端守卫：单条超长消息仍被截断（这是防计费放大的兜底，别为了
    附件顺手把这个限制去掉）。"""
    from app.ai import ASK_MAX_TEXT, normalize_ask_messages

    out, _ = normalize_ask_messages([{"role": "user", "content": "字" * 9000}])
    assert len(out[-1]["content"]) == ASK_MAX_TEXT


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_message_window_matches_backend(path):
    """附件块会占用消息位。后端只取最后 ASK_MAX_MESSAGES 条，前端必须用同一个
    数值先截断，否则被切掉的是最早的对话而不是附件。"""
    import re

    from app.ai import ASK_MAX_MESSAGES

    text = path.read_text(encoding="utf-8")
    m = re.search(r"const ASK_MAX_MESSAGES = (\d+);", text)
    assert m, f"{path.name} 缺 ASK_MAX_MESSAGES 常量"
    assert int(m.group(1)) == ASK_MAX_MESSAGES, f"{path.name} 与后端 {ASK_MAX_MESSAGES} 不一致"
    assert "his = his.slice(-ASK_MAX_MESSAGES);" in text, f"{path.name} 没按窗口截断"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_message_window_matches_backend(path):
    """附件块会占用消息位。后端只取最后 ASK_MAX_MESSAGES 条，前端必须用同一个
    数值先截断，否则被切掉的是最早的对话而不是附件。"""
    import re

    from app.ai import ASK_MAX_MESSAGES

    text = path.read_text(encoding="utf-8")
    m = re.search(r"const ASK_MAX_MESSAGES = (\d+);", text)
    assert m, f"{path.name} 缺 ASK_MAX_MESSAGES 常量"
    assert int(m.group(1)) == ASK_MAX_MESSAGES, f"{path.name} 与后端 {ASK_MAX_MESSAGES} 不一致"
    assert "his = his.slice(-ASK_MAX_MESSAGES);" in text, f"{path.name} 没按窗口截断"
