"""全局配置：目录常量 + JSON 设置文件（API Key 使用 Windows DPAPI 按当前用户加密落盘）。"""
import base64
import ctypes
import json
import re
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
    # N2 学习提醒：开关 / 每日提醒时间 'HH:mm' / 仅当天计划未完成时提醒
    "reminder_on": False,
    "reminder_time": "20:00",
    "reminder_plan_only": False,
    # G2 每日目标：题量 / 专注分钟（0 表示该项不设目标）
    "daily_goal_questions": 30,
    "daily_goal_minutes": 30,
}

# ---------------- 设置项归一化（桌面 / 移动共用同一口径） ----------------

_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_TRUTHY = ("1", "true", "on", "yes")
_FALSY = ("0", "false", "off", "no", "")

REMINDER_KEYS = ("reminder_on", "reminder_time", "reminder_plan_only")
# G2 每日目标字段（题量 / 专注分钟）
GOAL_KEYS = ("daily_goal_questions", "daily_goal_minutes")
# 目标上限：题量最多 500/天、专注最多 1440 分钟/天，防止脏值把进度环撑爆
GOAL_MAX = {"daily_goal_questions": 500, "daily_goal_minutes": 1440}


def normalize_goal(value, key: str = "daily_goal_questions") -> int | None:
    """把每日目标归一成 0~上限 的整数；非法返回 None（调用方丢弃）。

    0 是合法值，表示「该项不设目标」——因此不能用 `if not value` 过滤。
    接受 '30' 这类字符串（前端 input 传参），拒绝负数/非数字/bool。
    上限按 key 取（题量 500 / 分钟 1440），默认按题量。
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        try:
            value = int(float(v))
        except ValueError:
            return None
    elif isinstance(value, float):
        value = int(value)
    if not isinstance(value, int):
        return None
    return max(0, min(GOAL_MAX.get(key, 500), value))


def goal_patch(raw: dict) -> dict:
    """G2：从设置入参里挑出合法的每日目标字段。

    每个键按**自己的**上限夹（题量 500 / 分钟 1440）。
    与 `reminder_patch` 同思路：非法一律丢弃，不写进设置文件。
    """
    out: dict = {}
    for k in GOAL_KEYS:
        if k not in raw:
            continue
        v = normalize_goal(raw[k], k)
        if v is not None:
            out[k] = v
    return out


def normalize_time_hhmm(value) -> str | None:
    """把 'H:mm' / 'HH:mm' 规范成 'HH:mm'（24 小时制）；非法返回 None。

    必须与安卓端 `ReminderScheduler.normalize()` 同口径：两端都接受 '9:05'，
    否则同一份设置在网页上被丢弃、在 APP 上却被排程，行为不一致。
    """
    if not isinstance(value, str):
        return None
    m = _HHMM_RE.match(value.strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def reminder_patch(raw: dict) -> dict:
    """N2 学习提醒：从设置入参里挑出合法的提醒字段。

    开关类接受 bool，也接受 '1'/'true'/'on' 这类字符串（前端/原生传参格式不一）；
    时间必须是 24 小时制 HH:mm，**非法一律丢弃**，不写进设置文件（避免脏值
    让原生排程拿到一个解析不了的字符串）。
    """
    out: dict = {}
    for k in ("reminder_on", "reminder_plan_only"):
        if k not in raw:
            continue
        v = raw[k]
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, str)):
            s = str(v).strip().lower()
            if s in _TRUTHY:
                out[k] = True
            elif s in _FALSY:
                out[k] = False
    if "reminder_time" in raw:
        t = normalize_time_hhmm(raw["reminder_time"])
        if t:
            out["reminder_time"] = t
    return out


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
