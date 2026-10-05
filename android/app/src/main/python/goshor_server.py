"""GOSHORE 安卓独立版 · 内置本地服务器

标准库 http.server 实现（不依赖 FastAPI，启动快、体积小），
复用桌面端 app.db / app.formula_drill 核心逻辑，保证做题规则一致。
由 Java 端通过 Chaquopy 调用 start()，返回监听端口。
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import posixpath
import sqlite3
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import accounts, ai, argument, db, essay_rubric, formula_drill, importer, interview, knowledge, planner, speedcalc, variant, wordfill, zy_notes

# 运行路径（Java 注入）
_DB_PATH: Path = Path("")
_IMG_DIR: Path = Path("")
_WEB_DIR: Path = Path("")
_USERS_DIR: Path = Path("")

_lock = threading.Lock()  # 串行化写操作，手机单用户场景足够


def _today_str() -> str:
    """本地日期 YYYY-MM-DD（学习计划按本地日切分）。"""
    import datetime as _dt
    return _dt.date.today().isoformat()

_MOBILE_SETTINGS_DEFAULTS = {
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
}


def _mobile_load_settings() -> dict:
    """按身份读取手机端设置（users/data_<uid>.settings.json）。"""
    uid = accounts.get_session()
    p = _USERS_DIR / f"data_{uid}.settings.json"
    s = dict(_MOBILE_SETTINGS_DEFAULTS)
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return s


def _run_async(coro):
    """在请求线程中运行协程（每线程独立事件循环）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# wordfill / ai / importer 模块复用手机端设置读取（替代桌面 config.load_settings）
wordfill.load_settings = _mobile_load_settings
ai.load_settings = _mobile_load_settings
importer.load_settings = _mobile_load_settings


def _mobile_save_settings(patch: dict) -> None:
    """按身份合并写入手机端设置（原子替换）。"""
    uid = accounts.get_session()
    p = _USERS_DIR / f"data_{uid}.settings.json"
    s = _mobile_load_settings()
    s.update(patch)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(p)


# ---------------- DeepSeek 连通性验证 ----------------

async def _settings_test() -> dict:
    """保存设置后用最小请求（1 token）验证 Key 连通性，返回明确失败原因。"""
    import httpx
    s = _mobile_load_settings()
    key = s.get("deepseek_api_key") or ""
    if not key:
        return {"ok": False, "error": "尚未填写 API Key"}
    payload = {
        "model": s.get("deepseek_model") or "deepseek-chat",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    url = (s.get("deepseek_base_url") or "https://api.deepseek.com"
           ).rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {key}"})
    except Exception as e:
        return {"ok": False,
                "error": f"网络连接失败（{e.__class__.__name__}），请检查接口地址与网络"}
    if r.status_code == 200:
        return {"ok": True}
    if r.status_code in (401, 403):
        return {"ok": False, "error": "Key 无效或未授权（401），请重新复制完整 Key"}
    if r.status_code == 404:
        return {"ok": False, "error": "接口地址有误（404），请核对接口地址"}
    if r.status_code == 429:
        return {"ok": False, "error": "账户额度不足或被限流（429），请到平台充值/稍后再试"}
    return {"ok": False,
            "error": f"API 返回 {r.status_code}：{r.text[:120]}"}


# ---------------- 备份 / 恢复（整包：accounts.db + 全部 data_*.db） ----------------

_BACKUP_FMT = 2  # 备份格式版本：2 = 整包（含账号库，可整包还原）


def _users_data_dbs() -> list:
    """users 目录下全部个人库文件 data_<uid>.db（排除临时文件）。"""
    return sorted(p for p in _USERS_DIR.glob("data_*.db")
                  if not p.name.endswith((".restore", ".tmp", ".new")))


def _checkpoint_file(p: Path) -> None:
    """把单个 sqlite 文件的 WAL 全部落回主库，保证单文件可整体复制。"""
    try:
        c = sqlite3.connect(str(p))
        try:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            c.close()
    except Exception:
        pass


def _mobile_backup_export(include_key: bool) -> dict:
    """整包备份：accounts.db + 全部 data_*.db + 各账号设置 + manifest.json。

    恢复时整包还原，账号密码原样可用，无需重新注册。
    """
    import datetime, zipfile
    acc_db = _USERS_DIR / "accounts.db"
    if acc_db.exists():
        _checkpoint_file(acc_db)
    for p in _users_data_dbs():
        _checkpoint_file(p)
    meta = {
        "app": "goshore-mobile",
        "fmt": _BACKUP_FMT,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "include_key": include_key,
        "accounts": accounts.profiles(),
    }
    out_dir = _USERS_DIR / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"goshore_backup_{datetime.datetime.now():%Y%m%d_%H%M}.zip"
    out = out_dir / name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json",
                   json.dumps(meta, ensure_ascii=False, indent=2))
        if acc_db.exists():
            z.write(acc_db, "accounts.db")
        for p in _users_data_dbs():
            z.write(p, p.name)
            sp = _USERS_DIR / (p.stem + ".settings.json")
            if sp.exists():
                try:
                    s = json.loads(sp.read_text(encoding="utf-8"))
                except Exception:
                    s = {}
                if not include_key:
                    s.pop("deepseek_api_key", None)
                z.writestr(sp.name,
                           json.dumps(s, ensure_ascii=False, indent=2))
    return {"ok": True, "path": str(out), "name": name,
            "size": out.stat().st_size, "accounts": len(meta["accounts"])}


def _mobile_backup_import(data_b64: str) -> dict:
    """恢复备份：整包格式（manifest.json/accounts.db）优先；兼容旧版单账号包。"""
    import base64, io, zipfile
    try:
        raw = base64.b64decode(data_b64)
    except Exception:
        return {"ok": False, "error": "备份数据解码失败"}
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "不是合法的 zip 备份包"}
    with zf:
        names = set(zf.namelist())
        if "accounts.db" in names:
            return _restore_full(zf, names)
        if "data.db" in names:
            return _restore_legacy(zf, names)
        return {"ok": False, "error": "备份包中缺少 accounts.db / data.db"}


