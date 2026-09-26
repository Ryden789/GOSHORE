"""GOSHORE 安卓独立版 · 内置本地服务器

标准库 http.server 实现（不依赖 FastAPI，启动快、体积小），
复用桌面端 app.db / app.formula_drill 核心逻辑，保证做题规则一致。
由 Java 端通过 Chaquopy 调用 start()，返回监听端口。
"""
from __future__ import annotations

import json
import mimetypes
import posixpath
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import db, formula_drill

# 运行路径（Java 注入）
_DB_PATH: Path = Path("")
_IMG_DIR: Path = Path("")
_WEB_DIR: Path = Path("")

_lock = threading.Lock()  # 串行化写操作，手机单用户场景足够


def configure(db_path: str, img_dir: str, web_dir: str) -> None:
    global _DB_PATH, _IMG_DIR, _WEB_DIR
    _DB_PATH = Path(db_path)
    _IMG_DIR = Path(img_dir)
    _WEB_DIR = Path(web_dir)
    db.DB_PATH = _DB_PATH  # db.connect() 读这个模块级变量


# ---------------- HTTP 处理 ----------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "GOSHORE/1.0"

    def log_message(self, *a):
        pass  # 静默，避免刷屏

    # ---- 响应工具 ----

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg=""):
        self._json({"detail": msg or ("error %d" % code)}, code)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---- GET ----

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        q = lambda k, d="": qs.get(k, [d])[0]

        try:
            if path == "/api/stats":
                self._json(db.stats_overview())
            elif path == "/api/facets":
                self._json(db.facets())
            elif path == "/api/kaodian-tree":
                self._json({"items": db.kaodian_tree(q("module", "判断推理"))})
            elif path == "/api/wrong-book":
                self._json({"items": db.list_wrong_book()})
            elif path == "/api/marks":
                self._json({"items": db.list_marks()})
            elif path == "/api/report/weekly":
                self._json(db.weekly_report())
            elif path == "/img":
                self._serve_img(q("path"))
            else:
                self._serve_static(path)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self._err(500, str(e))
            except Exception:
                pass

    # ---- POST ----

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        b = self._read_json()
        try:
            if path == "/api/paper":
                ids = db.random_paper(
                    b.get("module", ""), b.get("kaodian", ""),
                    max(1, min(30, int(b.get("n", 10)))))
                self._json({"ids": ids})
            elif path == "/api/docs/batch":
                self._json({"items": db.get_docs_batch(b.get("ids", []))})
            elif path == "/api/answer":
                with _lock:
                    db.add_answer(int(b["doc_id"]), b.get("selected", ""),
                                  bool(b.get("correct")), int(b.get("ms", 0)))
                self._json({"ok": True})
            elif path == "/api/formula/generate":
                types = (b.get("config") or {}).get("types") or []
                n = max(5, min(30, int(b.get("n", 5))))
                self._json({"items": formula_drill.generate(types, n)})
            elif path == "/api/formula/result":
                with _lock:
                    db.add_formula_round(b.get("config", {}), int(b["total"]),
                                         int(b["correct"]), int(b["avg_ms"]),
                                         b.get("details", []))
                self._json({"ok": True})
            else:
                self._err(404, "not found")
        except (KeyError, ValueError, TypeError) as e:
            self._err(400, str(e))
        except Exception as e:
            self._err(500, str(e))

    # ---- 图片：解压目录内按相对路径读取 ----

    def _serve_img(self, url_path: str):
        rel = urllib.parse.unquote(url_path).replace("\\", "/").lstrip("/")
        fp = (_IMG_DIR / rel).resolve()
        try:
            fp.relative_to(_IMG_DIR.resolve())
        except ValueError:
            return self._err(403)
        if not fp.is_file():
            return self._err(404)
        self._send_file(fp)

    # ---- 静态前端 ----

    def _serve_static(self, path: str):
        # 独立版：/ 与 /m/ 均指向手机版入口
        if path in ("/", "/m", "/m/"):
            return self._send_file(_WEB_DIR / "m" / "index.html")
        # 其余路径（/m/m.css、/m/m.js 等）按完整相对路径映射 web/
        rel = posixpath.normpath(path).lstrip("/")
        fp = (_WEB_DIR / rel).resolve()
        try:
            fp.relative_to(_WEB_DIR.resolve())
        except ValueError:
            return self._err(403)
        if not fp.is_file():
            return self._err(404)
        self._send_file(fp)

    def _send_file(self, fp: Path):
        ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        if ctype.startswith("text/") or fp.suffix in (".js", ".json", ".svg"):
            ctype += "; charset=utf-8"
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ---------------- 启动入口（Java 调用） ----------------

_httpd: ThreadingHTTPServer | None = None


def start(db_path: str, img_dir: str, web_dir: str) -> int:
    """在后台线程启动服务，返回端口。"""
    global _httpd
    configure(db_path, img_dir, web_dir)
    _httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _httpd.daemon_threads = True
    t = threading.Thread(target=_httpd.serve_forever, daemon=True)
    t.start()
    return _httpd.server_address[1]


def stop() -> None:
    global _httpd
    if _httpd:
        _httpd.shutdown()
        _httpd = None
