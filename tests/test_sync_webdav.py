"""O1 多设备加密同步测试：加密层 / URL 归一 / 配置落盘 / mock WebDAV 往返。

三个关键不变量（任何一条破了都会让用户数据受损）：
1. **明文不落盘、不上云**：settings.json 里看不到口令原文，云端文件是信封；
2. **解不开就绝不覆盖**：错口令 / 被篡改 / 非本格式 → 返回错误，本地数据不动；
3. **双端同源**：桌面 `app/main.py` 与移动 `goshor_server.py` 走同一份
   `app/sync_webdav.py`，接口与设置项同口径。

mock WebDAV 用标准库 `http.server` 起在回环随机端口，只实现本次用到的
PROPFIND / MKCOL / PUT / GET / HEAD 六个动作，不依赖任何第三方库。

运行：python -m pytest tests/test_sync_webdav.py -q
"""
from __future__ import annotations

import base64
import io
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db, sync_webdav
from app.main import app


# ============================================================
# 一、信封加密层
# ============================================================

def test_encrypt_decrypt_roundtrip():
    plain = "上岸题库 backup payload".encode("utf-8")
    blob = sync_webdav.encrypt_bytes(plain, "我的口令123")
    assert sync_webdav.is_encrypted(blob)
    assert blob[:6] == b"GSYNC1"
    assert sync_webdav.decrypt_bytes(blob, "我的口令123") == plain
    # 明文不得以任何形式出现在密文里
    assert plain not in blob


def test_encrypt_is_randomized():
    """随机 salt：同一份明文两次加密结果必须不同（否则能看出「两次内容一样」）。"""
    plain = b"same payload"
    a = sync_webdav.encrypt_bytes(plain, "pw")
    b = sync_webdav.encrypt_bytes(plain, "pw")
    assert a != b
    assert sync_webdav.decrypt_bytes(a, "pw") == sync_webdav.decrypt_bytes(b, "pw") == plain


def test_wrong_passphrase_raises():
    blob = sync_webdav.encrypt_bytes(b"data", "right")
    with pytest.raises(sync_webdav.SyncError, match="校验失败"):
        sync_webdav.decrypt_bytes(blob, "wrong")


def test_tampered_ciphertext_raises():
    """encrypt-then-MAC：改一个字节就必须解不开，绝不能解出垃圾再覆盖本地。"""
    blob = bytearray(sync_webdav.encrypt_bytes(b"payload-abc", "pw"))
    blob[-1] ^= 0x01
    with pytest.raises(sync_webdav.SyncError):
        sync_webdav.decrypt_bytes(bytes(blob), "pw")


def test_tampered_tag_raises():
    blob = bytearray(sync_webdav.encrypt_bytes(b"payload-abc", "pw"))
    blob[6 + sync_webdav.SALT_LEN] ^= 0xFF          # 落在 tag 上
    with pytest.raises(sync_webdav.SyncError):
        sync_webdav.decrypt_bytes(bytes(blob), "pw")


