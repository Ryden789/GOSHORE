"""全局配置：目录常量 + JSON 设置文件（API Key 使用 Windows DPAPI 按当前用户加密落盘）。"""
import base64
import ctypes
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

# 设置文件的进程内互斥。必须是 RLock：save_settings 持锁期间会调用
# load_settings，而后者在「明文迁移密文」分支里也要拿同一把锁。
_SETTINGS_LOCK = threading.RLock()

try:  # wintypes 仅 Windows CPython 自带，安卓/其他平台降级为 None
    import ctypes.wintypes as wt
except Exception:
    wt = None

# 打包成单文件 exe（PyInstaller）后，源码和 static/ 被解到临时目录 _MEIPASS。
# 用户数据绝不能写进 _MEIPASS：关窗即删，下次启动就是一个全新的空库。
# 但也不能无条件写 exe 旁边：从压缩包/聊天附件直接双击时，exe 本身常被
# Windows 解到 %TEMP% 运行，旁边同样是「一次性目录」。因此冻结版默认落到
# 当前用户的 LOCALAPPDATA，只有检测到旁边已有 data/（便携版/老用户）时才
# 继续用旁边目录，保证已有数据不会因为升级而「消失」。
#   BASE_DIR    程序目录（资源/工具），源码运行时是仓库根，冻结后是 exe 所在目录；
#   BUNDLE_DIR  只读资源，跟着打包产物走（源码运行时与 BASE_DIR 相同）；
#   DATA_DIR    用户数据目录，数据库/设置/WebView 存储都放这里。
APP_NAME = "GOSHORE"


def _default_data_dir(env: dict | None = None) -> Path:
    """没有便携 data/ 时的稳定用户数据目录。

    Windows 用 LOCALAPPDATA（本地、不漫游），macOS/Linux 没有该变量时
    退回 APPDATA 或 ~/.goshore。单测把 env 显式传进来，避免碰真实用户目录。
    """
    env = os.environ if env is None else env
    for key in ("LOCALAPPDATA", "APPDATA"):
        raw = (env.get(key) or "").strip()
        if raw:
            return Path(raw) / APP_NAME / "data"
    return Path.home() / f".{APP_NAME.lower()}" / "data"


def _resolve_data_dir(frozen: bool, app_dir: Path, env: dict | None = None) -> Path:
    """决定用户数据目录。

    优先级：
      1. ``GOSHORE_DATA_DIR`` 环境变量（精确指定 data 目录，便于高级用户/测试）；
      2. 冻结版且 exe 旁边已有 ``data/`` —— 视为便携版，继续用原目录；
      3. 冻结版默认 ``%LOCALAPPDATA%/GOSHORE/data``；
      4. 源码运行：仓库根 ``data/``。
    """
    env = os.environ if env is None else env
    if not frozen:
        return Path(app_dir) / "data"
    override = (env.get("GOSHORE_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    portable = Path(app_dir) / "data"
    if portable.is_dir():
        return portable
    return _default_data_dir(env)


_FROZEN = bool(getattr(sys, "frozen", False))
if _FROZEN:
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = BASE_DIR

DATA_DIR = _resolve_data_dir(_FROZEN, BASE_DIR)
STATIC_DIR = BUNDLE_DIR / "static"
DB_PATH = DATA_DIR / "goshor.db"
# 桌面端「题库 / 个人数据」拆分后的两个库（见 tools/migrate_split.py）：
#   content.db  题库（documents / docs_fts / shizheng），可整体替换、可分发，
#               不带任何用户作答记录；
#   user.db     个人数据（answers / marks / review_plan / ... + doc_overrides）。
# 两者**同时存在**才算 split 模式；否则回落单库 legacy 模式，行为与旧版一致
# —— 未迁移的用户、以及只建了一个库的测试都不受影响。
CONTENT_DB_PATH = DATA_DIR / "content.db"
USER_DB_PATH = DATA_DIR / "user.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULTS = {
    # 题库源目录（vault）。**默认必须为空**：留成开发者本机的某个私人路径，
    # 会让每个首次启动的用户（尤其拿到的 exe）去扫描/导入我们自己的题库，
    # 既是隐私问题，也会让首次启动卡死在建库上。由用户在「设置」里自己指定。
    "vault_path": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_api_key": "",
    # V4.1 Flash（20261017）带日期固定版：显式锁定版本，避免服务端滚动升级
    # 带来的行为漂移。若官方端点不接受该字符串，改回 "deepseek-flash" 即可
    # （项目里看图功能一直用后者，已验证可用）。
    "deepseek_model": "deepseek-v4.1-flash-20261017",
    # 看图（拍照识题 / PDF 图形题）专用模型：必须是原生多模态，且要能关思考模式。
    # 空串表示「跟随 deepseek_model」——这样升级主模型时看图功能自动同步，
    # 不必在 ai.py / cube_vision.py / pdf_visual.py 三处逐一改。
    "deepseek_vision_model": "",
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

# ---------------- 视觉模型解析 ----------------

def vision_model(settings: dict | None = None) -> str:
    """看图所用模型：优先 deepseek_vision_model，为空则跟随 deepseek_model。

    三个调用点（ai.stream_chat / cube_vision / pdf_visual）都从这里取，
    避免各自硬编码模型名导致升级时漏改。
    """
    s = settings if settings is not None else load_settings()
    return (s.get("deepseek_vision_model") or "").strip() or s.get("deepseek_model") or "deepseek-flash"


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


def _atomic_write_json(path: Path, data: dict) -> None:
    """先写同目录临时文件再替换，避免中途被杀留下半截 JSON。

    半截 JSON 的后果很重：load_settings 会 parse 失败并静默回落到 DEFAULTS，
    用户会以为「所有设置凭空消失」。临时名带进程+线程号，避免并发互踩。
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:      # Windows：目标被读者占用
                time.sleep(0.02 * (attempt + 1))
        # 极端情况退化为直接覆盖：保住数据比保住原子性更重要
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def load_settings() -> dict:
    # 冻结版默认目录在 LOCALAPPDATA/GOSHORE/data，父目录 GOSHORE 可能还不存在；
    # 这里必须 parents=True，否则首次启动会直接抛 FileNotFoundError。
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
        # 迁移回写必须持锁：否则并发 save_settings 期间会用「迁移前的旧快照」
        # 覆盖掉别人刚写入的键。
        with _SETTINGS_LOCK:
            try:
                _atomic_write_json(SETTINGS_PATH, disk)
            except Exception:
                pass
    for enc_field in _SECRET_FIELDS.values():
        s.pop(enc_field, None)
    return s


def save_settings(patch: dict) -> dict:
    # 整个「读-改-写」必须在同一把锁内：设置页、导入、同步配置是三个独立入口，
    # 局域网多标签页同时保存时，无锁会让后写者用旧快照覆盖先写者的键且静默成功。
    with _SETTINGS_LOCK:
        return _save_settings_locked(patch)


def _save_settings_locked(patch: dict) -> dict:
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
    _atomic_write_json(SETTINGS_PATH, s)
    for enc_field in _SECRET_FIELDS.values():
        s.pop(enc_field, None)
    return s
