"""附件 → 纯文本：把用户上传的文件解析成可直接喂给模型的文字。

设计约束（见 docs/03-开发/2026-10-31-AI答疑与申论批改附件上传.md §C）：

- **只用标准库**。安卓端 Chaquopy 只装了 httpx 及其传递依赖，`python-docx`
  是桌面可选依赖。若这里 import docx，就会出现「电脑能传、手机 ImportError」，
  所以 docx 按 zip + XML 自己解。
- **PDF 分平台降级**。桌面有 pymupdf 可抽文本层；安卓没有，明确报错让人换路，
  不假装成功返回空串。
- **图片不在这里处理**。图片要走视觉模型，由 `app/ocr.py` 负责，前端按类型分派。

对外只暴露 `extract(name, data_url)`，失败一律抛 ValueError（中文原因），
由两端服务各自转 400。
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from xml.etree import ElementTree as ET

# 单文件解码后上限：6 MB。再大基本是整本教材，模型也吃不下。
MAX_FILE_BYTES = 6 * 1024 * 1024
# 解析后的文本上限：20,000 字。超出截断并置 truncated，前端提示用户。
MAX_FILE_CHARS = 20000

_DATA_URL_RE = re.compile(r"^data:([\w./+-]+)?(;charset=[\w.+-]+)?;base64,([A-Za-z0-9+/=]+)$")

# 文本类扩展名：直接按字符解码
_TEXT_EXT = {
    "txt", "text", "md", "markdown", "csv", "tsv", "json", "log",
    "py", "js", "ts", "html", "htm", "xml", "yaml", "yml", "ini", "cfg",
}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# 给前端的可读类型名
KIND_NAMES = {
    "text": "文本",
    "docx": "Word 文档",
    "pdf": "PDF",
    "image": "图片",
}


def _decode_data_url(data_url: object) -> tuple[str, bytes]:
    """拆 `data:<mime>;base64,<payload>`，返回 (mime, 原始字节)。"""
    if not isinstance(data_url, str) or not data_url:
        raise ValueError("没有收到文件内容")
    m = _DATA_URL_RE.match(data_url.strip())
    if not m:
        raise ValueError("文件格式不正确，请重新选择")
    mime = (m.group(1) or "").lower()
    payload = m.group(3)
    # 先按 base64 长度估算体积：几十 MB 的串不该先解码占一遍内存再报错
    if len(payload) * 3 // 4 > MAX_FILE_BYTES:
        raise ValueError(
            f"文件太大（约 {len(payload) * 3 // 4 / 1048576:.1f} MB），请控制在 "
            f"{MAX_FILE_BYTES // 1048576} MB 以内")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("文件内容损坏，请重新选择")
    if not raw:
        raise ValueError("文件是空的")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(
            f"文件太大（{len(raw) / 1048576:.1f} MB），请控制在 "
            f"{MAX_FILE_BYTES // 1048576} MB 以内")
    return mime, raw


def _ext_of(name: str) -> str:
    name = (name or "").strip().lower()
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[1]


def sniff_kind(name: str, mime: str, raw: bytes) -> str:
    """判定文件类型：扩展名优先，其次 mime，最后看魔数。

    扩展名优先是因为用户重命名的场景占多数（.docx 被存成 .dat 也能救回来）。
    """
    ext = _ext_of(name)
    if ext in _TEXT_EXT:
        return "text"
    if ext == "docx":
        return "docx"
    if ext == "pdf":
        return "pdf"
    if ext in ("jpg", "jpeg", "png", "webp", "bmp", "gif", "heic"):
        return "image"
    if mime.startswith("text/"):
        return "text"
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("image/"):
        return "image"
    # 魔数兜底：docx 与 xlsx 都是 zip，靠成员名区分
    if raw[:4] == b"%PDF":
        return "pdf"
    if raw[:2] == b"PK":
        return "docx" if _is_docx_zip(raw) else "zip"
    return ""


def _is_docx_zip(raw: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return "word/document.xml" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _plain_text(raw: bytes) -> str:
    """按常见编码依次试解。中文环境里 GBK/GB18030 的旧文件不少。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请另存为 UTF-8 后重试")