def test_plain_zip_is_rejected():
    """误把明文 zip 传到云端时，必须明确报「不是本应用的加密包」。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", "x")
    assert not sync_webdav.is_encrypted(buf.getvalue())
    with pytest.raises(sync_webdav.SyncError, match="不是本应用的加密包"):
        sync_webdav.decrypt_bytes(buf.getvalue(), "pw")


def test_truncated_envelope_raises():
    blob = sync_webdav.encrypt_bytes(b"data", "pw")[:20]
    with pytest.raises(sync_webdav.SyncError, match="损坏"):
        sync_webdav.decrypt_bytes(blob, "pw")


def test_empty_passphrase_rejected():
    with pytest.raises(sync_webdav.SyncError, match="口令为空"):
        sync_webdav.encrypt_bytes(b"x", "")


def test_cross_chunk_roundtrip():
    """跨 1MB 分块边界：分块取密钥流 + 分块 XOR 的正确性。"""
    n = sync_webdav.CHUNK * 2 + 12345
    plain = bytes((i * 7 + 3) & 0xFF for i in range(n))
    blob = sync_webdav.encrypt_bytes(plain, "pw")
    assert sync_webdav.decrypt_bytes(blob, "pw") == plain
    assert len(blob) == len(plain) + 6 + sync_webdav.SALT_LEN + sync_webdav.TAG_LEN


def test_b64_helpers_roundtrip():
    plain = b"binary\x00\xff payload"
    assert sync_webdav.decrypt_b64(
        sync_webdav.encrypt_b64(plain, "pw"), "pw") == plain
    with pytest.raises(sync_webdav.SyncError, match="base64"):
        sync_webdav.decrypt_b64("!!!not-base64!!!", "pw")


# ============================================================
# 二、地址与远端路径归一
# ============================================================

def test_normalize_base():
    assert sync_webdav.normalize_base("dav.jianguoyun.com/dav/") == \
        "https://dav.jianguoyun.com/dav"
    assert sync_webdav.normalize_base("  https://x.com/dav///  ") == "https://x.com/dav"
    assert sync_webdav.normalize_base("http://127.0.0.1:9999/") == "http://127.0.0.1:9999"
    with pytest.raises(sync_webdav.SyncError, match="地址为空"):
        sync_webdav.normalize_base("   ")


def test_join_url_escapes_segments():
    base = "https://dav.jianguoyun.com/dav"
    assert sync_webdav.join_url(base, "goshore/backup.gsync") == \
        "https://dav.jianguoyun.com/dav/goshore/backup.gsync"
    # 含空格/中文的段要转义，且不能把斜杠也转义掉（否则路径层级丢失）
    got = sync_webdav.join_url(base, "我的 目录/a b.gsync")
    assert got.startswith(base + "/")
    assert got.count("/") == base.count("/") + 2
    assert " " not in got


def test_normalize_remote_path_rejects_traversal():
    assert config.normalize_remote_path("goshore/backup.gsync") == "goshore/backup.gsync"
    assert config.normalize_remote_path("/a/b/") == "a/b"
    assert config.normalize_remote_path("a\\b") == "a/b"
    # 空 → 回落默认；`..`/`.` → 拒绝（路径会拼进 URL，放行等于给了目录穿越）
    assert config.normalize_remote_path("   ") == config.SYNC_REMOTE_DEFAULT
    assert config.normalize_remote_path("///") == config.SYNC_REMOTE_DEFAULT
    assert config.normalize_remote_path("a/../../etc/passwd") is None
    assert config.normalize_remote_path("./a") is None
    assert config.normalize_remote_path(123) is None


# ============================================================
# 三、双端共用的视图与时间判断
# ============================================================

def test_public_config_hides_secrets():
    s = {"sync_url": "https://x/dav", "sync_user": "me", "sync_password": "pw",
         "sync_passphrase": "pp", "sync_remote_path": "a/b.gsync",
         "sync_enabled": True, "sync_wifi_only": False,
         "sync_last_at": "2026-10-07T10:00:00", "sync_last_size": 123}
    out = sync_webdav.public_config(s)
    assert out["sync_has_password"] is True and out["sync_has_passphrase"] is True
    assert out["sync_url"] == "https://x/dav" and out["sync_last_size"] == 123
    assert "sync_password" not in out and "sync_passphrase" not in out
    assert "sync_local_stamp" not in out          # 内部状态不外泄


def test_remote_newer():
    later = "Wed, 07 Oct 2026 10:00:00 GMT"
    earlier = "Wed, 07 Oct 2026 08:00:00 GMT"
    # 本机从未同步过 → 视为云端更新（首次拉取）
    assert sync_webdav.remote_newer(later, "") is True
    # 云端更晚（按 UTC 比较，本地时区要正确换算）
    assert sync_webdav.remote_newer(later, "2026-10-07T09:00:00") is True
    assert sync_webdav.remote_newer(earlier, "2026-10-07T18:00:00") is False
    # 解析不了 → 保守判「不是更新」，不误报冲突
    assert sync_webdav.remote_newer("garbage", "2026-10-07T18:00:00") is False
    assert sync_webdav.remote_newer(later, "garbage") is False


def test_sync_patch_normalization():
    out = config.sync_patch({
        "sync_enabled": "on", "sync_wifi_only": 0, "sync_url": "  https://x/dav  ",
        "sync_user": " me ", "sync_remote_path": "../evil",
        "sync_password": " pw ", "sync_passphrase": " pp ",
        "sync_last_at": "hacker-set",           # 非用户字段不得被写进来
    })
    assert out["sync_enabled"] is True and out["sync_wifi_only"] is False
    assert out["sync_url"] == "https://x/dav" and out["sync_user"] == "me"
    assert "sync_remote_path" not in out        # 非法路径丢弃（不是回落默认）
    assert out["sync_password"] == "pw" and out["sync_passphrase"] == "pp"
    assert "sync_last_at" not in out
    # 开关认不出 → 丢弃；口令非字符串 → 丢弃；空串口令 = 清除
    out2 = config.sync_patch({"sync_enabled": "maybe", "sync_password": 5,
                              "sync_passphrase": ""})
    assert "sync_enabled" not in out2 and "sync_password" not in out2
    assert out2["sync_passphrase"] == ""


# ============================================================
# 四、设置落盘：口令不落明文
# ============================================================

@pytest.fixture()
def tmp_settings(tmp_path, monkeypatch):
    """把设置/数据库都指向临时目录，绝不碰真实 data/。"""
    sp = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", sp)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from app import main as main_mod
    monkeypatch.setattr(main_mod, "SETTINGS_PATH", sp)
    monkeypatch.setattr(main_mod, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    return sp


def test_secrets_never_written_in_plaintext(tmp_settings):
    config.save_settings({"sync_url": "https://x/dav",
                          "sync_password": "s3cret-pw",
                          "sync_passphrase": "s3cret-pp"})
    text = tmp_settings.read_text(encoding="utf-8")
    assert "s3cret-pw" not in text and "s3cret-pp" not in text
    disk = json.loads(text)
    if config._dpapi_available():
        assert disk.get("sync_password_enc") and disk.get("sync_passphrase_enc")
        assert disk.get("sync_password", "") == ""
    # 读回来必须是明文（否则用户重进设置页就没法继续用了）
    s = config.load_settings()
    assert s["sync_password"] == "s3cret-pw"
    assert s["sync_passphrase"] == "s3cret-pp"
    assert s["sync_url"] == "https://x/dav"
    # 密文字段不对外暴露
    assert "sync_password_enc" not in s and "sync_passphrase_enc" not in s


def test_settings_keep_existing_secret_when_not_passed(tmp_settings):
    """只改地址时不能把已保存的口令抹掉（前端不回填口令，只传变化的字段）。"""
    config.save_settings({"sync_password": "keep-me", "sync_passphrase": "keep-pp"})
    config.save_settings({"sync_url": "https://y/dav"})
    s = config.load_settings()
    assert s["sync_password"] == "keep-me" and s["sync_passphrase"] == "keep-pp"
    assert s["sync_url"] == "https://y/dav"


def test_settings_clear_secret_with_empty_string(tmp_settings):
    config.save_settings({"sync_password": "temp"})
    config.save_settings({"sync_password": ""})
    assert config.load_settings()["sync_password"] == ""


def test_deepseek_key_still_works_after_generalization(tmp_settings):
    """把单字段加密泛化成 _SECRET_FIELDS 后，原有 API Key 行为必须不变。"""
    config.save_settings({"deepseek_api_key": "sk-abc123"})
    disk = json.loads(tmp_settings.read_text(encoding="utf-8"))
    if config._dpapi_available():
        assert "sk-abc123" not in tmp_settings.read_text(encoding="utf-8")
    assert config.load_settings()["deepseek_api_key"] == "sk-abc123"
    # 存量明文 → 自动迁移成密文（老用户升级路径）
    tmp_settings.write_text(json.dumps({"deepseek_api_key": "legacy-key"}),
                            encoding="utf-8")
    assert config.load_settings()["deepseek_api_key"] == "legacy-key"
    after = json.loads(tmp_settings.read_text(encoding="utf-8"))
    if config._dpapi_available():
        assert after.get("deepseek_api_key", "") == ""
        assert after.get("deepseek_api_key_enc")


def test_android_without_dpapi_keeps_plaintext(tmp_settings, monkeypatch):
    """安卓无 DPAPI：明文留在应用私有目录，但读回来必须一致。"""
    monkeypatch.setattr(config, "_dpapi_available", lambda: False)
    config.save_settings({"sync_password": "phone-pw"})
    disk = json.loads(tmp_settings.read_text(encoding="utf-8"))
    assert disk["sync_password"] == "phone-pw"
    assert "sync_password_enc" not in disk
    assert config.load_settings()["sync_password"] == "phone-pw"


# ============================================================
# 五、mock WebDAV 服务器
# ============================================================

class MockDAV:
    """只实现本次用到的六个动作；用线程跑在回环随机端口。"""

    def __init__(self, user: str = "", password: str = "", no_propfind: bool = False):
        outer = self
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.user, self.password = user, password
        self.no_propfind = no_propfind

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):        # 静音
                pass

            def _path(self) -> str:
                p = urllib.parse.urlparse(self.path).path
                return urllib.parse.unquote(p).rstrip("/") or "/"

            def _auth(self) -> bool:
                if not outer.user:
                    return True
                want = "Basic " + base64.b64encode(
                    f"{outer.user}:{outer.password}".encode()).decode()
                if self.headers.get("Authorization") != want:
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return False
                return True

            def _send(self, code, body: bytes = b"", extra=None):
                self.send_response(code)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _handle(self, fn):
                outer.calls.append((self.command, self._path()))
                if not self._auth():
                    return
                fn()

            def do_OPTIONS(self):
                self._handle(lambda: self._send(200, b"", {"Allow": "OPTIONS"}))

            def do_PROPFIND(self):
                def go():
                    if outer.no_propfind:
                        self._send(405)
                        return
                    body = (b'<?xml version="1.0"?><D:multistatus '
                            b'xmlns:D="DAV:"><D:response/></D:multistatus>')
                    self._send(207, body, {"Content-Type": "application/xml"})
                self._handle(go)

            def do_MKCOL(self):
                def go():
                    p = self._path()
                    if p in outer.dirs:
                        self._send(405)
                    else:
                        outer.dirs.add(p)
                        self._send(201)
                self._handle(go)

            def do_PUT(self):
                def go():
                    n = int(self.headers.get("Content-Length") or 0)
                    outer.files[self._path()] = self.rfile.read(n)
                    self._send(201)
                self._handle(go)

            def do_GET(self):
                def go():
                    data = outer.files.get(self._path())
                    if data is None:
                        self._send(404)
                    else:
                        self._send(200, data)
                self._handle(go)

            def do_HEAD(self):
                def go():
                    data = outer.files.get(self._path())
                    if data is None:
                        self._send(404)
                    else:
                        self._send(200, b"", {
                            "Content-Length": str(len(data)),
                            "Last-Modified": "Wed, 07 Oct 2026 10:00:00 GMT",
                            "ETag": '"mock-1"',
                        })
                self._handle(go)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/dav"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def dav():
    s = MockDAV()
    yield s
    s.stop()


def test_client_test_and_dirs(dav):
    c = sync_webdav.WebDAVClient(dav.base + "/", "")
    assert c.test()["ok"] is True
    c.ensure_dirs("goshore/sub/backup.gsync")
    assert "/dav/goshore" in dav.dirs and "/dav/goshore/sub" in dav.dirs
    # 已存在的目录再 MKCOL 返回 405，必须静默跳过而不是报错
    c.ensure_dirs("goshore/sub/backup.gsync")
    assert dav.dirs == {"/dav/goshore", "/dav/goshore/sub"}


def test_client_test_reports_bad_credentials():
    s = MockDAV(user="me", password="right")
    try:
        bad = sync_webdav.WebDAVClient(s.base, "me", "wrong")
        res = bad.test()
        assert res["ok"] is False and "401" in res["message"]
        ok = sync_webdav.WebDAVClient(s.base, "me", "right")
        assert ok.test()["ok"] is True
    finally:
        s.stop()


def test_client_test_falls_back_when_propfind_disabled():
    """服务器禁 PROPFIND（部分网盘如此）时应退回 MKCOL/OPTIONS，而不是直接失败。"""
    s = MockDAV(no_propfind=True)
    try:
        res = sync_webdav.WebDAVClient(s.base).test()
        assert res["ok"] is True
        assert [m for m, _ in s.calls][:2] == ["PROPFIND", "MKCOL"]
    finally:
        s.stop()


def test_client_put_get_stat_roundtrip(dav):
    c = sync_webdav.WebDAVClient(dav.base)
    payload = b"\x00\x01binary\xff"
    assert c.put("a/b.gsync", payload) == len(payload)
    assert c.get("a/b.gsync") == payload
    st = c.stat("a/b.gsync")
    assert st["size"] == len(payload) and st["etag"] == '"mock-1"'
    # 不存在 → None（不算错误）
    assert c.get("nope.bin") is None and c.stat("nope.bin") is None


def test_client_auth_header_is_basic(dav):
    c = sync_webdav.WebDAVClient(dav.base, "user", "pass")
    h = c._auth_header()["Authorization"]
    assert h.startswith("Basic ")
    assert base64.b64decode(h[6:]).decode() == "user:pass"
    assert sync_webdav.WebDAVClient(dav.base)._auth_header() == {}


def test_client_connection_refused_raises():
    """连不上的地址必须抛 SyncError（而不是裸的 urllib 异常）。

    这里只断言**抛错类型**，不钉死文案：本用例依赖真实网络，在带 http_proxy 的
    机器上（且未把回环地址放进 no_proxy）拿回来的是代理的 5xx，文案会变成
    「HTTP 502」。文案契约由下面两条不依赖网络的用例钉住。
    """
    c = sync_webdav.WebDAVClient("http://127.0.0.1:1/dav", timeout=2)
    with pytest.raises(sync_webdav.SyncError):
        c.get("x")


class _BoomOpener:
    """把底层 opener 桩成固定抛连接异常。"""

    def __init__(self, exc):
        self.exc = exc

    def open(self, req, timeout=None):      # noqa: A003 - 对齐 OpenerDirector 接口
        raise self.exc


def test_connection_error_maps_to_readable_message(monkeypatch):
    """连接层异常 → 「连接 WebDAV 失败」这条文案契约（不依赖真实网络/代理环境）。"""
    monkeypatch.setattr(sync_webdav, "_OPENER",
                        _BoomOpener(urllib.error.URLError(
                            ConnectionRefusedError("refused"))))
    c = sync_webdav.WebDAVClient("http://127.0.0.1:1/dav")
    with pytest.raises(sync_webdav.SyncError, match="连接 WebDAV 失败"):
        c.get("x")


def test_client_bypasses_environment_proxy(monkeypatch):
    """WebDAV 客户端必须忽略 http_proxy 等环境变量。

    否则系统代理会把请求改写到意料之外的主机（本机/内网地址尤其危险），
    也让「连不上」的判断依赖环境而不可复现。

    实现要点：`build_opener(ProxyHandler({}))`。空代理表下 ProxyHandler 不会
    生成任何 `*_open` 方法，因此 `add_handler` 不会把它登记进 `.handlers`——
    这正是「不走代理」的效果（默认 ProxyHandler 也已被跳过）。
    所以断言是「opener 里**没有**代理 handler」，而不是「有」。
    """
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("all_proxy", "http://127.0.0.1:9")

    # 被测对象：不能带任何代理 handler
    ours = [h for h in sync_webdav._OPENER.handlers
            if isinstance(h, urllib.request.ProxyHandler)]
    assert not ours, (
        "WebDAV opener 不应携带 ProxyHandler——带了就会读 http_proxy 环境变量，"
        "把请求改写到环境代理去")

    # 对照组：同样环境下，默认 opener 一定会带上代理 handler。
    # 若这一条不成立，说明环境里根本没有代理变量，上一条断言就失去意义。
    default = urllib.request.build_opener()
    ctrl = [h for h in default.handlers
            if isinstance(h, urllib.request.ProxyHandler)]
    assert ctrl, "对照组失效：设置代理环境变量后，默认 opener 应带上 ProxyHandler"
    assert ctrl[0].proxies, "对照组代理表不应为空（否则本用例无法区分二者）"


# ============================================================
# 六、接口层（桌面，mock WebDAV + 临时库/设置）
# ============================================================

@pytest.fixture()
def client(tmp_settings, monkeypatch):
    """TestClient + 临时库；预插一条题目避免 lifespan 触发 reindex 扫真实 vault。"""
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','资料分析 / 增长量',?,?)""",
        (json.dumps({"options": [{"label": "A", "text": "x", "correct": True}]}),
         "增长量 计算"))
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def _configure(client, dav, **extra):
    body = {"sync_url": dav.base, "sync_user": "u", "sync_password": "p",
            "sync_passphrase": "pp-123456", "sync_remote_path": "goshore/backup.gsync",
            "sync_enabled": True}
    body.update(extra)
    r = client.post("/api/sync/config", json=body)
    assert r.status_code == 200, r.text
    return r.json()["config"]


