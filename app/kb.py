"""知识点综合知识库：读取 data/kb.json（由 scripts/pdf_notes_extract.py 生成），供 /api/kb/* 使用。"""
from __future__ import annotations

import json
from pathlib import Path

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "kb.json"
_DEFAULT_PATH = KB_PATH

_cache: dict = {"mtime": 0.0, "items": [], "names": {}}


def configure(path) -> None:
    """移动端 goshor_server 启动时把 kb.json 指到 assets/web 下。"""
    global KB_PATH
    KB_PATH = Path(path)
    _cache["mtime"] = 0.0


def _load() -> list[dict]:
    path = KB_PATH if KB_PATH.exists() else _DEFAULT_PATH
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        data = json.loads(path.read_text(encoding="utf-8"))
        _cache["items"] = data.get("items", [])
        _cache["names"] = {m["key"]: m["name"] for m in data.get("modules", [])}
        _cache["mtime"] = mtime
    return _cache["items"]


def module_names() -> dict[str, str]:
    _load()
    return _cache["names"]


def modules() -> list[dict]:
    items = _load()
    names = module_names()
    order = [k for k in names]
    counts: dict[str, int] = {}
    docs: dict[str, set] = {}
    for it in items:
        counts[it["module"]] = counts.get(it["module"], 0) + 1
        docs.setdefault(it["module"], set()).add(it["source"])
    keys = [k for k in order if k in counts] + [k for k in counts if k not in order]
    return [{"key": k, "name": names.get(k, k), "count": counts[k], "docs": len(docs[k])} for k in keys]


def _snippet(body: str, q: str, width: int = 60) -> str:
    if q:
        idx = body.find(q)
        if idx >= 0:
            start = max(0, idx - width)
            end = min(len(body), idx + len(q) + width)
            return ("…" if start else "") + body[start:end].replace("\n", " ") + ("…" if end < len(body) else "")
    return body[:width * 2].replace("\n", " ") + ("…" if len(body) > width * 2 else "")


def query(q: str = "", module: str = "", page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """按模块过滤 + 关键词搜索（标题权重 3、正文权重 1），返回精简条目。"""
    items = _load()
    names = module_names()
    q = (q or "").strip()
    rows = [it for it in items if not module or it["module"] == module]
    if q:
        scored = []
        for it in rows:
            t = it["title"].lower().count(q.lower())
            b = it["body"].lower().count(q.lower())
            if t or b:
                scored.append((t * 3 + b, it))
        scored.sort(key=lambda x: (-x[0], -x[1]["chars"]))
        rows = [it for _, it in scored]
    total = len(rows)
    page = max(1, page)
    size = max(1, min(50, size))
    out = [{
        "id": it["id"],
        "title": it["title"],
        "module": it["module"],
        "module_name": names.get(it["module"], it["module"]),
        "source": it["source"],
        "chars": it["chars"],
        "quality": it.get("quality", "text"),
        "snippet": _snippet(it["body"], q),
    } for it in rows[(page - 1) * size: page * size]]
    return out, total


def get(item_id: str) -> dict | None:
    for it in _load():
        if it["id"] == item_id:
            return {**it, "module_name": module_names().get(it["module"], it["module"])}
    return None