def _para_text(p: ET.Element) -> str:
    """取一个 <w:p> 的文字：w:t 拼接，w:tab → \\t，w:br → \\n。"""
    out: list[str] = []
    for node in p.iter():
        if node.tag == f"{_W}t":
            out.append(node.text or "")
        elif node.tag == f"{_W}tab":
            out.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            out.append("\n")
    return "".join(out)


def _block_lines(el: ET.Element, lines: list[str]) -> None:
    """按 body 的直接子节点逐块取文本。

    表格单独走一遍：一行表格压成一行文本，单元格之间用制表符，
    否则表格内容会被拆成几十个孤立短行，模型读不出对应关系。
    """
    for child in el:
        tag = child.tag
        if tag == f"{_W}p":
            lines.append(_para_text(child))
        elif tag == f"{_W}tbl":
            for tr in child.findall(f"{_W}tr"):
                cells = []
                for tc in tr.findall(f"{_W}tc"):
                    cells.append(" ".join(
                        _para_text(p).strip()
                        for p in tc.iter(f"{_W}p")).strip())
                lines.append("\t".join(cells))
        elif tag == f"{_W}sdt":
            # 内容控件（如目录、文本框）里面还嵌着段落
            content = child.find(f"{_W}sdtContent")
            if content is not None:
                _block_lines(content, lines)


def _docx_text(raw: bytes) -> str:
    if not _is_docx_zip(raw):
        raise ValueError("这个文件不是有效的 .docx，请用 Word 另存为 .docx 后重试")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        try:
            xml = z.read("word/document.xml")
        except KeyError:
            raise ValueError("这个 .docx 里没有正文，可能是空文档")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise ValueError("这个 .docx 已损坏，无法读取正文")
    body = root.find(f"{_W}body")
    if body is None:
        raise ValueError("这个 .docx 里没有正文，可能是空文档")
    lines: list[str] = []
    _block_lines(body, lines)
    return "\n".join(lines)


def _pdf_text(raw: bytes) -> str:
    try:
        import fitz  # pymupdf，桌面端可选依赖
    except ImportError:
        raise ValueError("手机端不支持直接读 PDF，请在电脑端导入，或截图后按图片上传")
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        raise ValueError("这个 PDF 已损坏或加密，无法读取")
    try:
        parts = [page.get_text() for page in doc]
    finally:
        doc.close()
    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("这个 PDF 没有文字层（多为扫描件），请截图后按图片上传")
    return text


def normalize(text: str) -> str:
    """统一换行、压掉多余空行。保留缩进与单空行（申论分段的信号）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(name: object, data_url: object) -> dict:
    """把上传文件解析成文本。

    返回 `{kind, kind_name, text, chars, truncated, note}`；
    解析不了抛 ValueError（中文，可直接展示给用户）。
    """
    file_name = str(name or "").strip()[:120]
    mime, raw = _decode_data_url(data_url)
    kind = sniff_kind(file_name, mime, raw)

    if kind == "image":
        raise ValueError("图片请走文字识别（OCR），不是文件解析")
    if kind == "zip":
        raise ValueError("暂不支持 .zip，请解压后逐个上传")
    if not kind:
        raise ValueError("不支持这个文件类型，可上传 txt / md / docx / pdf")
    if kind == "text" and raw[:2] in (b"PK", b"\xd0\xcf"):
        # 扩展名写着 .txt 其实是 Office 二进制，别硬解成乱码
        raise ValueError("文件内容与扩展名不符，请确认后重试")

    if kind == "docx":
        text = _docx_text(raw)
    elif kind == "pdf":
        text = _pdf_text(raw)
    else:
        text = _plain_text(raw)

    text = normalize(text)
    if not text:
        raise ValueError("这个文件没有可读的文字（可能是纯图片或空文件）")

    truncated = len(text) > MAX_FILE_CHARS
    if truncated:
        text = text[:MAX_FILE_CHARS]

    note = ""
    if truncated:
        note = f"内容较长，已截断到前 {MAX_FILE_CHARS} 字"
    return {
        "kind": kind,
        "kind_name": KIND_NAMES.get(kind, kind),
        "text": text,
        "chars": len(text),
        "truncated": truncated,
        "note": note,
    }
