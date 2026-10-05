"""题单分享码（功能 3.3）—— 自包含编码，零后端。

设计取舍
--------
方案原文提到"极简云端中转（GitHub Gist / 云函数）"。本项目定位本地优先、
数据私有，因此改为**把题单本身编码进分享码**：

    分享码 = base64url( zlib( JSON{ v, t, i[], a?, r? } ) )

- `i` 只存题目 id 列表（不传题库、不传题目内容），对方打开时用**自己本地**的题库
  按 id 取题；本地没有的题会被自动跳过并提示。
- `r` 可选，携带分享者的成绩（total/ok/ms），对方练完即可**异步 PK**。
- 好处：跨设备可用、无需服务器与备案、不泄露任何个人数据；缺点是长码
  （20 题约 60~120 字符），对复制粘贴完全够用。

编码失败一律返回 None，调用方降级为"分享码无效"。
"""
from __future__ import annotations

import base64
import binascii
import json
import zlib

MAX_IDS = 200          # 单个题单最多题数（防止生成超长码）
MAX_TITLE = 40
MAX_AUTHOR = 16
CODE_MAX_LEN = 4000    # 解码前的长度上限，防止恶意超长输入


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode_set(ids, title: str = "", author: str = "", result: dict | None = None) -> str:
    """题目 id 列表 → 分享码。ids 为空时返回空串。"""
    clean: list[int] = []
    for x in ids or []:
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v > 0 and v not in clean:
            clean.append(v)
        if len(clean) >= MAX_IDS:
            break
    if not clean:
        return ""
    payload: dict = {"v": 1, "i": clean}
    t = (title or "").strip()[:MAX_TITLE]
    if t:
        payload["t"] = t
    a = (author or "").strip()[:MAX_AUTHOR]
    if a:
        payload["a"] = a
    if isinstance(result, dict):
        try:
            payload["r"] = {
                "total": int(result.get("total") or 0),
                "ok": int(result.get("ok") or 0),
                "ms": int(result.get("ms") or 0),
            }
        except (TypeError, ValueError):
            pass
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _b64e(zlib.compress(raw, 9))


def decode_set(code: str) -> dict | None:
    """分享码 → {title, ids, author, result}。任何异常返回 None。"""
    if not code:
        return None
    code = code.strip()
    # 允许直接粘贴完整链接
    if "/" in code or "#" in code:
        code = code.split("#")[-1] if "#" in code else code
        code = code.rstrip("/").split("/")[-1]
    if not code or len(code) > CODE_MAX_LEN:
        return None
    try:
        raw = zlib.decompress(_b64d(code))
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, zlib.error, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    ids: list[int] = []
    for x in data.get("i") or []:
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v > 0 and v not in ids:
            ids.append(v)
    if not ids:
        return None
    out = {
        "title": str(data.get("t") or "")[:MAX_TITLE],
        "author": str(data.get("a") or "")[:MAX_AUTHOR],
        "ids": ids[:MAX_IDS],
    }
    r = data.get("r")
    if isinstance(r, dict):
        try:
            out["result"] = {
                "total": int(r.get("total") or 0),
                "ok": int(r.get("ok") or 0),
                "ms": int(r.get("ms") or 0),
            }
        except (TypeError, ValueError):
            pass
    return out


def share_url(base: str, code: str, mobile: bool = False) -> str:
    """生成可直接打开的分享链接。"""
    base = (base or "").rstrip("/")
    return f"{base}/m/#/share/{code}" if mobile else f"{base}/#/share/{code}"