def test_settings_endpoint_never_leaks_sync_secrets(client):
    client.post("/api/sync/config", json={"sync_url": "https://x/dav",
                                          "sync_password": "leak-me",
                                          "sync_passphrase": "leak-pp"})
    j = client.get("/api/settings").json()
    assert "leak-me" not in json.dumps(j) and "leak-pp" not in json.dumps(j)
    assert j["sync_has_password"] is True and j["sync_has_passphrase"] is True
    assert "sync_password" not in j and "sync_passphrase" not in j


def test_sync_config_endpoint_roundtrip(client):
    cfg = _configure(client, _dummy())
    assert cfg["sync_url"].endswith("/dav") and cfg["sync_remote_path"] == "goshore/backup.gsync"
    assert cfg["sync_has_password"] is True and cfg["sync_has_passphrase"] is True
    # GET 与 POST 返回同一视图
    assert client.get("/api/sync/config").json()["config"]["sync_enabled"] is True
    # 非法远端路径被丢弃，保留原值
    client.post("/api/sync/config", json={"sync_remote_path": "../etc"})
    assert client.get("/api/sync/config").json()["config"]["sync_remote_path"] == \
        "goshore/backup.gsync"


def _dummy():
    from types import SimpleNamespace
    return SimpleNamespace(base="https://dav.example.com/dav")


