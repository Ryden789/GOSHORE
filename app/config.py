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
    # O1 多设备加密同步（WebDAV）：开关 / 地址 / 账号 / 远端路径 / 仅 Wi-Fi
    "sync_enabled": False,
    "sync_url": "",
    "sync_user": "",
    "sync_remote_path": "goshore/backup.gsync",
    "sync_wifi_only": False,
    # 上次同步时间（本地时区 ISO 串，用于冲突判断「两边是否都动过」）
    "sync_last_at": "",
    "sync_last_up_at": "",
    "sync_last_down_at": "",
    "sync_last_size": 0,
    "sync_device": "",
    # 上次同步成功时本地数据的「版本戳」（内部状态，不对外暴露）：主库 + WAL 的
    # mtime_ns/size 拼串，用来判断「本机自上次同步后又写入了新数据」。
    "sync_local_stamp": "",
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


def as_bool(value) -> bool | None:
    """开关类字段统一口径：bool / 1 / 'on' / 'yes' → True，'0'/'off' → False。

    认不出的值返回 None，调用方据此**丢弃**（不落盘）。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        s = str(value).strip().lower()
        if s in _TRUTHY:
            return True
        if s in _FALSY:
            return False
    return None


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


# ---------------- O1 多设备同步（WebDAV）字段归一化 ----------------

SYNC_KEYS = ("sync_enabled", "sync_url", "sync_user", "sync_remote_path",
             "sync_wifi_only")
# 口令类字段：不放进 DEFAULTS，也不回给前端；只以 has_* 布尔暴露是否已配置
SYNC_SECRET_KEYS = ("sync_password", "sync_passphrase")
SYNC_REMOTE_DEFAULT = "goshore/backup.gsync"


def normalize_remote_path(value) -> str | None:
    """远端相对路径归一：去首尾斜杠、反斜杠转正斜杠；非法返回 None。

    拒绝 `..` / `.` 段——路径会拼进 WebDAV URL，放行等于给了目录穿越能力。
    空串 / 全是斜杠 → 回落到默认路径（用户在设置页清空输入框时不该报错）。
    """
    if not isinstance(value, str):
        return None
    v = value.strip().replace("\\", "/")
    if not v:
        return SYNC_REMOTE_DEFAULT
    parts = [p for p in v.split("/") if p]
    if not parts:
        return SYNC_REMOTE_DEFAULT
    if any(p in ("..", ".") for p in parts):
        return None
    return "/".join(parts)


def sync_patch(raw: dict) -> dict:
    """O1：从设置入参里挑出合法的同步字段（与移动端同口径）。

    - 开关类走 `as_bool`，认不出就丢弃；
    - `sync_url` / `sync_user` 只接受字符串并 strip；
    - `sync_remote_path` 归一化（见 `normalize_remote_path`）；
    - 口令类：**允许空串**（表示清除），非字符串丢弃。
    """
    out: dict = {}
    for k in ("sync_enabled", "sync_wifi_only"):
        if k in raw:
            b = as_bool(raw[k])
            if b is not None:
                out[k] = b
    for k in ("sync_url", "sync_user"):
        if k in raw and isinstance(raw[k], str):
            out[k] = raw[k].strip()
    if "sync_remote_path" in raw:
        p = normalize_remote_path(raw["sync_remote_path"])
        if p:
            out["sync_remote_path"] = p
    for k in SYNC_SECRET_KEYS:
        if k in raw and isinstance(raw[k], str):
            out[k] = raw[k].strip()
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

# 敏感字段 → 磁盘上的密文字段名。
# O1 复用了同一套「明文不落盘」机制：WebDAV 密码与同步口令都在这里登记，
# 而不是各写一份 DPAPI 调用（新增敏感项只需扩这张表）。
_SECRET_FIELDS = {
    "deepseek_api_key": "deepseek_api_key_enc",
    "sync_password": "sync_password_enc",
    "sync_passphrase": "sync_passphrase_enc",
}
_ENC_FIELD = _SECRET_FIELDS["deepseek_api_key"]      # 兼容旧引用


def _plain_of(disk: dict, field: str) -> str:
    """从磁盘设置里取某个敏感字段的明文（优先密文，其次存量明文）。

    安卓等无 DPAPI 的平台：密文字段不写、明文原样留着（设置文件在应用私有
    目录），这里同样要能读回来，否则手机上保存完口令就丢了。
    """
    enc_field = _SECRET_FIELDS[field]
    enc = disk.get(enc_field, "")
    if enc and _dpapi_available():
        return dpapi_decrypt(enc)
    return disk.get(field, "") or ""


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
    dirty = False
    for plain, enc_field in _SECRET_FIELDS.items():
        s[plain] = _plain_of(disk, plain)
        # 存量明文 → 立即迁移为密文（只在能加密的平台上做）
        if disk.get(plain) and not disk.get(enc_field) and _dpapi_available():
            try:
                disk[enc_field] = dpapi_encrypt(disk[plain])
                disk[plain] = ""
                dirty = True
            except OSError:
                pass  # 加密失败则保持现状，不影响功能
    if dirty:
        try:
            SETTINGS_PATH.write_text(
                json.dumps(disk, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    for enc_field in _SECRET_FIELDS.values():
        s.pop(enc_field, None)
    return s


def save_settings(patch: dict) -> dict:
    patch = dict(patch)
    # 所有敏感字段：明文一律转成密文再落盘（无 DPAPI 的平台保持明文）
    secrets = {k: patch.pop(k) for k in list(patch) if k in _SECRET_FIELDS}
    s = load_settings()
    for enc_field in _SECRET_FIELDS.values():
        s.pop(enc_field, None)
    if SETTINGS_PATH.exists():
        try:
            old = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            for field, enc_field in _SECRET_FIELDS.items():
                if old.get(enc_field):
                    s[enc_field] = old[enc_field]
        except Exception:
            pass
    for field, plain in secrets.items():
        plain = plain or ""
        enc_field = _SECRET_FIELDS[field]
        if _dpapi_available():
            s[enc_field] = dpapi_encrypt(plain) if plain else ""
            s[field] = ""
        else:
            s[field] = plain
            s.pop(enc_field, None)
    s.update(patch)
    if _dpapi_available():
        for field in _SECRET_FIELDS:      # 明文绝不落盘
            s[field] = ""
    SETTINGS_PATH.write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for enc_field in _SECRET_FIELDS.values():
        s.pop(enc_field, None)
    return s