def _restore_full(zf, names: set) -> dict:
    """整包还原：覆盖 users 目录下账号库与全部个人库，恢复后需重新登录。"""
    import re as _re
    # 1) 读出全部库文件并逐个校验（全部通过才动现有数据）
    payload = {}
    for n in sorted(names):
        if n == "accounts.db" or _re.fullmatch(r"data_\d+\.db", n):
            payload[n] = zf.read(n)
    settings = {}
    for n in sorted(names):
        if _re.fullmatch(r"data_\d+\.settings\.json", n):
            settings[n] = zf.read(n)
    tmps = []
    err = None
    for n, b in payload.items():
        tmp = _USERS_DIR / ("restore_" + n)
        tmp.write_bytes(b)
        tmps.append(tmp)
        try:
            chk = sqlite3.connect(f"file:{tmp.as_posix()}?mode=ro", uri=True)
            try:
                integ = chk.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                chk.close()
            if integ != "ok":
                err = f"{n} 校验失败，备份已损坏"
        except Exception as e:
            err = f"备份校验失败：{e}"
        if err:
            break
    if err:
        for t in tmps:
            t.unlink(missing_ok=True)
        return {"ok": False, "error": err}

    # 2) 替换 users 目录下的账号库与个人库（含 WAL/SHM 残留）
    with _lock:
        try:
            victims = [_USERS_DIR / "accounts.db"] + _users_data_dbs()
            for p in victims:
                for ext in ("", "-wal", "-shm"):
                    f = Path(str(p) + ext) if ext else p
                    f.unlink(missing_ok=True)
            for n in payload:
                (_USERS_DIR / ("restore_" + n)).replace(_USERS_DIR / n)
            for n, b in settings.items():
                (_USERS_DIR / n).write_bytes(b)
            # 会话失效：回到游客，恢复后用原账号密码直接登录
            accounts.set_session(0)
            db.set_user(0)
        except Exception as e:
            return {"ok": False, "error": f"写入恢复文件失败：{e}"}
        finally:
            for t in tmps:
                t.unlink(missing_ok=True)

    total_answers = 0
    for n in payload:
        if not n.startswith("data_"):
            continue
        try:
            c = sqlite3.connect(str(_USERS_DIR / n))
            try:
                total_answers += c.execute(
                    "SELECT COUNT(*) FROM answers").fetchone()[0]
            finally:
                c.close()
        except Exception:
            pass
    accs = accounts.profiles()
    return {"ok": True, "accounts": accs, "answers": total_answers,
            "restored": sorted(payload) + sorted(settings)}


def _restore_legacy(zf, names: set) -> dict:
    """旧版单账号备份（data.db + settings.json）：恢复到当前登录账号。"""
    uid = accounts.get_session()
    dbp = _USERS_DIR / f"data_{uid}.db"
    setp = _USERS_DIR / f"data_{uid}.settings.json"
    db_bytes = zf.read("data.db")
    settings_bytes = (zf.read("settings.json")
                      if "settings.json" in names else None)

    # 先落临时文件并校验 SQLite
    tmp = dbp.with_name(dbp.name + ".restore")
    tmp.write_bytes(db_bytes)
    chk = sqlite3.connect(f"file:{tmp.as_posix()}?mode=rw", uri=True)
    try:
        integ = chk.execute("PRAGMA integrity_check").fetchone()[0]
        ans_n = chk.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
    finally:
        chk.close()
    if integ != "ok":
        tmp.unlink(missing_ok=True)
        return {"ok": False, "error": "备份数据库校验失败"}

    # 覆盖个人库，清掉旧 WAL/SHM
    for ext in ("-wal", "-shm"):
        p = Path(str(dbp) + ext)
        if p.exists():
            p.unlink()
    tmp.replace(dbp)
    restored = ["data.db"]

    # 设置：备份无 Key 时保留当前 Key
    if settings_bytes:
        try:
            inc = json.loads(settings_bytes.decode("utf-8"))
        except Exception:
            inc = None
        if isinstance(inc, dict):
            cur = _mobile_load_settings()
            keep_key = cur.get("deepseek_api_key", "")
            cur.update(inc)
            if "deepseek_api_key" not in inc:
                cur["deepseek_api_key"] = keep_key
            setp.write_text(
                json.dumps(cur, ensure_ascii=False, indent=2),
                encoding="utf-8")
            restored.append("settings.json")

    # 恢复后统计（新连接读新库）
    conn = db.connect()
    try:
        counts = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                  for t in ("answers", "marks", "review_plan", "cards",
                            "essay_grades", "doubts")}
    finally:
        conn.close()
    return {"ok": True, "restored": restored,
            "answers": ans_n, "counts": counts}


# ---------------- 题库热更新 ----------------

# 「检查更新」拉取的 GitHub Releases 地址（最新发行版）
_UPDATE_RELEASES_API = (
    "https://api.github.com/repos/2936341939/GOSHORE/releases/latest")


def _shared_db_meta() -> dict:
    """只读打开共享题库，读 bank_meta 版本信息（无该表视为 v1 出厂版）。"""
    info = {"version": 1, "docs": 0, "date": ""}
    if not _DB_PATH.exists():
        return info
    uri = _DB_PATH.resolve().as_uri() + "?mode=ro"
    c = sqlite3.connect(uri, uri=True)
    try:
        info["docs"] = c.execute(
            "SELECT COUNT(*) FROM documents").fetchone()[0]
        has = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='bank_meta'").fetchone()
        if has:
            for k, v in c.execute("SELECT key, value FROM bank_meta"):
                if k == "version":
                    info["version"] = int(v)
                elif k == "date":
                    info["date"] = v
    finally:
        c.close()
    return info


def _mobile_update_apply(data_b64: str) -> dict:
    """选择题库更新包：校验 → 旧库改名 .bak → 写入新库 + 解压增量图片。

    校验规则：manifest 版本 > 当前版本；新库可打开、完整性通过且题数正常
    （与 manifest.docs 一致）。任何一步失败都不动现有题库。
    """
    import base64, io, zipfile
    try:
        raw = base64.b64decode(data_b64)
    except Exception:
        return {"ok": False, "error": "更新包数据解码失败"}
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "不是合法的 zip 更新包"}
    with zf:
        names = zf.namelist()
        if "manifest.json" not in names or "goshor.db" not in names:
            return {"ok": False, "error": "更新包缺少 manifest.json 或 goshor.db"}
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            new_ver = int(manifest["version"])
        except Exception:
            return {"ok": False, "error": "manifest.json 解析失败"}
        cur = _shared_db_meta()
        if new_ver <= cur["version"]:
            return {"ok": False,
                    "error": f"更新包 v{new_ver} 不高于当前题库 "
                             f"v{cur['version']}，无需更新"}
        # 新库先落临时文件，校验通过后再替换
        tmp = _DB_PATH.with_name(_DB_PATH.name + ".new")
        tmp.write_bytes(zf.read("goshor.db"))
        try:
            c = sqlite3.connect(f"file:{tmp.as_posix()}?mode=ro", uri=True)
            try:
                integ = c.execute("PRAGMA integrity_check").fetchone()[0]
                docs = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            finally:
                c.close()
        except Exception as e:
            tmp.unlink(missing_ok=True)
            return {"ok": False, "error": f"新题库无法打开：{e}"}
        if integ != "ok" or docs <= 0:
            tmp.unlink(missing_ok=True)
            return {"ok": False, "error": "新题库校验失败（文件损坏或无题目）"}
        if manifest.get("docs") is not None and int(manifest["docs"]) != docs:
            tmp.unlink(missing_ok=True)
            return {"ok": False,
                    "error": f"题数与 manifest 不符（{docs} ≠ "
                             f"{manifest['docs']}），更新包不可信"}
        # 旧库改名 .bak 留后路，再写入新库
        bak = _DB_PATH.with_name(_DB_PATH.name + ".bak")
        try:
            bak.unlink(missing_ok=True)
            if _DB_PATH.exists():
                _DB_PATH.rename(bak)
            tmp.replace(_DB_PATH)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            return {"ok": False, "error": f"替换题库失败：{e}"}
        # 解压增量图片（防路径穿越）
        n_img = 0
        img_root = _IMG_DIR.resolve()
        for n in names:
            if not n.startswith("img/") or n.endswith("/"):
                continue
            out = (_IMG_DIR / n[4:]).resolve()
            try:
                out.relative_to(img_root)
            except ValueError:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(n))
            n_img += 1
    return {"ok": True, "version": new_ver, "docs": docs, "images": n_img,
            "date": manifest.get("date", ""), "need_restart": True}


