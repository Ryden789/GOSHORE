"""O1 多设备加密同步：WebDAV 客户端 + 本地信封加密（桌面 / 移动共用）。

设计取舍
--------
1. **不引重依赖**：只走标准 HTTP 方法（PROPFIND / MKCOL / PUT / GET / HEAD），
   用标准库 `urllib.request` 发请求。手机端由 Chaquopy 打包，新增第三方
   加密库要额外准备 Android wheel，风险高，所以加密**也只用标准库**：

   - 密钥派生：`hashlib.pbkdf2_hmac('sha256', 口令, salt, 200000)`；
   - 流式加密：把 `hashlib.shake_256`（标准库里的 XOF）当 PRF 用，
     分块取 `keystream_i = SHAKE256(域串 ‖ key ‖ salt ‖ i)`，
     密文 = 明文 XOR keystream；每块的 i 不同 → 密钥流不重复；
   - 完整性：`hmac.new(mac_key, header ‖ 密文, sha256)`，**先加密后认证**
     （encrypt-then-MAC），密文被改动一定解不出来，不会「解出一堆乱码再覆盖本地」。

   包格式（二进制，大端）::

       b"GSYNC1" | salt(16B) | tag(32B) | ciphertext...

   口令错误 / 包被篡改 / 不是本格式 → 一律抛 `SyncError`，调用方据此提示，
   **绝不**把解出来的垃圾写进数据库。

2. **口令不落明文**：由 `app/config.py` 用 DPAPI（Windows）加密后写设置文件；
   安卓侧设置文件在应用私有目录，同样由 `config.dpapi_*` 的降级路径处理。

3. **明文永不出本机**：PUT 上去的永远是密文；口令只参与本地派生，不随请求发送。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import urllib.error
import urllib.parse
import urllib.request

MAGIC = b"GSYNC1"
SALT_LEN = 16
TAG_LEN = 32
PBKDF2_ITER = 200_000
_KEY_DOMAIN = b"goshore-sync-v1"
CHUNK = 1 << 20          # 1MB：分块取密钥流，避免一次性开出整包大小的内存

# 不走环境变量代理（http_proxy / https_proxy / all_proxy）：
# WebDAV 客户端只应连用户显式填写的地址。被系统代理悄悄改写会连到意料之外的主机
# （本机 / 内网地址尤其危险），也让「连不上」这类判断变得不可复现 ——
# 例如连 127.0.0.1:1 时若经代理，拿回来的是代理的 502，错误文案会从「连接失败」
# 变成「HTTP 502」。确需经代理访问时，把代理写进 WebDAV 地址本身即可。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class SyncError(Exception):
    """同步过程中的可读错误（凭据/网络/解密/包格式），前端直接展示文案。"""


# ============================================================
# 一、信封加密（双端必须逐字节一致）
# ============================================================

def _derive(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    """口令 + salt → (加密密钥, 认证密钥)；两把密钥各自独立。"""
    if not isinstance(passphrase, str) or not passphrase:
        raise SyncError("同步口令为空，无法加密/解密")
    prk = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"),
                              salt, PBKDF2_ITER, dklen=32)
    enc = hmac.new(prk, _KEY_DOMAIN + b"|enc", hashlib.sha256).digest()
    mac = hmac.new(prk, _KEY_DOMAIN + b"|mac", hashlib.sha256).digest()
    return enc, mac


def _keystream(enc_key: bytes, salt: bytes, start: int, length: int) -> bytes:
    """取 [start, start+length) 区间的密钥流（分块，块号进 PRF 输入）。"""
    out = bytearray()
    pos = start
    end = start + length
    while pos < end:
        blk = pos // CHUNK
        off = pos % CHUNK
        n = min(CHUNK - off, end - pos)
        xof = hashlib.shake_256()
        xof.update(_KEY_DOMAIN)
        xof.update(enc_key)
        xof.update(salt)
        xof.update(blk.to_bytes(8, "big"))
        out += xof.digest(CHUNK)[off:off + n]
        pos += n
    return bytes(out)


def _xor(data: bytes, ks: bytes) -> bytes:
    """分块做 XOR：整包走 int.from_bytes 会开出几百 MB 的大整数，太吃内存。"""
    out = bytearray(len(data))
    for i in range(0, len(data), CHUNK):
        a = data[i:i + CHUNK]
        b = ks[i:i + CHUNK]
        out[i:i + len(a)] = (int.from_bytes(a, "big")
                             ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")
    return bytes(out)


def encrypt_bytes(plain: bytes, passphrase: str) -> bytes:
    """明文 → 加密信封（每次随机 salt，同一份明文两次加密结果不同）。"""
    salt = os.urandom(SALT_LEN)
    enc_key, mac_key = _derive(passphrase, salt)
    ct = _xor(plain, _keystream(enc_key, salt, 0, len(plain)))
    header = MAGIC + salt
    tag = hmac.new(mac_key, header + ct, hashlib.sha256).digest()
    return header + tag + ct


def is_encrypted(blob: bytes) -> bool:
    """是不是本方案的信封（用于把「传了明文包」这种误操作挑出来）。"""
    return bool(blob) and blob[:len(MAGIC)] == MAGIC


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """加密信封 → 明文；格式不对 / 口令错 / 被改动 → SyncError。"""
    if not is_encrypted(blob):
        raise SyncError("云端文件不是本应用的加密包（可能是明文备份或其它文件）")
    if len(blob) < len(MAGIC) + SALT_LEN + TAG_LEN:
        raise SyncError("加密包已损坏（长度不足）")
    salt = blob[len(MAGIC):len(MAGIC) + SALT_LEN]
    tag = blob[len(MAGIC) + SALT_LEN:len(MAGIC) + SALT_LEN + TAG_LEN]
    ct = blob[len(MAGIC) + SALT_LEN + TAG_LEN:]
    enc_key, mac_key = _derive(passphrase, salt)
    want = hmac.new(mac_key, blob[:len(MAGIC) + SALT_LEN] + ct,
                    hashlib.sha256).digest()
    if not hmac.compare_digest(want, tag):
        raise SyncError("校验失败：同步口令不对，或云端文件被改动")
    return _xor(ct, _keystream(enc_key, salt, 0, len(ct)))


# 口令在设置文件里以 base64 形式流转，这里给一对便捷封装
def encrypt_b64(plain: bytes, passphrase: str) -> str:
    return base64.b64encode(encrypt_bytes(plain, passphrase)).decode("ascii")


def decrypt_b64(b64: str, passphrase: str) -> bytes:
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise SyncError("云端数据不是合法的 base64")
    return decrypt_bytes(raw, passphrase)


# ============================================================
# 二、WebDAV 客户端（标准库，四个方法够用）
# ============================================================

def normalize_base(url: str) -> str:
    """规范化 WebDAV 地址：补协议、去尾部斜杠。

    用户常直接粘坚果云的 `https://dav.jianguoyun.com/dav/` 或漏掉 https，
    这里统一成 `https://host/path` 形式，后面拼路径不出现双斜杠。
    """
    u = (url or "").strip()
    if not u:
        raise SyncError("WebDAV 地址为空")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u.rstrip("/")


def join_url(base: str, remote_path: str) -> str:
    """把远端相对路径（如 `goshore/backup.gsync`）拼到 base 后面，逐段转义。"""
    parts = [p for p in str(remote_path or "").replace("\\", "/").split("/") if p]
    if not parts:
        return base + "/"
    return base + "/" + "/".join(urllib.parse.quote(p, safe="") for p in parts)


class WebDAVClient:
    """极简 WebDAV 客户端。只用到 PROPFIND / MKCOL / PUT / GET / HEAD。"""

    def __init__(self, url: str, user: str = "", password: str = "",
                 timeout: int = 30):
        self.base = normalize_base(url)
        self.user = user or ""
        self.password = password or ""
        self.timeout = timeout

    # ---- 底层 ----

    def _auth_header(self) -> dict:
        if not self.user:
            return {}
        raw = f"{self.user}:{self.password}".encode("utf-8")
        return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}

    def _req(self, method: str, url: str, data: bytes | None = None,
             headers: dict | None = None):
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in self._auth_header().items():
            req.add_header(k, v)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            return _OPENER.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            return e                      # 交给调用方按状态码分支
        except urllib.error.URLError as e:
            raise SyncError(f"连接 WebDAV 失败：{getattr(e, 'reason', e)}")
        except Exception as e:
            raise SyncError(f"请求 WebDAV 出错：{e}")

    @staticmethod
    def _explain(code: int, what: str) -> str:
        if code == 401:
            return f"{what}失败：账号或密码不正确（401）"
        if code == 403:
            return f"{what}失败：账号无权限访问该目录（403）"
        if code == 404:
            return f"{what}失败：远端路径不存在（404）"
        if code == 405:
            return f"{what}失败：服务器不支持该方法（405）"
        if code == 507:
            return f"{what}失败：云端空间不足（507）"
        return f"{what}失败：HTTP {code}"

    # ---- 语义化操作 ----

    def test(self) -> dict:
        """连接测试：优先 PROPFIND 读根目录；405/501 时退回 MKCOL 探测。

        返回 {ok, status, message, server}；不抛异常（前端要显示结果）。
        """
        for method, hdrs in (("PROPFIND", {"Depth": "0"}),
                             ("MKCOL", None),
                             ("OPTIONS", None)):
            r = self._req(method, self.base + "/", b"" if method == "MKCOL" else None,
                          hdrs)
            code = getattr(r, "status", getattr(r, "code", 0))
            server = ""
            try:
                server = r.headers.get("Server") or ""
            except Exception:
                pass
            if code in (200, 207):
                return {"ok": True, "status": code, "server": server,
                        "message": "连接成功"}
            if method == "PROPFIND" and code in (401, 403):
                return {"ok": False, "status": code,
                        "message": self._explain(code, "连接测试")}
            if method == "PROPFIND" and code == 405:
                continue                  # 服务器禁 PROPFIND，试下一个
            if method == "MKCOL" and code in (201, 405):     # 已存在 / 不支持
                continue
            if method == "OPTIONS" and code in (200, 204):
                return {"ok": True, "status": code, "server": server,
                        "message": "连接成功（服务器未开放 PROPFIND）"}
            return {"ok": False, "status": code,
                    "message": self._explain(code, "连接测试")}
        return {"ok": False, "status": 0, "message": "连接测试失败：服务器无可用响应"}

    def ensure_dirs(self, remote_path: str) -> None:
        """逐级 MKCOL（已存在返回 405，静默跳过）。"""
        parts = [p for p in str(remote_path or "").replace("\\", "/").split("/") if p]
        parts = parts[:-1] if parts else []          # 最后一段是文件名
        cur = self.base
        for p in parts:
            cur = cur + "/" + urllib.parse.quote(p, safe="")
            r = self._req("MKCOL", cur + "/", b"")
            code = getattr(r, "status", getattr(r, "code", 0))
            if code not in (200, 201, 405, 301):
                raise SyncError(self._explain(code, f"创建目录 {p}"))

    def put(self, remote_path: str, data: bytes) -> int:
        r = self._req("PUT", join_url(self.base, remote_path), data,
                      {"Content-Type": "application/octet-stream",
                       "Content-Length": str(len(data))})
        code = getattr(r, "status", getattr(r, "code", 0))
        if code not in (200, 201, 204):
            raise SyncError(self._explain(code, "上传"))
        return len(data)

    def get(self, remote_path: str) -> bytes | None:
        """取回远端文件；不存在返回 None（不算错误）。"""
        r = self._req("GET", join_url(self.base, remote_path))
        code = getattr(r, "status", getattr(r, "code", 0))
        if code == 404:
            return None
        if code != 200:
            raise SyncError(self._explain(code, "下载"))
        return r.read()

    def stat(self, remote_path: str) -> dict | None:
        """远端文件元信息 {size, modified, etag}；不存在返回 None。"""
        r = self._req("HEAD", join_url(self.base, remote_path))
        code = getattr(r, "status", getattr(r, "code", 0))
        if code == 404:
            return None
        if code != 200:
            raise SyncError(self._explain(code, "读取云端信息"))
        h = r.headers
        try:
            size = int(h.get("Content-Length") or 0)
        except Exception:
            size = 0
        return {"size": size,
                "modified": h.get("Last-Modified") or "",
                "etag": h.get("ETag") or ""}


# ============================================================
# 三、备份包（把「哪些文件进包」交给两端各自决定）
# ============================================================

def build_zip(pairs, dest):
    """把 [(源路径, 包内名)] 打成一个 zip（跳过不存在的源）。

    两端复用自己的备份清单（桌面 goshor.db/settings.json/...，安卓
    accounts.db + 个人库），这里只负责打包动作，避免两套格式各写一遍。
    """
    import zipfile
    from pathlib import Path
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for src, arc in pairs:
            src = Path(src)
            if src.exists():
                z.write(src, arc)
    return dest


def read_zip_entry(zpath, name: str) -> bytes | None:
    """读包内单个文件（不存在返回 None）。"""
    import zipfile
    with zipfile.ZipFile(zpath) as z:
        if name in z.namelist():
            return z.read(name)
    return None


def zip_names(zpath) -> set:
    import zipfile
    with zipfile.ZipFile(zpath) as z:
        return set(z.namelist())


# ============================================================
# 四、双端共用的配置视图与时间判断（桌面 main.py / 移动 goshor_server.py
#     都调这里，避免各写一份导致行为漂移）
# ============================================================

def public_config(s: dict) -> dict:
    """同步配置的对外视图：去敏感、补 has_* 与上次同步状态。"""
    from .config import SYNC_KEYS
    out = {k: s.get(k) for k in SYNC_KEYS}
    out["sync_has_password"] = bool(s.get("sync_password"))
    out["sync_has_passphrase"] = bool(s.get("sync_passphrase"))
    for k in ("sync_last_at", "sync_last_up_at", "sync_last_down_at",
              "sync_last_size", "sync_device"):
        out[k] = s.get(k)
    return out


def remote_newer(modified: str, last_iso: str) -> bool:
    """云端 Last-Modified 是否晚于「本机上次同步时间」。

    本机记录的是朴素本地时间 ISO 串，HTTP 头是 GMT。本机从未同步过
    （last 为空）视为「云端更新」——此时下载属首次拉取。
    """
    if not last_iso:
        return True
    if not modified:
        return False
    try:
        import datetime
        from email.utils import parsedate_to_datetime
        remote = parsedate_to_datetime(modified)
        if remote.tzinfo is None:
            remote = remote.replace(tzinfo=datetime.timezone.utc)
        local = datetime.datetime.fromisoformat(last_iso)
        if local.tzinfo is None:
            local = local.astimezone()
        return remote > local
    except Exception:
        return False


def device_name() -> str:
    """本机名（写进设置便于用户分辨「上次同步来自哪台设备」）。"""
    import os
    import socket
    return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "")[:40]


def file_stamp(paths) -> str:
    """给一组数据文件算「版本戳」：每份文件 `{mtime_ns}:{size}` 拼成一串。

    两个坑都在这里绕开：
    - **WAL**：`goshor.db` 开了 WAL，新数据先进 `-wal` 再落主库，只看主库
      mtime 会把「本机写过新数据」判成没变，冲突提示就漏了 → `-wal` 一并统计；
    - **秒级精度**：`int(mtime)` 在同一秒内的两次写入看不出差别（测试与快速
      连点都会踩到）→ 用 `st_mtime_ns`。
    """
    import os
    parts = []
    for raw in paths:
        for suffix in ("", "-wal"):
            try:
                st = os.stat(f"{raw}{suffix}")
                parts.append(f"{st.st_mtime_ns}:{st.st_size}")
            except OSError:
                parts.append("0:0")
    return "|".join(parts)