def test_sync_test_endpoint_ok_and_401(client, dav):
    _configure(client, dav)
    r = client.post("/api/sync/test", json={})
    assert r.json()["ok"] is True and "连接成功" in r.json()["message"]


def test_sync_test_endpoint_reports_bad_credentials(client, tmp_settings):
    """临时传错密码 → 明确 401 提示，而不是 500（配置页「测试连接」要能显示原因）。"""
    auth = MockDAV(user="me", password="right")
    try:
        client.post("/api/sync/config", json={"sync_url": auth.base,
                                              "sync_user": "me",
                                              "sync_password": "wrong"})
        r = client.post("/api/sync/test", json={})
        assert r.status_code == 200
        assert r.json()["ok"] is False and "401" in r.json()["error"]
        # 未保存配置前也能用临时参数测（前端「测试连接」按钮的即时校验）
        r2 = client.post("/api/sync/test",
                         json={"sync_url": auth.base, "sync_user": "me",
                               "sync_password": "right"})
        assert r2.json()["ok"] is True
    finally:
        auth.stop()


def test_sync_up_encrypts_and_down_restores(client, dav, tmp_settings, monkeypatch):
    _configure(client, dav)
    r = client.post("/api/sync/up")
    j = r.json()
    assert j["ok"] is True and j["size"] > 0

    # 1) 云端文件必须是信封，绝不能是明文 zip（b"PK"）或明文库
    stored = dav.files["/dav/goshore/backup.gsync"]
    assert sync_webdav.is_encrypted(stored) and not stored.startswith(b"PK")
    # 2) 用口令能解回一个合法 zip，且含 goshor.db
    raw = sync_webdav.decrypt_bytes(stored, "pp-123456")
    names = set(zipfile.ZipFile(io.BytesIO(raw)).namelist())
    assert "goshor.db" in names
    # 3) 上传后记录同步状态，供冲突判断
    cfg = client.get("/api/sync/config").json()["config"]
    assert cfg["sync_last_up_at"] and cfg["sync_last_size"] == j["size"]
    assert cfg["sync_device"] != ""

    # 4) 本机再写一条数据 → 下载会被判定为冲突（本机有改动 + 云端更新过）
    conn = db.connect()
    conn.execute("UPDATE documents SET title='改过了' WHERE id=1")
    conn.commit()
    conn.close()
    assert client.post("/api/sync/down", json={}).json()["conflict"] is True
    # force 才允许覆盖
    r3 = client.post("/api/sync/down", json={"force": True})
    assert r3.json()["ok"] is True and "goshor.db" in r3.json()["restored"]
    # 覆盖后库内容回到上传那一刻（标题被还原）
    conn = db.connect()
    assert conn.execute("SELECT title FROM documents WHERE id=1").fetchone()["title"] \
        == "增长量计算"
    conn.close()