def _mobile_update_check() -> dict:
    """拉 GitHub Releases 最新题库更新包版本号，与本地比对。"""
    import re as _re
    import urllib.request
    cur = _shared_db_meta()
    try:
        req = urllib.request.Request(
            _UPDATE_RELEASES_API,
            headers={"User-Agent": "goshore-mobile",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "current": cur,
                "error": "检查失败（网络不可达），可在「导入 → 题库更新」"
                         "手动选择更新包"}
    latest, url = 0, ""
    for a in data.get("assets", []):
        m = _re.search(r"goshor-update-v(\d+)\.zip", a.get("name", ""))
        if m and int(m.group(1)) > latest:
            latest = int(m.group(1))
            url = a.get("browser_download_url", "")
    if not latest:  # 没有标准命名资产时退而用 tag 号
        m = _re.search(r"v(\d+)", data.get("tag_name", ""))
        if m:
            latest = int(m.group(1))
    if not latest:
        return {"ok": False, "current": cur,
                "error": "未在 Releases 中找到题库更新包，可手动选择更新包"}
    return {"ok": True, "current": cur, "latest": latest,
            "has_update": latest > cur["version"], "url": url}


def configure(db_path: str, img_dir: str, web_dir: str) -> None:
    global _DB_PATH, _IMG_DIR, _WEB_DIR
    _DB_PATH = Path(db_path)
    _IMG_DIR = Path(img_dir)
    _WEB_DIR = Path(web_dir)
    db.enable_mobile()
    db.DB_PATH = _DB_PATH  # db.connect() 读这个模块级变量
    db.MOBILE_CARDS_DIR = str(_WEB_DIR / "cards")


# ---------------- 综应：时政期次 / 真题库 ----------------

def _shizheng_period(now=None):
    import datetime
    dt = now or datetime.datetime.now()
    half = "上半月" if dt.day <= 15 else "下半月"
    return f"{dt.year}年{dt.month}月{half}", f"{dt.year}年{dt.month}月"


def _shizheng_recent_periods(n=12):
    """最近 n 个半月期次（含当期），倒序。"""
    import datetime
    dt = datetime.datetime.now()
    periods = []
    half = "上半月" if dt.day <= 15 else "下半月"
    periods.append(f"{dt.year}年{dt.month}月{half}")
    year, month = dt.year, dt.month
    for _ in range(n - 1):
        if half == "下半月":
            half = "上半月"
        else:
            half = "下半月"
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        periods.append(f"{year}年{month}月{half}")
    return periods


def _shizheng_overview() -> dict:
    period, _ = _shizheng_period()
    recent = _shizheng_recent_periods(12)
    existing = {it["period"] for it in db.list_shizheng()}
    return {
        "items": db.list_shizheng(),
        "current": period,
        "current_exists": db.get_shizheng(period) is not None,
        "recent_periods": recent,
        "missing_periods": [p for p in recent if p not in existing],
    }


def _load_essay_questions() -> list:
    p = _WEB_DIR / "m" / "essay_questions.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


# ---------------- 词语填空：免 Key 预置题降级 ----------------

_WORDFILL_SEED: list | None = None


def _load_wordfill_seed() -> list:
    """读取随包预置词填题（m/wordfill_seed.json），带缓存；加载时做结构校验并规范化空格占位。"""
    global _WORDFILL_SEED
    if _WORDFILL_SEED is None:
        items = []
        try:
            data = json.loads(
                (_WEB_DIR / "m" / "wordfill_seed.json").read_text(encoding="utf-8"))
            for raw in data.get("items", []):
                it = dict(raw)
                # _structural_check 返回空串为通过，同时会把占位统一为【　】
                if not wordfill._structural_check(it):
                    items.append(it)
        except Exception:
            items = []
        _WORDFILL_SEED = items
    return _WORDFILL_SEED


def _wordfill_qid_by_passage(passage: str) -> int:
    """按文段查个人库已有词填题 id（预置题去重落库用）。"""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id FROM wordfill_questions WHERE passage=? LIMIT 1",
            (passage,)).fetchone()
        return row["id"] if row else 0
    finally:
        conn.close()


