"""全局配置：目录常量 + JSON 设置文件（API Key 使用 Windows DPAPI 按当前用户加密落盘）。"""
import base64
import ctypes
import json
import sys
from pathlib import Path

try:  # wintypes 仅 Windows CPython 自带，安卓/其他平台降级为 None
    import ctypes.wintypes as wt
except Exception:
    wt = None

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "goshor.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULTS = {
    "vault_path": r"D:\人文\kaogongzhentizhengliu",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "port": 8765,
    # N3 考试倒计时：'YYYY-MM-DD'，空则首页不显示倒计时横幅
    "exam_date": "",
}

# ---------------- DPAPI（Windows 凭据级加密，仅当前用户可解） ----------------


if wt is not None:
    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _mk_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf  # buf 须保活


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def dpapi_encrypt(text: str) -> str:
    if not text:
        return ""
    blob_in, _keep = _mk_blob(text.encode("utf-8"))
    blob_out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        raise OSError("CryptProtectData 失败")
    try:
        enc = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return base64.b64encode(enc).decode("ascii")


def dpapi_decrypt(b64: str) -> str:
    if not b64:
        return ""
    try:
        blob_in, _keep = _mk_blob(base64.b64decode(b64))
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return ""
        try:
            raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw.decode("utf-8")
    except Exception:
        return ""


# ---------------- 设置读写 ----------------

_ENC_FIELD = "deepseek_api_key_enc"


def load_settings() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    s = dict(DEFAULTS)
    disk: dict = {}
    if SETTINGS_PATH.exists():
        try:
            disk = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            s.update(disk)
        except Exception:
            pass
    # 优先读加密 key
    enc = disk.get(_ENC_FIELD, "")
    if enc and _dpapi_available():
        s["deepseek_api_key"] = dpapi_decrypt(enc)
    elif disk.get("deepseek_api_key"):
        # 存量明文 key：立即迁移为加密存储
        plain = disk["deepseek_api_key"]
        if _dpapi_available():
            try:
                disk[_ENC_FIELD] = dpapi_encrypt(plain)
                disk["deepseek_api_key"] = ""
                SETTINGS_PATH.write_text(
                    json.dumps(disk, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except OSError:
                pass  # 加密失败则保持现状，不影响功能
        s["deepseek_api_key"] = plain
    s.pop(_ENC_FIELD, None)
    return s


def save_settings(patch: dict) -> dict:
    patch = dict(patch)
    # 明文 key 不落盘：转为 DPAPI 密文
    if "deepseek_api_key" in patch:
        plain = patch.pop("deepseek_api_key") or ""
        if _dpapi_available():
            patch[_ENC_FIELD] = dpapi_encrypt(plain) if plain else ""
            patch["deepseek_api_key"] = ""
        else:
            patch["deepseek_api_key"] = plain
    s = load_settings()
    s.pop(_ENC_FIELD, None)
    s.update(patch)
    # 读出现有磁盘密文，避免被默认值覆盖
    if SETTINGS_PATH.exists() and _ENC_FIELD not in patch:
        try:
            old = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if old.get(_ENC_FIELD):
                s[_ENC_FIELD] = old[_ENC_FIELD]
        except Exception:
            pass
    if _dpapi_available():
        s["deepseek_api_key"] = ""  # 明文 key 绝不落盘
    SETTINGS_PATH.write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    s.pop(_ENC_FIELD, None)
    return s