def test_sync_down_keeps_local_sync_credentials(client, dav, tmp_settings):
    """恢复不能把本机的同步凭据冲掉（DPAPI 密文跨机器解不开）。"""
    _configure(client, dav)
    client.post("/api/sync/up")
    client.post("/api/sync/down", json={"force": True})
    cfg = client.get("/api/sync/config").json()["config"]
    assert cfg["sync_url"] == dav.base
    assert cfg["sync_has_password"] is True and cfg["sync_has_passphrase"] is True
    # 口令还能用：再解一次云端包
    assert sync_webdav.is_encrypted(dav.files["/dav/goshore/backup.gsync"])


def test_sync_down_wrong_passphrase_does_not_touch_local(client, dav, tmp_settings):
    """云端包是别的口令加密的：必须报错，且本地库一字节不动。"""
    _configure(client, dav)
    client.post("/api/sync/up")
    dav.files["/dav/goshore/backup.gsync"] = sync_webdav.encrypt_bytes(
        b"someone else's zip", "another-passphrase")
    conn = db.connect()
    conn.execute("UPDATE documents SET title='本机数据' WHERE id=1")
    conn.commit()
    conn.close()
    r = client.post("/api/sync/down", json={"force": True})
    assert r.json()["ok"] is False and "校验失败" in r.json()["error"]
    conn = db.connect()
    assert conn.execute("SELECT title FROM documents WHERE id=1").fetchone()["title"] \
        == "本机数据"                      # 本地没被覆盖
    conn.close()