def _wordfill_recent_qids(limit: int = 100) -> set:
    """本机最近作答过的词填题 qid 集合（避免短期重复抽题）。"""
    conn = db.connect()
    try:
        return {r["qid"] for r in conn.execute(
            "SELECT qid FROM wordfill_answers ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()}
    finally:
        conn.close()


def _wordfill_seed_pick(category: str, difficulty: str, n: int) -> list[dict]:
    """免 Key 模式抽题：按类型/难度过滤预置题，避开最近做过的，落库取稳定 id 后返回。"""
    import random
    pool = _load_wordfill_seed()
    if not pool:
        return []
    recent = _wordfill_recent_qids(100)

    def match(it, cat, diff):
        return ((not cat or it.get("category") == cat)
                and (not diff or it.get("difficulty") == diff))

    cands = [it for it in pool if match(it, category, difficulty)]
    if len(cands) < n:
        cands = [it for it in pool if match(it, category, "")]  # 放宽难度
    if len(cands) < n:
        cands = list(pool)                                      # 再放宽类型
    random.shuffle(cands)

    fresh, done = [], []
    for it in cands:
        qid = _wordfill_qid_by_passage(it["passage"])
        if not qid:
            q = dict(it)
            q["verified"] = False  # 预置题未走 AI 盲选复核
            qid = db.save_wordfill(q)
        q = dict(it)
        q["id"] = qid
        (done if qid in recent else fresh).append(q)
        if len(fresh) >= n:
            break
    out = fresh[:n]
    if len(out) < n:  # 新题不够时用最近做过的补齐，保证题量
        out += done[:n - len(out)]
    return out


def _rubric_points(rubric: str) -> list[str]:
    """从评分细则文本抽出编号给分规则行，作为对照自评的勾选维度。"""
    import re
    pts = []
    for line in (rubric or "").splitlines():
        line = line.strip()
        if re.match(r"^\d+[\.、]", line):
            pts.append(re.sub(r"^\d+[\.、]\s*", "", line))
    return pts[:10]


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
        db.set_user(accounts.get_session())

        try:
            if path == "/api/auth/me":
                self._json(accounts.me())
            elif path == "/api/auth/profiles":
                self._json({"items": accounts.profiles()})
            elif path == "/api/stats":
                self._json(db.stats_overview())
            elif path == "/api/facets":
                self._json(db.facets())
            elif path == "/api/exams":
                self._json({"items": db.list_exams()})
            elif path == "/api/kaodian-tree":
                self._json({"items": db.kaodian_tree(q("module", "判断推理"))})
            elif path == "/api/mastery":
                self._json({"items": db.kaodian_mastery(q("module"))})
            elif path == "/api/ability/radar":
                self._json({"items": db.ability_radar()})
            elif path == "/api/interview/questions":
                self._json({
                    "items": db.list_interview_questions(q("category")),
                    "counts": db.interview_category_counts(),
                    "categories": interview.CATEGORIES,
                    "hints": interview.CATEGORY_HINT,
                    "think_seconds": interview.THINK_SECONDS,
                    "answer_seconds": interview.ANSWER_SECONDS})
            elif path == "/api/interview/stats":
                self._json(db.interview_stats())
            elif path == "/api/interview/logs":
                self._json({"items": db.list_interview_logs()})
            elif path.startswith("/api/interview/log/"):
                try:
                    lid = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self._err(404)
                else:
                    it = db.get_interview_log(lid)
                    if not it:
                        self._err(404)
                    else:
                        self._json(it)
            elif path.startswith("/api/interview/question/"):
                try:
                    qid = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self._err(404)
                else:
                    it = db.get_interview_question(qid)
                    if not it:
                        self._err(404)
                    else:
                        self._json(it)
            elif path == "/api/study-plan":
                today = _today_str()
                self._json({"items": db.list_study_plan(),
                            "summary": db.study_plan_summary(today),
                            "today": today})
            elif path == "/api/zy/notes":
                self._json({"ok": True, "data": zy_notes.NOTES})
            elif path == "/api/wrong-book":
                self._json({"items": db.list_wrong_book()})
            elif path == "/api/marks":
                self._json({"items": db.list_marks()})
            elif path == "/api/my-documents":
                self._json({"items": db.list_my_documents()})
            elif path == "/api/reviews":
                self._json({"items": db.due_reviews()})
            elif path == "/api/review/dashboard":
                self._json(db.review_dashboard())
            elif path == "/api/wrong-reasons":
                self._json(db.wrong_reason_map())
            elif path == "/api/wrong-reason/ai-map":
                self._json({"items": db.wrong_reason_ai_map()})
            elif path == "/api/wrong-reason/distribution":
                self._json({"items": db.wrong_reason_distribution()})
            elif path == "/api/cards":
                self._json({"items": db.list_cards(
                    q("card_type"), q("category"), q("module"))})
            elif path == "/api/cards/facets":
                self._json(db.card_facets())
            elif path == "/api/cards/progress":
                self._json(db.cards_progress())
            elif path == "/api/cards/weak":
                self._json({"items": db.weak_cards()})
            elif path == "/api/due-cards":
                self._json({"items": db.due_cards()})
            elif path == "/api/settings":
                s = _mobile_load_settings()
                key = s.get("deepseek_api_key") or ""
                s["deepseek_api_key"] = ("***" + key[-4:]) if key else ""
                self._json(s)
            elif path == "/api/argument/overview":
                ov = argument.list_materials()
                ov["taxonomy"] = argument._TAXONOMY
                ov["quiz_stats"] = argument.quiz_stats()
                ov["quiz_type_stats"] = argument.quiz_type_stats()
                self._json(ov)
            elif path.startswith("/api/argument/material/"):
                m = argument.get_material(path.rsplit("/", 1)[-1])
                if m:
                    self._json(m)
                else:
                    self._json({"error": "not found"}, 404)
            elif path.startswith("/api/doc/"):
                try:
                    doc_id = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self._err(404)
                else:
                    doc = db.get_doc(doc_id)
                    if not doc:
                        self._err(404)
                    else:
                        self._json(doc)
            elif path == "/api/doubts":
                items, total, counts = db.list_doubts(
                    q("status"), int(q("page") or "1"))
                for it in items:
                    it["doc_id"] = db.doc_id_by_qid(it["qid"])
                self._json({"items": items, "total": total, "counts": counts})
            elif path == "/api/history":
                self._json(db.answer_history(
                    min(500, int(q("limit") or "100")),
                    int(q("offset") or "0")))
            elif path == "/api/report/weekly":
                self._json(db.weekly_report())
            elif path == "/api/speed/type-stats":
                self._json({"items": db.speed_type_stats()})
            elif path == "/api/speed/history":
                self._json({"items": db.speed_history()})
            elif path == "/api/wordfill/stats":
                self._json(db.wordfill_stats())
            elif path == "/api/knowledge/essay":
                self._json(knowledge.ESSAY_KNOWLEDGE)
            elif path == "/api/essay/rubrics":
                self._json({"items": [
                    {"key": k, "name": v["name"], "hint": v["hint"],
                     "default_score": v["default_score"],
                     "points": _rubric_points(v["rubric"])}
                    for k, v in essay_rubric.RUBRICS.items()]})
            elif path == "/api/essay/history":
                items = db.list_essay_grades()
                for it in items:
                    it["summary"] = (it.get("result") or "").split("\n", 1)[0][:60]
                    it.pop("result", None)
                    it.pop("answer", None)
                self._json({"items": items})
            elif path == "/api/essay/trend":
                cat = (q.get("category", [""])[0] or "")
                try:
                    lim = int(q.get("limit", ["30"])[0])
                except (TypeError, ValueError):
                    lim = 30
                self._json({"items": db.essay_score_trend(cat, lim)})
            elif path.startswith("/api/essay/history/"):
                try:
                    gid = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self._err(404)
                else:
                    it = db.get_essay_grade(gid)
                    if not it:
                        self._err(404)
                    else:
                        self._json(it)
            elif path == "/api/essay/questions":
                self._json({"items": [
                    {"id": q["id"], "exam": q.get("exam", ""),
                     "category": q.get("category", ""), "title": q.get("title", ""),
                     "total_score": q.get("total_score", 0),
                     "has_reference": bool(q.get("reference"))}
                    for q in _load_essay_questions()]})
            elif path.startswith("/api/essay/question/"):
                qid = urllib.parse.unquote(path.rsplit("/", 1)[1])
                q = next((x for x in _load_essay_questions() if x["id"] == qid), None)
                if q is None:
                    self._err(404)
                else:
                    self._json(q)
            elif path == "/api/shizheng":
                self._json(_shizheng_overview())
            elif path == "/api/update/current":
                self._json({"ok": True, **_shared_db_meta()})
            elif path == "/api/update/check":
                self._json(_mobile_update_check())
            elif path == "/api/backup/download":
                self._serve_backup(q("name"))
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

    # ---- DELETE ----

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        db.set_user(accounts.get_session())
        try:
            if path.startswith("/api/my-documents/"):
                try:
                    doc_id = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self._err(404, "题目不存在")
                else:
                    if db.delete_my_document(doc_id):
                        self._json({"ok": True})
                    else:
                        self._err(404, "题目不存在")
            else:
                self._err(404, "not found")
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
        db.set_user(accounts.get_session())
        try:
            if path == "/api/auth/register":
                self._json(accounts.register(
                    b.get("username", ""), b.get("password", ""),
                    bool(b.get("migrateGuest"))))
            elif path == "/api/auth/login":
                self._json(accounts.login(b.get("username", ""), b.get("password", "")))
            elif path == "/api/auth/logout":
                self._json(accounts.logout())
            elif path == "/api/paper":
                ids = db.random_paper(
                    b.get("module", ""), b.get("kaodian", ""),
                    max(1, min(30, int(b.get("n", 10)))))
                self._json({"ids": ids})
            elif path == "/api/paper/adaptive":
                ids = db.adaptive_paper(
                    b.get("module", ""), max(1, min(30, int(b.get("n", 15)))),
                    b.get("kaodian", ""))
                self._json({"ids": ids})
            elif path == "/api/paper/sequential":
                ids = db.sequential_paper(
                    b.get("module", ""), b.get("kaodian", ""),
                    max(1, min(50, int(b.get("n", 10)))))
                self._json({"ids": ids})
            elif path == "/api/exam-paper":
                exam = str(b.get("exam", ""))
                ids = db.exam_paper_ids(exam)
                n = len(ids)
                minutes = max(10, round(n * 0.89)) if n else 0
                self._json({"ids": ids, "minutes": minutes, "name": exam})
            elif path == "/api/docs/batch":
                self._json({"items": db.get_docs_batch(b.get("ids", []))})
            elif path == "/api/answer":
                with _lock:
                    info = db.add_answer(int(b["doc_id"]), b.get("selected", ""),
                                         bool(b.get("correct")), int(b.get("ms", 0)),
                                         bool(b.get("guessed")))
                self._json({"ok": True, "annihilated": bool(info.get("annihilated"))})
            elif path == "/api/focus/add":
                with _lock:
                    total = db.add_focus(int(b.get("seconds", 0)))
                self._json({"ok": True, "today_total": total})
            elif path == "/api/wrong-reason":
                with _lock:
                    db.set_wrong_reason(int(b["doc_id"]), b.get("reason", ""))
                self._json({"ok": True})
            elif path == "/api/wrong-book/dismiss":
                db.dismiss_wrong_book(int(b["doc_id"]))
                self._json({"ok": True})
            elif path == "/api/wrong-book/restore":
                db.restore_wrong_book(int(b["doc_id"]))
                self._json({"ok": True})
            elif path == "/api/wrong-reason/ai-suggest":
                self._json(_run_async(self._wrong_reason_ai(b)))
            elif path == "/api/annihilate/start":
                self._json(_run_async(variant.start_annihilation(int(b["doc_id"]))))
            elif path == "/api/annihilate/finish":
                with _lock:
                    variant.finish_annihilation(int(b["doc_id"]))
                self._json({"ok": True})
            elif path == "/api/argument/overview":
                ov = argument.list_materials()
                ov["taxonomy"] = argument._TAXONOMY
                ov["quiz_stats"] = argument.quiz_stats()
                ov["quiz_type_stats"] = argument.quiz_type_stats()
                self._json(ov)
            elif path.startswith("/api/argument/material/"):
                m = argument.get_material(path.rsplit("/", 1)[-1])
                if m:
                    self._json(m)
                else:
                    self._json({"error": "not found"}, 404)
            elif path == "/api/argument/submit":
                marks = b.get("marks", [])
                r = argument.submit(str(b.get("mid", "")), marks)
                if r.get("ok") and b.get("with_ai"):
                    r["ai_comments"] = _run_async(
                        argument.ai_comment(str(b.get("mid", "")), r["detail"]))
                self._json(r)
            elif path == "/api/argument/quiz/draw":
                # types 兼容字符串（单类型专练）与列表，归一化在 quiz_draw 内
                self._json(argument.quiz_draw(
                    max(1, min(20, int(b.get("n", 5)))),
                    types=b.get("types") or None))
            elif path == "/api/argument/quiz/check":
                self._json(argument.quiz_check(b.get("answers", [])))
            elif path == "/api/cards/import":
                with _lock:
                    r = db.import_cards()
                self._json(r)
            elif path == "/api/difficulty/tag":
                with _lock:
                    r = db.tag_difficulty_batch()
                self._json(r)
            elif path == "/api/card-review":
                with _lock:
                    db.card_review(str(b["card_id"]), int(b.get("level", 2)))
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
            elif path == "/api/speed/generate":
                self._json({"items": speedcalc.generate(
                    b.get("config", {}), int(b.get("n", 10)))})
            elif path == "/api/speed/result":
                with _lock:
                    db.add_speed_round(b.get("config", {}), int(b["total"]),
                                       int(b["correct"]), int(b["avg_ms"]),
                                       b.get("details", []))
                    rec = None
                    if b.get("best_key") and b.get("round_ms"):
                        rec = db.speed_best_check(
                            str(b["best_key"]), int(b["round_ms"]))
                self._json({"ok": True, "record": rec})
            elif path == "/api/wordfill/generate":
                self._json(_run_async(self._wordfill_generate(b)))
            elif path == "/api/wordfill/practice":
                self._json(_run_async(self._wordfill_practice(b)))
            elif path == "/api/wordfill/answer":
                with _lock:
                    db.add_wordfill_answer(
                        int(b["qid"]), b.get("selected", ""),
                        bool(b.get("correct")), int(b.get("ms", 0)))
                self._json({"ok": True})
            elif path == "/api/study-plan/generate":
                self._json(self._study_plan_generate(b))
            elif path == "/api/study-plan/toggle":
                ok = db.toggle_study_plan(
                    b.get("day", ""), b.get("module", ""), bool(b.get("done", True)))
                today = _today_str()
                self._json({"ok": ok, "summary": db.study_plan_summary(today)})
            elif path == "/api/interview/grade":
                self._interview_grade(b)
            elif path == "/api/essay/grade":
                self._essay_grade(b)
            elif path == "/api/essay/self-grade":
                self._json(self._essay_self_grade(b))
            elif path == "/api/ai/ask":
                self._ai_ask(b)
            elif path == "/api/shizheng/generate":
                self._json(_run_async(self._shizheng_generate(b)))
            elif path == "/api/shizheng/quiz":
                self._json(_run_async(self._shizheng_quiz(b)))
            elif path == "/api/search":
                rows, total = db.search_docs(
                    q=b.get("q", ""), kind=b.get("kind", ""),
                    module=b.get("module", ""), daclass=b.get("daclass", ""),
                    region=b.get("region", ""), year=b.get("year", ""),
                    page=int(b.get("page", 1)),
                    page_size=int(b.get("page_size", 20)))
                self._json({"items": rows, "total": total,
                            "page": int(b.get("page", 1))})
            elif path == "/api/doubts/sync":
                with _lock:
                    r = db.sync_doubts()
                self._json(r)
            elif path == "/api/doubt/status":
                status = b.get("status", "")
                if status not in ("pending", "confirmed", "dismissed"):
                    self._err(400, "非法状态")
                else:
                    with _lock:
                        db.set_doubt_status(b.get("qid", ""), status)
                    self._json({"ok": True})
            elif path.startswith("/api/doubt/recheck/"):
                qid = urllib.parse.unquote(path.rsplit("/", 1)[1])
                self._json(_run_async(self._doubt_recheck(qid)))
            elif path == "/api/import/json/preview":
                items, errors = importer.parse_json_bank(b.get("text", ""))
                self._json({"items": items, "errors": errors,
                            "count": len(items)})
            elif path == "/api/import/web/preview":
                self._json(_run_async(self._import_web_preview(b)))
            elif path == "/api/import/commit":
                raw_items = b.get("items") or []
                if not raw_items:
                    self._json({"ok": False, "error": "没有可导入的题目"})
                elif len(raw_items) > 200:
                    self._json({"ok": False,
                                "error": "单次最多导入 200 题"})
                else:
                    items, errors = [], []
                    for i, raw in enumerate(raw_items, 1):
                        item, err = importer.normalize_item(raw, i)
                        if item:
                            items.append(item)
                        else:
                            errors.append(err)
                    if not items:
                        self._json({"ok": False,
                                    "error": "全部题目校验失败："
                                             + "；".join(errors[:3])})
                    else:
                        with _lock:
                            r = db.mobile_commit_items(
                                items, b.get("defaults") or {})
                        r["skipped"] = errors
                        self._json(r)
            elif path == "/api/settings":
                patch = {}
                for k in ("deepseek_base_url", "deepseek_model",
                          "deepseek_api_key"):
                    if k in b and isinstance(b[k], str):
                        v = b[k].strip()
                        if k == "deepseek_api_key" and v.startswith("***"):
                            continue
                        patch[k] = v
                _mobile_save_settings(patch)
                self._json({"ok": True})
            elif path == "/api/settings/test":
                self._json(_run_async(_settings_test()))
            elif path == "/api/backup/export":
                self._json(_mobile_backup_export(
                    bool(b.get("include_key"))))
            elif path == "/api/backup/import":
                self._json(_mobile_backup_import(
                    str(b.get("data_b64", ""))))
            elif path == "/api/update/apply":
                self._json(_mobile_update_apply(
                    str(b.get("data_b64", ""))))
            else:
                self._err(404, "not found")
        except (KeyError, ValueError, TypeError, accounts.AuthError) as e:
            self._err(400, str(e))
        except Exception as e:
            self._err(500, str(e))

    # ---- 错因 AI 预归因（与桌面规则一致） ----

    async def _wrong_reason_ai(self, b):
        doc_id = int(b["doc_id"])
        doc = db.get_doc(doc_id)
        if not doc:
            return {"ok": False, "error": "题目不存在"}
        d = doc["data"]
        hist = db.get_user_history(doc_id)
        correct = next((o["label"] for o in d.get("options") or []
                        if o.get("correct")), "")
        opts = "\n".join(f"{o['label']}. {o['text']}"
                         for o in d.get("options") or [])
        prompt = ai.build_wrong_reason_prompt(
            str(d.get("stem", "")), opts, correct,
            str(hist.get("last_selected") or ""), hist.get("tries", 0),
            hist.get("wrongs", 0))
        try:
            raw = await ai.chat_once(
                [{"role": "user", "content": prompt}], temperature=0)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        data = ai.parse_wrong_reason_json(raw)
        if not data:
            # 兜底：AI 未按 JSON 返回时退化为关键词匹配
            reason = next((r for r in ai.WRONG_CATEGORIES if r in raw), "")
            if reason:
                db.set_wrong_ai(doc_id, reason)
            return {"ok": bool(reason), "reason": reason, "category": reason,
                    "specific": "", "kaodian": "", "advice": ""}
        db.set_wrong_ai(doc_id, data["category"], data["specific"],
                        data["kaodian"], data["advice"])
        return {"ok": True, "reason": data["category"], **data}

    # ---- 疑点 AI 独立复核（与桌面规则一致） ----

    async def _doubt_recheck(self, qid):
        conn = db.connect()
        db._ensure_doubt(conn)
        row = conn.execute(
            "SELECT * FROM doubts WHERE qid=?", (qid,)).fetchone()
        conn.close()
        if not row:
            return {"ok": False, "error": "疑点不存在"}
        target = dict(row)
        doc_id = db.doc_id_by_qid(qid)
        doc = db.get_doc(doc_id) if doc_id else None

        parts = [
            "你是行测命题质检员。下面是一道真题及其「疑点描述」，请你独立重算/重读，判断疑点是否成立，给出结论与理由，200 字以内。",
            f"【疑点描述】{target['descr']}",
        ]
        if doc:
            d = doc["data"]
            if d.get("stem"):
                parts.append(f"【题干】{d['stem'][:800]}")
            if d.get("options"):
                parts.append("【选项】" + "；".join(
                    f"{o['label']}.{o['text']}" for o in d["options"]))
            ans = next((o["label"] for o in d.get("options", [])
                        if o.get("correct")), "")
            if ans:
                parts.append(f"【给定答案】{ans}")
            if d.get("official"):
                import re as _re2
                off = _re2.sub(r"<[^>]+>", "", d["official"])[:600]
                parts.append(f"【官方解析】{off}")
        else:
            parts.append("（题库中未找到原题，仅根据疑点描述判断）")

        messages = [
            {"role": "system",
             "content": "你是行测命题质检员，独立复核题目疑点，只给结论与依据。"},
            {"role": "user", "content": "\n\n".join(parts)},
        ]
        buf = []
        async for kind, payload in ai.stream_chat(messages):
            if kind == "delta":
                buf.append(payload)
            elif kind == "error":
                return {"ok": False, "error": payload}
        note = "".join(buf).strip()
        if note:
            db.set_doubt_ai(qid, note)
        return {"ok": True, "note": note}

    # ---- 网页/文本真题 AI 抽取预览 ----

    async def _import_web_preview(self, b):
        try:
            if b.get("url"):
                text = await importer.fetch_url_text(b["url"])
                if len(text) < 50:
                    return {"items": [],
                            "error": "网页正文过短，可能被反爬；请改用粘贴文本模式"}
            else:
                text = (b.get("text") or "").strip()
        except Exception as e:
            return {"items": [], "error": f"抓取失败：{e}"}
        if not text:
            return {"items": [], "error": "内容为空"}
        items, err = await importer.ai_extract_questions(text)
        return {"items": items, "error": err, "count": len(items)}

    # ---- 词语填空：AI 生成（协程，与桌面规则一致） ----

    async def _wordfill_generate(self, b):
        # AI 扩充题量：仅配 Key 后可用
        if not _mobile_load_settings().get("deepseek_api_key"):
            return {"items": [], "total": db.wordfill_count(),
                    "need_key": True,
                    "error": "配置 DeepSeek Key 后可使用 AI 命题"}
        category = b.get("category", "")
        difficulty = b.get("difficulty", "mid")
        n = max(1, min(5, int(b.get("n", 1))))
        out = []
        for _ in range(n):
            q = await wordfill.generate_one(category, difficulty)
            if q:
                q["difficulty"] = difficulty
                q["id"] = db.save_wordfill(q)
                out.append(q)
        return {"items": out, "total": db.wordfill_count()}

    async def _wordfill_practice(self, b):
        category = b.get("category", "")
        difficulty = b.get("difficulty", "")
        n = max(1, min(20, int(b.get("n", 10))))
        # 免 Key 降级：未配置 Key 时从随包预置题抽题（判分字段与 AI 命题同构）
        if not _mobile_load_settings().get("deepseek_api_key"):
            return {"items": _wordfill_seed_pick(category, difficulty, n),
                    "generated": 0, "mode": "seed"}
        existing = db.random_wordfill(n, category, difficulty)
        if len(existing) >= n:
            return {"items": existing, "generated": 0}
        need = n - len(existing)
        for _ in range(min(need, 5)):
            q = await wordfill.generate_one(category, difficulty or "mid")
            if q:
                q["difficulty"] = difficulty or "mid"
                q["id"] = db.save_wordfill(q)
                existing.append(q)
        return {"items": existing, "generated": need}

    # ---- 综应 AI 批改（SSE 流式，HTTP/1.0 close 模式） ----

    def _sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse_chunk(self, data: bytes):
        if data:
            self.wfile.write(data)
            self.wfile.flush()

    def _stream_sse(self, agen):
        self._sse_open()
        loop = asyncio.new_event_loop()
        try:
            while True:
                try:
                    kind, payload = loop.run_until_complete(agen.__anext__())
                except StopAsyncIteration:
                    break
                if isinstance(payload, dict):
                    obj = {"type": kind}
                    obj.update(payload)
                else:
                    obj = {"type": kind, "text": payload}
                frame = ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n")
                self._sse_chunk(frame.encode("utf-8"))
        except BrokenPipeError:
            pass
        finally:
            loop.close()

    # ---- 自由提问 AI 答疑（不做题也能问，SSE 流式） ----

    def _ai_ask(self, b):
        raw = b.get("messages") or []
        msgs = []
        for m in raw[-12:]:
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue
            content = str(m.get("content") or "")[:4000]
            if content:
                msgs.append({"role": role, "content": content})
        if not msgs or msgs[-1]["role"] != "user":
            return self._err(400, "最后一条必须是用户提问")
        messages = [{"role": "system", "content": ai.ASK_SYSTEM}] + msgs

        async def gen():
            async for kind, payload in ai.stream_chat(messages):
                yield kind, payload

        self._stream_sse(gen())

    # ---- 面试模块：AI 模拟考官（功能 2.3） ----

    def _interview_grade(self, b):
        question = (b.get("question") or "").strip()
        answer = (b.get("answer") or "").strip()
        if not question or not answer:
            return self._err(400, "题目与作答均不能为空")
        category = b.get("category") or "综合分析"
        try:
            qid = int(b.get("qid") or 0)
        except (TypeError, ValueError):
            qid = 0
        q = db.get_interview_question(qid) if qid else None
        messages = interview.build_grade_messages(
            category, question, answer, (q or {}).get("reference", ""))

        async def gen():
            yield "phase", "模拟考官正在点评…"
            buffer = []
            async for kind, payload in ai.stream_chat_with_temp(messages, 0.3):
                if kind == "delta":
                    buffer.append(payload)
                elif kind == "error":
                    yield "error", payload
                    return
            raw = "".join(buffer).strip()
            parsed = interview.parse_grade_json(raw)
            if parsed:
                md_text = interview.render_grade_markdown(parsed)
                with _lock:
                    gid = db.save_interview_log(
                        qid, category, answer, parsed["content"], parsed["logic"],
                        parsed["express"], md_text,
                        int(b.get("think_ms") or 0), int(b.get("answer_ms") or 0))
                yield "result", {"data": parsed}
                yield "saved", str(gid)
            elif raw:
                with _lock:
                    gid = db.save_interview_log(
                        qid, category, answer, 0, 0, 0, raw,
                        int(b.get("think_ms") or 0), int(b.get("answer_ms") or 0))
                yield "fallback", raw
                yield "saved", str(gid)
            else:
                yield "error", "点评未返回内容，请重试"

        self._stream_sse(gen())

    # ---- 能力雷达 & 学习计划（功能 2.1） ----

    def _study_plan_generate(self, b):
        try:
            days = int(b.get("days", 14))
        except (TypeError, ValueError):
            days = 14
        try:
            daily_n = int(b.get("daily_n", 30))
        except (TypeError, ValueError):
            daily_n = 30
        radar = db.ability_radar()
        pool = {}
        for m in planner.MODULE_WEIGHT:
            rows = db.kaodian_mastery(m)
            pool[m] = [r["kaodian"] for r in rows
                       if r.get("level") in ("red", "amber")
                       and r.get("total", 0) >= 3][:8]
        items = planner.build_plan(
            radar, exam_date=(b.get("exam_date") or ""),
            days=max(1, min(60, days)), daily_n=max(10, min(200, daily_n)),
            kaodian_pool=pool)
        with _lock:
            n = db.save_study_plan(items)
        today = _today_str()
        return {"ok": True, "n": n, "items": db.list_study_plan(),
                "summary": db.study_plan_summary(today), "today": today}

    # ---- 综应免 Key 对照自评（与 AI 批改同一落库路径） ----

    def _essay_self_grade(self, b):
        category = b.get("category", "")
        rub = essay_rubric.RUBRICS.get(category)
        if not rub:
            return {"ok": False, "error": "未知题型"}
        question = (b.get("question") or "").strip()
        answer = (b.get("answer") or "").strip()
        if not question or not answer:
            return {"ok": False, "error": "题目与作答均不能为空"}
        try:
            total = int(b.get("total_score") or 0)
        except (TypeError, ValueError):
            total = 0
        total = total if 10 <= total <= 100 else rub["default_score"]
        try:
            score = float(b.get("score"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "自评分数无效"}
        score = max(0.0, min(float(total), score))
        note = (b.get("note") or "").strip()[:500]
        # 勾选维度：{text, ok}，文本去掉竖线避免破坏 Markdown 表格
        checks = []
        for c in (b.get("checks") or [])[:30]:
            if isinstance(c, dict) and c.get("text"):
                checks.append((str(c["text"])[:80].replace("|", "｜"),
                               bool(c.get("ok"))))

        lines = [
            f"## 总分：{score:g} / {total}分",
            "（对照自评：未配置 DeepSeek Key，按评分细则自行勾选评分）",
            "",
            "## 得分明细",
            "| 评分点 | 状态 |",
            "|---|---|",
        ]
        lines += [f"| {t} | ✅ 达成 |" for t, ok in checks if ok]
        lines += [f"| {t} | ❌ 未达成 |" for t, ok in checks if not ok]
        if note:
            lines += ["", "## 自评小结", note]
        lines += ["", "## 评分细则（对照用）", rub["rubric"]]
        result = "\n".join(lines)
        with _lock:
            gid = db.save_essay_grade(category, question, answer, total, result)
        return {"ok": True, "id": gid, "score": score,
                "total": total, "result": result}

    def _essay_grade(self, b):
        category = b.get("category", "")
        rub = essay_rubric.RUBRICS.get(category)
        if not rub:
            return self._err(400, "未知题型")
        question = b.get("question", "").strip()
        answer = b.get("answer", "").strip()
        material = b.get("material", "").strip()
        if not question or not answer:
            return self._err(400, "题目与作答均不能为空")
        try:
            total = int(b.get("total_score") or 0)
        except (TypeError, ValueError):
            total = 0
        total = total if 10 <= total <= 100 else rub["default_score"]
        reference = b.get("reference", "") or ""

        messages = essay_rubric.build_grade_messages(
            category, total, question, material, answer, reference)

        async def gen():
            yield "phase", "正在拆解得分点并逐条评分…"
            buffer = []
            async for kind, payload in ai.stream_chat_with_temp(messages, 0.2):
                if kind == "delta":
                    buffer.append(payload)
                elif kind == "error":
                    yield "error", payload
                    return
            raw = "".join(buffer).strip()
            parsed = essay_rubric.parse_grade_json(raw)
            if parsed:
                parsed["score"] = max(
                    0.0, min(float(total), float(parsed.get("score") or 0)))
                essay_rubric.enrich_dims(parsed, category, total)
                md_text = essay_rubric.render_grade_markdown(parsed, total)
                with _lock:
                    gid = db.save_essay_grade(
                        category, question, answer, total, md_text,
                        score=parsed["score"], level=parsed.get("level", ""),
                        points_json=json.dumps(parsed["points"], ensure_ascii=False),
                        dims_json=json.dumps(parsed["dims"], ensure_ascii=False),
                        rewrite_json=json.dumps(parsed["rewrite"], ensure_ascii=False))
                yield "result", {"data": parsed, "total": total}
                yield "saved", str(gid)
            elif raw:
                with _lock:
                    gid = db.save_essay_grade(
                        category, question, answer, total, raw)
                yield "fallback", raw
                yield "saved", str(gid)
            else:
                yield "error", "批改未返回内容，请重试"

        self._stream_sse(gen())

    # ---- 时政生成 / 自测（与桌面规则一致） ----

    async def _shizheng_generate(self, b):
        import re as _re
        period = b.get("period") or _shizheng_period()[0]
        existed = db.get_shizheng(period)
        if existed:
            return {"ok": True, "item": existed, "cached": True}
        m = _re.search(r"(\d{4})年(\d{1,2})月(上|下)半月", period)
        if not m:
            return {"ok": False, "error": "期次格式错误"}
        year, month, half = (m.group(1), m.group(2),
                              ("1-15日" if m.group(3) == "上" else "16-月末"))
        prompt = (
            f"你是公务员考试时政辅导老师。请整理 {year}年{month}月{half} 的时政常识积累，"
            "面向事业单位/公务员考试考生。若该时段在你的知识截止日期之后，请基于最近一次可确认的时事动态"
            "与长期高频考点（重要会议精神、科技成就、民生政策、纪念日、国际组织等）整理，并在开头注明"
            "「内容基于模型知识整理，考前请以权威时政资料核对」。"
            "输出 Markdown，结构如下：\n"
            "# {期次}时政常识\n"
            "## 一、国内要闻（10-14条，每条一行：**事件**——一句考点式说明）\n"
            "## 二、科技与民生（5-8条）\n"
            "## 三、国际要闻（4-6条）\n"
            "## 四、自测小测（5道单选题，题目后用「答案：X」标注）"
        )
        try:
            content = await ai.chat_once(
                [{"role": "user", "content": prompt}], temperature=0.3)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        if not content.strip():
            return {"ok": False, "error": "生成内容为空，请重试"}
        db.save_shizheng(period, f"{period}时政常识", content)
        return {"ok": True, "item": db.get_shizheng(period)}

    async def _shizheng_quiz(self, b):
        import json as _json
        import re as _re
        period = b.get("period") or _shizheng_period()[0]
        cached = db.get_shizheng_quiz(period)
        if cached:
            try:
                return {"ok": True, "cached": True, "items": _json.loads(cached)}
            except Exception:
                pass
        item = db.get_shizheng(period)
        if not item:
            return {"ok": False, "error": "该期时政尚未生成"}
        prompt = ai.build_shizheng_quiz_prompt(item["content"])
        try:
            out = await ai.chat_once(
                [{"role": "user", "content": prompt}], temperature=0.4)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        items = ai.parse_shizheng_quiz_json(out)
        if not items:
            return {"ok": False, "error": "生成格式异常或解析失败，请重试"}
        db.save_shizheng_quiz(period, _json.dumps(items, ensure_ascii=False))
        return {"ok": True, "cached": False, "items": items}

    # ---- 备份 zip 下载（浏览器环境回退用；文件名白名单校验） ----

    def _serve_backup(self, name: str):
        import re as _re
        if not _re.fullmatch(r"goshore_backup_[0-9_]+\.zip", name or ""):
            return self._err(400, "非法文件名")
        fp = _USERS_DIR / "exports" / name
        if not fp.is_file():
            return self._err(404)
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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


def _bank_db_ok(p: Path) -> bool:
    """题库可用性：能打开且 documents 有题。"""
    try:
        c = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True)
        try:
            n = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        finally:
            c.close()
        return n > 0
    except Exception:
        return False


def _rollback_bank_if_corrupt() -> bool:
    """启动自检：题库损坏且存在 .bak 则自动回滚。返回是否发生回滚。"""
    if _DB_PATH.exists() and _bank_db_ok(_DB_PATH):
        return False
    bak = _DB_PATH.with_name(_DB_PATH.name + ".bak")
    if bak.exists() and _bank_db_ok(bak):
        _DB_PATH.unlink(missing_ok=True)
        bak.replace(_DB_PATH)
        return True
    return False


def start(db_path: str, img_dir: str, web_dir: str) -> int:
    """在后台线程启动服务，返回端口。"""
    global _httpd
    configure(db_path, img_dir, web_dir)
    rolled = _rollback_bank_if_corrupt()
    global _USERS_DIR
    _USERS_DIR = _DB_PATH.parent / "users"
    accounts.configure(_USERS_DIR)
    # 老版本单用户库 → 游客（幂等）
    accounts.migrate_legacy_if_needed(_DB_PATH)
    _httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _httpd.daemon_threads = True
    t = threading.Thread(target=_httpd.serve_forever, daemon=True)
    t.start()
    _startup_selfcheck()
    return _httpd.server_address[1]


def _startup_selfcheck() -> None:
    """启动时自检核心数据接口。"""
    checks = [
        ("题库 facets", lambda: db.facets()),
        ("试卷列表 list_exams", lambda: db.list_exams()),
    ]
    ok, fail = 0, 0
    for name, fn in checks:
        try:
            r = fn()
            if r is None:
                raise RuntimeError("返回 None")
            ok += 1
        except Exception as e:
            fail += 1
            print(f"[FAIL] {name}: {e}")
    print(f"启动自检: {ok}/{ok + fail} 通过" + ("" if fail == 0 else f"（{fail} 项失败）"))


def stop() -> None:
    global _httpd
    if _httpd:
        _httpd.shutdown()
        _httpd = None