def test_sync_up_and_down_require_config(client):
    assert client.post("/api/sync/up").json()["error"] == "请先填写 WebDAV 地址"
    client.post("/api/sync/config", json={"sync_url": "https://x/dav"})
    assert "同步口令" in client.post("/api/sync/up").json()["error"]
    # 下载同理
    assert "同步口令" in client.post("/api/sync/down", json={}).json()["error"]


def test_sync_remote_reports_missing_and_present(client, dav):
    _configure(client, dav)
    j = client.get("/api/sync/remote").json()
    assert j["ok"] is True and j["exists"] is False
    client.post("/api/sync/up")
    j2 = client.get("/api/sync/remote").json()
    assert j2["exists"] is True and j2["size"] > 0
    assert j2["modified"] and j2["local_changed"] is False


def test_sync_up_creates_remote_dirs(client, dav):
    _configure(client, dav, sync_remote_path="deep/nested/dir/backup.gsync")
    assert client.post("/api/sync/up").json()["ok"] is True
    assert "/dav/deep" in dav.dirs and "/dav/deep/nested/dir" in dav.dirs
    assert "/dav/deep/nested/dir/backup.gsync" in dav.files


def test_sync_up_reports_pack_failure(client, dav, monkeypatch):
    """打包失败（如磁盘写满）应是可读错误，而不是 500。"""
    _configure(client, dav)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(sync_webdav, "build_zip", boom)
    r = client.post("/api/sync/up")
    assert r.status_code == 200
    assert r.json()["ok"] is False and "打包备份失败" in r.json()["error"]


# ============================================================
# 七、移动端同源
# ============================================================

MOBILE_SRC = (Path(__file__).resolve().parents[1] / "android" / "app"
              / "src" / "main" / "python" / "goshor_server.py")


def _mobile_src() -> str:
    return MOBILE_SRC.read_text(encoding="utf-8")


def test_mobile_settings_defaults_have_sync_keys():
    src = _mobile_src()
    block = src[src.index("_MOBILE_SETTINGS_DEFAULTS = {"):]
    block = block[:block.index("\n}")]
    for k in ("sync_enabled", "sync_url", "sync_user", "sync_remote_path",
              "sync_wifi_only", "sync_last_at", "sync_last_size",
              "sync_device", "sync_local_stamp"):
        assert f'"{k}"' in block, f"移动端默认设置缺少 {k}"
    # 关键默认值必须与桌面 DEFAULTS 同口径（否则同一份配置两端行为不同）
    assert config.DEFAULTS["sync_remote_path"] == "goshore/backup.gsync"
    assert config.DEFAULTS["sync_enabled"] is False
    assert config.DEFAULTS["sync_wifi_only"] is False
    assert '"goshore/backup.gsync"' in block


def test_mobile_sync_routes_registered():
    src = _mobile_src()
    for p in ("/api/sync/config", "/api/sync/test", "/api/sync/up",
              "/api/sync/down", "/api/sync/remote"):
        assert f'"{p}"' in src, f"移动端缺少路由 {p}"
    for fn in ("_mobile_sync_up", "_mobile_sync_down", "_mobile_sync_test",
               "_mobile_sync_remote", "_mobile_local_stamp",
               "_mobile_sync_ready", "_mobile_sync_client",
               "_write_sync_state_all"):
        assert f"def {fn}(" in src, f"移动端缺少函数 {fn}"


def test_mobile_reuses_shared_sync_module():
    """移动端必须复用同一份加密实现与设置归一化，不能各写一份（会漂移）。"""
    src = _mobile_src()
    assert "sync_webdav" in src
    assert "sync_webdav.encrypt_bytes" in src
    assert "sync_webdav.decrypt_bytes" in src
    assert "sync_webdav.public_config" in src
    assert "sync_webdav.remote_newer" in src
    assert "config.sync_patch" in src
    # 不得在移动端另起一套加解密
    assert "pbkdf2_hmac" not in src and "shake_256" not in src


def test_mobile_settings_endpoint_masks_sync_secrets():
    src = _mobile_src()
    i = src.index('elif path == "/api/settings":')
    block = src[i:i + 900]
    assert 'sync_has_password' in block and 'sync_has_passphrase' in block
    assert 's.pop("sync_password"' in block
    assert 's.pop("sync_passphrase"' in block


def test_mobile_down_restores_via_existing_backup_import():
    """移动端下载必须走既有的整包还原（账号与记录完整），不另写一套。"""
    src = _mobile_src()
    i = src.index("def _mobile_sync_down(")
    block = src[i:i + 2200]
    assert "_mobile_backup_import(" in block
    assert "base64.b64encode(raw)" in block


def test_mobile_up_uses_export_without_api_key():
    """上传包不含 DeepSeek Key（长期有效的第三方密钥不进任何云包）。"""
    src = _mobile_src()
    i = src.index("def _mobile_sync_up(")
    block = src[i:i + 1400]
    assert "_mobile_backup_export(False)" in block


def test_mobile_server_compiles_without_python_extras():
    """移动端源码不得 import 只有桌面才有的第三方加密库（Chaquopy 要备 wheel）。"""
    src = _mobile_src()
    for name in ("cryptography", "pycryptodome", "Crypto", "nacl",
                 "requests_toolbelt"):
        assert not re.search(rf"^\s*(import|from)\s+{name}\b", src, re.M), \
            f"移动端不应引入重依赖 {name}"


# ============================================================
# 八、前端接线（桌面 app.js / 移动 m.js）
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"


def _piece(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


def test_desktop_sync_panel_wired():
    src = APP_JS.read_text(encoding="utf-8")
    for el in ("#syncOn", "#syncUrl", "#syncUser", "#syncPass", "#syncPhrase",
               "#syncPath", "#syncWifi", "#syncSave", "#syncTest",
               "#syncUp", "#syncDown", "#syncMsg", "#syncLast"):
        assert el in src, f"桌面端同步面板缺少 {el}"
    for ep in ("/api/sync/config", "/api/sync/test", "/api/sync/up",
               "/api/sync/down"):
        assert ep in src, f"桌面端未调用 {ep}"
    # 面板渲染依赖的摘要函数必须存在
    assert "function fmtBytes(" in src and "function syncLastText(" in src
    # api() 不传 body 会走 GET，而该端点只注册在 POST
    assert 'api("/api/sync/up", {})' in src


def test_desktop_sync_secrets_never_backfilled():
    src = APP_JS.read_text(encoding="utf-8")
    # 输入框绝不回填口令（避免把密文/明文塞进 DOM）
    seg = _piece(src, 'id="syncPass"', 'id="syncPath"')
    assert "sync_password" not in seg and "sync_passphrase" not in seg
    # 提交时「留空 = 不修改」
    patch = _piece(src, "const syncPatch = () => {", "const syncBusy")
    assert "if (pw) p.sync_password = pw;" in patch
    assert "if (ph) p.sync_passphrase = ph;" in patch


def test_desktop_sync_confirm_and_conflict_force():
    src = APP_JS.read_text(encoding="utf-8")
    up = _piece(src, '$("#syncUp").onclick', '$("#syncDown").onclick')
    down = _piece(src, '$("#syncDown").onclick',
                  "/* =====================================================")
    assert "confirmBox(" in up and "confirmBox(" in down
    # 冲突：先 force:false 探测，二次确认后再 force:true 覆盖
    assert "r.conflict" in down
    assert "force: false" in down and "force: true" in down


def test_mobile_sync_panel_wired():
    src = M_JS.read_text(encoding="utf-8")
    for el in ("#syOn", "#syUrl", "#syUser", "#syPass", "#syPhrase",
               "#syPath", "#syWifi", "#sySave", "#syTest", "#syUp",
               "#syDown", "#syStatus", "#syLast"):
        assert el in src, f"移动端同步面板缺少 {el}"
    for ep in ("/api/sync/config", "/api/sync/test", "/api/sync/up",
               "/api/sync/down"):
        assert ep in src, f"移动端未调用 {ep}"
    # 卡片模板直接调用 syncLastText()，函数缺失会让整个设置页 ReferenceError
    assert "function fmtBytes(" in src and "function syncLastText(" in src
    assert "syncLastText(s)" in src
    assert "syncLastText((await api(\"/api/sync/config\")).config)" in src
    # api() 不传 body 会走 GET，而该端点只注册在 POST（会 404 静默失败）
    assert 'api("/api/sync/up", {})' in src


def test_mobile_sync_uses_two_step_confirm():
    """WebView 的 confirm 不可靠，移动端一律「两步点击」（dataset.armed）。"""
    src = M_JS.read_text(encoding="utf-8")
    up = _piece(src, '$("#syUp").onclick', '$("#syDown").onclick')
    down = _piece(src, '$("#syDown").onclick', "Theme.bindPicker")
    for block in (up, down):
        assert "confirm(" not in block, "移动端不应依赖 WebView 的 confirm"
        assert "dataset.armed" in block
    assert "r.conflict" in down and "dataset.force" in down


def test_mobile_sync_secrets_never_backfilled():
    src = M_JS.read_text(encoding="utf-8")
    seg = _piece(src, 'id="syPass"', 'id="syPath"')
    assert "sync_password" not in seg and "sync_passphrase" not in seg
    patch = _piece(src, "const syPatch = () => {", '$("#sySave")')
    assert "if (pw) p.sync_password = pw;" in patch
    assert "if (ph) p.sync_passphrase = ph;" in patch